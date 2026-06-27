"""Unit tests for Phase 3 advanced features in the CLI interactive terminal."""

import os
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
from rich.console import Console
from src.cli.chat.repl import expand_file_references, retrieve_episodic_memories, run_repl
from src.cli.chat.session import ChatSession
from src.cli.chat.renderer import StreamRenderer

class DummyConsole(Console):
    def __init__(self):
        super().__init__(color_system=None, force_terminal=False)
        self.printed = []

    def print(self, *args, **kwargs):
        self.printed.append(args)

def test_expand_file_references_valid(tmp_path):
    renderer = StreamRenderer(console=DummyConsole())
    
    # Create a temp file in workspace
    workspace_dir = tmp_path
    test_file = workspace_dir / "code.py"
    test_file.write_text("print('hello')", encoding="utf-8")
    
    user_input = "Please review @code.py in the project"
    processed_text, injected = expand_file_references(user_input, str(workspace_dir), renderer)
    
    assert "code.py" in injected
    assert "print('hello')" in processed_text
    assert "--- File Context: code.py ---" in processed_text

def test_expand_file_references_missing(tmp_path):
    renderer = StreamRenderer(console=DummyConsole())
    user_input = "Please review @missing_file.py in the project"
    processed_text, injected = expand_file_references(user_input, str(tmp_path), renderer)
    
    assert len(injected) == 0
    assert processed_text == user_input

@pytest.mark.asyncio
async def test_retrieve_episodic_memories_success():
    renderer = StreamRenderer(console=DummyConsole())
    
    # Mock RAG manager query
    mock_rag = MagicMock()
    mock_rag.connected = True
    mock_rag.query_episodic_memory = MagicMock(return_value=[
        {
            "prompt": "Fix import error",
            "error_stack": "ImportError: no module named foo",
            "patch": "import bar as foo"
        }
    ])
    
    with patch("src.core.memory.rag_manager.rag_manager", mock_rag):
        mem_text = await retrieve_episodic_memories("fix import", renderer)
        
        assert "Fix import error" in mem_text
        assert "ImportError: no module named foo" in mem_text
        assert "import bar as foo" in mem_text
        mock_rag.query_episodic_memory.assert_called_once_with("fix import", limit=2)

@pytest.mark.asyncio
async def test_retrieve_episodic_memories_no_results():
    renderer = StreamRenderer(console=DummyConsole())
    
    mock_rag = MagicMock()
    mock_rag.connected = True
    mock_rag.query_episodic_memory = MagicMock(return_value=[])
    
    with patch("src.core.memory.rag_manager.rag_manager", mock_rag):
        mem_text = await retrieve_episodic_memories("some query", renderer)
        assert mem_text == ""
        mock_rag.query_episodic_memory.assert_called_once_with("some query", limit=2)


def test_repl_bottom_toolbar_pricing():
    # Test that the bottom toolbar function calculates and renders the cost estimates
    from src.cli.chat.repl import run_repl
    from src.cli.chat.session import ChatSession
    from src.core.budget.manager import budget_manager
    import sys

    session = ChatSession(model="claude-sonnet-4-20250514")
    # Add a mock message to have estimated tokens
    session.add_raw_message({"role": "user", "content": "hello " * 100})
    
    # Set spent_usd in memory
    budget_manager._in_memory_spent_usd[session.tenant_id] = 1.2345

    # We want to patch PromptSession and extract the bottom_toolbar callback passed to it
    with patch("src.cli.chat.repl.PromptSession") as mock_prompt_session, \
         patch("src.cli.chat.repl.FileHistory"), \
         patch("src.cli.chat.repl.ToolBridge"), \
         patch("src.cli.chat.repl.StreamRenderer"), \
         patch("src.cli.chat.repl.os.path.exists", return_value=True), \
         patch("src.cli.chat.repl.Path.read_text", return_value=""), \
         patch("src.config.settings") as mock_settings:
         
        mock_settings.resolved_workspace_path = "/tmp"
        
        captured_toolbar = None
        def mock_init(*args, **kwargs):
            nonlocal captured_toolbar
            captured_toolbar = kwargs.get("bottom_toolbar")
            raise KeyboardInterrupt() # Exit run_repl immediately during initialization

        mock_prompt_session.side_effect = mock_init

        import asyncio
        from src.cli.chat.renderer import StreamRenderer
        renderer = StreamRenderer(None)
        try:
            asyncio.run(run_repl(session, renderer))
        except KeyboardInterrupt:
            pass

        assert captured_toolbar is not None
        toolbar_text = captured_toolbar()
        assert "Model: claude-sonnet-4-20250514" in toolbar_text
        assert "Est. Context" in toolbar_text
        assert "Spent: $1.2345" in toolbar_text
