"""Pydantic models for Role API."""

from pydantic import BaseModel, Field


class RoleCreate(BaseModel):
    """Schema for creating a new Role."""

    role_id: str = Field(..., description="Unique identifier, e.g. 'senior_coder'")
    name: str = Field(..., description="Human-readable name")
    description: str | None = Field(default=None)
    system_prompt_prefix: str = Field(..., description="Role-specific system prompt prefix")
    allowed_skills: list[str] = Field(default_factory=list, description="Skills allowed for this role")
    default_model: str | None = Field(default=None)
    max_token_budget: int = Field(default=50000)


class RoleUpdate(BaseModel):
    """Schema for updating a Role (all fields optional)."""

    name: str | None = None
    description: str | None = None
    system_prompt_prefix: str | None = None
    allowed_skills: list[str] | None = None
    default_model: str | None = None
    max_token_budget: int | None = None


class RoleResponse(BaseModel):
    """Schema for Role API responses."""

    id: str
    role_id: str
    name: str
    description: str | None = None
    system_prompt_prefix: str
    allowed_skills: list[str] = []
    default_model: str | None = None
    max_token_budget: int = 50000
    is_active: bool = True
    created_at: str | None = None
    updated_at: str | None = None
