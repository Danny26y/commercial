import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import httpx
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_v1_router
from app.core.config import get_settings

# Configure logging format
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("fastapi_ai_router")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan manager.
    Initializes high-performance pooled HTTP client and records boot time.
    """
    settings = get_settings()
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION} [{settings.ENVIRONMENT}]")

    app.state.start_time = time.time()
    app.state.http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.REQUEST_TIMEOUT_SECONDS, connect=5.0),
        limits=httpx.Limits(max_keepalive_connections=50, max_connections=200),
        follow_redirects=True,
    )

    yield

    logger.info("Gracefully closing pooled HTTP client connections...")
    await app.state.http_client.aclose()
    logger.info("Application shutdown complete.")


settings = get_settings()

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "Commercial-grade, production-ready AI router with intelligent multi-provider fallback, "
        "circuit breaking, and unified OpenAI-compatible completion endpoints."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# ------------------------------------------------------------------------------
# CORS Middleware
# ------------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS if settings.CORS_ORIGINS else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------------------
# Observability & Structured Request Logging Middleware
# ------------------------------------------------------------------------------
@app.middleware("http")
async def observability_logging_middleware(request: Request, call_next) -> Response:
    request_id = request.headers.get("X-Request-ID") or f"req_{uuid.uuid4().hex[:12]}"
    request.state.request_id = request_id

    start_time = time.perf_counter()
    client_ip = request.client.host if request.client else "unknown"

    try:
        response = await call_next(request)
        process_time_ms = round((time.perf_counter() - start_time) * 1000, 2)

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time-Ms"] = str(process_time_ms)

        logger.info(
            f"[{request_id}] {request.method} {request.url.path} "
            f"-> status={response.status_code} latency={process_time_ms}ms client={client_ip}"
        )
        return response

    except Exception as exc:
        process_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
        logger.error(
            f"[{request_id}] {request.method} {request.url.path} "
            f"-> UNHANDLED EXCEPTION after {process_time_ms}ms client={client_ip}: {exc}",
            exc_info=True,
        )
        raise exc


# ------------------------------------------------------------------------------
# Standardized Error Handlers (OpenAI Format)
# ------------------------------------------------------------------------------
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    detail = exc.detail
    if isinstance(detail, dict) and "error" in detail:
        content = detail
    else:
        content = {
            "error": {
                "message": str(detail),
                "type": "api_error",
                "param": None,
                "code": f"http_{exc.status_code}",
            }
        }
    return JSONResponse(
        status_code=exc.status_code,
        content=content,
        headers={"X-Request-ID": request_id},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    errors = exc.errors()
    formatted_message = "; ".join([f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}" for err in errors])
    content = {
        "error": {
            "message": f"Validation error: {formatted_message}",
            "type": "invalid_request_error",
            "param": None,
            "code": "validation_failed",
        }
    }
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=content,
        headers={"X-Request-ID": request_id},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    logger.critical(f"[{request_id}] Critical unhandled error: {exc}", exc_info=True)
    content = {
        "error": {
            "message": "Internal server error occurred.",
            "type": "internal_server_error",
            "param": None,
            "code": "internal_error",
        }
    }
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=content,
        headers={"X-Request-ID": request_id},
    )


# ------------------------------------------------------------------------------
# Route Registration
# ------------------------------------------------------------------------------
app.include_router(api_v1_router, prefix="/v1")


@app.get("/", summary="Root Metadata")
async def root() -> dict:
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "online",
        "docs": "/docs",
        "health": "/health",
        "chat_endpoint": "/v1/chat/completions",
    }


@app.get("/health", summary="Root Health Check Alias")
async def health_alias(request: Request) -> dict:
    """Convenience alias for orchestrators testing /health directly."""
    from app.api.v1.endpoints.health import health_check
    from app.services.llm_router import get_llm_router
    return await health_check(request, settings=settings, router_engine=get_llm_router())
