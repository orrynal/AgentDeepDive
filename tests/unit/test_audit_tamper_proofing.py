import pytest
import uuid
import os
import json
import shutil
from pathlib import Path
from datetime import datetime, timezone
from sqlalchemy import select, delete

from src.config import settings
from src.database import async_session, Base, engine
from src.core.auth.models import TenantModel
from src.core.governance.audit import audit_logger
from src.core.governance.models import AuditLogModel

@pytest.fixture(autouse=True)
async def setup_lightweight_mode():
    # Save original system mode
    original_mode = settings.system_mode
    settings.system_mode = "lightweight"
    
    # Clean up lock directory and db file
    db_file = Path("agentdeep.db")
    if db_file.exists():
        try:
            db_file.unlink()
        except Exception:
            pass
        
    # Re-initialize DB tables on SQLite
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    yield
    
    # Restore original system mode
    settings.system_mode = original_mode
    
    # Clean up db file
    if db_file.exists():
        try:
            db_file.unlink()
        except Exception:
            pass

@pytest.mark.anyio
async def test_audit_tamper_proofing_and_recovery():
    """Verify cryptographic hash chain integrity, secure local backup HMAC signatures, and self-healing recovery."""
    tenant_id = str(uuid.uuid4())
    tenant_uuid = uuid.UUID(tenant_id)
    
    # Pre-populate the TenantModel to avoid Foreign Key violations
    async with async_session() as session:
        async with session.begin():
            test_tenant = TenantModel(id=tenant_uuid, name=f"tenant-{tenant_id}")
            session.add(test_tenant)
            
    # Ensure a clean backup state for this tenant
    audit_logger.clean_backup(tenant_id)
    
    try:
        # 1. Log three events to build a hash chain and a local signed backup
        await audit_logger.log_event("test.event_1", "task-1", "agent-1", {"val": 100}, tenant_id)
        await audit_logger.log_event("test.event_2", "task-1", "agent-1", {"val": 200}, tenant_id)
        await audit_logger.log_event("test.event_3", "task-2", "agent-2", {"val": 300}, tenant_id)
        
        # Verify backup files were created
        backup_dir = os.path.join(settings.resolved_workspace_path, ".memory", "audit_backup")
        backup_file = os.path.join(backup_dir, f"{tenant_id}.jsonl")
        sig_file = os.path.join(backup_dir, f"{tenant_id}.sig")
        
        assert os.path.exists(backup_file)
        assert os.path.exists(sig_file)
        
        # 2. Check initial integrity -> Should be HEALTHY
        res = await audit_logger.verify_audit_integrity(tenant_id)
        print("VERIFY RESULT IS:", res)
        assert res["status"] == "healthy"
        assert res["database_count"] == 3
        assert res["backup_count"] == 3
        
        # 3. Simulate Database Tampering: Modify details of the second record
        async with async_session() as session:
            async with session.begin():
                stmt = select(AuditLogModel).where(AuditLogModel.tenant_id == tenant_uuid).order_by(AuditLogModel.timestamp.asc())
                records = list((await session.execute(stmt)).scalars().all())
                assert len(records) == 3
                
                # Modify details to break the hash of record[1]
                records[1].details = {"val": 999} # originally 200
                session.add(records[1])
            await session.commit()
            
        # Verify integrity -> Should be TAMPERED
        res_tampered = await audit_logger.verify_audit_integrity(tenant_id)
        assert res_tampered["status"] == "tampered"
        assert len(res_tampered["tampered_ids"]) >= 1
        
        # 4. Trigger Self-Healing Recovery
        recovery_res = await audit_logger.recover_audit_from_backup(tenant_id)
        assert recovery_res["success"] is True
        assert recovery_res["recovered_count"] == 3
        
        # Verify integrity is restored -> Should be HEALTHY (plus the recovery log event itself)
        res_restored = await audit_logger.verify_audit_integrity(tenant_id)
        assert res_restored["status"] == "healthy"
        # 3 original restored + 1 recovery log event = 4 database logs, and backup is also updated with recovery log
        assert res_restored["database_count"] == 4
        assert res_restored["backup_count"] == 4
        
        # 5. Simulate Backup Tampering: Appending an unsigned line
        with open(backup_file, "a", encoding="utf-8") as f:
            f.write(json.dumps({"id": str(uuid.uuid4()), "event_type": "fake"}) + "\n")
            
        # Verify integrity -> Should be CORRUPTED_BACKUP (since the signature doesn't match the file contents anymore)
        res_corrupt = await audit_logger.verify_audit_integrity(tenant_id)
        assert res_corrupt["status"] == "corrupted_backup"
        
        # Verify recovery fails when backup is corrupted
        failed_recovery = await audit_logger.recover_audit_from_backup(tenant_id)
        assert failed_recovery["success"] is False
        assert "backup signature is corrupted" in failed_recovery["message"]
        
    finally:
        # Cleanup backups
        audit_logger.clean_backup(tenant_id)
