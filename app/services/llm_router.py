import asyncio
import logging
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.core.config import Settings, get_settings
from app.schemas.chat import (
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    RouterMetadata,
    UsageInfo,
)

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    CLOSED = "CLOSED"        # Normal operation: requests pass through
    OPEN = "OPEN"            # Tripped: traffic is blocked / skipped
    HALF_OPEN = "HALF_OPEN"  # Recovery testing: allow a single probe request


class CircuitBreaker:
    """
    In-memory Circuit Breaker tracking health per LLM provider.
    Automatically trips after consecutive failures and recovers after a cooldown.
    """

    def __init__(self, failure_threshold: int = 3, recovery_time_seconds: float = 60.0):
        self.failure_threshold = failure_threshold
        self.recovery_time_seconds = recovery_time_seconds
        self._failure_counts: Dict[str, int] = {}
        self._last_failure_time: Dict[str, float] = {}
        self._states: Dict[str, CircuitState] = {}

    def can_execute(self, provider: str) -> bool:
        provider = provider.lower()
        state = self._states.get(provider, CircuitState.CLOSED)

        if state == CircuitState.CLOSED:
            return True

        if state == CircuitState.OPEN:
            last_fail = self._last_failure_time.get(provider, 0.0)
            elapsed = time.time() - last_fail
            if elapsed >= self.recovery_time_seconds:
                logger.info(
                    f"[CircuitBreaker] Provider '{provider}' entered HALF_OPEN state after {elapsed:.1f}s cooldown."
                )
                self._states[provider] = CircuitState.HALF_OPEN
                return True
            return False

        if state == CircuitState.HALF_OPEN:
            return True

        return True

    def record_success(self, provider: str) -> None:
        provider = provider.lower()
        previous_state = self._states.get(provider, CircuitState.CLOSED)
        self._failure_counts[provider] = 0
        self._states[provider] = CircuitState.CLOSED

        if previous_state != CircuitState.CLOSED:
            logger.info(f"[CircuitBreaker] Provider '{provider}' recovered successfully. Circuit is now CLOSED.")

    def record_failure(self, provider: str, error_msg: str) -> None:
        provider = provider.lower()
        now = time.time()
        self._last_failure_time[provider] = now
        current_failures = self._failure_counts.get(provider, 0) + 1
        self._failure_counts[provider] = current_failures

        if current_failures >= self.failure_threshold:
            self._states[provider] = CircuitState.OPEN
            logger.warning(
                f"[CircuitBreaker] Circuit TRIPPED to OPEN for provider '{provider}'. "
                f"Failures: {current_failures}/{self.failure_threshold}. Error: {error_msg}"
            )
        else:
            logger.warning(
                f"[CircuitBreaker] Recorded failure for '{provider}' ({current_failures}/{self.failure_threshold}): {error_msg}"
            )

    def get_status(self) -> Dict[str, Dict[str, Any]]:
        status = {}
        all_providers = set(self._states.keys()) | set(self._failure_counts.keys())
        for provider in all_providers:
            state = self._states.get(provider, CircuitState.CLOSED)
            failures = self._failure_counts.get(provider, 0)
            last_fail = self._last_failure_time.get(provider, 0.0)
            status[provider] = {
                "state": state.value,
                "consecutive_failures": failures,
                "last_failure_timestamp": last_fail if last_fail > 0 else None,
            }
        return status


class ProviderException(Exception):
    """Raised when an upstream LLM provider fails."""

    def __init__(self, provider: str, status_code: int, message: str):
        super().__init__(f"Provider '{provider}' failed with HTTP {status_code}: {message}")
        self.provider = provider
        self.status_code = status_code
        self.message = message


class AllProvidersExhaustedException(Exception):
    """Raised when every candidate provider in the fallback chain has failed."""

    def __init__(self, attempts: List[str]):
        summary = " -> ".join(attempts) if attempts else "No active providers configured"
        super().__init__(f"All LLM providers failed. Attempt trail: {summary}")
        self.attempts = attempts


class LLMRouter:
    """
    Production-grade multi-provider LLM router with intelligent fallback,
    circuit breaking, request payload translation, and observability diagnostics.
    """

    DEFAULT_MODELS: Dict[str, str] = {
        "openai": "gpt-4o",
        "anthropic": "claude-3-5-sonnet-20241022",
        "groq": "llama-3.3-70b-versatile",
        "openrouter": "meta-llama/llama-3.3-70b-instruct",
    }

    MODEL_FALLBACK_MAP: Dict[str, Dict[str, str]] = {
        "gpt-4o": {
            "openai": "gpt-4o",
            "anthropic": "claude-3-5-sonnet-20241022",
            "groq": "llama-3.3-70b-versatile",
            "openrouter": "meta-llama/llama-3.3-70b-instruct",
        },
        "gpt-4o-mini": {
            "openai": "gpt-4o-mini",
            "anthropic": "claude-3-5-haiku-20241022",
            "groq": "llama-3.1-8b-instant",
            "openrouter": "meta-llama/llama-3.1-8b-instruct",
        },
    }

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=self.settings.CIRCUIT_BREAKER_FAILURE_THRESHOLD,
            recovery_time_seconds=self.settings.CIRCUIT_BREAKER_RECOVERY_TIME_SECONDS,
        )

    def resolve_model_for_provider(self, provider: str, requested_model: str) -> str:
        provider = provider.lower()
        if requested_model == "default" or not requested_model:
            return self.DEFAULT_MODELS.get(provider, "gpt-4o")

        if requested_model in self.MODEL_FALLBACK_MAP:
            return self.MODEL_FALLBACK_MAP[requested_model].get(
                provider, self.DEFAULT_MODELS.get(provider, requested_model)
            )

        # Provider specific prefixes
        if provider == "anthropic" and requested_model.startswith("claude-"):
            return requested_model
        if provider == "openai" and (requested_model.startswith("gpt-") or requested_model.startswith("o1-")):
            return requested_model
        if provider == "groq" and requested_model.startswith("llama-"):
            return requested_model

        # Fallback to provider default if model name doesn't match provider conventions
        if provider == "anthropic" and not requested_model.startswith("claude-"):
            return self.DEFAULT_MODELS["anthropic"]
        if provider == "groq" and not (requested_model.startswith("llama-") or requested_model.startswith("mixtral-")):
            return self.DEFAULT_MODELS["groq"]

        return requested_model

    async def route(
        self, request: ChatCompletionRequest, client: httpx.AsyncClient
    ) -> ChatCompletionResponse:
        start_time = time.perf_counter()
        fallback_chain: List[str] = []
        total_retries = 0

        # Build candidate providers sequence
        candidate_providers: List[str] = []
        if request.provider and self.settings.is_provider_configured(request.provider):
            candidate_providers.append(request.provider.lower())

        for p in self.settings.PROVIDER_FALLBACK_ORDER:
            p_lower = p.lower()
            if self.settings.is_provider_configured(p_lower) and p_lower not in candidate_providers:
                candidate_providers.append(p_lower)

        if not candidate_providers:
            error_msg = "No LLM providers are configured with valid API keys in environment."
            logger.error(error_msg)
            raise AllProvidersExhaustedException([error_msg])

        for provider in candidate_providers:
            if not self.circuit_breaker.can_execute(provider):
                skip_msg = f"{provider}: skipped (circuit breaker OPEN)"
                fallback_chain.append(skip_msg)
                logger.warning(f"[LLMRouter] {skip_msg}")
                continue

            target_model = self.resolve_model_for_provider(provider, request.model)
            provider_attempts = 0

            while provider_attempts <= self.settings.MAX_RETRIES_PER_PROVIDER:
                provider_attempts += 1
                try:
                    logger.info(
                        f"[LLMRouter] Attempting provider '{provider}' with model '{target_model}' (attempt {provider_attempts})."
                    )

                    response = await self._dispatch_provider(
                        provider=provider,
                        target_model=target_model,
                        request=request,
                        client=client,
                    )

                    # Successful response: record in circuit breaker and return
                    self.circuit_breaker.record_success(provider)
                    elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

                    response.router_meta = RouterMetadata(
                        provider_used=provider,
                        model_used=target_model,
                        latency_ms=elapsed_ms,
                        fallback_chain=fallback_chain,
                        retries_attempted=total_retries,
                    )

                    logger.info(
                        f"[LLMRouter] SUCCESS from '{provider}' ({target_model}) in {elapsed_ms}ms. Fallbacks: {len(fallback_chain)}."
                    )
                    return response

                except ProviderException as pe:
                    total_retries += 1
                    fail_desc = f"{provider} (attempt {provider_attempts}): HTTP {pe.status_code} - {pe.message}"
                    fallback_chain.append(fail_desc)
                    self.circuit_breaker.record_failure(provider, fail_desc)

                    # 429 Rate Limit or 5xx Server Error -> immediate fallback to next provider
                    if pe.status_code == 429 or pe.status_code >= 500:
                        logger.warning(f"[LLMRouter] {fail_desc}. Triggering immediate fallback.")
                        break  # Break retry loop on this provider, move to next provider

                except (httpx.TimeoutException, httpx.NetworkError) as net_err:
                    total_retries += 1
                    fail_desc = f"{provider} (attempt {provider_attempts}): Network/Timeout - {str(net_err)}"
                    fallback_chain.append(fail_desc)
                    self.circuit_breaker.record_failure(provider, fail_desc)
                    logger.warning(f"[LLMRouter] {fail_desc}. Triggering fallback.")
                    break

                except Exception as unexpected_err:
                    total_retries += 1
                    fail_desc = f"{provider} (attempt {provider_attempts}): Unexpected error - {str(unexpected_err)}"
                    fallback_chain.append(fail_desc)
                    self.circuit_breaker.record_failure(provider, fail_desc)
                    logger.error(f"[LLMRouter] {fail_desc}", exc_info=True)
                    break

        raise AllProvidersExhaustedException(fallback_chain)

    async def _dispatch_provider(
        self,
        provider: str,
        target_model: str,
        request: ChatCompletionRequest,
        client: httpx.AsyncClient,
    ) -> ChatCompletionResponse:
        base_url = self.settings.get_provider_base_url(provider)
        api_key = self.settings.get_provider_key(provider)

        if not api_key:
            raise ProviderException(provider, 401, f"Missing API key for provider '{provider}'")

        if provider == "anthropic":
            return await self._call_anthropic(
                base_url=base_url,
                api_key=api_key,
                model=target_model,
                request=request,
                client=client,
            )
        else:
            # OpenAI, Groq, OpenRouter share the OpenAI completions standard
            return await self._call_openai_compatible(
                provider=provider,
                base_url=base_url,
                api_key=api_key,
                model=target_model,
                request=request,
                client=client,
            )

    async def _call_openai_compatible(
        self,
        provider: str,
        base_url: str,
        api_key: str,
        model: str,
        request: ChatCompletionRequest,
        client: httpx.AsyncClient,
    ) -> ChatCompletionResponse:
        url = f"{base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        if provider == "openrouter":
            headers["HTTP-Referer"] = "https://fastapi-ai-router.internal"
            headers["X-Title"] = "FastAPI Multi-Provider AI Router"

        payload: Dict[str, Any] = {
            "model": model,
            "messages": [m.model_dump(exclude_none=True) for m in request.messages],
        }

        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.top_p is not None:
            payload["top_p"] = request.top_p
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        if request.stop is not None:
            payload["stop"] = request.stop

        response = await client.post(
            url,
            json=payload,
            headers=headers,
            timeout=self.settings.REQUEST_TIMEOUT_SECONDS,
        )

        if response.status_code != 200:
            error_text = response.text
            try:
                err_json = response.json()
                error_text = err_json.get("error", {}).get("message", response.text)
            except Exception:
                pass
            raise ProviderException(provider, response.status_code, error_text)

        data = response.json()

        # Parse standard choices
        choices = []
        for choice_data in data.get("choices", []):
            msg = choice_data.get("message", {})
            choices.append(
                ChatCompletionChoice(
                    index=choice_data.get("index", 0),
                    message=ChatCompletionChoiceMessage(
                        role=msg.get("role", "assistant"),
                        content=msg.get("content", ""),
                    ),
                    finish_reason=choice_data.get("finish_reason", "stop"),
                )
            )

        usage_data = data.get("usage", {})
        usage = UsageInfo(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
        )

        return ChatCompletionResponse(
            id=data.get("id", f"chatcmpl-{uuid.uuid4().hex[:12]}"),
            object="chat.completion",
            created=data.get("created", int(time.time())),
            model=data.get("model", model),
            choices=choices,
            usage=usage,
            _router_meta=RouterMetadata(
                provider_used=provider,
                model_used=model,
                latency_ms=0.0,
                fallback_chain=[],
                retries_attempted=0,
            ),
        )

    async def _call_anthropic(
        self,
        base_url: str,
        api_key: str,
        model: str,
        request: ChatCompletionRequest,
        client: httpx.AsyncClient,
    ) -> ChatCompletionResponse:
        url = f"{base_url}/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        system_prompt: Optional[str] = None
        anthropic_messages = []

        for msg in request.messages:
            if msg.role == "system":
                if system_prompt is None:
                    system_prompt = msg.content
                else:
                    system_prompt += f"\n{msg.content}"
            elif msg.role in ("user", "assistant"):
                anthropic_messages.append({"role": msg.role, "content": msg.content})

        if not anthropic_messages:
            anthropic_messages.append({"role": "user", "content": "Hello"})

        payload: Dict[str, Any] = {
            "model": model,
            "messages": anthropic_messages,
            "max_tokens": request.max_tokens or 1024,
        }

        if system_prompt:
            payload["system"] = system_prompt
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.top_p is not None:
            payload["top_p"] = request.top_p

        response = await client.post(
            url,
            json=payload,
            headers=headers,
            timeout=self.settings.REQUEST_TIMEOUT_SECONDS,
        )

        if response.status_code != 200:
            error_text = response.text
            try:
                err_json = response.json()
                error_text = err_json.get("error", {}).get("message", response.text)
            except Exception:
                pass
            raise ProviderException("anthropic", response.status_code, error_text)

        data = response.json()

        # Combine text content blocks
        text_content = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_content += block.get("text", "")

        stop_reason = data.get("stop_reason")
        finish_reason = "stop" if stop_reason == "end_turn" else (stop_reason or "stop")

        usage_data = data.get("usage", {})
        prompt_tokens = usage_data.get("input_tokens", 0)
        completion_tokens = usage_data.get("output_tokens", 0)

        choices = [
            ChatCompletionChoice(
                index=0,
                message=ChatCompletionChoiceMessage(
                    role="assistant",
                    content=text_content,
                ),
                finish_reason=finish_reason,
            )
        ]

        usage = UsageInfo(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        )

        return ChatCompletionResponse(
            id=data.get("id", f"msg_{uuid.uuid4().hex[:12]}"),
            object="chat.completion",
            created=int(time.time()),
            model=data.get("model", model),
            choices=choices,
            usage=usage,
            _router_meta=RouterMetadata(
                provider_used="anthropic",
                model_used=model,
                latency_ms=0.0,
                fallback_chain=[],
                retries_attempted=0,
            ),
        )


_router_instance: Optional[LLMRouter] = None


def get_llm_router() -> LLMRouter:
    """Returns singleton LLMRouter instance."""
    global _router_instance
    if _router_instance is None:
        _router_instance = LLMRouter()
    return _router_instance
