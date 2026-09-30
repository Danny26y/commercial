import json
from unittest.mock import patch
import httpx
import pytest
from httpx import AsyncClient, Response

from app.main import app
from app.services.llm_router import CircuitBreaker, CircuitState


@pytest.mark.asyncio
async def test_auth_missing_header(client: AsyncClient):
    response = await client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "Hello"}]},
    )
    assert response.status_code == 401
    data = response.json()
    assert data["error"]["code"] == "missing_api_key"


@pytest.mark.asyncio
async def test_auth_invalid_header(client: AsyncClient):
    response = await client.post(
        "/v1/chat/completions",
        headers={"X-API-Key": "wrong-key"},
        json={"messages": [{"role": "user", "content": "Hello"}]},
    )
    assert response.status_code == 401
    data = response.json()
    assert data["error"]["code"] == "invalid_api_key"


def test_circuit_breaker_trip_and_recover():
    cb = CircuitBreaker(failure_threshold=2, recovery_time_seconds=1.0)
    assert cb.can_execute("openai") is True

    cb.record_failure("openai", "HTTP 500")
    assert cb.can_execute("openai") is True

    cb.record_failure("openai", "HTTP 500")
    # Tripped to OPEN
    assert cb.can_execute("openai") is False
    status = cb.get_status()
    assert status["openai"]["state"] == CircuitState.OPEN.value

    # Test recovery cooldown
    import time
    time.sleep(1.1)
    assert cb.can_execute("openai") is True  # Enters HALF_OPEN

    cb.record_success("openai")
    assert cb.can_execute("openai") is True
    assert cb.get_status()["openai"]["state"] == CircuitState.CLOSED.value


@pytest.mark.asyncio
async def test_router_fallback_on_429(client: AsyncClient):
    """
    Test scenario:
    1. Primary provider (OpenAI) returns 429 Rate Limit.
    2. Router intercepts 429 and cascades immediately to fallback provider (Groq).
    3. Groq returns 200 OK.
    4. Client receives 200 OK with _router_meta showing fallback history.
    """
    openai_429_resp = Response(
        status_code=429,
        content=json.dumps({"error": {"message": "Rate limit exceeded"}}).encode(),
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
    )
    groq_200_resp = Response(
        status_code=200,
        content=json.dumps({
            "id": "chatcmpl-mock-groq",
            "created": 1700000000,
            "model": "llama-3.3-70b-versatile",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "Hello from Groq fallback!"},
                "finish_reason": "stop"
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18}
        }).encode(),
        request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
    )

    async def mock_post(*args, **kwargs):
        url = kwargs.get("url")
        if not url:
            for arg in args:
                if isinstance(arg, (str, httpx.URL)):
                    url = arg
                    break
        url_str = str(url) if url else ""
        if "openai.com" in url_str:
            return openai_429_resp
        if "groq.com" in url_str:
            return groq_200_resp
        return Response(status_code=500, request=httpx.Request("POST", url_str or "http://unknown"))

    with patch.object(app.state.http_client, "post", side_effect=mock_post):
        response = await client.post(
            "/v1/chat/completions",
            headers={"X-API-Key": "test-secret-key-123"},
            json={
                "model": "default",
                "messages": [{"role": "user", "content": "Explain circuit breakers"}],
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["choices"][0]["message"]["content"] == "Hello from Groq fallback!"
        assert data["_router_meta"]["provider_used"] == "groq"
        assert len(data["_router_meta"]["fallback_chain"]) >= 1
        assert "openai" in data["_router_meta"]["fallback_chain"][0]


@pytest.mark.asyncio
async def test_all_providers_exhausted(client: AsyncClient):
    """Test scenario: All configured providers return 500 errors."""
    error_resp = Response(
        status_code=500,
        content=b"Service Unavailable",
        request=httpx.Request("POST", "http://any"),
    )

    with patch.object(app.state.http_client, "post", return_value=error_resp):
        response = await client.post(
            "/v1/chat/completions",
            headers={"X-API-Key": "test-secret-key-123"},
            json={
                "model": "default",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )

        assert response.status_code == 503
        data = response.json()
        assert data["error"]["code"] == "all_providers_exhausted"
