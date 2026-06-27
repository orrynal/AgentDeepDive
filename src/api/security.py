"""Security dependencies for API endpoints (PC/Mobile pairing authorization)."""

from fastapi import Header, HTTPException, Security, Request
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
import structlog

from src.config import settings

logger = structlog.get_logger()

# Optional headers/bearer schemes for client convenience
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)

async def verify_api_key(
    request: Request,
    x_api_key: Optional[str] = Security(api_key_header),
    auth: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme)
):
    """Verify pre-shared API Key for secure dashboard / mobile connectivity.
    
    If settings.api_key is not configured, security is disabled (convenient for local offline use).
    """
    if not settings.api_key:
        return
        
    token = None
    if auth:
        token = auth.credentials
    elif x_api_key:
        token = x_api_key
        
    if not token or token != settings.api_key:
        logger.warning(
            "Unauthorized connection attempt",
            client_host=request.client.host if request.client else "unknown"
        )
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Invalid or missing API Key (PC/Mobile Pairing Code required)"
        )
