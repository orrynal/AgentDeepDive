"""FIPA-ACL Contract Net Protocol (CNP) Bidding System.

Allows Agents/Roles to bid on tasks based on token budget, workload, and model estimated cost.
"""

import asyncio
import json
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field
import structlog
import litellm

from src.config import settings
from src.core.agent.pool import agent_bus, agent_pool
from src.core.role.service import RoleService

logger = structlog.get_logger()


class FIPAPerformative(str, Enum):
    CFP = "cfp"                       # Call for Proposal
    PROPOSE = "propose"               # Bid proposal
    REFUSE = "refuse"                 # Refuse to bid
    ACCEPT_PROPOSAL = "accept-proposal"
    REJECT_PROPOSAL = "reject-proposal"
    INFORM = "inform"                 # Execution success report
    FAILURE = "failure"               # Execution failure report


class FIPAACLMessage(BaseModel):
    sender: str
    receiver: str
    performative: FIPAPerformative
    reply_with: Optional[str] = None
    in_reply_to: Optional[str] = None
    content: dict[str, Any] = Field(default_factory=dict)
    protocol: str = "fipa-contract-net"


class ContractNetManager:
    """Manages the FIPA-ACL Contract Net Protocol bidding process for task allocation."""

    def __init__(self, session):
        self.session = session
        self.role_service = RoleService(session)

    async def run_bidding_cycle(
        self,
        task_id: str,
        task_description: str,
        skill: dict,
    ) -> Optional[dict]:
        """Runs the complete CNP bidding cycle to select the best Role for a task.

        Returns:
            The selected Role dictionary, or None if no bidders are available.
        """
        skill_id = skill.get("skill_id")
        logger.info("Starting FIPA-ACL Contract Net bidding", task_id=task_id, skill_id=skill_id)

        # 1. Retrieve potential Bidders (Roles)
        all_roles = await self.role_service.list_all(active_only=True)
        # Filter roles that have allowed_skills containing skill_id
        bidders = [r for r in all_roles if skill_id in r.get("allowed_skills", [])]

        # If no specialized bidders, fall back to all active roles
        if not bidders:
            logger.warning("No specialized roles for skill. Broadcasting CFP to all active roles.", skill_id=skill_id)
            bidders = all_roles

        if not bidders:
            logger.error("No active roles found in the database. Bidding aborted.")
            return None

        # 2. Broadcast CFP (Call for Proposal) to all candidates
        cfp_msg = FIPAACLMessage(
            sender="manager",
            receiver="all",
            performative=FIPAPerformative.CFP,
            reply_with=f"reply-cfp-{task_id}",
            content={
                "task_id": task_id,
                "task_description": task_description,
                "skill_id": skill_id,
                "risk_level": skill.get("risk_level", "low"),
            }
        )
        await agent_bus.publish(
            topic="contract_net",
            sender_id="manager",
            payload=cfp_msg.model_dump()
        )

        # 3. Collect proposals
        proposals: list[FIPAACLMessage] = []
        redis_client = await agent_bus._get_redis()
        active_agents = await agent_pool.get_active_agents()

        bid_tasks = []
        for role in bidders:
            bid_tasks.append(self._generate_proposal(role, cfp_msg, active_agents, redis_client))

        results = await asyncio.gather(*bid_tasks)
        for res in results:
            if res:
                proposals.append(res)
                # Publish PROPOSE/REFUSE to the bus
                await agent_bus.publish(
                    topic="contract_net",
                    sender_id=res.sender,
                    payload=res.model_dump()
                )

        # Filter out REFUSE messages
        valid_proposes = [p for p in proposals if p.performative == FIPAPerformative.PROPOSE]

        if not valid_proposes:
            logger.error("No valid bids received for task (all bidders refused or errored)", task_id=task_id)
            return None

        # 4. Evaluate proposals & select winner
        winner_msg = self._evaluate_proposals(valid_proposes)
        winner_role_id = winner_msg.sender
        logger.info("Bidding won by role", role_id=winner_role_id, task_id=task_id, score=winner_msg.content.get("bid_score"))

        # Send ACCEPT_PROPOSAL and REJECT_PROPOSAL
        for prop in proposals:
            if prop.performative == FIPAPerformative.PROPOSE:
                perf = FIPAPerformative.ACCEPT_PROPOSAL if prop.sender == winner_role_id else FIPAPerformative.REJECT_PROPOSAL
                reply = FIPAACLMessage(
                    sender="manager",
                    receiver=prop.sender,
                    performative=perf,
                    in_reply_to=prop.reply_with,
                    content={"winner_role_id": winner_role_id}
                )
                await agent_bus.publish(
                    topic="contract_net",
                    sender_id="manager",
                    payload=reply.model_dump()
                )

        # Find and return the winning Role object
        for r in bidders:
            if r["role_id"] == winner_role_id:
                # Enrich role dict with bidding details
                r["bid_info"] = winner_msg.content
                return r

        return None

    async def _generate_proposal(
        self,
        role: dict,
        cfp: FIPAACLMessage,
        active_agents: dict[str, str],
        redis_client,
    ) -> Optional[FIPAACLMessage]:
        """Simulates/Generates a bid proposal from a Role."""
        role_id = role["role_id"]
        max_budget = role.get("max_token_budget", 50000)

        # Retrieve current spent tokens from Redis
        spent_str = await redis_client.get(f"agentdeep:spent_tokens:{role_id}")
        spent_tokens = int(spent_str) if spent_str else 0

        # Check if the role is currently running a task (load check)
        is_active = any(role_id in aid for aid in active_agents.keys())

        # If spent tokens exceed or equal maximum budget, refuse to bid
        if spent_tokens >= max_budget:
            logger.warning("Role refused to bid due to budget exhaustion", role_id=role_id)
            return FIPAACLMessage(
                sender=role_id,
                receiver="manager",
                performative=FIPAPerformative.REFUSE,
                in_reply_to=cfp.reply_with,
                content={"reason": "budget_exhaustion", "spent_tokens": spent_tokens, "max_budget": max_budget}
            )

        # Calculate estimated values
        est_tokens = 5000  # Default fallback
        est_time = 15     # Default fallback
        reasoning = f"Capable of executing skill '{cfp.content['skill_id']}'."

        if settings.contract_net_llm_bidding:
            try:
                # Call LiteLLM to generate Bid reasoning and estimation
                prompt = (
                    f"You are the bidding agent for the Role '{role['name']}' (description: '{role['description']}').\n"
                    f"You have received a Call for Proposal (CFP) for the task: '{cfp.content['task_description']}' using skill '{cfp.content['skill_id']}'.\n"
                    f"Your default model is '{role.get('default_model') or settings.default_model}'.\n"
                    f"Current spent tokens: {spent_tokens}, Max token budget: {max_budget}.\n"
                    f"Currently active on another task: {is_active}.\n\n"
                    f"Propose a bid by returning a JSON object containing:\n"
                    f"1. \"estimated_tokens\": estimated number of tokens (typically 2000-15000 based on task complexity)\n"
                    f"2. \"estimated_time_sec\": estimated time in seconds (typically 5-60)\n"
                    f"3. \"reasoning\": a brief sentence (in Chinese) on how your role is best suited to solve this task.\n\n"
                    f"Return ONLY valid JSON."
                )

                # Use a fast low-cost model for bidding
                resp = await litellm.acompletion(
                    model=settings.default_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                    response_format={"type": "json_object"},
                    timeout=5.0
                )
                bid_data = json.loads(resp.choices[0].message.content)
                est_tokens = int(bid_data.get("estimated_tokens", est_tokens))
                est_time = int(bid_data.get("estimated_time_sec", est_time))
                reasoning = bid_data.get("reasoning", reasoning)
            except Exception as e:
                logger.warning("Failed to generate LLM bidding proposal, using fallback", role_id=role_id, error=str(e))

        # Calculate Bid Score using Multidimensional High-Accuracy Formula:
        # 1. Skill Matching Score - 30% weight
        skill_id = cfp.content.get("skill_id")
        allowed_skills = role.get("allowed_skills", [])
        if skill_id in allowed_skills:
            skill_score = 30.0
        else:
            skill_score = 10.0  # Fallback boost

        # 2. Budget Health Score - 25% weight
        budget_ratio = (max_budget - spent_tokens) / max_budget if max_budget > 0 else 0.0
        budget_score = max(0.0, budget_ratio) * 25.0

        # 3. Execution Efficiency & Speed Score - 25% weight
        speed_score = (10.0 / max(est_time, 1)) * 12.5
        efficiency_score = (5000.0 / max(est_tokens, 1)) * 12.5
        perf_score = min(speed_score + efficiency_score, 25.0)

        # 4. Task Risk & Model Cost Tier Matching Score - 20% weight
        model_name = (role.get("default_model") or settings.default_model or "").lower()
        expensive_models = ["gpt-4", "claude-3", "gemini-pro"]
        is_expensive_model = any(m in model_name for m in expensive_models)
        
        risk_level = cfp.content.get("risk_level", "low").lower()
        if risk_level in ["high", "medium"]:
            # High-risk task demands powerful model
            model_match_score = 20.0 if is_expensive_model else 5.0
        else:
            # Low-risk task should favor cheap lightweight models to save cost
            model_match_score = 5.0 if is_expensive_model else 20.0

        bid_score = skill_score + budget_score + perf_score + model_match_score

        # 5. Non-linear Dynamic Load Penalty
        # Count all tasks in active_agents where role_id is part of the agent key
        active_tasks_count = 0
        try:
            active_tasks_count = sum(1 for aid in active_agents.keys() if role_id in aid)
        except Exception:
            if is_active:
                active_tasks_count = 1

        # Non-linear penalty curves (quadratic scaling prevents hot-spot role collisions)
        load_penalty = (active_tasks_count ** 1.5) * 20.0
        bid_score -= load_penalty

        return FIPAACLMessage(
            sender=role_id,
            receiver="manager",
            performative=FIPAPerformative.PROPOSE,
            reply_with=f"reply-propose-{role_id}-{cfp.content['task_id']}",
            in_reply_to=cfp.reply_with,
            content={
                "estimated_tokens": est_tokens,
                "estimated_time_sec": est_time,
                "reasoning": reasoning,
                "bid_score": round(max(0.0, bid_score), 2),
                "spent_tokens": spent_tokens,
                "max_budget": max_budget,
                "is_active": is_active,
                "active_tasks_count": active_tasks_count
            }
        )

    def _evaluate_proposals(self, proposals: list[FIPAACLMessage]) -> FIPAACLMessage:
        """Selects the best proposal from PROPOSE messages."""
        # Sort by bid_score descending
        sorted_proposals = sorted(proposals, key=lambda x: x.content.get("bid_score", 0.0), reverse=True)
        return sorted_proposals[0]
