"""Celery background task execution performance monitoring using Celery signals."""

import time
import json
import traceback
from datetime import datetime, timezone
import structlog
from celery.signals import task_prerun, task_postrun, task_failure

from src.core.redis_pool import get_redis_client, get_async_redis_client

logger = structlog.get_logger()

STATS_PREFIX = "agentdeep:celery:stats:"


@task_prerun.connect
def on_task_prerun(task_id, task, args, kwargs, **keyw):
    """Signal fired right before a Celery task starts execution."""
    task.start_time = time.perf_counter()
    logger.info(
        "Celery task started",
        task_id=task_id,
        task_name=task.name,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@task_postrun.connect
def on_task_postrun(task_id, task, args, kwargs, retval, state, **keyw):
    """Signal fired right after a Celery task finishes execution (success or failure)."""
    start_time = getattr(task, "start_time", None)
    if start_time is None:
        return

    duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
    task_name = task.name or "unknown"
    status = state or "UNKNOWN"

    logger.info(
        "Celery task finished",
        task_id=task_id,
        task_name=task_name,
        duration_ms=duration_ms,
        status=status,
    )

    # Update Redis statistics synchronously (Celery signals run in worker subprocess)
    try:
        r = get_redis_client()
        key = f"{STATS_PREFIX}{task_name}"
        
        # Increment run counts
        r.hincrby(key, "total_runs", 1)
        if status == "SUCCESS":
            r.hincrby(key, "success_runs", 1)
        else:
            r.hincrby(key, "failure_runs", 1)

        # Calculate moving average duration
        current_avg = r.hget(key, "avg_duration_ms")
        total_runs = int(r.hget(key, "total_runs") or 1)
        
        if current_avg:
            try:
                avg = float(current_avg)
                # Weighted average calculation
                new_avg = round(((avg * (total_runs - 1)) + duration_ms) / total_runs, 2)
            except ValueError:
                new_avg = duration_ms
        else:
            new_avg = duration_ms

        # Set last execution details
        r.hset(key, mapping={
            "avg_duration_ms": str(new_avg),
            "last_duration_ms": str(duration_ms),
            "last_run_time": datetime.now(timezone.utc).isoformat(),
            "last_run_status": status,
        })
    except Exception as redis_err:
        logger.error(
            "Failed to save Celery task performance metrics to Redis",
            task_name=task_name,
            error=str(redis_err),
        )


@task_failure.connect
def on_task_failure(task_id, exception, args, kwargs, traceback_obj, sender, **keyw):
    """Signal fired when a task fails execution."""
    task_name = sender.name if sender else "unknown"
    error_msg = str(exception)
    tb_str = "".join(traceback.format_tb(traceback_obj)) if traceback_obj else ""

    logger.error(
        "Celery task execution failed",
        task_id=task_id,
        task_name=task_name,
        error=error_msg,
    )

    try:
        r = get_redis_client()
        key = f"{STATS_PREFIX}{task_name}"
        r.hset(key, mapping={
            "last_error": error_msg,
            "last_error_traceback": tb_str,
            "last_error_time": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as redis_err:
        logger.error(
            "Failed to record Celery task error details to Redis",
            task_name=task_name,
            error=str(redis_err),
        )


async def get_celery_task_stats() -> dict[str, dict]:
    """Retrieve all collected Celery task execution statistics from Redis asynchronously."""
    r = get_async_redis_client()
    stats = {}
    try:
        # Scan for all stats keys
        async for key in r.scan_iter(f"{STATS_PREFIX}*"):
            task_name = key.replace(STATS_PREFIX, "")
            data = await r.hgetall(key)
            if data:
                stats[task_name] = {
                    "total_runs": int(data.get("total_runs", 0)),
                    "success_runs": int(data.get("success_runs", 0)),
                    "failure_runs": int(data.get("failure_runs", 0)),
                    "avg_duration_ms": float(data.get("avg_duration_ms", 0.0)),
                    "last_duration_ms": float(data.get("last_duration_ms", 0.0)),
                    "last_run_time": data.get("last_run_time"),
                    "last_run_status": data.get("last_run_status"),
                    "last_error": data.get("last_error"),
                    "last_error_time": data.get("last_error_time"),
                }
    except Exception as err:
        logger.error("Failed to query Celery task stats from Redis", error=str(err))
    return stats
