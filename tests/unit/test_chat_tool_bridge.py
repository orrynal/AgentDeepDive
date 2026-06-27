"""Unit tests for the CLI chat tool execution bridge."""

import os
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from rich.console import Console
from src.cli.chat.tool_bridge import ToolBridge
from src.config import settings

class DummyConsole(Console):
    def __init__(self):
        super().__init__(color_system=None, force_terminal=False)
        self.printed = []

    def print(self, *args, **kwargs):
        self.printed.append(args)

def test_get_tool_schemas():
    bridge = ToolBridge()
    schemas = bridge.get_tool_schemas()
    assert isinstance(schemas, list)
    assert len(schemas) > 0
    # Must have file_read
    file_read_schema = next((s for s in schemas if s["function"]["name"] == "file_read"), None)
    assert file_read_schema is not None

def test_resolve_safe_paths():
    bridge = ToolBridge()
    workspace = settings.resolved_workspace_path
    
    # 1. Relative path
    args1 = {"path": "hello.txt"}
    bridge.resolve_safe_paths("file_read", args1)
    assert args1["path"] == os.path.abspath(os.path.join(workspace, "hello.txt"))

@pytest.mark.asyncio
async def test_execute_tool_l4_blocked():
    bridge = ToolBridge(console=DummyConsole())
    
    # rm -rf / is L4 forbidden
    args = {"command": "rm -rf /"}
    res_str = await bridge.execute_tool("shell_exec", args, "00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000001")
    res = json.loads(res_str)
    
    assert res["status"] == "error"
    assert "Security Violation" in res["error"]

@pytest.mark.asyncio
async def test_execute_tool_path_traversal_l4():
    bridge = ToolBridge(console=DummyConsole())
    
    # Path traversal with .. in path is L4 forbidden
    args = {"path": "../secret.txt", "content": "leak"}
    res_str = await bridge.execute_tool("file_write", args, "00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000001")
    res = json.loads(res_str)
    
    assert res["status"] == "error"
    assert "Security Violation" in res["error"]

@pytest.mark.asyncio
async def test_execute_tool_l3_approved():
    console = DummyConsole()
    bridge = ToolBridge(console=console)
    
    # Mock Confirm.ask to return True (approved)
    with patch("src.cli.chat.tool_bridge.Confirm.ask", return_value=True) as mock_ask:
        # Mock actual tool execution to return success
        mock_tool = MagicMock()
        mock_tool.execute = AsyncMock(return_value={"status": "success", "output": "done"})
        
        # Mock lock manager
        from src.core.concurrency.lock_manager import lock_manager, LockResult
        with patch.object(lock_manager, "acquire", AsyncMock(return_value=LockResult(granted=True, file_path=".env"))), \
             patch.object(lock_manager, "release", AsyncMock(return_value=True)), \
             patch("src.cli.chat.tool_bridge.tool_registry.get", return_value=mock_tool):
             
            # .env write is L3 sensitive
            args = {"path": ".env", "content": "KEY=VAL"}
            res_str = await bridge.execute_tool("file_write", args, "00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000001")
            
            res = json.loads(res_str)
            assert res["status"] == "success"
            mock_ask.assert_called_once()

@pytest.mark.asyncio
async def test_execute_tool_l3_rejected():
    console = DummyConsole()
    bridge = ToolBridge(console=console)
    
    # Mock Confirm.ask to return False (rejected)
    with patch("src.cli.chat.tool_bridge.Confirm.ask", return_value=False) as mock_ask:
        # Mock lock manager
        from src.core.concurrency.lock_manager import lock_manager, LockResult
        with patch.object(lock_manager, "acquire", AsyncMock(return_value=LockResult(granted=True, file_path=".env"))), \
             patch.object(lock_manager, "release", AsyncMock(return_value=True)):
             
            # .env write is L3 sensitive
            args = {"path": ".env", "content": "KEY=VAL"}
            res_str = await bridge.execute_tool("file_write", args, "00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000001")
            
            res = json.loads(res_str)
            assert res["status"] == "error"
            assert "Permission denied" in res["error"]
            mock_ask.assert_called_once()

@pytest.mark.asyncio
async def test_lock_acquisition_during_write(tmp_path):
    console = DummyConsole()
    bridge = ToolBridge(console=console)
    
    # Mock tool execution
    mock_tool = MagicMock()
    mock_tool.execute = AsyncMock(return_value={"status": "success", "output": "written"})
    
    # We want to verify lock is acquired
    from src.core.concurrency.lock_manager import lock_manager
    original_acquire = lock_manager.acquire
    original_release = lock_manager.release
    
    acquired_paths = []
    released_paths = []
    
    async def mock_acquire(file_path, agent_id, task_id, priority, ttl_sec=300):
        acquired_paths.append(file_path)
        # return dummy granted LockResult
        from src.core.concurrency.lock_manager import LockResult
        return LockResult(granted=True, file_path=file_path)
        
    async def mock_release(file_path, agent_id):
        released_paths.append(file_path)
        return True

    lock_manager.acquire = mock_acquire
    lock_manager.release = mock_release
    
    try:
        with patch("src.cli.chat.tool_bridge.tool_registry.get", return_value=mock_tool):
            args = {"path": str(tmp_path / "hello.txt"), "content": "hello"}
            res_str = await bridge.execute_tool("file_write", args, "00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000001")
            
            res = json.loads(res_str)
            assert res["status"] == "success"
            
            # Lock should be acquired for resolved file path
            resolved_path = args["path"]
            assert resolved_path in acquired_paths
            assert resolved_path in bridge.acquired_locks
            
            # Release all locks
            await bridge.release_all_locks()
            assert resolved_path in released_paths
            assert len(bridge.acquired_locks) == 0
            
    finally:
        lock_manager.acquire = original_acquire
        lock_manager.release = original_release
