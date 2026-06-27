"""Unit tests for chat REPL slash commands in AgentDeepDive CLI."""

import pytest
from pathlib import Path
from rich.console import Console
from src.cli.chat.session import ChatSession
from src.cli.chat.renderer import StreamRenderer
from src.cli.chat.slash_commands import handle_slash_command

class DummyConsole(Console):
    def __init__(self):
        super().__init__(color_system=None, force_terminal=False)
        self.printed = []

    def print(self, *args, **kwargs):
        self.printed.append(args)

@pytest.mark.asyncio
async def test_slash_help():
    session = ChatSession()
    console = DummyConsole()
    renderer = StreamRenderer(console)
    
    res = await handle_slash_command("/help", session, renderer)
    assert res is True
    assert len(console.printed) > 0

@pytest.mark.asyncio
async def test_slash_clear():
    session = ChatSession()
    session.add_user_message("Hello")
    console = DummyConsole()
    renderer = StreamRenderer(console)
    
    res = await handle_slash_command("/clear", session, renderer)
    assert res is True
    assert len(session.messages) == 1  # only system prompt remains

@pytest.mark.asyncio
async def test_slash_model():
    session = ChatSession(model="old-model")
    console = DummyConsole()
    renderer = StreamRenderer(console)
    
    # Query model
    res = await handle_slash_command("/model", session, renderer)
    assert res is True
    
    # Switch model
    res = await handle_slash_command("/model new-model-name", session, renderer)
    assert res is True
    assert session.model == "new-model-name"

@pytest.mark.asyncio
async def test_slash_status():
    session = ChatSession()
    console = DummyConsole()
    renderer = StreamRenderer(console)
    
    res = await handle_slash_command("/status", session, renderer)
    assert res is True
    assert len(console.printed) > 0

@pytest.mark.asyncio
async def test_slash_exit():
    session = ChatSession()
    console = DummyConsole()
    renderer = StreamRenderer(console)
    
    res = await handle_slash_command("/exit", session, renderer)
    assert res is False
    
    res2 = await handle_slash_command("/quit", session, renderer)
    assert res2 is False

@pytest.mark.asyncio
async def test_slash_save_load(tmp_path):
    import src.cli.chat.slash_commands
    import src.cli.chat.session
    
    orig_slash_dir = src.cli.chat.slash_commands.HISTORY_DIR
    orig_sess_dir = src.cli.chat.session.HISTORY_DIR
    
    src.cli.chat.slash_commands.HISTORY_DIR = tmp_path
    src.cli.chat.session.HISTORY_DIR = tmp_path
    
    try:
        session = ChatSession(model="save-load-model")
        session.add_user_message("Hello world")
        console = DummyConsole()
        renderer = StreamRenderer(console)
        
        # Save
        res = await handle_slash_command("/save my_test_session", session, renderer)
        assert res is True
        
        # Load
        session2 = ChatSession()
        res2 = await handle_slash_command("/load my_test_session", session2, renderer)
        assert res2 is True
        assert session2.model == "save-load-model"
        assert len(session2.messages) == 2
        assert session2.messages[1]["content"] == "Hello world"
        
    finally:
        src.cli.chat.slash_commands.HISTORY_DIR = orig_slash_dir
        src.cli.chat.session.HISTORY_DIR = orig_sess_dir

@pytest.mark.asyncio
async def test_slash_dag():
    from unittest.mock import AsyncMock, MagicMock, patch
    from src.core.orchestrator.models import DAGDefinition, DAGNode
    
    session = ChatSession()
    console = DummyConsole()
    renderer = StreamRenderer(console)
    
    # Construct a dummy DAG
    node1 = DAGNode(node_id="node-1", name="Task 1", skill_id="skill-1")
    node2 = DAGNode(node_id="node-2", name="Task 2", skill_id="skill-2", dependencies=["node-1"])
    dag = DAGDefinition(dag_id="dag-test-123", name="Test DAG Flow", nodes=[node1, node2])
    
    # Mock CLIContext and load_dags_from_disk
    mock_ctx = MagicMock()
    mock_ctx.detect_mode_async = AsyncMock(return_value=MagicMock(value="local"))
    mock_ctx.resolve_tenant_id = AsyncMock(return_value="00000000-0000-0000-0000-000000000000")
    
    # Setup async context manager mock for get_db
    mock_db = AsyncMock()
    mock_ctx.get_db = MagicMock(return_value=mock_db)
    mock_db.__aenter__.return_value = MagicMock()
    
    with patch("src.cli.context.CLIContext", return_value=mock_ctx), \
         patch("src.core.orchestrator.persistence.load_dags_from_disk", return_value={"dag-test-123": dag}):
        
        # Test default last DAG
        res = await handle_slash_command("/dag", session, renderer)
        assert res is True
        
        # Check printed output contains DAG name and node name
        found_dag = False
        for args in console.printed:
            for arg in args:
                # If it's a Panel, check its renderable string
                if hasattr(arg, "renderable") and isinstance(arg.renderable, str):
                    if "Test DAG Flow" in arg.renderable and "Task 1" in arg.renderable and "Task 2" in arg.renderable:
                        found_dag = True
                # If it's a plain string, check directly
                elif isinstance(arg, str):
                    if "Test DAG Flow" in arg:
                        found_dag = True
                        
        assert found_dag is True

