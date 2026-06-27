"""SQLAlchemy ORM models for the Agent Role System."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from src.database import Base, CompatibleArray as ARRAY


class RoleModel(Base):
    """Roles table ORM model."""

    __tablename__ = "roles"

    __table_args__ = (
        UniqueConstraint("tenant_id", "role_id", name="uq_roles_tenant_role_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    system_prompt_prefix: Mapped[str] = mapped_column(Text, nullable=False)
    allowed_skills: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    default_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    max_token_budget: Mapped[int] = mapped_column(Integer, default=50000)
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
            "role_id": self.role_id,
            "name": self.name,
            "description": self.description,
            "system_prompt_prefix": self.system_prompt_prefix,
            "allowed_skills": self.allowed_skills or [],
            "default_model": self.default_model,
            "max_token_budget": self.max_token_budget,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
