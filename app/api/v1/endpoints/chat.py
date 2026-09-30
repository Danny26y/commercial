import logging
from typing import Any, Dict

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.security import verify_api_key
from app.schemas.chat import ChatCompletionRequest, ChatCompletionResponse, ErrorResponse
from app.services.llm_router import (
    AllProvidersExhaustedException,
    LLMRouter,
    get_llm_router,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def get_http_client(request: Request) -> httpx.AsyncClient:
    """Dependency retrieving the pooled httpx.AsyncClient from FastAPI application state."""
    client = getattr(request.app.state, "http_client", None)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": {
                    "message": "HTTP client pool uninitialized in application state.",
                    "type": "server_error",
                    "param": None,
                    "code": "http_client_uninitialized",
                }
            },
        )
    return client


@router.post(
    "/chat/completions",
    response_model=ChatCompletionResponse,
    responses={
        200: {"description": "Successful chat completion from active provider."},
        401: {"model": ErrorResponse, "description": "Invalid or missing API key."},
        422: {"description": "Validation error on request schema."},
        503: {"model": ErrorResponse, "description": "All LLM providers in fallback chain failed."},
    },
    summary="Create Chat Completion with Multi-Provider Fallback",
    description="Drop-in OpenAI-compatible chat completion endpoint. Automatically cascades through fallback providers on 429 rate limits or 5xx server errors.",
)
async def create_chat_completion(
    request: ChatCompletionRequest,
    http_client: httpx.AsyncClient = Depends(get_http_client),
    api_key: str = Depends(verify_api_key),
    router_engine: LLMRouter = Depends(get_llm_router),
) -> ChatCompletionResponse:
    """
    Unified chat completion endpoint with circuit-breaker protection and automatic failover.
    """
    try:
        response = await router_engine.route(request=request, client=http_client)
        return response

    except AllProvidersExhaustedException as exc:
        logger.error(f"[ChatAPI] Complete failure across all configured providers: {exc}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": {
                    "message": f"All LLM providers failed to complete the request. Attempt history: {exc.attempts}",
                    "type": "provider_routing_error",
                    "param": None,
                    "code": "all_providers_exhausted",
                }
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"[ChatAPI] Unexpected error during completion: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": {
                    "message": f"Internal routing engine error: {str(exc)}",
                    "type": "server_error",
                    "param": None,
                    "code": "internal_error",
                }
            },
        )
