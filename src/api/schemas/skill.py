"""Pydantic models for Skill API."""

from pydantic import BaseModel, Field


class SkillCreate(BaseModel):
    """Schema for creating a new Skill."""

    skill_id: str = Field(..., description="Unique identifier, e.g. 'code-refactor-v2'")
    name: str = Field(..., description="Human-readable name")
    version: str = Field(default="1.0.0")
    description: str | None = Field(default=None)
    tags: list[str] = Field(default_factory=list, description="Matching tags")
    trigger_patterns: list[str] = Field(default_factory=list, description="Natural language triggers")
    context_budget: int = Field(default=8000, description="Max tokens for context")
    required_tools: list[str] = Field(default_factory=list)
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict = Field(default_factory=dict)
    system_prompt: str | None = Field(default=None)
    risk_level: str = Field(default="low", pattern="^(low|medium|high|critical)$")
    approval_required: bool = Field(default=False)
    estimated_tokens: int = Field(default=10000)
    estimated_duration_sec: int = Field(default=120)
    workspace_path: str | None = Field(default=None, description="Workspace isolation path, if project-specific")


class SkillUpdate(BaseModel):
    """Schema for updating a Skill (all fields optional)."""

    name: str | None = None
    version: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    trigger_patterns: list[str] | None = None
    context_budget: int | None = None
    required_tools: list[str] | None = None
    input_schema: dict | None = None
    output_schema: dict | None = None
    system_prompt: str | None = None
    risk_level: str | None = None
    approval_required: bool | None = None
    estimated_tokens: int | None = None
    estimated_duration_sec: int | None = None
    workspace_path: str | None = None
    is_active: bool | None = None


class SkillResponse(BaseModel):
    """Schema for Skill API responses."""

    id: str
    skill_id: str
    name: str
    version: str
    description: str | None = None
    tags: list[str] = []
    trigger_patterns: list[str] = []
    context_budget: int = 8000
    required_tools: list[str] = []
    input_schema: dict = {}
    output_schema: dict = {}
    system_prompt: str | None = None
    risk_level: str = "low"
    approval_required: bool = False
    estimated_tokens: int = 10000
    estimated_duration_sec: int = 120
    workspace_path: str | None = None
    is_active: bool = True
    created_at: str
    updated_at: str


class SkillInstallRequest(BaseModel):
    """Schema for installing a Skill from the market or URL."""
    skill_name_or_url: str = Field(..., description="Skill name or URL to install")
    scope: str = Field(..., pattern="^(global|project)$", description="Scope of installation")
    workspace_path: str | None = Field(default=None, description="Workspace path if scope is project")


class SkillPreviewRequest(BaseModel):
    """Schema for skill import preview request."""
    content: str = Field(..., description="Raw Markdown or YAML file content")


class SkillPreviewResponse(BaseModel):
    """Schema for skill import preview response."""
    parser_type: str = Field(..., description="'yaml' or 'markdown'")
    metadata: dict = Field(..., description="Extracted metadata dict")
    warnings: list[str] = Field(default_factory=list, description="Parsing warnings or corrections log")
