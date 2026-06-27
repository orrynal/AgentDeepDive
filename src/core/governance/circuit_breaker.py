"""State-machine resource circuit breaker protecting scheduler from host and system overloads."""

import os
import time
import asyncio
from typing import Tuple, Dict, List
import structlog

from src.config import settings
from src.core.orchestrator.central_brain import central_brain
from src.core.governance.notifications.dispatcher import dispatch_workflow_notification
from src.core.agent.pool import agent_bus

logger = structlog.get_logger()


class CircuitBreakerState:
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class ResourceCircuitBreaker:
    """Resource-aware Circuit Breaker.
    
    Protects the system by blocking/pausing scheduled task triggers
    under critical conditions (CPU overload, memory exhaustion, execution failures).
    """
    
    def __init__(self):
        self.state = CircuitBreakerState.CLOSED
        self.last_state_change = time.time()
        self.failure_count = 0
        self.success_count = 0
        self.tripped_at = 0.0
        self.cooldown_sec = 15.0  # Cooldown before testing half-open state
        self.failure_threshold = 3  # Failures before tripping
        
        # Threshold bounds
        self.max_cpu_ratio = 0.90
        self.max_mem_ratio = 0.90
        self.max_sessions = 5

    def get_system_cpu_ratio(self) -> float:
        """Gets normalized load average of the system on Linux."""
        try:
            if hasattr(self, "_mock_cpu_ratio"):
                return getattr(self, "_mock_cpu_ratio")
                
            if os.path.exists("/proc/loadavg"):
                with open("/proc/loadavg", "r") as f:
                    load = float(f.read().split()[0])
                cpus = os.cpu_count() or 1
                return min(1.0, load / cpus)
        except Exception:
            pass
        return 0.1

    def get_system_mem_ratio(self) -> float:
        """Gets system memory usage ratio on Linux."""
        try:
            if hasattr(self, "_mock_mem_ratio"):
                return getattr(self, "_mock_mem_ratio")

            if os.path.exists("/proc/meminfo"):
                with open("/proc/meminfo", "r") as f:
                    lines = f.readlines()
                mem_total = 0
                mem_available = 0
                for line in lines:
                    if line.strip().startswith("MemTotal:"):
                        mem_total = int(line.split()[1])
                    elif line.strip().startswith("MemAvailable:"):
                        mem_available = int(line.split()[1])
                if mem_total > 0:
                    return (mem_total - mem_available) / mem_total
        except Exception:
            pass
        return 0.1

    async def get_active_sessions_count(self) -> int:
        """Fetch concurrent active supervised DAG sessions."""
        try:
            sessions = await central_brain.get_active_sessions()
            return len(sessions)
        except Exception:
            return 0

    async def check_resources(self) -> Tuple[bool, str]:
        """Checks if any configured resource limit is exceeded."""
        cpu = self.get_system_cpu_ratio()
        if cpu > self.max_cpu_ratio:
            return False, f"CPU usage too high ({cpu:.1%})"
            
        mem = self.get_system_mem_ratio()
        if mem > self.max_mem_ratio:
            return False, f"Memory usage too high ({mem:.1%})"
            
        sessions = await self.get_active_sessions_count()
        if sessions >= self.max_sessions:
            return False, f"Active task sessions limit reached ({sessions}/{self.max_sessions})"
            
        return True, "All resources normal"

    async def allow_execution(self, task_description: str, task_id: str | None = None, is_manual: bool = False, force: bool = False) -> Tuple[bool, str]:
        """Determines if the scheduler is allowed to trigger a task."""
        if force:
            return True, "Forced override"

        now = time.time()

        # State transition: OPEN -> HALF_OPEN
        if self.state == CircuitBreakerState.OPEN:
            if now - self.tripped_at > self.cooldown_sec:
                await self._transition_to(CircuitBreakerState.HALF_OPEN, "Cooldown period elapsed")
            else:
                return False, f"Circuit Breaker is OPEN (tripped due to overload/failures)"

        # Check resource constraints
        resources_ok, resource_reason = await self.check_resources()
        if not resources_ok:
            if self.state != CircuitBreakerState.OPEN:
                await self._transition_to(CircuitBreakerState.OPEN, f"Resource constraint triggered: {resource_reason}")
            return False, resource_reason

        # HALF_OPEN state permits 1 trial execution
        if self.state == CircuitBreakerState.HALF_OPEN:
            logger.info("Circuit Breaker in HALF-OPEN state, permitting trial execution")
            return True, "Trial execution"

        return True, "Circuit Breaker CLOSED"

    async def record_success(self):
        """Record success to reset circuit state."""
        if self.state == CircuitBreakerState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= 1:
                await self._transition_to(CircuitBreakerState.CLOSED, "Trial execution succeeded")
        self.failure_count = 0

    async def record_failure(self, error_msg: str):
        """Record failure to trip circuit state."""
        self.failure_count += 1
        self.success_count = 0
        
        if self.state == CircuitBreakerState.HALF_OPEN:
            await self._transition_to(CircuitBreakerState.OPEN, f"Trial execution failed: {error_msg}")
        elif self.state == CircuitBreakerState.CLOSED and self.failure_count >= self.failure_threshold:
            await self._transition_to(CircuitBreakerState.OPEN, f"Consecutive failures exceeded threshold ({self.failure_count})")

    async def _transition_to(self, new_state: str, reason: str):
        """Execute state transition, log events, and dispatch alarms."""
        old_state = self.state
        self.state = new_state
        self.last_state_change = time.time()
        
        if new_state == CircuitBreakerState.OPEN:
            self.tripped_at = time.time()

        logger.warn("Circuit Breaker state transitioned", old_state=old_state, new_state=new_state, reason=reason)
        
        # Publish notification warning to agent bus
        await agent_bus.publish(
            topic="security_alert",
            sender_id="circuit_breaker",
            payload={
                "event_type": "circuit_breaker_transition",
                "old_state": old_state,
                "new_state": new_state,
                "reason": reason,
                "timestamp": time.time()
            }
        )
        
        # Trigger global notifications
        try:
            await dispatch_workflow_notification(
                workflow_id="circuit_breaker",
                event_type="circuit_breaker_transition",
                details={
                    "old_state": old_state,
                    "new_state": new_state,
                    "reason": reason
                }
            )
        except Exception as e:
            logger.error("Failed to send circuit breaker transition notification", error=str(e))


resource_circuit_breaker = ResourceCircuitBreaker()
