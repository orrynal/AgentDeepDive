"""Scheduler manager wrapping APScheduler with persistent task loading."""

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from src.core.scheduler.models import ScheduledTaskModel
from src.database import async_session

logger = structlog.get_logger()

async def execute_scheduled_task(task_description: str, task_id: str | None = None, force: bool = False):
    """Execution wrapper for scheduled tasks under circuit breaker protection."""
    logger.info("Executing scheduled task", task_id=task_id, task_description=task_description, force=force)
    
    # ── Celery Distributed Routing ────────────────────────
    from src.config import settings
    if settings.celery_enabled:
        try:
            from src.core.celery_tasks import execute_dag_task_async
            execute_dag_task_async.delay(task_description, task_id, force)
            logger.info("Dispatched scheduled task to Celery Queue", task_id=task_id, description=task_description)
            return
        except Exception as celery_err:
            logger.warning("Failed to dispatch scheduled task via Celery. Fallback to local execution", error=str(celery_err))
    
    # Check circuit breaker
    from src.core.governance.circuit_breaker import resource_circuit_breaker
    allowed, reason = await resource_circuit_breaker.allow_execution(task_description, task_id, force=force)
    if not allowed:
        logger.warning("Scheduled task trigger BLOCKED by Circuit Breaker", task_id=task_id, reason=reason)
        if task_id:
            import uuid
            from datetime import datetime, timezone
            from src.core.scheduler.models import ScheduledTaskModel
            try:
                async with async_session() as session:
                    task = await session.get(ScheduledTaskModel, uuid.UUID(task_id))
                    if task:
                        task.last_run_time = datetime.now(timezone.utc)
                        task.last_run_status = "BLOCKED"
                        await session.commit()
            except Exception as err:
                logger.warning("Failed to update schedule status to BLOCKED", task_id=task_id, error=str(err))
        return

    if task_id:
        import uuid
        from datetime import datetime, timezone
        from src.core.scheduler.models import ScheduledTaskModel
        try:
            async with async_session() as session:
                task = await session.get(ScheduledTaskModel, uuid.UUID(task_id))
                if task:
                    task.last_run_time = datetime.now(timezone.utc)
                    task.last_run_status = "RUNNING"
                    await session.commit()
        except Exception as err:
            logger.warning("Failed to update schedule status to RUNNING", task_id=task_id, error=str(err))
            
    status = "SUCCESS"
    try:
        from src.core.orchestrator.dag_engine import DAGEngine
        from src.core.orchestrator.task_splitter import split_task
        from src.core.skill.service import SkillService
        
        # 1. Decompose
        dag = await split_task(task_description)
        logger.info("Split scheduled task into DAG", dag_id=dag.dag_id, nodes=len(dag.nodes))
        
        # 2. Add to store
        from src.api.routes.dags import _dag_store
        _dag_store[dag.dag_id] = dag
        
        # 3. Execute
        async with async_session() as session:
            skill_svc = SkillService(session)
            engine = DAGEngine(skill_svc)
            result_dag = await engine.execute(dag)
            await session.commit()
            
        _dag_store[dag.dag_id] = result_dag
        logger.info("Scheduled task finished execution", dag_id=dag.dag_id, status=result_dag.status)
        if result_dag.status == "FAILED":
            status = "FAILED"
            await resource_circuit_breaker.record_failure("DAG status is FAILED")
        else:
            await resource_circuit_breaker.record_success()
    except Exception as e:
        logger.error("Error executing scheduled task", task_description=task_description, error=str(e))
        status = "FAILED"
        await resource_circuit_breaker.record_failure(str(e))
        
    if task_id:
        import uuid
        from src.core.scheduler.models import ScheduledTaskModel
        try:
            async with async_session() as session:
                task = await session.get(ScheduledTaskModel, uuid.UUID(task_id))
                if task:
                    task.last_run_status = status
                    await session.commit()
        except Exception as err:
            logger.warning("Failed to update schedule status with final result", task_id=task_id, error=str(err))

class SchedulerManager:
    """Manages scheduling and database integration for persistent background tasks."""
    
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self._initialized = False

    async def initialize(self):
        """Load all active scheduled tasks from the DB and register them."""
        if self._initialized:
            return
            
        logger.info("Initializing Scheduler Manager")
        
        # Ensure database tables are created automatically
        from src.core.scheduler.models import Base as SchedulerBase
        from src.database import engine
        async with engine.begin() as conn:
            await conn.run_sync(SchedulerBase.metadata.create_all)
            
        # Load tasks
        async with async_session() as session:
            result = await session.execute(
                select(ScheduledTaskModel).where(ScheduledTaskModel.is_active == True)
            )
            tasks = result.scalars().all()
            
        for t in tasks:
            self.register_task(t)
            
        self.scheduler.start()
        self._initialized = True
        logger.info("Scheduler Manager started", registered_jobs=len(tasks))

    def register_task(self, task: ScheduledTaskModel):
        """Add or update a task in the running APScheduler runner."""
        job_id = str(task.id)
        
        # Remove if already exists to update
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)
            
        try:
            trigger = CronTrigger.from_crontab(task.cron_expression)
            self.scheduler.add_job(
                execute_scheduled_task,
                trigger=trigger,
                args=[task.task_description, job_id],
                id=job_id,
                name=task.name
            )
            logger.info("Registered scheduled job", name=task.name, cron=task.cron_expression, job_id=job_id)
        except Exception as e:
            logger.error("Failed to register scheduled job", name=task.name, error=str(e))

    def remove_task(self, task_id: str):
        """Remove a task from the running scheduler runner."""
        if self.scheduler.get_job(task_id):
            self.scheduler.remove_job(task_id)
            logger.info("Removed scheduled job from runner", job_id=task_id)

    async def shutdown(self):
        """Shut down the running APScheduler runner."""
        if self._initialized:
            try:
                self.scheduler.shutdown()
            except Exception as e:
                logger.warning("Error shutting down scheduler", error=str(e))
            self._initialized = False
            logger.info("Scheduler Manager shut down successfully")

# Singleton instance
scheduler_manager = SchedulerManager()
