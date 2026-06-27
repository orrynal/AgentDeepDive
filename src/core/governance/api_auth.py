"""REST API fine-grained authorization dependency using Open Policy Agent."""

from fastapi import Depends, HTTPException, Request
from src.config import settings
from src.core.auth.models import UserModel
from src.core.auth.security import get_current_user
from src.core.governance.guardrails import guardrail_engine

async def verify_opa_api_permission(
    request: Request,
    user: UserModel = Depends(get_current_user)
) -> UserModel:
    """Enforce fine-grained REST API permissions using OPA."""
    if not settings.opa_enabled:
        return user

    # Evaluate REST API access via OPA api_auth policy
    allowed = guardrail_engine.evaluate_api_permission(
        method=request.method,
        path=request.url.path,
        tenant_id=str(user.tenant_id) if user.tenant_id else "00000000-0000-0000-0000-000000000000",
        role=user.role,
        path_params=dict(request.path_params)
    )

    if not allowed:
        raise HTTPException(
            status_code=403,
            detail=f"OPA Security Block: Access denied for role '{user.role}' to {request.method} {request.url.path}"
        )

    return user
