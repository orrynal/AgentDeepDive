"""Audit System for logging security events and tool invocations.

Logs all security classifications (L0-L4), policy violations, and human approval decisions
to a persistent log file and structlog interface.
"""

import json
import os
import time
from typing import Any
import structlog

logger = structlog.get_logger("audit")

AUDIT_LOG_FILE = "logs/audit.log"


class AuditLogger:
    """Handles logging and persistence of security audit events, securing history via HMAC and Hash Chains."""

    def __init__(self, log_file: str | None = None):
        pass

    def _calculate_backup_signature(self, file_path: str) -> str:
        """Calculate HMAC-SHA256 of the backup file using settings.jwt_secret to detect tampering."""
        import hmac
        import hashlib
        from src.config import settings
        if not os.path.exists(file_path):
            return ""
        hasher = hmac.new(settings.jwt_secret.encode('utf-8'), digestmod=hashlib.sha256)
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                hasher.update(chunk)
        return hasher.hexdigest()

    async def _append_to_backup(self, tenant_id: str, entry_dict: dict):
        """Append an audit entry to the secure local backup file and update its HMAC signature."""
        from src.config import settings
        backup_dir = os.path.join(settings.resolved_workspace_path, ".memory", "audit_backup")
        os.makedirs(backup_dir, exist_ok=True)
        
        file_path = os.path.join(backup_dir, f"{tenant_id}.jsonl")
        sig_path = os.path.join(backup_dir, f"{tenant_id}.sig")
        
        # Serialize/deserialize to ensure clean types (like datetime conversion)
        entry_serialized = json.loads(json.dumps(entry_dict))
        
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry_serialized, sort_keys=True) + "\n")
            
        sig = self._calculate_backup_signature(file_path)
        with open(sig_path, "w", encoding="utf-8") as f:
            f.write(sig)

    def clean_backup(self, tenant_id: str):
        """Remove local secure backups for a specific tenant (primarily for unit tests/cleanup)."""
        from src.config import settings
        backup_dir = os.path.join(settings.resolved_workspace_path, ".memory", "audit_backup")
        file_path = os.path.join(backup_dir, f"{tenant_id}.jsonl")
        sig_path = os.path.join(backup_dir, f"{tenant_id}.sig")
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
        if os.path.exists(sig_path):
            try:
                os.remove(sig_path)
            except Exception:
                pass

    async def log_event(
        self,
        event_type: str,
        task_id: str,
        agent_id: str,
        details: dict[str, Any],
        tenant_id: str | None = None,
    ):
        """Log a security event to database, secure local backup, and structlog."""
        import uuid
        from datetime import datetime, timezone
        tenant_uuid = uuid.UUID(tenant_id or '00000000-0000-0000-0000-000000000000')

        # 1. Write to PostgreSQL database
        db_write_success = False
        try:
            from src.database import async_session
            from src.core.governance.models import AuditLogModel
            from sqlalchemy import select, desc
            async with async_session() as session:
                async with session.begin():
                    # Query the latest hash for this tenant to build the chain
                    stmt = (
                        select(AuditLogModel.hash)
                        .where(AuditLogModel.tenant_id == tenant_uuid)
                        .order_by(desc(AuditLogModel.timestamp), desc(AuditLogModel.id))
                        .limit(1)
                    )
                    res = await session.execute(stmt)
                    prev_hash = res.scalar_one_or_none() or "0" * 64

                    audit_entry = AuditLogModel(
                        event_type=event_type,
                        task_id=task_id,
                        agent_id=agent_id,
                        details=details,
                        tenant_id=tenant_uuid,
                        previous_hash=prev_hash,
                        timestamp=datetime.now(timezone.utc),
                    )
                    audit_entry.hash = audit_entry.calculate_hash(prev_hash)
                    session.add(audit_entry)
            db_write_success = True
        except Exception as e:
            logger.error("Failed to write audit record to database", error=str(e))

        # 2. Append to local secure backup file
        if db_write_success:
            try:
                await self._append_to_backup(str(tenant_uuid), audit_entry.to_dict())
            except Exception as e:
                logger.error("Failed to write audit record to local backup", error=str(e))

        # 3. Log with structlog for console/collector observability (stdout)
        logger.info(
            "Security Audit Event",
            event_type=event_type,
            task_id=task_id,
            agent_id=agent_id,
            **details,
        )

    async def verify_audit_integrity(self, tenant_id: str) -> dict[str, Any]:
        """Verify integrity of audit logs for a tenant, checking database chain and local backup HMAC."""
        import uuid
        from src.config import settings
        from src.database import async_session
        from src.core.governance.models import AuditLogModel
        from sqlalchemy import select
        
        tenant_uuid = uuid.UUID(tenant_id or '00000000-0000-0000-0000-000000000000')
        
        backup_dir = os.path.join(settings.resolved_workspace_path, ".memory", "audit_backup")
        backup_file = os.path.join(backup_dir, f"{tenant_uuid}.jsonl")
        sig_file = os.path.join(backup_dir, f"{tenant_uuid}.sig")
        
        # A. Verify backup file signature
        backup_exists = os.path.exists(backup_file)
        backup_healthy = True
        backup_entries = []
        
        if backup_exists:
            current_sig = self._calculate_backup_signature(backup_file)
            expected_sig = ""
            if os.path.exists(sig_file):
                with open(sig_file, "r", encoding="utf-8") as f:
                    expected_sig = f.read().strip()
            
            if current_sig != expected_sig:
                backup_healthy = False
            else:
                with open(backup_file, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            backup_entries.append(json.loads(line.strip()))
        
        # B. Verify database chain (Reconstructed topologically via hash pointers)
        db_entries = []
        try:
            async with async_session() as session:
                # We fetch all entries without sorting strictly by time to avoid microsecond collisions
                stmt = (
                    select(AuditLogModel)
                    .where(AuditLogModel.tenant_id == tenant_uuid)
                )
                res = await session.execute(stmt)
                db_entries = list(res.scalars().all())
        except Exception as e:
            logger.error("Database query failed during integrity check", error=str(e))
            return {
                "status": "error",
                "database_count": 0,
                "backup_count": len(backup_entries),
                "tampered_ids": [],
                "description": f"Database integrity check failed: {str(e)}"
            }
        
        # Reconstruct chain order topologically starting from previous_hash = "0" * 64
        prev_map = {}
        for entry in db_entries:
            prev_map[entry.previous_hash] = entry
            
        sorted_db_entries = []
        curr_prev = "0" * 64
        visited = set()
        
        while curr_prev in prev_map:
            if curr_prev in visited:
                break # Avoid circular chain infinite loop
            visited.add(curr_prev)
            
            entry = prev_map[curr_prev]
            sorted_db_entries.append(entry)
            curr_prev = entry.hash
            
        # Append isolated/unlinked entries to make sure they get validated/exposed
        if len(sorted_db_entries) < len(db_entries):
            connected_ids = {e.id for e in sorted_db_entries}
            for entry in db_entries:
                if entry.id not in connected_ids:
                    sorted_db_entries.append(entry)
                    
        tampered_ids = []
        db_chain_healthy = True
        
        # Verify the reconstructed chain
        prev_hash = "0" * 64
        for entry in sorted_db_entries:
            if entry.previous_hash != prev_hash:
                db_chain_healthy = False
                tampered_ids.append(str(entry.id))
                
            recalculated = entry.calculate_hash(entry.previous_hash)
            if entry.hash != recalculated:
                db_chain_healthy = False
                if str(entry.id) not in tampered_ids:
                    tampered_ids.append(str(entry.id))
                    
            prev_hash = entry.hash
            
        db_count = len(db_entries)
        backup_count = len(backup_entries)
        
        # C. Comprehensive analysis
        if backup_exists and not backup_healthy:
            desc = "CRITICAL: Secure local backup file has signature mismatches (unauthorized filesystem write)."
            try:
                from src.core.governance.notifications.dispatcher import dispatch_workflow_notification
                await dispatch_workflow_notification(
                    event_type="audit.backup_corrupted",
                    dag_id="AUDIT_SYSTEM",
                    node_id="INTEGRITY_CHECK",
                    error=desc,
                    tenant_id=str(tenant_uuid)
                )
            except Exception:
                pass
            return {
                "status": "corrupted_backup",
                "database_count": db_count,
                "backup_count": backup_count,
                "tampered_ids": tampered_ids,
                "description": desc
            }
            
        if not db_chain_healthy or db_count != backup_count:
            desc = f"WARNING: Audit logs have been tampered. DB count: {db_count}, Backup count: {backup_count}."
            if tampered_ids:
                desc += f" Tampered record IDs: {', '.join(tampered_ids)}"
            else:
                desc += " Detected record deletion/mismatch."
                
            try:
                from src.core.governance.notifications.dispatcher import dispatch_workflow_notification
                await dispatch_workflow_notification(
                    event_type="audit.tampered",
                    dag_id="AUDIT_SYSTEM",
                    node_id="INTEGRITY_CHECK",
                    error=desc,
                    tenant_id=str(tenant_uuid)
                )
            except Exception:
                pass
            return {
                "status": "tampered",
                "database_count": db_count,
                "backup_count": backup_count,
                "tampered_ids": tampered_ids,
                "description": desc
            }
            
        return {
            "status": "healthy",
            "database_count": db_count,
            "backup_count": backup_count,
            "tampered_ids": [],
            "description": "Audit trail is fully verified and secure."
        }

    async def recover_audit_from_backup(self, tenant_id: str) -> dict[str, Any]:
        """Restore DB audit logs from the signed secure local backup if valid."""
        import uuid
        from src.config import settings
        from src.database import async_session
        from src.core.governance.models import AuditLogModel
        from sqlalchemy import delete
        from datetime import datetime, timezone
        
        tenant_uuid = uuid.UUID(tenant_id or '00000000-0000-0000-0000-000000000000')
        
        verification = await self.verify_audit_integrity(str(tenant_uuid))
        status = verification["status"]
        
        if status == "healthy":
            return {
                "success": True,
                "recovered_count": 0,
                "message": "Audit logs are already healthy. No recovery needed."
            }
            
        if status == "corrupted_backup":
            return {
                "success": False,
                "recovered_count": 0,
                "message": "Recovery aborted: Secure backup signature is corrupted. Manual recovery required."
            }
            
        backup_dir = os.path.join(settings.resolved_workspace_path, ".memory", "audit_backup")
        backup_file = os.path.join(backup_dir, f"{tenant_uuid}.jsonl")
        
        if not os.path.exists(backup_file):
            return {
                "success": False,
                "recovered_count": 0,
                "message": "Recovery failed: No secure backup file exists."
            }
            
        backup_entries = []
        with open(backup_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    backup_entries.append(json.loads(line.strip()))
                    
        try:
            async with async_session() as session:
                async with session.begin():
                    stmt = delete(AuditLogModel).where(AuditLogModel.tenant_id == tenant_uuid)
                    await session.execute(stmt)
                    
                    for item in backup_entries:
                        ts = datetime.fromisoformat(item["timestamp"]) if item["timestamp"] else datetime.now(timezone.utc)
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                            
                        db_entry = AuditLogModel(
                            id=uuid.UUID(item["id"]),
                            tenant_id=uuid.UUID(item["tenant_id"]),
                            timestamp=ts,
                            event_type=item["event_type"],
                            task_id=item["task_id"],
                            agent_id=item["agent_id"],
                            details=item["details"],
                            previous_hash=item["previous_hash"],
                            hash=item["hash"]
                        )
                        session.add(db_entry)
            await session.commit()
        except Exception as e:
            logger.error("Failed to restore audit logs from backup", error=str(e))
            return {
                "success": False,
                "recovered_count": 0,
                "message": f"Database restoration failed: {str(e)}"
            }
            
        await self.log_event(
            event_type="audit.recovered",
            task_id="AUDIT_SYSTEM",
            agent_id="SYSTEM",
            details={"recovered_count": len(backup_entries), "reason": "Self-healing triggered due to audit tampering."},
            tenant_id=str(tenant_uuid)
        )
        
        return {
            "success": True,
            "recovered_count": len(backup_entries),
            "message": f"Successfully recovered {len(backup_entries)} audit entries and re-anchored hash chain."
        }


# Global Singleton
audit_logger = AuditLogger()
