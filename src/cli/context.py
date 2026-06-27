"""CLI Context and Mode Detection for AgentDeepDive."""

import asyncio
import os
import json
from enum import Enum
from pathlib import Path
import httpx
class CLIMode(str, Enum):
    LOCAL = "local"
    REMOTE = "remote"
    AUTO = "auto"

AUTH_FILE_PATH = Path.home() / ".agentdeep_auth.json"

class CLIContext:
    tenant_override: str | None = None
    mode_override: str | None = None

    def __init__(self, mode: CLIMode = CLIMode.AUTO, api_url: str = "http://localhost:8000/api/v1"):
        self.mode = mode
        self.api_url = api_url
        self._resolved_mode = None

    @property
    def resolved_mode(self) -> CLIMode:
        if self._resolved_mode is None:
            self._resolved_mode = self.detect_mode()
        return self._resolved_mode

    @resolved_mode.setter
    def resolved_mode(self, mode: CLIMode):
        self._resolved_mode = mode

    def detect_mode(self) -> CLIMode:
        """Synchronously detect if the API Server is reachable."""
        if CLIContext.mode_override:
            return CLIMode(CLIContext.mode_override)
        if self.mode != CLIMode.AUTO:
            return self.mode

        # Check API health endpoint
        health_url = self.api_url.replace("/api/v1", "/health")
        try:
            # Short timeout to avoid blocking CLI startups
            with httpx.Client(timeout=1.5) as client:
                resp = client.get(health_url)
                if resp.status_code == 200:
                    return CLIMode.REMOTE
        except Exception:
            pass

        return CLIMode.LOCAL

    async def detect_mode_async(self) -> CLIMode:
        """Asynchronously detect if the API Server is reachable."""
        if CLIContext.mode_override:
            return CLIMode(CLIContext.mode_override)
        if self.mode != CLIMode.AUTO:
            return self.mode

        health_url = self.api_url.replace("/api/v1", "/health")
        try:
            async with httpx.AsyncClient(timeout=1.5) as client:
                resp = await client.get(health_url)
                if resp.status_code == 200:
                    return CLIMode.REMOTE
        except Exception:
            pass

        return CLIMode.LOCAL

    def load_auth(self) -> dict:
        """Load auth credentials from the local config file."""
        if AUTH_FILE_PATH.exists():
            try:
                with open(AUTH_FILE_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def save_auth(self, token: str, username: str, tenant_id: str, role: str):
        """Save auth credentials to the local config file."""
        data = {
            "access_token": token,
            "username": username,
            "tenant_id": tenant_id,
            "role": role,
        }
        AUTH_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(AUTH_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def clear_auth(self):
        """Remove the local auth config file."""
        if AUTH_FILE_PATH.exists():
            try:
                AUTH_FILE_PATH.unlink()
            except Exception:
                pass

    def get_auth_headers(self) -> dict:
        """Get the HTTP headers including the Bearer token if logged in."""
        auth = self.load_auth()
        headers = {}
        if auth.get("access_token"):
            headers["Authorization"] = f"Bearer {auth['access_token']}"
        return headers

    def get_http_client(self, **kwargs) -> httpx.AsyncClient:
        """Get an AsyncClient configured with auth headers."""
        headers = self.get_auth_headers()
        if "headers" in kwargs:
            headers.update(kwargs.pop("headers"))
        return httpx.AsyncClient(headers=headers, **kwargs)

    async def resolve_tenant_id(self, db_session) -> str:
        """Resolve the active tenant ID, querying DB if a name is given in local mode."""
        tenant = CLIContext.tenant_override
        if not tenant:
            auth = self.load_auth()
            tenant = auth.get("tenant_id")

        if not tenant:
            return "00000000-0000-0000-0000-000000000000"

        # Check if it's already a valid UUID
        import uuid
        try:
            uuid.UUID(tenant)
            return tenant
        except ValueError:
            pass

        # If it's a name, query the DB
        from sqlalchemy import select
        from src.core.auth.models import TenantModel
        try:
            result = await db_session.execute(
                select(TenantModel).where(TenantModel.name == tenant)
            )
            t_model = result.scalar_one_or_none()
            if t_model:
                return str(t_model.id)
        except Exception:
            pass

        return "00000000-0000-0000-0000-000000000000"

    def get_redis(self):
        """Get the synchronous Redis client."""
        from src.core.redis_pool import get_redis_client
        return get_redis_client()

    def get_async_redis(self):
        """Get the asynchronous Redis client."""
        from src.core.redis_pool import get_async_redis_client
        return get_async_redis_client()

    def get_db(self):
        """Returns an async session context manager."""
        from src.database import async_session
        return async_session()

