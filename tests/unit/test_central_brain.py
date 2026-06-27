import asyncio
import pytest
from httpx import ASGITransport, AsyncClient
from src.api.main import app
from src.config import settings
from src.core.orchestrator.central_brain import central_brain, BrainDialogueMessage
from src.core.orchestrator.models import DAGDefinition, DAGNode
from src.core.agent.pool import agent_bus


class MockMessageBus:
    """Mock Message Bus to run tests completely in-memory without requiring Redis."""
    def __init__(self):
        self.listeners = {}
        self.published = []

    async def subscribe(self, topic: str, callback):
        if topic not in self.listeners:
            self.listeners[topic] = []
        if callback not in self.listeners[topic]:
            self.listeners[topic].append(callback)

    async def unsubscribe(self, topic: str, callback):
        if topic in self.listeners and callback in self.listeners[topic]:
            self.listeners[topic].remove(callback)

    async def publish(self, topic: str, sender_id: str, payload: dict):
        self.published.append((topic, sender_id, payload))
        callbacks = self.listeners.get(topic, [])
        for cb in callbacks:
            message = {
                "sender_id": sender_id,
                "topic": topic,
                "payload": payload,
            }
            # Run the callback directly asynchronously
            await cb(message)


@pytest.fixture(autouse=True)
def mock_agent_bus(monkeypatch):
    """Monkeypatch the global agent_bus with MockMessageBus to avoid Redis calls."""
    mock_bus = MockMessageBus()
    monkeypatch.setattr("src.core.orchestrator.central_brain.agent_bus", mock_bus)
    monkeypatch.setattr("src.api.routes.brain.central_brain", central_brain)
    return mock_bus


@pytest.fixture(autouse=True)
async def cleanup_brain():
    """Ensure central brain starts clean and is stopped after tests."""
    await central_brain.stop()
    central_brain._active_sessions.clear()
    central_brain._dialogue_history.clear()
    yield
    await central_brain.stop()


@pytest.mark.asyncio
async def test_central_brain_registration_and_budget():
    # 1. Test Session Registration
    dag = DAGDefinition(name="Test Brain DAG", nodes=[DAGNode(name="Node 1", skill_id="test")])
    await central_brain.register_session(dag)

    sessions = await central_brain.get_active_sessions()
    assert dag.dag_id in sessions
    assert sessions[dag.dag_id].name == "Test Brain DAG"

    # 2. Test Budget safety check
    assert await central_brain.check_budget_safety(dag) is True

    # High projected cost
    big_dag = DAGDefinition(
        name="Big DAG",
        nodes=[DAGNode(name=f"Node {i}", skill_id="test") for i in range(100)]
    )
    assert await central_brain.check_budget_safety(big_dag) is False

    # 3. Test Deregistration
    await central_brain.deregister_session(dag.dag_id)
    sessions = await central_brain.get_active_sessions()
    assert dag.dag_id not in sessions


@pytest.mark.asyncio
async def test_central_brain_consensus(mock_agent_bus):
    # Test Consensus Resolution
    selected = await central_brain.coordinate_consensus(
        task_id="task-123",
        topic="select_framework",
        options=["Next.js", "Vite+React", "Nuxt.js"]
    )
    assert selected == "Next.js"
    assert len(mock_agent_bus.published) == 1
    topic, sender, payload = mock_agent_bus.published[0]
    assert topic == "consensus_result"
    assert sender == "central_brain"
    assert payload["selected"] == "Next.js"


@pytest.mark.asyncio
async def test_central_brain_dialogue_logging(mock_agent_bus):
    # Start Central Brain to listen to dialogue channel
    await central_brain.start()

    # Publish dialogue message to mock bus
    await mock_agent_bus.publish(
        topic="dialogue",
        sender_id="engineer_agent",
        payload={
            "message_id": "msg-999",
            "task_id": "task-abc",
            "recipient_id": "executor_agent",
            "content": "Let's align on database design",
            "timestamp": 1234567.8
        }
    )

    history = await central_brain.get_dialogue_history()
    assert len(history) >= 1
    assert any(m.message_id == "msg-999" for m in history)
    
    # Clean up
    await central_brain.stop()


@pytest.mark.asyncio
async def test_brain_api_endpoints(monkeypatch, mock_agent_bus):
    # Mock settings API Key for authentication
    monkeypatch.setattr(settings, "api_key", "test_brain_key")

    dag = DAGDefinition(name="API Supervised Task", nodes=[])
    await central_brain.register_session(dag)

    dialogue = BrainDialogueMessage(
        message_id="msg-api-test",
        task_id="task-api",
        sender_id="agent-1",
        recipient_id="agent-2",
        content="Testing API retrieval",
        timestamp=987654.3
    )
    async with central_brain._lock:
        central_brain._dialogue_history.append(dialogue)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        headers = {"X-API-Key": "test_brain_key"}

        # 1. Get Sessions
        resp = await ac.get("/api/v1/brain/sessions", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert dag.dag_id in data
        assert data[dag.dag_id]["name"] == "API Supervised Task"

        # 2. Get Dialogue History
        resp = await ac.get("/api/v1/brain/dialogues", headers=headers)
        assert resp.status_code == 200
        dialogues = resp.json()
        assert len(dialogues) >= 1
        assert dialogues[0]["message_id"] == "msg-api-test"

        # 3. Request Consensus
        resp = await ac.post(
            "/api/v1/brain/consensus",
            json={
                "task_id": "task-consensus",
                "topic": "db_type",
                "options": ["Postgres", "MySQL"]
            },
            headers=headers
        )
        assert resp.status_code == 200
        res = resp.json()
        assert res["selected"] == "Postgres"
        assert res["status"] == "resolved"
