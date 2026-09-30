import secrets
from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader
from app.core.config import get_settings

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str = Security(API_KEY_HEADER)) -> str:
    """
    Validates incoming request against configured API keys.
    Protects against timing attacks using secrets.compare_digest.
    """
    settings = get_settings()

    # In development mode, allow requests if no keys are configured
    if not settings.API_KEYS:
        if settings.ENVIRONMENT.lower() == "development":
            return "dev-unrestricted"
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": {
                    "message": "No API keys configured on server. Define API_KEYS in your .env file.",
                    "type": "configuration_error",
                    "param": None,
                    "code": "server_misconfigured",
                }
            },
        )

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "message": "Missing API Key. Pass a valid key in the 'X-API-Key' header.",
                    "type": "authentication_error",
                    "param": None,
                    "code": "missing_api_key",
                }
            },
        )

    is_valid = any(
        secrets.compare_digest(api_key, valid_key)
        for valid_key in settings.API_KEYS
    )

    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "message": "Invalid API Key provided.",
                    "type": "authentication_error",
                    "param": None,
                    "code": "invalid_api_key",
                }
            },
        )

    return api_key
