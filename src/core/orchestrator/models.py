"""DAG Orchestrator data models — defines nodes, edges, and state machine."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


class NodeColor(str, Enum):
    """Color state machine for DAG nodes."""
    GRAY = "gray"       # 未开始
    BLUE = "blue"       # 已排队
    YELLOW = "yellow"   # 执行中
    GREEN = "green"     # 已完成
    ORANGE = "orange"   # 需人工审批
    RED = "red"         # 失败/阻塞
    SUSPENDED = "suspended" # 执行失败挂起

    @property
    def can_transition_to(self) -> list["NodeColor"]:
        transitions = {
            NodeColor.GRAY:   [NodeColor.BLUE],
            NodeColor.BLUE:   [NodeColor.YELLOW, NodeColor.GRAY],
            NodeColor.YELLOW: [NodeColor.GREEN, NodeColor.RED, NodeColor.ORANGE, NodeColor.SUSPENDED],
            NodeColor.GREEN:  [],  # Terminal
            NodeColor.ORANGE: [NodeColor.YELLOW, NodeColor.RED, NodeColor.SUSPENDED],
            NodeColor.RED:    [NodeColor.YELLOW, NodeColor.GRAY],  # Retry
            NodeColor.SUSPENDED: [NodeColor.GRAY, NodeColor.GREEN, NodeColor.RED], # Retry, Bypass, Terminate
        }
        return transitions.get(self, [])



class DAGNode(BaseModel):
    """A single node (task) in the DAG."""
    node_id: str = Field(default_factory=lambda: f"node-{uuid4().hex[:8]}")
    name: str = ""
    skill_id: str = ""
    role_id: str | None = None  # Optional Role identifier (e.g., senior_coder, auto)
    description: str = ""
    color: NodeColor = NodeColor.GRAY
    priority: int = 50
    dependencies: list[str] = Field(default_factory=list)  # node_ids this depends on
    input_mapping: dict[str, str] = Field(default_factory=dict)  # key → "node_id.output.field"
    constraints: dict[str, Any] = Field(default_factory=dict)
    approval_id: str | None = None  # Persistent L3/L4 approval tracking ID
    result: dict[str, Any] | None = None
    error: str | None = None
    started_at: str | None = None
    completed_at: str | None = None

    @field_validator("result", mode="before")
    @classmethod
    def coerce_result(cls, v: Any) -> Any:
        if isinstance(v, str):
            return {"output": v}
        return v



class DAGEdge(BaseModel):
    """An edge connecting two nodes."""
    from_node: str
    to_node: str
    condition: str | None = None  # Optional condition for conditional edges


class DAGDefinition(BaseModel):
    """Complete DAG definition."""
    dag_id: str = Field(default_factory=lambda: f"dag-{uuid4().hex[:8]}")
    tenant_id: str = "00000000-0000-0000-0000-000000000000"
    name: str
    description: str = ""
    nodes: list[DAGNode] = Field(default_factory=list)
    edges: list[DAGEdge] = Field(default_factory=list)
    status: str = "pending"  # pending, running, completed, failed, paused
    routing_tier: str | None = None  # small, medium, large
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None
    workspace_path: str | None = None
    project_name: str | None = None
    constraints: dict[str, Any] = Field(default_factory=dict)

    def get_node(self, node_id: str) -> DAGNode | None:
        for n in self.nodes:
            if n.node_id == node_id:
                return n
        return None

    def get_ready_nodes(self) -> list[DAGNode]:
        """Find nodes whose dependencies are all GREEN (completed)."""
        ready = []
        for node in self.nodes:
            if node.color not in (NodeColor.GRAY, NodeColor.ORANGE):
                continue
            deps_met = all(
                self.get_node(dep) and self.get_node(dep).color == NodeColor.GREEN
                for dep in node.dependencies
            )
            if deps_met:
                ready.append(node)
        return ready

    def is_complete(self) -> bool:
        return all(n.color in (NodeColor.GREEN, NodeColor.RED) for n in self.nodes)

    def has_failed(self) -> bool:
        return any(n.color == NodeColor.RED for n in self.nodes)
