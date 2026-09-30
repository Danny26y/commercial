import os
from typing import AsyncGenerator
import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Inject test environment variables before importing app
os.environ["ENVIRONMENT"] = "testing"
os.environ["API_KEYS"] = "test-secret-key-123"
os.environ["OPENAI_API_KEY"] = "mock-openai-key"
os.environ["GROQ_API_KEY"] = "mock-groq-key"
os.environ["ANTHROPIC_API_KEY"] = "mock-anthropic-key"
os.environ["PROVIDER_FALLBACK_ORDER"] = "openai,groq,anthropic"

from app.core.config import get_settings
from app.main import app


@pytest.fixture(autouse=True)
def clear_lru_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Test client wrapping the ASGI application with initialized mock state."""
    app.state.start_time = 1000.0
    mock_http_client = httpx.AsyncClient()
    app.state.http_client = mock_http_client

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        yield test_client

    await mock_http_client.aclose()
