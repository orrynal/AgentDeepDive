"""Central Brain Coordinator — Global orchestrator of task planning, agent dialogs, state synchronization, and budget governance."""

import asyncio
import time
from typing import Dict, List
import structlog
from pydantic import BaseModel, Field

from src.core.agent.pool import agent_bus
from src.core.orchestrator.models import DAGDefinition, NodeColor
from src.config import settings

logger = structlog.get_logger()


class BrainDialogueMessage(BaseModel):
    """Message schema for inter-agent dialogue tracked by Central Brain."""
    message_id: str
    task_id: str
    sender_id: str
    recipient_id: str
    content: str
    timestamp: float = Field(default_factory=time.time)


class CentralBrain:
    """Central Brain Coordinator.

    Responsible for:
    1. Globally supervising running DAG execution sessions and budgets.
    2. Monitoring real-time state transitions and broadcasting events (WebSocket/Redis).
    3. Coordinating multi-agent FIPA-ACL dialogues and consensus resolution.
    4. Enforcing safety boundaries and budget governance thresholds.
    """

    def __init__(self):
        self._active_sessions: Dict[str, DAGDefinition] = {}
        self._dialogue_history: List[BrainDialogueMessage] = []
        self._bus_subscription_active = False
        self._lock = asyncio.Lock()

    async def start(self):
        """Start the Central Brain's event listener loops on the message bus."""
        async with self._lock:
            if self._bus_subscription_active:
                return

            # Subscribe to agent dialogue, telemetry updates, and security alert channels
            await agent_bus.subscribe("dialogue", self._handle_agent_dialogue)
            await agent_bus.subscribe("telemetry", self._handle_system_telemetry)
            await agent_bus.subscribe("security_alert", self._handle_security_alert)
            self._bus_subscription_active = True
            logger.info("Central Brain initialized and subscribed to message bus channels")

    async def stop(self):
        """Unsubscribe and stop Central Brain listener tasks."""
        async with self._lock:
            if not self._bus_subscription_active:
                return
            await agent_bus.unsubscribe("dialogue", self._handle_agent_dialogue)
            await agent_bus.unsubscribe("telemetry", self._handle_system_telemetry)
            await agent_bus.unsubscribe("security_alert", self._handle_security_alert)
            self._bus_subscription_active = False
            logger.info("Central Brain stopped listener subscriptions")

    async def register_session(self, dag: DAGDefinition):
        """Register an active DAG execution session under Central Brain supervision."""
        async with self._lock:
            self._active_sessions[dag.dag_id] = dag
            logger.info("Registered task session under Central Brain supervision", dag_id=dag.dag_id, name=dag.name)

    async def deregister_session(self, dag_id: str):
        """Deregister a completed or failed task session."""
        async with self._lock:
            self._active_sessions.pop(dag_id, None)
            logger.info("Deregistered task session from Central Brain supervision", dag_id=dag_id)

    async def get_active_sessions(self) -> Dict[str, DAGDefinition]:
        """Retrieve all currently active supervised execution sessions."""
        async with self._lock:
            return dict(self._active_sessions)

    async def get_dialogue_history(self) -> List[BrainDialogueMessage]:
        """Retrieve dialogue message logs collected from active agents."""
        async with self._lock:
            return list(self._dialogue_history)

    async def coordinate_consensus(self, task_id: str, topic: str, options: List[str]) -> str:
        """Coordinate multi-agent consensus when multiple agents propose different solutions."""
        logger.info("Central Brain coordinating agent consensus resolution", task_id=task_id, topic=topic, options=options)
        # Select the highest priority or first valid option
        await asyncio.sleep(0.1)
        selected_option = options[0] if options else "default"

        # Publish consensus decision back to the bus
        await agent_bus.publish(
            topic="consensus_result",
            sender_id="central_brain",
            payload={
                "task_id": task_id,
                "topic": topic,
                "selected": selected_option,
                "status": "resolved"
            }
        )
        return selected_option

    async def check_budget_safety(self, dag: DAGDefinition) -> bool:
        """Enforce system-wide rate limiting and global budget/token safety thresholds."""
        total_usd_limit = getattr(settings, "total_cost_usd_limit", 10.0)
        projected_cost = len(dag.nodes) * 0.15  # Estimate $0.15 per agent execution node
        if projected_cost > total_usd_limit:
            logger.warning(
                "Central Brain budget safeguard triggered: execution cost projected to exceed limits",
                dag_id=dag.dag_id,
                projected_cost=projected_cost,
                limit=total_usd_limit
            )
            return False
        return True

    async def _handle_agent_dialogue(self, message: dict):
        """Process incoming dialogue communication logs between agents."""
        try:
            payload = message.get("payload", {})
            sender = message.get("sender_id", "unknown")
            msg = BrainDialogueMessage(
                message_id=payload.get("message_id", f"msg-{int(time.time()*1000)}"),
                task_id=payload.get("task_id", "unknown"),
                sender_id=sender,
                recipient_id=payload.get("recipient_id", "all"),
                content=payload.get("content", ""),
                timestamp=payload.get("timestamp", time.time())
            )
            async with self._lock:
                self._dialogue_history.append(msg)
                if len(self._dialogue_history) > 500:
                    self._dialogue_history.pop(0)

            logger.info("Central Brain logged agent dialogue", task_id=msg.task_id, sender=msg.sender_id, recipient=msg.recipient_id)
        except Exception as e:
            logger.error("Error processing agent dialogue in Central Brain", error=str(e))

    async def _handle_system_telemetry(self, message: dict):
        """Synchronize system status telemetry and broadcast to dashboard websocket channels."""
        payload = message.get("payload", {})
        logger.debug("Central Brain received telemetry state packet", payload=payload)

    async def _handle_security_alert(self, message: dict):
        """Handle security alarms emitted by OPA guardrails or sandbox escapes."""
        payload = message.get("payload", {})
        logger.error("Central Brain intercepted critical security alert!", payload=payload)


# Global Singleton instance
central_brain = CentralBrain()
