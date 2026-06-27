"""Auth security helpers for JWT, hashing, and FastAPI dependencies."""

import base64
import hashlib
import hmac
import json
import time
import uuid
from typing import Optional

from fastapi import Depends, HTTPException, Request, Security, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import get_db
from src.core.auth.models import UserModel, TenantModel
from src.core.auth.context import current_tenant_id

bearer_scheme = HTTPBearer(auto_error=False)


# ── Password Hashing ──

def hash_password(password: str) -> str:
    """Hash password using PBKDF2-HMAC-SHA256 with a salt, defaulting to 600,000 iterations."""
    import os
    salt = os.urandom(16)
    iterations = 600000
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${key.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    """Verify password against its hash supporting backward compatibility for legacy format."""
    try:
        if hashed.startswith("pbkdf2_sha256$"):
            parts = hashed.split("$")
            iterations = int(parts[1])
            salt = bytes.fromhex(parts[2])
            key = bytes.fromhex(parts[3])
        else:
            salt_hex, key_hex = hashed.split(":")
            iterations = 100000
            salt = bytes.fromhex(salt_hex)
            key = bytes.fromhex(key_hex)
            
        new_key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, iterations)
        return hmac.compare_digest(key, new_key)
    except Exception:
        return False


# ── JWT Encoding/Decoding ──

def base64url_encode(data: bytes) -> str:
    """Encode bytes to base64url format (no padding, url-safe)."""
    return base64.urlsafe_b64encode(data).decode('utf-8').rstrip('=')


def base64url_decode(data: str) -> bytes:
    """Decode base64url format string back to bytes."""
    padding = '=' * (4 - len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def create_jwt_token(payload: dict, secret: str = settings.jwt_secret, expires_in: int = 86400) -> str:
    """Create a self-signed HS256 JWT token."""
    header = {"alg": "HS256", "typ": "JWT"}
    header_b64 = base64url_encode(json.dumps(header).encode('utf-8'))
    
    # Ensure expiration is set
    token_payload = payload.copy()
    if "exp" not in token_payload:
        token_payload["exp"] = int(time.time()) + expires_in
        
    payload_b64 = base64url_encode(json.dumps(token_payload).encode('utf-8'))
    
    message = f"{header_b64}.{payload_b64}".encode('utf-8')
    signature = hmac.new(secret.encode('utf-8'), message, hashlib.sha256).digest()
    signature_b64 = base64url_encode(signature)
    
    return f"{header_b64}.{payload_b64}.{signature_b64}"


def decode_jwt_token(token: str, secret: str = settings.jwt_secret) -> Optional[dict]:
    """Decode and verify HS256 JWT token."""
    try:
        parts = token.split('.')
        if len(parts) != 3:
            return None
        header_b64, payload_b64, signature_b64 = parts
        
        # Verify signature
        message = f"{header_b64}.{payload_b64}".encode('utf-8')
        expected_sig = hmac.new(secret.encode('utf-8'), message, hashlib.sha256).digest()
        actual_sig = base64url_decode(signature_b64)
        if not hmac.compare_digest(expected_sig, actual_sig):
            return None
            
        # Parse payload
        payload = json.loads(base64url_decode(payload_b64).decode('utf-8'))
        
        # Check expiration
        if "exp" in payload and payload["exp"] < time.time():
            return None
            
        return payload
    except Exception:
        return None


# ── FastAPI Dependencies ──

async def _resolve_user(
    auth: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    session: AsyncSession = Depends(get_db),
) -> UserModel:
    """Dependency to retrieve the currently authenticated user from JWT or API Key fallback."""
    current_tenant_id.set(None)
    from src.config import settings

    # 1. First check if a JWT Bearer token is provided
    if auth and auth.credentials:
        if settings.api_key and auth.credentials == settings.api_key:
            return UserModel(
                id=None,
                username="apikey_client",
                tenant_id="00000000-0000-0000-0000-000000000000",
                role="admin"
            )
        
        payload = decode_jwt_token(auth.credentials)
        if payload:
            user_id_str = payload.get("user_id")
            if user_id_str:
                try:
                    user_uuid = uuid.UUID(user_id_str)
                    result = await session.execute(select(UserModel).where(UserModel.id == user_uuid))
                    user = result.scalar_one_or_none()
                    if user:
                        return user
                except ValueError:
                    pass
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired authentication token."
            )
        else:
            if settings.api_key:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid or expired authentication token."
                )

    # 2. Check X-API-Key header
    if x_api_key:
        if settings.api_key and x_api_key == settings.api_key:
            return UserModel(
                id=None,
                username="apikey_client",
                tenant_id="00000000-0000-0000-0000-000000000000",
                role="admin"
            )
        if settings.api_key:
            raise HTTPException(
                status_code=401,
                detail="Invalid API key."
            )

    # 3. No credentials provided
    if not settings.api_key:
        return UserModel(
            id=None,
            username="anonymous",
            tenant_id="00000000-0000-0000-0000-000000000000",
            role="viewer"
        )

    raise HTTPException(
        status_code=401,
        detail="Authentication credentials were not provided."
    )


async def get_current_user(
    user: UserModel = Depends(_resolve_user)
) -> UserModel:
    """Retrieve user and bind tenant to context."""
    return user


async def get_current_tenant(
    user: UserModel = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> TenantModel:
    """Dependency to retrieve the current user's Tenant."""
    result = await session.execute(select(TenantModel).where(TenantModel.id == user.tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=404,
            detail="Tenant not found."
        )
    return tenant


class RoleRequired:
    """Dependency factory enforcing role requirements (RBAC)."""

    def __init__(self, allowed_roles: list[str]):
        self.allowed_roles = allowed_roles

    def __call__(self, user: UserModel = Depends(get_current_user)) -> UserModel:
        if user.role not in self.allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"Permission denied: role '{user.role}' is not authorized."
            )
        return user
