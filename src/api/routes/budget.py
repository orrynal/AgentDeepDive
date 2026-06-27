"""Budget management and tracking endpoints."""

from fastapi import APIRouter, Depends
from src.core.budget.manager import budget_manager
from src.core.auth.security import get_current_user
from src.core.auth.models import UserModel

router = APIRouter()


@router.get("/budget/summary", response_model=dict)
async def get_budget_summary(user: UserModel = Depends(get_current_user)):
    """Get the current token budget summary and total spend for the tenant."""
    return await budget_manager.get_summary(tenant_id=user.tenant_id)
