"""Authentication API endpoints for tenant registration and login."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.core.auth.models import TenantModel, UserModel
from src.core.auth.security import hash_password, verify_password, create_jwt_token, get_current_user

router = APIRouter()


# ── Schemas ──

class TenantRegister(BaseModel):
    tenant_name: str = Field(..., min_length=3, max_length=64, description="Unique name of the tenant organization")
    username: str = Field(..., min_length=3, max_length=64, description="Admin username")
    password: str = Field(..., min_length=6, description="Admin password")


class UserLogin(BaseModel):
    username: str = Field(...)
    password: str = Field(...)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    tenant_id: str


class UserMeResponse(BaseModel):
    id: str
    username: str
    tenant_id: str
    role: str


# ── API Endpoints ──

@router.post("/auth/register", status_code=status.HTTP_201_CREATED)
async def register_tenant(body: TenantRegister, session: AsyncSession = Depends(get_db)):
    """Register a new tenant organization along with its first Admin user."""
    # Check if tenant name exists
    existing_tenant = await session.execute(
        select(TenantModel).where(TenantModel.name == body.tenant_name)
    )
    if existing_tenant.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tenant organization '{body.tenant_name}' already exists."
        )

    # Check if username exists
    existing_user = await session.execute(
        select(UserModel).where(UserModel.username == body.username)
    )
    if existing_user.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Username '{body.username}' is already taken."
        )

    # Create Tenant
    tenant = TenantModel(name=body.tenant_name)
    session.add(tenant)
    await session.flush()  # Populate tenant.id

    # Create User
    pwd_hash = hash_password(body.password)
    user = UserModel(
        username=body.username,
        password_hash=pwd_hash,
        tenant_id=tenant.id,
        role="admin"
    )
    session.add(user)
    await session.commit()

    return {
        "message": "Tenant and Admin user successfully registered.",
        "tenant": tenant.to_dict(),
        "user": user.to_dict()
    }


@router.post("/auth/login", response_model=TokenResponse)
async def login(body: UserLogin, session: AsyncSession = Depends(get_db)):
    """Login with credentials to obtain a JWT token."""
    result = await session.execute(
        select(UserModel).where(UserModel.username == body.username)
    )
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password."
        )

    payload = {
        "user_id": str(user.id),
        "tenant_id": str(user.tenant_id),
        "role": user.role,
        "username": user.username
    }
    
    token = create_jwt_token(payload)
    return TokenResponse(
        access_token=token,
        role=user.role,
        tenant_id=str(user.tenant_id)
    )


@router.get("/auth/me", response_model=UserMeResponse)
async def get_me(user: UserModel = Depends(get_current_user)):
    """Retrieve details of the currently logged-in user."""
    return UserMeResponse(
        id=str(user.id),
        username=user.username,
        tenant_id=str(user.tenant_id),
        role=user.role
    )
