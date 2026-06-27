"""Agent Pool Manager & Inter-Agent Communication Bus.

Provides worker pooling, resource load balancing, and a Redis-backed
pub/sub message bus for collaborative multi-agent execution.
"""

import asyncio
import json
from typing import Any, Callable, Coroutine
import redis.asyncio as aioredis
import structlog

from src.config import settings

logger = structlog.get_logger()

BUS_CHANNEL_PREFIX = "agentdeep:bus:"


class AgentPool:
    """Manages active Agent execution slots and load balancing."""

    def __init__(self, max_concurrency: int = 10):
        self.max_concurrency = max_concurrency
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._active_agents: dict[str, str] = {}  # agent_id -> task_id
        self._active_tasks: dict[str, asyncio.Task] = {}  # agent_id -> asyncio Task
        self._lock = asyncio.Lock()

    async def acquire_slot(self, agent_id: str, task_id: str) -> bool:
        """Acquire a slot in the pool. Blocks if pool is full."""
        logger.info("Agent requesting pool slot", agent_id=agent_id, task_id=task_id)
        
        # Wait for semaphore slot
        await self._semaphore.acquire()
        
        async with self._lock:
            self._active_agents[agent_id] = task_id
            
        logger.info(
            "Agent pool slot acquired",
            agent_id=agent_id,
            task_id=task_id,
            active_count=len(self._active_agents),
            max_slots=self.max_concurrency,
        )
        return True

    async def register_active_task(self, agent_id: str, task: asyncio.Task):
        """Register the running asyncio Task for an Agent."""
        async with self._lock:
            if agent_id in self._active_agents:
                self._active_tasks[agent_id] = task
                logger.debug("Registered active task for agent", agent_id=agent_id, task=task)

    async def release_slot(self, agent_id: str):
        """Release an agent's slot back to the pool."""
        async with self._lock:
            if agent_id in self._active_agents:
                task_id = self._active_agents.pop(agent_id)
                self._active_tasks.pop(agent_id, None)
                self._semaphore.release()
                logger.info(
                    "Agent pool slot released",
                    agent_id=agent_id,
                    task_id=task_id,
                    active_count=len(self._active_agents),
                )
            else:
                logger.warning("Attempted to release non-active agent slot", agent_id=agent_id)

    async def get_active_agents(self) -> dict[str, str]:
        """Get dict of currently active agents and their tasks."""
        async with self._lock:
            return dict(self._active_agents)

    async def get_active_tasks(self) -> dict[str, asyncio.Task]:
        """Get dict of currently active tasks."""
        async with self._lock:
            return dict(self._active_tasks)

    def start_sentinel(self, check_interval_sec: float = 5.0, expiry_threshold_sec: float = 8.0):
        """Start the background sentinel daemon to check active agent heartbeats."""
        if hasattr(self, "_sentinel_task") and self._sentinel_task and not self._sentinel_task.done():
            return
        self._sentinel_task = asyncio.create_task(self._sentinel_loop(check_interval_sec, expiry_threshold_sec))
        logger.info("Agent Sentinel Daemon started", interval=check_interval_sec, expiry_threshold=expiry_threshold_sec)

    async def stop_sentinel(self):
        """Stop the background sentinel daemon."""
        if hasattr(self, "_sentinel_task") and self._sentinel_task:
            self._sentinel_task.cancel()
            try:
                await self._sentinel_task
            except asyncio.CancelledError:
                pass
            logger.info("Agent Sentinel Daemon stopped")

    async def _sentinel_loop(self, check_interval_sec: float, expiry_threshold_sec: float):
        """Loop checking for zombie/dead agents based on Redis heartbeats."""
        import time
        from src.core.concurrency.lock_manager import lock_manager
        
        while True:
            try:
                await asyncio.sleep(check_interval_sec)
                
                # Get list of currently active agents
                active_agents = await self.get_active_agents()
                
                # GC orphaned sandbox resources (Docker containers and K8s Pods)
                if settings.docker_sandbox_enabled or settings.k8s_sandbox_enabled:
                    from src.core.workspace.runtime import sandbox_runtime_manager
                    try:
                        await sandbox_runtime_manager.prune_zombie_resources()
                    except Exception as prune_err:
                        logger.error("Failed to prune sandbox zombie resources", error=str(prune_err))
                
                if not active_agents:
                    continue
                    
                # Get redis client
                r = await agent_bus._get_redis()
                
                for agent_id, task_id in active_agents.items():
                    key = f"agentdeep:heartbeat:{agent_id}"
                    ts_str = await r.get(key)
                    
                    is_expired = False
                    if not ts_str:
                        is_expired = True
                    else:
                        try:
                            ts = float(ts_str)
                            if time.time() - ts > expiry_threshold_sec:
                                is_expired = True
                        except ValueError:
                            is_expired = True
                            
                    if is_expired:
                        logger.warning(
                            "Zombie agent detected (heartbeat expired)",
                            agent_id=agent_id,
                            task_id=task_id
                        )
                        
                        # 1. Cancel running python Task
                        active_tasks = await self.get_active_tasks()
                        task = active_tasks.get(agent_id)
                        if task and not task.done():
                            logger.info("Cancelling task for zombie agent", agent_id=agent_id, task=task)
                            task.cancel()
                            
                        # 2. Release lock and slot cleanups as fallback
                        try:
                            await lock_manager.release_all_for_agent(agent_id)
                        except Exception as lock_ex:
                            logger.error("Failed to release locks for zombie agent", agent_id=agent_id, error=str(lock_ex))
                            
                        try:
                            await self.release_slot(agent_id)
                        except Exception as slot_ex:
                            logger.error("Failed to release slot for zombie agent", agent_id=agent_id, error=str(slot_ex))
                            
                        # 3. Publish error/recovery event to bus
                        try:
                            await agent_bus.publish(
                                topic="recovery",
                                sender_id="sentinel",
                                payload={
                                    "status": "recovered",
                                    "agent_id": agent_id,
                                    "task_id": task_id,
                                    "reason": "heartbeat_timeout"
                                }
                            )
                        except Exception as bus_ex:
                            logger.error("Failed to publish recovery event to bus", error=str(bus_ex))
                            
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in Agent Sentinel Loop iteration", error=str(e))




class AgentMessageBus:
    """Redis-backed pub/sub bus for inter-agent communication."""

    def __init__(self, redis_url: str | None = None):
        self.redis_url = redis_url or settings.redis_url
        self._redis: aioredis.Redis | None = None
        self._pubsub: aioredis.client.PubSub | None = None
        self._listeners: dict[str, list[Callable[[dict], Coroutine[Any, Any, None]]]] = {}
        self._listen_task: asyncio.Task | None = None
        self._publish_semaphore = asyncio.Semaphore(20)

    async def _get_redis(self) -> aioredis.Redis:
        from src.core.redis_pool import get_async_redis_client
        self._redis = get_async_redis_client()
        return self._redis

    async def publish(self, topic: str, sender_id: str, payload: dict[str, Any]):
        """Publish a message to a topic on the bus."""
        from src.config import settings
        if settings.system_mode == "lightweight":
            logger.debug("Lightweight mode: bypassing Redis publish", topic=topic, sender=sender_id)
            callbacks = self._listeners.get(topic, [])
            for callback in callbacks:
                try:
                    message = {
                        "sender_id": sender_id,
                        "topic": topic,
                        "payload": payload,
                    }
                    asyncio.create_task(callback(message))
                except Exception as e:
                    logger.error("Failed to execute in-memory callback in lightweight mode", error=str(e))
            return

        async with self._publish_semaphore:
            r = await self._get_redis()
            message = {
                "sender_id": sender_id,
                "topic": topic,
                "payload": payload,
            }
            channel = f"{BUS_CHANNEL_PREFIX}{topic}"
            await r.publish(channel, json.dumps(message, ensure_ascii=False))
            logger.debug("Published to bus", topic=topic, sender=sender_id)

    async def subscribe(self, topic: str, callback: Callable[[dict], Coroutine[Any, Any, None]]):
        """Subscribe to a topic and register an async callback."""
        from src.config import settings
        if topic not in self._listeners:
            self._listeners[topic] = []
            
        self._listeners[topic].append(callback)
        logger.info("Subscribed to bus topic", topic=topic)

        if settings.system_mode == "lightweight":
            return

        r = await self._get_redis()
        channel = f"{BUS_CHANNEL_PREFIX}{topic}"

        # Start listening loop if not running or if event loop changed
        current_loop = asyncio.get_running_loop()
        if (self._listen_task is None 
            or self._listen_task.done() 
            or getattr(self, "_listen_loop_ref", None) != current_loop):
            self._pubsub = r.pubsub()
            await self._pubsub.psubscribe(**{f"{BUS_CHANNEL_PREFIX}*": self._handle_raw_message})
            self._listen_task = asyncio.create_task(self._listen_loop())
            self._listen_loop_ref = current_loop

    async def unsubscribe(self, topic: str, callback: Callable[[dict], Coroutine[Any, Any, None]]):
        """Unsubscribe a callback from a topic."""
        if topic in self._listeners:
            if callback in self._listeners[topic]:
                self._listeners[topic].remove(callback)
                logger.info("Unsubscribed callback from bus topic", topic=topic)
            if not self._listeners[topic]:
                del self._listeners[topic]

    async def _handle_raw_message(self, message: dict):
        """Internal callback for Redis pattern pub/sub."""
        if message.get("type") != "pmessage":
            return

        channel = message.get("channel", "")
        topic = channel.replace(BUS_CHANNEL_PREFIX, "")
        data_str = message.get("data", "")

        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            logger.error("Failed to parse pub/sub message payload", data=data_str)
            return

        callbacks = self._listeners.get(topic, [])
        for cb in callbacks:
            try:
                await cb(data)
            except Exception as e:
                logger.error("Error in bus subscription callback", topic=topic, error=str(e))

    async def _listen_loop(self):
        """Background loop reading from Redis pubsub with self-healing reconnection."""
        while True:
            try:
                if self._pubsub:
                    await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
                else:
                    await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Bus listen loop error, attempting self-healing reconnect", error=str(e))
                try:
                    if self._pubsub:
                        await self._pubsub.aclose()
                except Exception:
                    pass
                self._pubsub = None
                
                # Wait briefly before attempting to reconnect
                await asyncio.sleep(1.0)
                
                try:
                    r = await self._get_redis()
                    self._pubsub = r.pubsub()
                    if self._listeners:
                        await self._pubsub.psubscribe(**{f"{BUS_CHANNEL_PREFIX}*": self._handle_raw_message})
                        logger.info("Bus listen loop self-healing: Re-subscribed successfully")
                except Exception as reconnect_err:
                    logger.error("Bus self-healing reconnect failed, will retry", error=str(reconnect_err))

    async def close(self):
        """Close pub/sub connection."""
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
        if self._pubsub:
            await self._pubsub.aclose()


# Global Singletons
agent_pool = AgentPool()
agent_bus = AgentMessageBus()
