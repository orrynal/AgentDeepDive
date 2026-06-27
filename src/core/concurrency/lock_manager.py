"""Distributed File Lock Manager — Redis-backed concurrency control.

Implements the 3-layer hybrid strategy:
- Layer 1: Module-level partition ownership (implicit via skill assignment)
- Layer 2: File-level optimistic locking with version tracking
- Layer 3: Dynamic priority arbitration with preemption
"""

import time
import abc
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

import redis.asyncio as aioredis
import structlog

from src.config import settings

logger = structlog.get_logger()

LOCK_PREFIX = "agentdeep:lock:"
QUEUE_PREFIX = "agentdeep:queue:"
PREEMPT_THRESHOLD = 30  # Priority diff to trigger preemption


@dataclass
class LockResult:
    granted: bool
    file_path: str
    holder_agent: str = ""
    queue_position: int = 0
    preempted_agent: str = ""
    version: str = ""


@dataclass
class LockInfo:
    file_path: str
    holder_agent: str
    task_id: str
    priority: int
    acquired_at: float
    ttl_sec: int
    version: str


class LockManagerStrategy(abc.ABC):
    """Abstract Strategy interface for Lock Management."""

    @abc.abstractmethod
    async def acquire(
        self,
        file_path: str,
        agent_id: str,
        task_id: str,
        priority: int = 50,
        ttl_sec: int = 300,
    ) -> LockResult:
        pass

    @abc.abstractmethod
    async def release(self, file_path: str, agent_id: str) -> Optional[str]:
        pass

    @abc.abstractmethod
    async def get_lock_info(self, file_path: str) -> Optional[LockInfo]:
        pass

    @abc.abstractmethod
    async def list_locks(self) -> List[LockInfo]:
        pass

    @abc.abstractmethod
    async def release_all_for_agent(self, agent_id: str):
        pass

    @abc.abstractmethod
    async def close(self):
        pass


class LocalFileLockStrategy(LockManagerStrategy):
    """Lightweight local file lock strategy using filelock package."""

    def _get_lock_paths(self, file_path: str):
        import hashlib
        import os
        from pathlib import Path
        lock_dir = Path(".locks")
        os.makedirs(lock_dir, exist_ok=True)
        h = hashlib.sha256(file_path.encode("utf-8")).hexdigest()
        lock_file = lock_dir / f"{h}.lock"
        meta_file = lock_dir / f"{h}.json"
        queue_file = lock_dir / f"{h}_queue.json"
        return lock_file, meta_file, queue_file

    async def acquire(
        self,
        file_path: str,
        agent_id: str,
        task_id: str,
        priority: int = 50,
        ttl_sec: int = 300,
    ) -> LockResult:
        import os
        import json
        from filelock import FileLock, Timeout
        lock_file, meta_file, queue_file = self._get_lock_paths(file_path)
        fl = FileLock(str(lock_file))
        try:
            with fl.acquire(timeout=2.0):
                now = time.time()
                is_held = False
                current_holder = ""
                current_priority = 50
                current_task = ""
                current_version = ""

                if os.path.exists(meta_file):
                    try:
                        with open(meta_file, "r") as f:
                            meta = json.load(f)
                        acquired_at = meta.get("acquired_at", 0)
                        ttl = meta.get("ttl_sec", 300)
                        if now - acquired_at < ttl:
                            is_held = True
                            current_holder = meta.get("holder_agent", "")
                            current_priority = int(meta.get("priority", 50))
                            current_task = meta.get("task_id", "")
                            current_version = meta.get("version", "")
                            if current_holder == agent_id:
                                logger.info("Lock already held by self (lightweight)", file=file_path, agent=agent_id)
                                return LockResult(granted=True, file_path=file_path, holder_agent=agent_id, version=current_version)
                        else:
                            os.remove(meta_file)
                    except Exception:
                        pass

                version = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

                if not is_held:
                    meta = {
                        "file_path": file_path,
                        "holder_agent": agent_id,
                        "task_id": task_id,
                        "priority": priority,
                        "acquired_at": now,
                        "ttl_sec": ttl_sec,
                        "version": version
                    }
                    with open(meta_file, "w") as f:
                        json.dump(meta, f)
                    logger.info("Lock acquired (lightweight)", file=file_path, agent=agent_id)
                    return LockResult(granted=True, file_path=file_path, holder_agent=agent_id, version=version)

                priority_diff = priority - current_priority
                if priority_diff > PREEMPT_THRESHOLD:
                    old_holder = current_holder
                    meta = {
                        "file_path": file_path,
                        "holder_agent": agent_id,
                        "task_id": task_id,
                        "priority": priority,
                        "acquired_at": now,
                        "ttl_sec": ttl_sec,
                        "version": version
                    }
                    with open(meta_file, "w") as f:
                        json.dump(meta, f)
                    logger.warning(
                        "Lock preempted (lightweight)",
                        file=file_path,
                        new_holder=agent_id,
                        old_holder=old_holder,
                        priority_diff=priority_diff,
                    )
                    return LockResult(
                        granted=True, file_path=file_path,
                        holder_agent=agent_id, preempted_agent=old_holder,
                        version=version
                    )
                else:
                    queue = []
                    if os.path.exists(queue_file):
                        try:
                            with open(queue_file, "r") as f:
                                queue = json.load(f)
                        except Exception:
                            pass
                    
                    queue = [item for item in queue if not (item.get("agent_id") == agent_id and item.get("task_id") == task_id)]
                    queue.append({
                        "agent_id": agent_id,
                        "task_id": task_id,
                        "priority": priority
                    })
                    queue.sort(key=lambda x: (-x["priority"], x["agent_id"]))
                    with open(queue_file, "w") as f:
                        json.dump(queue, f)

                    rank = 0
                    for idx, item in enumerate(queue):
                        if item["agent_id"] == agent_id and item["task_id"] == task_id:
                            rank = idx
                            break

                    logger.info(
                        "Lock queued (lightweight)",
                        file=file_path, agent=agent_id,
                        position=rank, current_holder=current_holder,
                    )
                    return LockResult(
                        granted=False, file_path=file_path,
                        holder_agent=current_holder, queue_position=rank + 1,
                        version=current_version
                    )
        except Timeout:
            logger.error("Lock acquisition critical section timeout", file=file_path)
            return LockResult(granted=False, file_path=file_path)

    async def release(self, file_path: str, agent_id: str) -> Optional[str]:
        import os
        import json
        from filelock import FileLock, Timeout
        lock_file, meta_file, queue_file = self._get_lock_paths(file_path)
        fl = FileLock(str(lock_file))
        try:
            with fl.acquire(timeout=2.0):
                if not os.path.exists(meta_file):
                    return None
                try:
                    with open(meta_file, "r") as f:
                        meta = json.load(f)
                    if meta.get("holder_agent") != agent_id:
                        logger.warning("Release attempt by non-holder (lightweight)", file=file_path,
                                      requester=agent_id, actual_holder=meta.get("holder_agent"))
                        return None
                except Exception:
                    return None

                try:
                    os.remove(meta_file)
                except Exception:
                    pass
                logger.info("Lock released (lightweight)", file=file_path, agent=agent_id)

                queue = []
                if os.path.exists(queue_file):
                    try:
                        with open(queue_file, "r") as f:
                            queue = json.load(f)
                    except Exception:
                        pass
                
                if queue:
                    next_item = queue.pop(0)
                    with open(queue_file, "w") as f:
                        json.dump(queue, f)
                    
                    next_agent = next_item["agent_id"]
                    next_task = next_item["task_id"]
                    next_priority = next_item["priority"]

                    version = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
                    meta = {
                        "file_path": file_path,
                        "holder_agent": next_agent,
                        "task_id": next_task,
                        "priority": next_priority,
                        "acquired_at": time.time(),
                        "ttl_sec": 300,
                        "version": version
                    }
                    with open(meta_file, "w") as f:
                        json.dump(meta, f)
                    logger.info("Lock promoted (lightweight)", file=file_path, new_holder=next_agent)
                    return next_agent
                return None
        except Timeout:
            logger.error("Lock release critical section timeout", file=file_path)
            return None

    async def get_lock_info(self, file_path: str) -> Optional[LockInfo]:
        import os
        import json
        lock_file, meta_file, _ = self._get_lock_paths(file_path)
        if not os.path.exists(meta_file):
            return None
        try:
            with open(meta_file, "r") as f:
                meta = json.load(f)
            now = time.time()
            acquired_at = meta.get("acquired_at", 0)
            ttl = meta.get("ttl_sec", 300)
            if now - acquired_at >= ttl:
                return None
            return LockInfo(
                file_path=file_path,
                holder_agent=meta["holder_agent"],
                task_id=meta.get("task_id", ""),
                priority=int(meta.get("priority", 50)),
                acquired_at=float(acquired_at),
                ttl_sec=int(ttl),
                version=meta.get("version", ""),
            )
        except Exception:
            return None

    async def list_locks(self) -> List[LockInfo]:
        import os
        import json
        from pathlib import Path
        locks = []
        lock_dir = Path(".locks")
        if not lock_dir.exists():
            return locks
        for p in lock_dir.glob("*.json"):
            if p.name.endswith("_queue.json"):
                continue
            try:
                with open(p, "r") as f:
                    meta = json.load(f)
                now = time.time()
                acquired_at = meta.get("acquired_at", 0)
                ttl = meta.get("ttl_sec", 300)
                if now - acquired_at < ttl:
                    locks.append(LockInfo(
                        file_path=meta.get("file_path", "unknown"),
                        holder_agent=meta["holder_agent"],
                        task_id=meta.get("task_id", ""),
                        priority=int(meta.get("priority", 50)),
                        acquired_at=float(acquired_at),
                        ttl_sec=int(ttl),
                        version=meta.get("version", ""),
                    ))
            except Exception:
                pass
        return locks

    async def release_all_for_agent(self, agent_id: str):
        for info in await self.list_locks():
            if info.holder_agent == agent_id:
                await self.release(info.file_path, agent_id)

    async def close(self):
        pass


class RedisLockStrategy(LockManagerStrategy):
    """Redis-backed distributed lock strategy with atomic Lua script control."""

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or settings.redis_url
        self._redis: Optional[aioredis.Redis] = None

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            from src.core.redis_pool import get_async_redis_client
            self._redis = get_async_redis_client()
        return self._redis

    async def acquire(
        self,
        file_path: str,
        agent_id: str,
        task_id: str,
        priority: int = 50,
        ttl_sec: int = 300,
    ) -> LockResult:
        r = await self._get_redis()
        lock_key = f"{LOCK_PREFIX}{file_path}"
        queue_key = f"{QUEUE_PREFIX}{file_path}"

        if not hasattr(r, "eval"):
            # Fallback for mock clients in unit tests
            existing = await r.hgetall(lock_key)
            if not existing:
                await self._set_lock(r, file_path, agent_id, task_id, priority, ttl_sec)
                logger.info("Lock acquired (mock fallback)", file=file_path, agent=agent_id)
                return LockResult(granted=True, file_path=file_path, holder_agent=agent_id)

            current_priority = int(existing.get("priority", 50))
            current_holder = existing.get("holder_agent", "")
            if current_holder == agent_id:
                logger.info("Lock already held by self (mock fallback)", file=file_path, agent=agent_id)
                return LockResult(granted=True, file_path=file_path, holder_agent=agent_id)
            priority_diff = priority - current_priority

            if priority_diff > PREEMPT_THRESHOLD:
                old_holder = current_holder
                await self._set_lock(r, file_path, agent_id, task_id, priority, ttl_sec)
                logger.warning(
                    "Lock preempted (mock fallback)",
                    file=file_path,
                    new_holder=agent_id,
                    old_holder=old_holder,
                    priority_diff=priority_diff,
                )
                await r.publish(f"agentdeep:preempt:{old_holder}", f"preempted:{file_path}")
                return LockResult(
                    granted=True, file_path=file_path,
                    holder_agent=agent_id, preempted_agent=old_holder,
                )
            else:
                await r.zadd(queue_key, {f"{agent_id}:{task_id}": priority})
                pos = await r.zrevrank(queue_key, f"{agent_id}:{task_id}")
                logger.info(
                    "Lock queued (mock fallback)",
                    file=file_path, agent=agent_id,
                    position=pos, current_holder=current_holder,
                )
                return LockResult(
                    granted=False, file_path=file_path,
                    holder_agent=current_holder, queue_position=(pos or 0) + 1,
                )

        # Production-grade atomic Lua script execution
        lua_acquire = """
        local lock_key = KEYS[1]
        local queue_key = KEYS[2]
        local agent_id = ARGV[1]
        local task_id = ARGV[2]
        local priority = tonumber(ARGV[3])
        local ttl_sec = tonumber(ARGV[4])
        local preempt_threshold = tonumber(ARGV[5])
        local acquired_at = ARGV[6]
        local version = ARGV[7]

        local current_holder = redis.call('HGET', lock_key, 'holder_agent')
        if current_holder == agent_id then
            return {1, '', 0, 0}
        end
        if not current_holder then
            redis.call('HMSET', lock_key,
                'holder_agent', agent_id,
                'task_id', task_id,
                'priority', tostring(priority),
                'acquired_at', acquired_at,
                'ttl_sec', tostring(ttl_sec),
                'version', version
            )
            redis.call('EXPIRE', lock_key, ttl_sec)
            return {1, '', 0, 0}
        end

        local current_priority = tonumber(redis.call('HGET', lock_key, 'priority') or '50')
        local priority_diff = priority - current_priority

        if priority_diff > preempt_threshold then
            redis.call('HMSET', lock_key,
                'holder_agent', agent_id,
                'task_id', task_id,
                'priority', tostring(priority),
                'acquired_at', acquired_at,
                'ttl_sec', tostring(ttl_sec),
                'version', version
            )
            redis.call('EXPIRE', lock_key, ttl_sec)
            return {2, current_holder, 0, current_priority}
        else
            local member = agent_id .. ':' .. task_id
            redis.call('ZADD', queue_key, priority, member)
            local rank = redis.call('ZREVRANK', queue_key, member)
            return {3, current_holder, rank, current_priority}
        end
        """
        
        acquired_at = str(time.time())
        version = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        
        res = await r.eval(
            lua_acquire, 
            2, 
            lock_key, 
            queue_key, 
            agent_id, 
            task_id, 
            str(priority), 
            str(ttl_sec), 
            str(PREEMPT_THRESHOLD), 
            acquired_at, 
            version
        )
        
        status_code, holder, pos, old_p = res[0], res[1], res[2], res[3]
        if status_code == 1:
            logger.info("Lock acquired (atomic)", file=file_path, agent=agent_id)
            return LockResult(granted=True, file_path=file_path, holder_agent=agent_id)
        elif status_code == 2:
            logger.warning(
                "Lock preempted (atomic)",
                file=file_path,
                new_holder=agent_id,
                old_holder=holder,
                priority_diff=priority - old_p,
            )
            # Notify old holder via pub/sub
            await r.publish(
                f"agentdeep:preempt:{holder}",
                f"preempted:{file_path}",
            )
            return LockResult(
                granted=True, file_path=file_path,
                holder_agent=agent_id, preempted_agent=holder,
            )
        else:
            logger.info(
                "Lock queued (atomic)",
                file=file_path, agent=agent_id,
                position=pos, current_holder=holder,
            )
            return LockResult(
                granted=False, file_path=file_path,
                holder_agent=holder, queue_position=pos + 1,
            )

    async def release(self, file_path: str, agent_id: str) -> Optional[str]:
        r = await self._get_redis()
        lock_key = f"{LOCK_PREFIX}{file_path}"
        queue_key = f"{QUEUE_PREFIX}{file_path}"

        if not hasattr(r, "eval"):
            # Fallback for mock clients in unit tests
            current = await r.hget(lock_key, "holder_agent")
            if current != agent_id:
                logger.warning("Release attempt by non-holder (mock fallback)", file=file_path,
                              requester=agent_id, actual_holder=current)
                return None

            await r.delete(lock_key)
            logger.info("Lock released (mock fallback)", file=file_path, agent=agent_id)

            next_entry = await r.zpopmax(queue_key)
            if next_entry:
                member, score = next_entry[0]
                next_agent, next_task = member.rsplit(":", 1)
                await self._set_lock(r, file_path, next_agent, next_task, int(score))
                await r.publish(
                    f"agentdeep:lock_available:{next_agent}",
                    f"granted:{file_path}",
                )
                logger.info("Lock promoted (mock fallback)", file=file_path, new_holder=next_agent)
                return next_agent
            return None

        # Production-grade atomic Lua script execution
        lua_release = """
        local lock_key = KEYS[1]
        local queue_key = KEYS[2]
        local agent_id = ARGV[1]
        local acquired_at = ARGV[2]
        local version = ARGV[3]

        local current_holder = redis.call('HGET', lock_key, 'holder_agent')
        if current_holder ~= agent_id then
            return {0, ''}
        end

        redis.call('DEL', lock_key)

        local next_entry = redis.call('ZPOPMAX', queue_key)
        if next_entry and next_entry[1] then
            local member = next_entry[1]
            local score = tonumber(next_entry[2])
            
            local next_agent, next_task = string.match(member, "^(.+):([^:]+)$")
            if not next_agent then
                next_agent = member
                next_task = ""
            end
            
            redis.call('HMSET', lock_key,
                'holder_agent', next_agent,
                'task_id', next_task,
                'priority', tostring(score),
                'acquired_at', acquired_at,
                'ttl_sec', '300',
                'version', version
            )
            redis.call('EXPIRE', lock_key, 300)
            return {1, next_agent}
        end

        return {2, ''}
        """

        acquired_at = str(time.time())
        version = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

        res = await r.eval(
            lua_release,
            2,
            lock_key,
            queue_key,
            agent_id,
            acquired_at,
            version
        )

        status_code, next_agent = res[0], res[1]
        if status_code == 0:
            logger.warning("Release attempt by non-holder (atomic)", file=file_path,
                          requester=agent_id)
            return None
        elif status_code == 1:
            logger.info("Lock released and promoted (atomic)", file=file_path, agent=agent_id, new_holder=next_agent)
            await r.publish(
                f"agentdeep:lock_available:{next_agent}",
                f"granted:{file_path}",
            )
            return next_agent
        else:
            logger.info("Lock released (atomic)", file=file_path, agent=agent_id)
            return None

    async def get_lock_info(self, file_path: str) -> Optional[LockInfo]:
        r = await self._get_redis()
        data = await r.hgetall(f"{LOCK_PREFIX}{file_path}")
        if not data:
            return None
        return LockInfo(
            file_path=file_path,
            holder_agent=data["holder_agent"],
            task_id=data.get("task_id", ""),
            priority=int(data.get("priority", 50)),
            acquired_at=float(data.get("acquired_at", 0)),
            ttl_sec=int(data.get("ttl_sec", 300)),
            version=data.get("version", ""),
        )

    async def list_locks(self) -> List[LockInfo]:
        r = await self._get_redis()
        locks = []
        async for key in r.scan_iter(f"{LOCK_PREFIX}*"):
            file_path = key.replace(LOCK_PREFIX, "")
            info = await self.get_lock_info(file_path)
            if info:
                locks.append(info)
        return locks

    async def release_all_for_agent(self, agent_id: str):
        r = await self._get_redis()
        async for key in r.scan_iter(f"{LOCK_PREFIX}*"):
            holder = await r.hget(key, "holder_agent")
            if holder == agent_id:
                file_path = key.replace(LOCK_PREFIX, "")
                await self.release(file_path, agent_id)

    async def _set_lock(self, r, file_path, agent_id, task_id, priority, ttl_sec=300):
        lock_key = f"{LOCK_PREFIX}{file_path}"
        await r.hset(lock_key, mapping={
            "holder_agent": agent_id,
            "task_id": task_id,
            "priority": str(priority),
            "acquired_at": str(time.time()),
            "ttl_sec": str(ttl_sec),
            "version": datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
        })
        await r.expire(lock_key, ttl_sec)

    async def close(self):
        pass


class FileLockManager:
    """Redis-based distributed file lock with priority preemption (delegates to strategy)."""

    def __init__(self, redis_url: Optional[str] = None, strategy: Optional[LockManagerStrategy] = None):
        self.redis_url = redis_url or settings.redis_url
        self._strategy = strategy

    def get_strategy(self) -> LockManagerStrategy:
        if self._strategy is None:
            if settings.system_mode == "lightweight":
                self._strategy = LocalFileLockStrategy()
            else:
                self._strategy = RedisLockStrategy(self.redis_url)
        return self._strategy

    @property
    def _redis(self) -> Optional[aioredis.Redis]:
        strat = self.get_strategy()
        if isinstance(strat, RedisLockStrategy):
            return strat._redis
        return None

    @_redis.setter
    def _redis(self, value: Optional[aioredis.Redis]):
        strat = self.get_strategy()
        if isinstance(strat, RedisLockStrategy):
            strat._redis = value

    async def _get_redis(self) -> aioredis.Redis:
        strat = self.get_strategy()
        if isinstance(strat, RedisLockStrategy):
            return await strat._get_redis()
        from src.core.redis_pool import get_async_redis_client
        return get_async_redis_client()

    async def acquire(
        self,
        file_path: str,
        agent_id: str,
        task_id: str,
        priority: int = 50,
        ttl_sec: int = 300,
    ) -> LockResult:
        return await self.get_strategy().acquire(file_path, agent_id, task_id, priority, ttl_sec)

    async def release(self, file_path: str, agent_id: str) -> Optional[str]:
        return await self.get_strategy().release(file_path, agent_id)

    async def get_lock_info(self, file_path: str) -> Optional[LockInfo]:
        return await self.get_strategy().get_lock_info(file_path)

    async def list_locks(self) -> List[LockInfo]:
        return await self.get_strategy().list_locks()

    async def release_all_for_agent(self, agent_id: str):
        await self.get_strategy().release_all_for_agent(agent_id)

    async def close(self):
        if self._strategy is not None:
            await self._strategy.close()
            self._strategy = None


# Global singleton
lock_manager = FileLockManager()
