import contextvars
import uuid
from typing import Optional

current_tenant_id: contextvars.ContextVar[Optional[uuid.UUID]] = contextvars.ContextVar(
    "current_tenant_id", default=None
)
