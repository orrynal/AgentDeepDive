"""SQLAlchemy ORM models for the Governance & Security Audit System."""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, String, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from src.database import Base
from src.core.auth.models import TenantModel


class AuditLogModel(Base):
    """Audit logs table ORM model."""

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    previous_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    def calculate_hash(self, prev_hash: str) -> str:
        """Calculate SHA-256 hash for the log entry block."""
        import hashlib
        import json
        from datetime import timezone
        
        ts = getattr(self, "timestamp", None)
        if ts:
            if ts.tzinfo is not None:
                ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
            ts_str = ts.isoformat()
        else:
            ts_str = ""
            
        details_str = json.dumps(self.details or {}, sort_keys=True)
        payload = f"{prev_hash}{ts_str}{self.event_type}{self.task_id}{self.agent_id}{details_str}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        """Convert model to dictionary for API responses."""
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "event_type": self.event_type,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "details": self.details,
            "previous_hash": self.previous_hash,
            "hash": self.hash,
        }
