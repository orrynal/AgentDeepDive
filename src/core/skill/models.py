"""SQLAlchemy ORM models for the Skill Registry."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text, ForeignKey, UniqueConstraint, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from src.database import Base, CompatibleArray as ARRAY


class SkillModel(Base):
    """Skills table ORM model."""

    __tablename__ = "skills"

    __table_args__ = (
        UniqueConstraint("tenant_id", "skill_id", name="uq_skills_tenant_skill_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    skill_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    version: Mapped[str] = mapped_column(String(32), default="1.0.0")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    trigger_patterns: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    context_budget: Mapped[int] = mapped_column(Integer, default=8000)
    required_tools: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    input_schema: Mapped[dict] = mapped_column(JSON, default=dict)
    output_schema: Mapped[dict] = mapped_column(JSON, default=dict)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_level: Mapped[str] = mapped_column(String(16), default="low")
    approval_required: Mapped[bool] = mapped_column(Boolean, default=False)
    estimated_tokens: Mapped[int] = mapped_column(Integer, default=10000)
    estimated_duration_sec: Mapped[int] = mapped_column(Integer, default=120)
    workspace_path: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def to_dict(self) -> dict:
        """Convert model to dictionary for API responses."""
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "skill_id": self.skill_id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "tags": self.tags or [],
            "trigger_patterns": self.trigger_patterns or [],
            "context_budget": self.context_budget,
            "required_tools": self.required_tools or [],
            "input_schema": self.input_schema or {},
            "output_schema": self.output_schema or {},
            "system_prompt": self.system_prompt,
            "risk_level": self.risk_level,
            "approval_required": self.approval_required,
            "estimated_tokens": self.estimated_tokens,
            "estimated_duration_sec": self.estimated_duration_sec,
            "workspace_path": self.workspace_path,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
