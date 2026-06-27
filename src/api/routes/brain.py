"""Central Brain endpoints for API server."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Dict

from src.core.orchestrator.central_brain import central_brain
from src.core.auth.security import RoleRequired
from src.core.auth.models import UserModel

router = APIRouter()


class ConsensusRequest(BaseModel):
    task_id: str
    topic: str
    options: List[str]


class ConsensusResponse(BaseModel):
    selected: str
    status: str


@router.get("/brain/sessions", response_model=Dict[str, Dict])
async def get_supervised_sessions(
    user: UserModel = Depends(RoleRequired(["admin", "developer"]))
):
    """Retrieve all active supervised task execution sessions."""
    sessions = await central_brain.get_active_sessions()
    return {
        dag_id: {
            "dag_id": dag.dag_id,
            "name": dag.name,
            "status": dag.status,
            "routing_tier": dag.routing_tier,
            "created_at": dag.created_at
        }
        for dag_id, dag in sessions.items()
    }


@router.get("/brain/dialogues", response_model=List[Dict])
async def get_dialogue_history(
    user: UserModel = Depends(RoleRequired(["admin", "developer"]))
):
    """Retrieve collected dialogue and inter-agent communication history."""
    dialogues = await central_brain.get_dialogue_history()
    return [
        {
            "message_id": d.message_id,
            "task_id": d.task_id,
            "sender_id": d.sender_id,
            "recipient_id": d.recipient_id,
            "content": d.content,
            "timestamp": d.timestamp
        }
        for d in dialogues
    ]


@router.post("/brain/consensus", response_model=ConsensusResponse)
async def coordinate_consensus(
    body: ConsensusRequest,
    user: UserModel = Depends(RoleRequired(["admin", "developer"]))
):
    """Trigger a Central Brain consensus resolution among options proposed by agents."""
    selected = await central_brain.coordinate_consensus(body.task_id, body.topic, body.options)
    return ConsensusResponse(selected=selected, status="resolved")
