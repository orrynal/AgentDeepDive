import pytest
import json
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.config import settings
from src.core.orchestrator.models import DAGDefinition, DAGNode, NodeColor
from src.core.orchestrator.dag_engine import DAGEngine
from src.core.skill.service import SkillService
from src.core.evolution.ab_manager import ab_manager

class MockRedis:
    def __init__(self):
        self.store = {}
        self.published = []

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, val):
        self.store[key] = str(val)
        return True

    async def hset(self, name, key=None, value=None, mapping=None):
        if name not in self.store:
            self.store[name] = {}
        if mapping:
            for k, v in mapping.items():
                self.store[name][k] = str(v)
        elif key is not None:
            self.store[name][key] = str(value)
        return 1

    async def hgetall(self, name):
        val = self.store.get(name, {})
        return {
            k.encode() if isinstance(k, str) else k: v.encode() if isinstance(v, str) else v 
            for k, v in val.items()
        }

    async def hincrby(self, name, key, amount=1):
        if name not in self.store:
            self.store[name] = {}
        curr = int(self.store[name].get(key, 0))
        new_val = curr + amount
        self.store[name][key] = str(new_val)
        return new_val

    async def delete(self, *names):
        for name in names:
            if name in self.store:
                del self.store[name]
        return len(names)


class MockSession:
    async def commit(self):
        pass
    async def __aenter__(self):
        return self
    async def __aexit__(self, exc_type, exc, tb):
        pass


@pytest.fixture
def mock_redis_client(monkeypatch):
    redis_mock = MockRedis()
    async def mock_get_redis():
        return redis_mock
    monkeypatch.setattr(ab_manager, "_get_redis", mock_get_redis)
    return redis_mock


@pytest.mark.anyio
async def test_ab_fork_grey_skill(mock_redis_client, monkeypatch):
    # Setup mock parent skill
    parent_skill = {
        "skill_id": "test_skill",
        "name": "Test Skill",
        "version": "1.0.0",
        "description": "Original description",
        "tags": ["test"],
        "trigger_patterns": ["run test"],
        "context_budget": 4000,
        "required_tools": [],
        "input_schema": {},
        "output_schema": {},
        "system_prompt": "original prompt",
        "risk_level": "low",
        "approval_required": False,
        "estimated_tokens": 1000,
        "estimated_duration_sec": 60,
        "workspace_path": "/workspace",
        "is_active": True
    }

    # Mock SkillService
    async def mock_get_by_id(self, s_id):
        if s_id == "test_skill":
            return parent_skill
        return None

    created_skill = []
    async def mock_create(self, data):
        created_skill.append(data)
        return data

    monkeypatch.setattr(SkillService, "get_by_id", mock_get_by_id)
    monkeypatch.setattr(SkillService, "create", mock_create)

    # Run fork
    session = MockSession()
    variant = await ab_manager.fork_grey_skill(
        parent_skill_id="test_skill",
        new_prompt="improved prompt",
        session=session
    )

    assert variant is not None
    assert len(created_skill) == 1
    assert created_skill[0]["system_prompt"] == "improved prompt"
    assert "test_skill:flywheel:" in created_skill[0]["skill_id"]
    assert "beta.flywheel" in created_skill[0]["version"]

    # Check Redis registry
    config_data = await mock_redis_client.get("agentdeep:ab_config:test_skill")
    assert config_data is not None
    config = json.loads(config_data)
    assert config["variant_id"] == created_skill[0]["skill_id"]


@pytest.mark.anyio
async def test_ab_routing_decision(mock_redis_client, monkeypatch):
    parent_id = "test_skill"
    variant_id = "test_skill:flywheel:123"

    # Setup config in Redis
    await mock_redis_client.set(
        f"agentdeep:ab_config:{parent_id}",
        json.dumps({"variant_id": variant_id, "weight": 0.2})
    )

    # 1. Random returns 0.1 (< 0.2 weight) -> should route to variant
    monkeypatch.setattr(settings, "ab_testing_enabled", True)
    with patch("random.random", return_value=0.1):
        decision = await ab_manager.get_routing_decision(parent_id)
        assert decision == variant_id

    # 2. Random returns 0.5 (>= 0.2 weight) -> should route to parent
    with patch("random.random", return_value=0.5):
        decision = await ab_manager.get_routing_decision(parent_id)
        assert decision == parent_id

    # 3. Disabled -> should route to parent
    monkeypatch.setattr(settings, "ab_testing_enabled", False)
    decision = await ab_manager.get_routing_decision(parent_id)
    assert decision == parent_id


@pytest.mark.anyio
async def test_ab_record_run_result(mock_redis_client):
    skill_id = "test_skill:flywheel:123"
    await ab_manager.record_run_result(skill_id, success=True, tokens=150)
    await ab_manager.record_run_result(skill_id, success=False, tokens=200)

    telemetry = await mock_redis_client.hgetall(f"agentdeep:ab_telemetry:{skill_id}")
    assert telemetry[b"success"] == b"1"
    assert telemetry[b"total"] == b"2"
    assert telemetry[b"spent_tokens"] == b"350"


@pytest.mark.anyio
async def test_ab_evaluate_and_promote(mock_redis_client, monkeypatch):
    parent_id = "test_skill"
    variant_id = "test_skill:flywheel:123"
    session = MockSession()

    # Mock SkillService database actions
    skills_db = {
        "test_skill": {
            "skill_id": "test_skill",
            "system_prompt": "original prompt",
            "version": "1.0.0"
        },
        "test_skill:flywheel:123": {
            "skill_id": "test_skill:flywheel:123",
            "system_prompt": "improved prompt",
            "version": "1.0.0-beta.flywheel"
        }
    }

    async def mock_get_by_id(self, s_id):
        return skills_db.get(s_id)

    updated_data = {}
    async def mock_update(self, s_id, data):
        updated_data[s_id] = data
        if s_id in skills_db:
            skills_db[s_id].update(data)

    deleted_skills = []
    async def mock_delete(self, s_id):
        deleted_skills.append(s_id)
        if s_id in skills_db:
            del skills_db[s_id]

    monkeypatch.setattr(SkillService, "get_by_id", mock_get_by_id)
    monkeypatch.setattr(SkillService, "update", mock_update)
    monkeypatch.setattr(SkillService, "delete", mock_delete)
    monkeypatch.setattr(settings, "ab_min_eval_runs", 5)

    # 1. Not enough runs yet (runs = 4, target = 5)
    await mock_redis_client.hset(f"agentdeep:ab_telemetry:{variant_id}", mapping={"success": 3, "total": 4, "spent_tokens": 100})
    result = await ab_manager.evaluate_and_promote(parent_id, variant_id, session)
    assert result is None
    assert "test_skill" not in updated_data

    # 2. Variant runs = 5, success_rate = 1.0 (5/5). Parent runs = 5, success_rate = 0.6 (3/5).
    # Promotion should occur.
    await mock_redis_client.hset(f"agentdeep:ab_telemetry:{variant_id}", mapping={"success": 5, "total": 5, "spent_tokens": 1000})
    await mock_redis_client.hset(f"agentdeep:ab_telemetry:{parent_id}", mapping={"success": 3, "total": 5, "spent_tokens": 1000})
    
    promoted = await ab_manager.evaluate_and_promote(parent_id, variant_id, session)
    assert promoted is True
    assert updated_data["test_skill"]["system_prompt"] == "improved prompt"
    assert updated_data["test_skill"]["version"] == "1.0.1"
    assert variant_id in deleted_skills

    # 3. Lightweight mode check (runs = 1, target = 1). Promotion should occur.
    monkeypatch.setattr(settings, "system_mode", "lightweight")
    # Reset databases
    skills_db["test_skill"] = {
        "skill_id": "test_skill",
        "system_prompt": "original prompt",
        "version": "1.0.0"
    }
    skills_db["test_skill:flywheel:123"] = {
        "skill_id": "test_skill:flywheel:123",
        "system_prompt": "improved prompt",
        "version": "1.0.0-beta.flywheel"
    }
    updated_data.clear()
    deleted_skills.clear()
    
    await mock_redis_client.hset(f"agentdeep:ab_telemetry:{variant_id}", mapping={"success": 1, "total": 1, "spent_tokens": 80})
    await mock_redis_client.hset(f"agentdeep:ab_telemetry:{parent_id}", mapping={"success": 1, "total": 1, "spent_tokens": 100})
    
    promoted = await ab_manager.evaluate_and_promote(parent_id, variant_id, session)
    assert promoted is True
    assert updated_data["test_skill"]["system_prompt"] == "improved prompt"
    # Restore mode
    monkeypatch.setattr(settings, "system_mode", "full")


@pytest.mark.anyio
async def test_dag_engine_prompt_patch_self_healing(mock_redis_client, monkeypatch):
    # Setup node and DAG
    node = DAGNode(
        node_id="node_a",
        name="Compile Task",
        skill_id="test_skill",
        description="Compile main module",
        color=NodeColor.GRAY,
        dependencies=[]
    )
    dag = DAGDefinition(
        dag_id="dag-123",
        name="Test DAG",
        status="pending",
        nodes=[node],
        edges=[]
    )

    # Mock SkillService
    parent_skill = {
        "skill_id": "test_skill",
        "name": "Test Skill",
        "version": "1.0.0",
        "description": "Original description",
        "tags": ["test"],
        "trigger_patterns": ["run test"],
        "context_budget": 4000,
        "required_tools": [],
        "input_schema": {},
        "output_schema": {},
        "system_prompt": "original prompt",
        "risk_level": "low",
        "approval_required": False,
        "estimated_tokens": 1000,
        "estimated_duration_sec": 60,
        "workspace_path": "/workspace",
        "is_active": True
    }
    async def mock_get_by_id(self, s_id):
        if s_id == "test_skill":
            return parent_skill
        elif "test_skill:flywheel:" in s_id:
            return {**parent_skill, "skill_id": s_id, "system_prompt": "improved prompt"}
        return None

    async def mock_create(self, data):
        return data

    monkeypatch.setattr(SkillService, "get_by_id", mock_get_by_id)
    monkeypatch.setattr(SkillService, "create", mock_create)

    # Mock LiteLLM diagnostics response with should_patch_prompt = True
    class MockMessage:
        content = '{"can_heal": true, "should_patch_prompt": true, "patched_prompt": "improved prompt"}'
    
    class MockChoice:
        message = MockMessage()
        
    class MockResponse:
        choices = [MockChoice()]

    mock_acompletion = AsyncMock(return_value=MockResponse())
    import litellm
    monkeypatch.setattr(litellm, "acompletion", mock_acompletion)

    # Run attempt_self_healing
    engine = DAGEngine(SkillService(MockSession()))
    healed = await engine._attempt_self_healing(dag, node, "LogicException: Invalid configuration value")
    
    assert healed is True
    assert node.color == NodeColor.GRAY
    assert "resolved_skill_id" in node.constraints
    assert "test_skill:flywheel:" in node.constraints["resolved_skill_id"]
