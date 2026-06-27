"""Token Budget Manager — 3-tier cost control and intelligent model routing.

Budget hierarchy:
  L1: Project monthly cap
  L2: Per-task budget limit
  L3: Per-step token limit

Model routing:
  Simple tasks → local free model
  Medium tasks → cloud mid-tier
  Complex tasks → cloud top-tier
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

import redis.asyncio as aioredis
import structlog

from src.config import settings

logger = structlog.get_logger()


# Model pricing ($ per 1M tokens) — estimates for Ollama cloud models
MODEL_PRICING = {
    "ollama/qwen3.5:2b":              {"input": 0.0, "output": 0.0},
    "ollama/qwen3-coder:480b-cloud":  {"input": 2.0, "output": 6.0},
    "ollama/deepseek-v3.1:671b-cloud":{"input": 2.5, "output": 8.0},
    "claude-sonnet-4-20250514":       {"input": 3.0, "output": 15.0},
    "gpt-4o":                         {"input": 2.5, "output": 10.0},
    "agnes-2.0-flash":                {"input": 0.075, "output": 0.30},
    "agnes-1.5-flash":                {"input": 0.075, "output": 0.30},
    "agnes-image-2.1-flash":          {"input": 0.15, "output": 0.60},
    "agnes-video-v2.0":               {"input": 1.0, "output": 4.0},
    "deepseek/deepseek-chat":         {"input": 0.14, "output": 0.28},
}

# Task type → recommended model tier and token budget
TASK_BUDGETS = {
    "formatting":     {"tier": "local",   "max_tokens": 1024000},
    "documentation":  {"tier": "local",   "max_tokens": 1024000},
    "analysis":       {"tier": "mid",     "max_tokens": 1024000},
    "test_generation":{"tier": "mid",     "max_tokens": 1024000},
    "refactor":       {"tier": "top",     "max_tokens": 1024000},
    "bug_fix":        {"tier": "top",     "max_tokens": 1024000},
    "architecture":   {"tier": "top",     "max_tokens": 1024000},
    "default":        {"tier": "mid",     "max_tokens": 1024000},
}

TIER_TO_MODEL = {
    "local": settings.local_model or "ollama/qwen3.5:2b",
    "mid":   settings.default_model,
    "top":   settings.fallback_model,
}


@dataclass
class BudgetApproval:
    approved: bool
    model: str = ""
    max_tokens: int = 0
    estimated_cost_usd: float = 0.0
    reason: str = ""
    suggestion: str = ""


@dataclass
class UsageRecord:
    model: str
    task_type: str
    tokens_input: int
    tokens_output: int
    cost_usd: float
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class TokenBudgetManager:
    """Manages token budgets and routes tasks to appropriate models with Redis persistence."""

    DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000000"

    def __init__(self, redis_url: str | None = None):
        self.redis_url = redis_url or settings.redis_url
        self.monthly_budget_usd = settings.monthly_budget_usd
        self.per_task_budget_usd = settings.per_task_budget_usd
        self._redis: aioredis.Redis | None = None
        # In-memory fallbacks in case Redis is unavailable, mapped by tenant_id
        self._in_memory_spent_usd: dict[str, float] = {}
        self._in_memory_records: dict[str, list[UsageRecord]] = {}

    async def _get_redis(self) -> aioredis.Redis | None:
        if self._redis is None:
            try:
                from src.core.redis_pool import get_async_redis_client
                self._redis = get_async_redis_client()
                await self._redis.ping()
            except Exception as e:
                logger.error("Failed to connect to Redis for budget manager, using in-memory fallback", error=str(e))
                self._redis = None
        return self._redis

    def _get_redis_spent_key(self, tenant_id: str) -> str:
        return f"agentdeep:budget:{tenant_id}:spent_usd"

    def _get_redis_records_key(self, tenant_id: str) -> str:
        return f"agentdeep:budget:{tenant_id}:usage_records"

    async def _get_spent_usd(self, tenant_id: str = DEFAULT_TENANT_ID) -> float:
        r = await self._get_redis()
        if r:
            try:
                key = self._get_redis_spent_key(tenant_id)
                val = await r.get(key)
                return float(val) if val else 0.0
            except Exception as e:
                logger.error("Redis budget read failed, using in-memory value", error=str(e))
        return self._in_memory_spent_usd.get(tenant_id, 0.0)

    async def _add_spent_usd(self, amount: float, tenant_id: str = DEFAULT_TENANT_ID):
        self._in_memory_spent_usd[tenant_id] = self._in_memory_spent_usd.get(tenant_id, 0.0) + amount
        r = await self._get_redis()
        if r:
            try:
                key = self._get_redis_spent_key(tenant_id)
                await r.incrbyfloat(key, amount)
            except Exception as e:
                logger.error("Redis budget write failed", error=str(e))

    async def _get_usage_records(self, tenant_id: str = DEFAULT_TENANT_ID) -> list[UsageRecord]:
        r = await self._get_redis()
        if r:
            try:
                key = self._get_redis_records_key(tenant_id)
                raw_records = await r.lrange(key, 0, -1)
                records = []
                for rr in raw_records:
                    data = json.loads(rr)
                    records.append(UsageRecord(**data))
                return records
            except Exception as e:
                logger.error("Redis budget records read failed, using in-memory records", error=str(e))
        return self._in_memory_records.get(tenant_id, [])

    async def _add_usage_record(self, record: UsageRecord, tenant_id: str = DEFAULT_TENANT_ID):
        if tenant_id not in self._in_memory_records:
            self._in_memory_records[tenant_id] = []
        self._in_memory_records[tenant_id].append(record)
        r = await self._get_redis()
        if r:
            try:
                key = self._get_redis_records_key(tenant_id)
                # Store up to 5000 records to prevent unbounded memory growth in Redis
                await r.rpush(key, json.dumps(asdict(record)))
                await r.ltrim(key, -5000, -1)
            except Exception as e:
                logger.error("Redis budget record save failed", error=str(e))

    async def request_budget(self, task_type: str = "default", tenant_id: str = DEFAULT_TENANT_ID) -> BudgetApproval:
        """Request a budget allocation for a task.

        Returns the recommended model and token limits.
        """
        config = TASK_BUDGETS.get(task_type, TASK_BUDGETS["default"])
        tier = config["tier"]
        max_tokens = config["max_tokens"]
        model = TIER_TO_MODEL.get(tier, settings.default_model)

        # Estimate cost
        pricing = MODEL_PRICING.get(model, {"input": 0, "output": 0})
        est_cost = (max_tokens * pricing["input"] + max_tokens * 0.3 * pricing["output"]) / 1_000_000

        # Check project budget
        spent_usd = await self._get_spent_usd(tenant_id)
        remaining = self.monthly_budget_usd - spent_usd
        if est_cost > remaining and tier != "local":
            # Try to downgrade to cheaper model
            if tier == "top":
                model = TIER_TO_MODEL["mid"]
                logger.warning("Budget constraint: downgraded to mid-tier", task_type=task_type)
            elif tier == "mid":
                model = TIER_TO_MODEL["local"]
                logger.warning("Budget constraint: downgraded to local", task_type=task_type)
            else:
                return BudgetApproval(
                    approved=False, reason="Monthly budget exhausted",
                    suggestion="Wait for budget reset or add more budget",
                )

        return BudgetApproval(
            approved=True,
            model=model,
            max_tokens=max_tokens,
            estimated_cost_usd=est_cost,
        )

    async def record_usage(self, model: str, task_type: str, tokens_in: int, tokens_out: int, tenant_id: str = DEFAULT_TENANT_ID):
        """Record actual token usage after task completion."""
        pricing = MODEL_PRICING.get(model, {"input": 0, "output": 0})
        cost = (tokens_in * pricing["input"] + tokens_out * pricing["output"]) / 1_000_000

        record = UsageRecord(
            model=model, task_type=task_type,
            tokens_input=tokens_in, tokens_output=tokens_out, cost_usd=cost,
        )
        await self._add_usage_record(record, tenant_id)
        await self._add_spent_usd(cost, tenant_id)

        spent_usd = await self._get_spent_usd(tenant_id)
        logger.info(
            "Usage recorded",
            model=model, tokens_in=tokens_in, tokens_out=tokens_out,
            cost=f"${cost:.6f}", monthly_total=f"${spent_usd:.4f}",
            tenant_id=tenant_id
        )

    async def get_summary(self, tenant_id: str = DEFAULT_TENANT_ID) -> dict:
        """Get current budget usage summary."""
        by_model: dict[str, dict] = {}
        by_type: dict[str, float] = {}

        records = await self._get_usage_records(tenant_id)
        for r in records:
            if r.model not in by_model:
                by_model[r.model] = {"calls": 0, "tokens": 0, "cost": 0.0}
            by_model[r.model]["calls"] += 1
            by_model[r.model]["tokens"] += r.tokens_input + r.tokens_output
            by_model[r.model]["cost"] += r.cost_usd

            by_type[r.task_type] = by_type.get(r.task_type, 0.0) + r.cost_usd

        spent_usd = await self._get_spent_usd(tenant_id)
        return {
            "monthly_budget_usd": self.monthly_budget_usd,
            "spent_usd": round(spent_usd, 6),
            "remaining_usd": round(self.monthly_budget_usd - spent_usd, 6),
            "usage_percent": round(spent_usd / self.monthly_budget_usd * 100, 2) if self.monthly_budget_usd > 0 else 0.0,
            "total_requests": len(records),
            "by_model": by_model,
            "by_task_type": by_type,
            "tenant_id": tenant_id
        }


# Global singleton
budget_manager = TokenBudgetManager()

