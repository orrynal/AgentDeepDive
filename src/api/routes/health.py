"""Health check endpoints."""

from datetime import datetime, timezone

import redis.asyncio as aioredis
from fastapi import APIRouter

from src.config import settings

router = APIRouter()


@router.get("/health")
async def health_check():
    """Basic health check - always returns OK if server is running."""
    return {
        "status": "healthy",
        "service": settings.app_name,
        "version": settings.app_version,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/health/ready")
async def readiness_check():
    """Deep health check - verifies all dependencies are reachable."""
    checks = {}

    # Check PostgreSQL
    try:
        from sqlalchemy import text
        from src.database import engine

        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as e:
        checks["postgres"] = f"error: {str(e)[:100]}"

    # Check Redis
    try:
        from src.core.redis_pool import get_async_redis_client
        r = get_async_redis_client()
        await r.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {str(e)[:100]}"

    # Check Milvus
    if settings.system_mode != "lightweight":
        try:
            from src.core.memory.rag_manager import rag_manager
            if rag_manager.connected:
                checks["milvus"] = "ok"
            else:
                checks["milvus"] = "degraded (mock mode)"
        except Exception as e:
            checks["milvus"] = f"error: {str(e)[:100]}"

    # Check OPA
    if settings.opa_enabled:
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                res = await client.get(f"{settings.opa_url}/v1/policies", timeout=2.0)
                if res.status_code == 200:
                    checks["opa"] = "ok"
                else:
                    checks["opa"] = f"degraded (status {res.status_code})"
        except Exception as e:
            checks["opa"] = f"error: {str(e)[:100]}"

    all_ok = all(v == "ok" for v in checks.values())
    return {
        "status": "ready" if all_ok else "degraded",
        "checks": checks,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/health/pool")
async def get_pool_status():
    """Get active Agent Pool slots and load status."""
    from src.core.agent.pool import agent_pool
    active = await agent_pool.get_active_agents()
    return {
        "max_concurrency": agent_pool.max_concurrency,
        "active_count": len(active),
        "active_agents": active,
    }


from pydantic import BaseModel

class AutoApproveToggleRequest(BaseModel):
    auto_approve_l3: bool | None = None
    auto_approve_l4: bool | None = None


@router.get("/config/auto-approve")
async def get_auto_approve_status():
    """Get the current state of L3 and L4 auto-approval governance switch."""
    return {
        "auto_approve_l3": settings.auto_approve_l3,
        "auto_approve_l4": settings.auto_approve_l4
    }


@router.post("/config/auto-approve")
async def toggle_auto_approve(body: AutoApproveToggleRequest):
    """Toggle the state of L3 and L4 auto-approval switches at runtime."""
    if body.auto_approve_l3 is not None:
        settings.auto_approve_l3 = body.auto_approve_l3
    if body.auto_approve_l4 is not None:
        settings.auto_approve_l4 = body.auto_approve_l4
    return {
        "status": "ok",
        "auto_approve_l3": settings.auto_approve_l3,
        "auto_approve_l4": settings.auto_approve_l4
    }


class SaasKeysUpdateRequest(BaseModel):
    openai_api_key: str | None = None
    openai_api_base: str | None = None
    anthropic_api_key: str | None = None
    cohere_api_key: str | None = None
    gemini_api_key: str | None = None
    notion_integration_token: str | None = None
    airtable_api_key: str | None = None
    airtable_base_id: str | None = None
    supabase_url: str | None = None
    supabase_key: str | None = None


@router.get("/config/saas-keys")
async def get_saas_keys():
    """Get the current state of SaaS integration and cloud LLM keys (masked for security)."""
    def mask(val: str) -> str:
        if not val:
            return ""
        if len(val) <= 8:
            return "********"
        return f"{val[:4]}...{val[-4:]}"

    return {
        "openai_api_key": mask(settings.openai_api_key),
        "openai_api_base": settings.openai_api_base,
        "anthropic_api_key": mask(settings.anthropic_api_key),
        "cohere_api_key": mask(settings.cohere_api_key),
        "gemini_api_key": mask(settings.gemini_api_key),
        "notion_integration_token": mask(settings.notion_integration_token),
        "airtable_api_key": mask(settings.airtable_api_key),
        "airtable_base_id": settings.airtable_base_id,
        "supabase_url": settings.supabase_url,
        "supabase_key": mask(settings.supabase_key),
    }


@router.post("/config/saas-keys")
async def update_saas_keys(body: SaasKeysUpdateRequest):
    """Update cloud LLM provider and SaaS integration keys at runtime."""
    if body.openai_api_key is not None:
        settings.openai_api_key = body.openai_api_key
    if body.openai_api_base is not None:
        settings.openai_api_base = body.openai_api_base
    if body.anthropic_api_key is not None:
        settings.anthropic_api_key = body.anthropic_api_key
    if body.cohere_api_key is not None:
        settings.cohere_api_key = body.cohere_api_key
    if body.gemini_api_key is not None:
        settings.gemini_api_key = body.gemini_api_key
    if body.notion_integration_token is not None:
        settings.notion_integration_token = body.notion_integration_token
    if body.airtable_api_key is not None:
        settings.airtable_api_key = body.airtable_api_key
    if body.airtable_base_id is not None:
        settings.airtable_base_id = body.airtable_base_id
    if body.supabase_url is not None:
        settings.supabase_url = body.supabase_url
    if body.supabase_key is not None:
        settings.supabase_key = body.supabase_key

    # Re-apply to environment variables
    from src.config import apply_keys_to_env
    apply_keys_to_env()

    return {
        "status": "ok",
        "message": "SaaS keys updated successfully and loaded into runtime environment."
    }


@router.get("/health/diagnostics")
async def diagnostics_check():
    """Comprehensive system diagnostics check covering resource, singletons, DB, Redis, scheduler, agent pool, and overall system status."""
    import os
    import shutil
    from src.core.scheduler.manager import scheduler_manager
    from src.core.agent.pool import agent_pool
    import time

    diagnostics = {}
    health_level = "GREEN"
    errors = []

    # 1. Resource and Disk Diagnostics
    try:
        import threading
        thread_count = threading.active_count()
        memory_usage_mb = None
        
        try:
            import psutil
            process = psutil.Process(os.getpid())
            mem_info = process.memory_info()
            memory_usage_mb = round(mem_info.rss / (1024 * 1024), 2)
            thread_count = process.num_threads()
        except ImportError:
            try:
                with open("/proc/self/status", "r") as f:
                    for line in f:
                        if line.startswith("VmRSS:"):
                            parts = line.split()
                            if len(parts) >= 2:
                                memory_usage_mb = round(int(parts[1]) / 1024, 2)
                                break
            except Exception:
                pass
        
        # Disk Space
        ws_path = settings.resolved_workspace_path
        total_b, used_b, free_b = shutil.disk_usage(ws_path)
        
        diagnostics["system"] = {
            "pid": os.getpid(),
            "memory_usage_mb": memory_usage_mb,
            "thread_count": thread_count,
            "workspace_path": ws_path,
            "disk_total_gb": round(total_b / (1024**3), 2),
            "disk_free_gb": round(free_b / (1024**3), 2),
            "disk_usage_percent": round((used_b / total_b) * 100, 1)
        }
    except Exception as sys_err:
        diagnostics["system"] = {"status": "error", "message": str(sys_err)}
        errors.append(f"System diagnostics failed: {sys_err}")

    # 2. Database Diagnostics
    try:
        from sqlalchemy import text
        from src.database import engine

        db_start = time.perf_counter()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_latency_ms = round((time.perf_counter() - db_start) * 1000, 2)
        
        diagnostics["database"] = {
            "status": "healthy",
            "latency_ms": db_latency_ms,
            "pool_size": engine._engine.pool.size() if hasattr(engine._engine, "pool") else None,
            "checked_at": datetime.now(timezone.utc).isoformat()
        }
    except Exception as db_err:
        diagnostics["database"] = {"status": "unhealthy", "message": str(db_err)}
        health_level = "RED"
        errors.append(f"Database unavailable: {db_err}")

    # 3. Redis Diagnostics
    try:
        from src.core.redis_pool import get_async_redis_client

        redis_client = get_async_redis_client()
        redis_start = time.perf_counter()
        await redis_client.ping()
        redis_latency_ms = round((time.perf_counter() - redis_start) * 1000, 2)

        diagnostics["redis"] = {
            "status": "healthy",
            "latency_ms": redis_latency_ms,
            "checked_at": datetime.now(timezone.utc).isoformat()
        }
    except Exception as redis_err:
        diagnostics["redis"] = {"status": "unhealthy", "message": str(redis_err)}
        health_level = "RED"
        errors.append(f"Redis unavailable: {redis_err}")

    # 3.5. Milvus Diagnostics (if not lightweight)
    if settings.system_mode != "lightweight":
        try:
            from src.core.memory.rag_manager import rag_manager
            milvus_start = time.perf_counter()
            milvus_status = "healthy" if rag_manager.connected else "degraded (mock mode)"
            milvus_latency_ms = round((time.perf_counter() - milvus_start) * 1000, 2)
            diagnostics["milvus"] = {
                "status": milvus_status,
                "latency_ms": milvus_latency_ms,
                "checked_at": datetime.now(timezone.utc).isoformat()
            }
        except Exception as milvus_err:
            diagnostics["milvus"] = {"status": "unhealthy", "message": str(milvus_err)}
            health_level = "YELLOW"
            errors.append(f"Milvus diagnostics failed: {milvus_err}")

    # 3.6. OPA Diagnostics (if enabled)
    if settings.opa_enabled:
        try:
            import httpx
            opa_start = time.perf_counter()
            async with httpx.AsyncClient() as client:
                res = await client.get(f"{settings.opa_url}/v1/policies", timeout=2.0)
                opa_latency_ms = round((time.perf_counter() - opa_start) * 1000, 2)
                if res.status_code == 200:
                    diagnostics["opa"] = {
                        "status": "healthy",
                        "latency_ms": opa_latency_ms,
                        "checked_at": datetime.now(timezone.utc).isoformat()
                    }
                else:
                    diagnostics["opa"] = {
                        "status": "unhealthy",
                        "message": f"Status code: {res.status_code}",
                        "latency_ms": opa_latency_ms,
                        "checked_at": datetime.now(timezone.utc).isoformat()
                    }
                    health_level = "YELLOW"
                    errors.append(f"OPA returned non-200 status code: {res.status_code}")
        except Exception as opa_err:
            diagnostics["opa"] = {"status": "unhealthy", "message": str(opa_err)}
            health_level = "YELLOW"
            errors.append(f"OPA unavailable: {opa_err}")

    # 4. Scheduler (APScheduler) Diagnostics
    try:
        scheduler_status = "active" if scheduler_manager._initialized else "inactive"
        job_count = len(scheduler_manager.scheduler.get_jobs()) if scheduler_manager._initialized else 0
        diagnostics["scheduler"] = {
            "status": scheduler_status,
            "registered_jobs_count": job_count,
            "jobs": [
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None
                }
                for job in scheduler_manager.scheduler.get_jobs()
            ] if scheduler_manager._initialized else []
        }
    except Exception as sched_err:
        diagnostics["scheduler"] = {"status": "error", "message": str(sched_err)}
        errors.append(f"Scheduler diagnostics failed: {sched_err}")

    # 5. Agent Pool Sentinel & Governance Diagnostics
    try:
        active_agents = await agent_pool.get_active_agents()
        diagnostics["agent_pool"] = {
            "status": "active" if hasattr(agent_pool, "_sentinel_task") and agent_pool._sentinel_task and not agent_pool._sentinel_task.done() else "inactive",
            "max_concurrency": agent_pool.max_concurrency,
            "active_agent_count": len(active_agents),
            "active_agents": active_agents
        }
    except Exception as pool_err:
        diagnostics["agent_pool"] = {"status": "error", "message": str(pool_err)}
        errors.append(f"Agent pool diagnostics failed: {pool_err}")

    # Evaluate intermediate warning status
    if health_level == "GREEN" and errors:
        health_level = "YELLOW"

    return {
        "health_level": health_level,
        "errors": errors,
        "diagnostics": diagnostics,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@router.post("/health/cleanup")
async def manual_cleanup():
    """Manually trigger garbage collection and memory cache cleanup."""
    import gc
    import os
    import time

    # Measure memory before
    mem_before = None
    try:
        import psutil
        process = psutil.Process(os.getpid())
        mem_before = process.memory_info().rss / (1024 * 1024)
    except ImportError:
        try:
            with open("/proc/self/status", "r") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        parts = line.split()
                        if len(parts) >= 2:
                            mem_before = int(parts[1]) / 1024
                            break
        except Exception:
            pass

    # 1. Clear local caches if any
    try:
        from src.core.memory.rag_manager import rag_manager
        # Release and garbage collect collections
        if hasattr(rag_manager, "kb_collection"):
            rag_manager.kb_collection = None
        if hasattr(rag_manager, "em_collection"):
            rag_manager.em_collection = None
    except Exception:
        pass

    # 2. Trigger python gc
    gc.collect()

    # Measure memory after
    mem_after = None
    try:
        import psutil
        process = psutil.Process(os.getpid())
        mem_after = process.memory_info().rss / (1024 * 1024)
    except ImportError:
        try:
            with open("/proc/self/status", "r") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        parts = line.split()
                        if len(parts) >= 2:
                            mem_after = int(parts[1]) / 1024
                            break
        except Exception:
            pass

    released_mb = 0.0
    if mem_before is not None and mem_after is not None:
        released_mb = max(0.0, round(mem_before - mem_after, 2))

    return {
        "status": "ok",
        "message": "Garbage collection and cache cleanup completed successfully.",
        "memory_before_mb": round(mem_before, 2) if mem_before is not None else None,
        "memory_after_mb": round(mem_after, 2) if mem_after is not None else None,
        "released_mb": released_mb,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@router.get("/health/celery-stats")
async def get_celery_stats():
    """Retrieve collected performance and latency statistics for Celery tasks."""
    from src.core.celery_monitoring import get_celery_task_stats
    stats = await get_celery_task_stats()
    return {
        "status": "ok",
        "stats": stats,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

