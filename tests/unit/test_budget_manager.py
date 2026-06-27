import pytest
from src.core.budget.manager import TokenBudgetManager
from src.config import settings

class MockRedisForBudget:
    def __init__(self, fail=False):
        self.store = {}
        self.fail = fail
        self.list_store = {}

    async def ping(self):
        if self.fail:
            raise Exception("Redis connection refused")
        return True

    async def get(self, key):
        if self.fail:
            raise Exception("Redis error")
        return self.store.get(key)

    async def incrbyfloat(self, key, amount):
        if self.fail:
            raise Exception("Redis error")
        val = float(self.store.get(key, 0.0)) + amount
        self.store[key] = str(val)
        return val

    async def rpush(self, key, val):
        if self.fail:
            raise Exception("Redis error")
        if key not in self.list_store:
            self.list_store[key] = []
        self.list_store[key].append(val)
        return len(self.list_store[key])

    async def ltrim(self, key, start, stop):
        if self.fail:
            raise Exception("Redis error")
        if key in self.list_store:
            self.list_store[key] = self.list_store[key][start:stop+1] if stop != -1 else self.list_store[key][start:]
        return True

    async def lrange(self, key, start, stop):
        if self.fail:
            raise Exception("Redis error")
        lst = self.list_store.get(key, [])
        if stop == -1:
            return lst[start:]
        return lst[start:stop+1]

@pytest.mark.anyio
async def test_budget_manager_redis_success():
    manager = TokenBudgetManager(redis_url="redis://localhost:6379")
    mock_redis = MockRedisForBudget()
    manager._redis = mock_redis

    # Test request_budget
    appr = await manager.request_budget(task_type="formatting")
    assert appr.approved is True
    assert appr.model == (settings.local_model or "ollama/qwen3.5:2b")

    # Test record_usage
    await manager.record_usage(
        model="gpt-4o",
        task_type="refactor",
        tokens_in=500000,
        tokens_out=200000
    )

    # Verify summary
    summary = await manager.get_summary()
    assert summary["total_requests"] == 1
    assert "gpt-4o" in summary["by_model"]

@pytest.mark.anyio
async def test_budget_manager_in_memory_fallback():
    manager = TokenBudgetManager(redis_url="redis://localhost:6379")
    mock_redis_fail = MockRedisForBudget(fail=True)
    manager._redis = mock_redis_fail

    # Test request_budget fallback
    appr = await manager.request_budget(task_type="default")
    assert appr.approved is True

    # Test record_usage fallback
    await manager.record_usage(
        model="gpt-4o",
        task_type="default",
        tokens_in=10000,
        tokens_out=5000
    )

    summary = await manager.get_summary()
    assert summary["total_requests"] == 1
    assert summary["spent_usd"] > 0.0
