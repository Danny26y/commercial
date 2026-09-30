import time
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Request

from app.core.config import Settings, get_settings
from app.services.llm_router import LLMRouter, get_llm_router

router = APIRouter()


@router.get(
    "/health",
    summary="Health & Readiness Check",
    description="Returns service uptime, configuration environment, and live provider circuit-breaker statuses.",
)
async def health_check(
    request: Request,
    settings: Settings = Depends(get_settings),
    router_engine: LLMRouter = Depends(get_llm_router),
) -> Dict[str, Any]:
    start_time = getattr(request.app.state, "start_time", time.time())
    uptime_seconds = round(time.time() - start_time, 2)

    all_providers = ["openai", "anthropic", "groq", "openrouter"]
    configured_providers = [p for p in all_providers if settings.is_provider_configured(p)]

    return {
        "status": "healthy",
        "app_name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "uptime_seconds": uptime_seconds,
        "configured_providers": configured_providers,
        "default_provider": settings.DEFAULT_PROVIDER,
        "fallback_order": settings.PROVIDER_FALLBACK_ORDER,
        "circuit_breakers": router_engine.circuit_breaker.get_status(),
    }
