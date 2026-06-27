import pytest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

from src.config import settings
from src.core.agent.contract_net import (
    FIPAPerformative,
    FIPAACLMessage,
    ContractNetManager
)
from src.core.agent.pool import agent_bus


class MockRedis:
    def __init__(self):
        self.store = {}
        self.published = []

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, val):
        self.store[key] = str(val)
        return True

    async def publish(self, channel, val):
        self.published.append((channel, val))
        return 1


@pytest.mark.anyio
async def test_fipa_acl_message_serialization():
    # Test valid message creation
    msg = FIPAACLMessage(
        sender="role_a",
        receiver="manager",
        performative=FIPAPerformative.PROPOSE,
        reply_with="reply-123",
        content={"bid_score": 85.5}
    )
    data = msg.model_dump()
    assert data["sender"] == "role_a"
    assert data["performative"] == "propose"
    assert data["content"]["bid_score"] == 85.5


@pytest.mark.anyio
async def test_evaluate_proposals():
    # Mock manager
    manager = ContractNetManager(session=MagicMock())
    
    msg_a = FIPAACLMessage(
        sender="senior_coder",
        receiver="manager",
        performative=FIPAPerformative.PROPOSE,
        content={"bid_score": 90.0}
    )
    msg_b = FIPAACLMessage(
        sender="junior_coder",
        receiver="manager",
        performative=FIPAPerformative.PROPOSE,
        content={"bid_score": 95.0}
    )
    
    winner = manager._evaluate_proposals([msg_a, msg_b])
    assert winner.sender == "junior_coder"
    assert winner.content["bid_score"] == 95.0


@pytest.mark.anyio
async def test_generate_proposal(monkeypatch):
    mock_redis = MockRedis()
    
    # 1. Test proposal generation with standard budget
    manager = ContractNetManager(session=MagicMock())
    role = {
        "role_id": "senior_coder",
        "name": "Senior Coder",
        "description": "Expert developer",
        "allowed_skills": ["code_refactor"],
        "max_token_budget": 50000
    }
    
    cfp = FIPAACLMessage(
        sender="manager",
        receiver="all",
        performative=FIPAPerformative.CFP,
        reply_with="cfp-123",
        content={"task_id": "task-1", "task_description": "Fix bug", "skill_id": "code_refactor"}
    )
    
    # Active agents load: senior_coder is NOT active
    active_agents = {}
    
    monkeypatch.setattr(settings, "contract_net_llm_bidding", False)
    
    proposal = await manager._generate_proposal(role, cfp, active_agents, mock_redis)
    assert proposal.performative == FIPAPerformative.PROPOSE
    assert proposal.content["bid_score"] > 0
    assert proposal.content["is_active"] is False

    # 2. Test proposal generation when bidder is active (load penalty)
    active_agents = {"senior_coder": "task-other"}
    proposal_active = await manager._generate_proposal(role, cfp, active_agents, mock_redis)
    assert proposal_active.performative == FIPAPerformative.PROPOSE
    # Score must be 20 points lower due to active load penalty (1**1.5 * 20)
    assert proposal_active.content["bid_score"] == round(proposal.content["bid_score"] - 20.0, 2)
    assert proposal_active.content["is_active"] is True

    # 3. Test proposal generation with exhausted budget (refusal)
    await mock_redis.set("agentdeep:spent_tokens:senior_coder", 60000)
    proposal_exhausted = await manager._generate_proposal(role, cfp, active_agents, mock_redis)
    assert proposal_exhausted.performative == FIPAPerformative.REFUSE
    assert proposal_exhausted.content["reason"] == "budget_exhaustion"


@pytest.mark.anyio
async def test_run_bidding_cycle_full(monkeypatch):
    # Setup mock session and DB results
    mock_session = MagicMock()
    manager = ContractNetManager(session=mock_session)
    
    roles_list = [
        {
            "role_id": "senior_coder",
            "name": "Senior Coder",
            "description": "Expert developer",
            "allowed_skills": ["code_refactor"],
            "max_token_budget": 100000
        },
        {
            "role_id": "junior_coder",
            "name": "Junior Coder",
            "description": "Junior developer",
            "allowed_skills": ["code_refactor"],
            "max_token_budget": 50000
        }
    ]
    
    # Mock RoleService methods
    mock_list_all = AsyncMock(return_value=roles_list)
    monkeypatch.setattr(manager.role_service, "list_all", mock_list_all)
    
    # Mock redis and agent message bus
    mock_redis = MockRedis()
    async def mock_get_redis():
        return mock_redis
    monkeypatch.setattr(agent_bus, "_get_redis", mock_get_redis)
    
    # Disable LLM bidding to use fallbacks
    monkeypatch.setattr(settings, "contract_net_llm_bidding", False)
    
    # Run cycle
    winning_role = await manager.run_bidding_cycle(
        task_id="task-1",
        task_description="Refactor codebase",
        skill={"skill_id": "code_refactor", "risk_level": "medium"}
    )
    
    # Since both have 0 spent tokens, senior_coder has higher max_token_budget (100k vs 50k),
    # meaning its budget ratio (100k/100k = 1.0) is the same, but wait!
    # Let's check which wins:
    # Senior Coder budget ratio = 100k/100k = 1.0. Score = 1.0 * 40 + speed_score + efficiency_score
    # Junior Coder budget ratio = 50k/50k = 1.0. Score = 1.0 * 40 + speed_score + efficiency_score
    # Both have the same score, so the first one returned (senior_coder) will win.
    assert winning_role is not None
    assert winning_role["role_id"] == "senior_coder"
    assert winning_role["bid_info"]["bid_score"] > 0
