"""API routes for Governance Security Audit Logs verification and self-healing recovery."""

import uuid
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, desc

from src.core.auth.models import UserModel
from src.core.auth.security import get_current_user
from src.core.governance.audit import audit_logger
from src.core.governance.models import AuditLogModel
from src.database import async_session

router = APIRouter()


@router.get("/audit/logs", response_model=dict)
async def get_audit_logs(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    event_type: Optional[str] = None,
    task_id: Optional[str] = None,
    user: UserModel = Depends(get_current_user),
):
    """Retrieve security audit logs for the authenticated user's tenant, with filtering and pagination."""
    tenant_uuid = user.tenant_id or uuid.UUID('00000000-0000-0000-0000-000000000000')
    
    try:
        async with async_session() as session:
            stmt = (
                select(AuditLogModel)
                .where(AuditLogModel.tenant_id == tenant_uuid)
            )
            if event_type:
                stmt = stmt.where(AuditLogModel.event_type == event_type)
            if task_id:
                stmt = stmt.where(AuditLogModel.task_id == task_id)
                
            # Order by timestamp desc for logging view
            stmt = stmt.order_by(desc(AuditLogModel.timestamp), desc(AuditLogModel.id)).limit(limit).offset(offset)
            res = await session.execute(stmt)
            entries = res.scalars().all()
            
            return {
                "logs": [entry.to_dict() for entry in entries],
                "limit": limit,
                "offset": offset,
            }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to query audit logs: {str(e)}"
        )


@router.post("/audit/verify", response_model=dict)
async def verify_audit_integrity(user: UserModel = Depends(get_current_user)):
    """Run cryptographic Hash Chain and secure backup HMAC validation on the audit trails of the current tenant."""
    tenant_uuid = user.tenant_id or uuid.UUID('00000000-0000-0000-0000-000000000000')
    try:
        verification = await audit_logger.verify_audit_integrity(str(tenant_uuid))
        return verification
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Integrity check failed: {str(e)}"
        )


@router.post("/audit/recover", response_model=dict)
async def recover_audit(user: UserModel = Depends(get_current_user)):
    """Trigger self-healing to reconstruct database audit records from the HMAC-signed local secure backup."""
    tenant_uuid = user.tenant_id or uuid.UUID('00000000-0000-0000-0000-000000000000')
    try:
        recovery = await audit_logger.recover_audit_from_backup(str(tenant_uuid))
        if not recovery["success"]:
            raise HTTPException(
                status_code=400,
                detail=recovery["message"]
            )
        return recovery
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Audit recovery execution failed: {str(e)}"
        )
