from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import Request
from fastapi.responses import JSONResponse


def _key_func(request: Request) -> str:
    """Rate limit by API key if present, else by IP."""
    api_key = request.headers.get("X-API-Key", "")
    if api_key:
        return api_key[:8]  # Use key prefix as identifier
    return get_remote_address(request)


limiter = Limiter(key_func=_key_func, storage_uri="memory://")


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={
            "status": "error",
            "error": {
                "code": "RATE_LIMIT_EXCEEDED",
                "message": f"Rate limit exceeded: {exc.detail}. Upgrade your tier for higher limits.",
                "retry_after": getattr(exc, 'retry_after', 60),
            },
        },
    )
