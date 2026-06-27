"""AgentDeepDive API server entry point."""

from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import approvals, auth, brain, budget, dags, evolution, health, skills, roles, tasks, webhooks, schedules, websocket, workspaces, opa, audit
from src.config import settings
from src.core.skill.loader import load_skills_from_directory
from src.core.role.loader import load_roles_from_directory
from src.core.role.models import Base as RoleBase
from src.core.scheduler.manager import scheduler_manager
from src.database import async_session, engine
from src.api.security import verify_api_key
from src.core.governance.api_auth import verify_opa_api_permission

logger = structlog.get_logger()

SKILLS_DIR = Path(__file__).parent.parent.parent / "skills"
ROLES_DIR = Path(__file__).parent.parent.parent / "roles"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    # Initialize OpenTelemetry Tracing
    try:
        from src.core.telemetry import initialize_telemetry
        initialize_telemetry(app)
    except Exception as telemetry_err:
        logger.error("Failed to initialize telemetry on startup", error=str(telemetry_err))

    # Initialize Workspace configuration
    try:
        from src.core.workspace.manager import workspace_manager
        if workspace_manager.active_workspace:
            settings.project_workspace_path = workspace_manager.active_workspace
            logger.info("Workspace restored on startup", path=workspace_manager.active_workspace)
        else:
            default_ws = settings.resolved_workspace_path
            workspace_manager.set_active_workspace(default_ws)
            logger.info("Initialized default workspace on startup", path=default_ws)
    except Exception as e:
        logger.error("Failed to initialize workspace settings", error=str(e))

    logger.info(
        "AgentDeepDive starting",
        version=settings.app_version,
        debug=settings.debug,
    )

    # Auto-create roles database tables if they do not exist
    try:
        async with engine.begin() as conn:
            await conn.run_sync(RoleBase.metadata.create_all)
            logger.info("Roles database tables initialized")
    except Exception as e:
        logger.error("Failed to initialize roles database tables", error=str(e))

    # Initialize scheduler and load persistent cron tasks
    try:
        await scheduler_manager.initialize()
    except Exception as e:
        logger.error("Failed to initialize scheduler manager", error=str(e))

    # Auto-load Skills from YAML files on startup
    try:
        async with async_session() as session:
            count = await load_skills_from_directory(SKILLS_DIR, session)
            await session.commit()
            logger.info("Skills loaded from YAML", count=count)
    except Exception as e:
        logger.warning("Failed to auto-load skills (DB may not be ready)", error=str(e))

    # Auto-load Roles from YAML files on startup
    try:
        async with async_session() as session:
            count = await load_roles_from_directory(ROLES_DIR, session)
            await session.commit()
            logger.info("Roles loaded from YAML", count=count)
    except Exception as e:
        logger.warning("Failed to auto-load roles", error=str(e))

    # Start Agent Pool Sentinel Daemon
    try:
        from src.core.agent.pool import agent_pool
        agent_pool.start_sentinel()
    except Exception as e:
        logger.error("Failed to start Agent Sentinel Daemon", error=str(e))

    # Start Central Brain Coordinator
    try:
        from src.core.orchestrator.central_brain import central_brain
        await central_brain.start()
    except Exception as cb_err:
        logger.error("Failed to start Central Brain Coordinator", error=str(cb_err))

    # Subscribe to workflow events for multi-channel notifications
    try:
        from src.core.agent.pool import agent_bus
        from src.core.governance.notifications import dispatch_workflow_notification
        
        async def on_workflow_event(message: dict):
            try:
                topic = message.get("topic")
                payload = message.get("payload", {})
                
                # If topic is dag_updates, check if the status changed to failed
                if topic == "dag_updates":
                    if payload.get("dag_status") == "failed":
                        await dispatch_workflow_notification(
                            event_type="workflow.failed",
                            dag_id=payload.get("dag_id"),
                            error=payload.get("error") or "DAG execution failed",
                            tenant_id=payload.get("tenant_id"),
                            timestamp=payload.get("timestamp")
                        )
                else:
                    await dispatch_workflow_notification(
                        event_type=topic,
                        dag_id=payload.get("dag_id"),
                        node_id=payload.get("node_id"),
                        error=payload.get("error"),
                        tenant_id=payload.get("tenant_id"),
                        timestamp=payload.get("timestamp")
                    )
            except Exception as notify_err:
                logger.error("Error in workflow notification handler", error=str(notify_err))

        await agent_bus.subscribe("workflow.suspended", on_workflow_event)
        await agent_bus.subscribe("dag_updates", on_workflow_event)
        logger.info("Subscribed to workflow events for multi-channel notifications")
    except Exception as sub_err:
        logger.error("Failed to subscribe to workflow events on startup", error=str(sub_err))

    # Auto-resume running or paused DAGs in the background with multi-tenant and node self-healing support
    try:
        import asyncio
        from src.api.routes.dags import restore_running_dags
        # Execute restoration task in background after a short delay to allow system initialization
        async def trigger_recovery_with_delay():
            await asyncio.sleep(2.0)
            await restore_running_dags()
            
        asyncio.create_task(trigger_recovery_with_delay())
    except Exception as e:
        logger.error("Failed to trigger DAG recovery on startup", error=str(e))

    yield
    # Unsubscribe from workflow events
    try:
        from src.core.agent.pool import agent_bus
        await agent_bus.unsubscribe("workflow.suspended", on_workflow_event)
        await agent_bus.unsubscribe("dag_updates", on_workflow_event)
        logger.info("Unsubscribed from workflow events successfully")
    except Exception as unsub_err:
        logger.error("Failed to unsubscribe from workflow events on shutdown", error=str(unsub_err))

    # Stop Agent Pool Sentinel Daemon
    try:
        from src.core.agent.pool import agent_pool
        await agent_pool.stop_sentinel()
    except Exception as e:
        logger.error("Failed to stop Agent Sentinel Daemon", error=str(e))

    # Stop Central Brain Coordinator
    try:
        from src.core.orchestrator.central_brain import central_brain
        await central_brain.stop()
    except Exception as cb_err:
        logger.error("Failed to stop Central Brain Coordinator", error=str(cb_err))

    # Stop Scheduler Manager
    try:
        await scheduler_manager.shutdown()
    except Exception as sched_err:
        logger.error("Failed to stop Scheduler Manager on shutdown", error=str(sched_err))

    # Close Agent Message Bus
    try:
        from src.core.agent.pool import agent_bus
        await agent_bus.close()
        logger.info("Agent Message Bus closed successfully")
    except Exception as bus_close_err:
        logger.error("Failed to close Agent Message Bus on shutdown", error=str(bus_close_err))

    # Close RAG Memory connections
    try:
        from src.core.memory.rag_manager import rag_manager
        rag_manager.close()
        logger.info("RAG memory collections and client connections closed successfully")
    except Exception as rag_close_err:
        logger.error("Failed to close RAG memory on shutdown", error=str(rag_close_err))

    # Close Redis Connections
    try:
        from src.core.redis_pool import close_redis_connections
        await close_redis_connections()
        logger.info("Redis connections closed successfully")
    except Exception as redis_err:
        logger.error("Failed to close Redis connections on shutdown", error=str(redis_err))

    # Close Database Engine Connections
    try:
        from src.database import close_db_connections
        await close_db_connections()
        logger.info("Database connections closed successfully")
    except Exception as db_err:
        logger.error("Failed to close Database connections on shutdown", error=str(db_err))

    logger.info("AgentDeepDive shutting down")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Multi-Agent Orchestration Platform for Super Engineering",
    lifespan=lifespan,
)

# CORS middleware
origins = list(settings.cors_origins)
if "*" in origins and not settings.debug:
    logger.warning(
        "CORS wildcard '*' detected in non-debug mode. "
        "Forcing CORS origins to empty (disallowing all cross-origin requests) for security. "
        "Please configure AGENTDEEP_CORS_ORIGINS environment variable with explicit domains."
    )
    origins = []

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Multi-Tenant context management middleware
from src.core.auth.context import current_tenant_id
from src.core.auth.security import decode_jwt_token
import uuid

@app.middleware("http")
async def tenant_context_middleware(request, call_next):
    t_id = None
    auth_header = request.headers.get("Authorization")
    x_api_key = request.headers.get("X-API-Key")
    
    token = None
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
    elif x_api_key:
        token = x_api_key
        
    if token:
        if settings.api_key and token == settings.api_key:
            t_id = uuid.UUID("00000000-0000-0000-0000-000000000000")
        else:
            try:
                payload = decode_jwt_token(token)
                if payload and "tenant_id" in payload:
                    t_id = uuid.UUID(payload["tenant_id"])
            except Exception:
                pass
    else:
        t_id = None
            
    token_val = current_tenant_id.set(t_id)
    try:
        response = await call_next(request)
        return response
    finally:
        current_tenant_id.reset(token_val)


# Register routes
app.include_router(health.router, tags=["Health"])
app.include_router(auth.router, prefix="/api/v1", tags=["Authentication"])
app.include_router(skills.router, prefix="/api/v1", tags=["Skills"], dependencies=[Depends(verify_api_key), Depends(verify_opa_api_permission)])
app.include_router(roles.router, prefix="/api/v1", tags=["Roles"], dependencies=[Depends(verify_api_key), Depends(verify_opa_api_permission)])
app.include_router(tasks.router, prefix="/api/v1", tags=["Tasks"], dependencies=[Depends(verify_api_key), Depends(verify_opa_api_permission)])
app.include_router(dags.router, prefix="/api/v1", tags=["DAGs"], dependencies=[Depends(verify_api_key), Depends(verify_opa_api_permission)])
app.include_router(brain.router, prefix="/api/v1", tags=["Central Brain"], dependencies=[Depends(verify_api_key), Depends(verify_opa_api_permission)])
app.include_router(budget.router, prefix="/api/v1", tags=["Budget"], dependencies=[Depends(verify_api_key), Depends(verify_opa_api_permission)])
app.include_router(approvals.router, prefix="/api/v1", tags=["Approvals"])
app.include_router(evolution.router, prefix="/api/v1", tags=["Evolution"], dependencies=[Depends(verify_api_key), Depends(verify_opa_api_permission)])
app.include_router(webhooks.router, prefix="/api/v1", tags=["Webhooks"], dependencies=[Depends(verify_api_key), Depends(verify_opa_api_permission)])
app.include_router(schedules.router, prefix="/api/v1", tags=["Schedules"], dependencies=[Depends(verify_api_key), Depends(verify_opa_api_permission)])
app.include_router(websocket.router, prefix="/api/v1", tags=["WebSocket"])
app.include_router(workspaces.router, prefix="/api/v1", tags=["Workspaces"], dependencies=[Depends(verify_api_key), Depends(verify_opa_api_permission)])
app.include_router(opa.router, prefix="/api/v1", tags=["OPA Governance"], dependencies=[Depends(verify_api_key), Depends(verify_opa_api_permission)])
app.include_router(audit.router, prefix="/api/v1", tags=["Audit Observability"], dependencies=[Depends(verify_api_key), Depends(verify_opa_api_permission)])

