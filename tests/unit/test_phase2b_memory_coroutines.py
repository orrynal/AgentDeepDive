import asyncio
import gc
import sys
import pytest
from unittest.mock import MagicMock, patch

from src.core.memory.rag_manager import rag_manager
from src.core.orchestrator.models import DAGDefinition, DAGNode, NodeColor
from src.core.orchestrator.dag_engine import DAGEngine
from src.api.routes.health import manual_cleanup


@pytest.mark.asyncio
async def test_rag_manager_close():
    # Mock pymilvus connections
    with patch("src.core.memory.rag_manager.connections") as mock_connections:
        # Save original states
        orig_kb = getattr(rag_manager, "kb_collection", None)
        orig_em = getattr(rag_manager, "em_collection", None)
        orig_connected = getattr(rag_manager, "connected", False)
        
        # Set dummy collections
        mock_kb = MagicMock()
        mock_em = MagicMock()
        rag_manager.kb_collection = mock_kb
        rag_manager.em_collection = mock_em
        rag_manager.connected = True
        
        try:
            rag_manager.close()
            
            # Assert connections.disconnect is called
            mock_connections.disconnect.assert_any_call("default")
            assert rag_manager.kb_collection is None
            assert rag_manager.em_collection is None
        finally:
            # Restore
            rag_manager.kb_collection = orig_kb
            rag_manager.em_collection = orig_em
            rag_manager.connected = orig_connected


@pytest.mark.asyncio
async def test_dag_engine_execution_cascade_cancel():
    engine = DAGEngine(skill_service=None)
    
    # Directly mock _execute_node to simulate a long running node execution that handles cancel
    async def mock_execute_node(dag, node):
        engine._transition(dag, node, NodeColor.YELLOW)
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            engine._transition(dag, node, NodeColor.RED)
            node.error = "Cancelled"
            raise

    engine._execute_node = mock_execute_node
    
    node_a = DAGNode(node_id="A", name="Node A", skill_id="test")
    dag = DAGDefinition(
        dag_id="test-cancel-dag",
        name="Cancel DAG",
        nodes=[node_a]
    )
    
    # We run the DAG execution in a task and then cancel it.
    loop = asyncio.get_running_loop()
    exec_task = loop.create_task(engine.execute(dag, {}))
    
    # Let it start and enter the sleep
    await asyncio.sleep(0.1)
    
    # Cancel the main execution task
    exec_task.cancel()
    
    with pytest.raises(asyncio.CancelledError):
        await exec_task
        
    # Verify node A was set to RED on cancel
    assert node_a.color == NodeColor.RED


@pytest.mark.asyncio
async def test_health_cleanup_endpoint():
    # Test the POST /health/cleanup endpoint logic
    # Injects mock psutil into sys.modules to prevent ModuleNotFoundError
    mock_psutil = MagicMock()
    mock_process = MagicMock()
    mock_psutil.Process.return_value = mock_process
    
    sys.modules["psutil"] = mock_psutil
    
    with patch("gc.collect", return_value=123) as mock_gc:
         
        # Make sure rag_manager collections are mockable
        orig_kb = getattr(rag_manager, "kb_collection", None)
        orig_em = getattr(rag_manager, "em_collection", None)
        rag_manager.kb_collection = MagicMock()
        rag_manager.em_collection = MagicMock()
        
        try:
            # We simulate memory dropping after cleanup
            def side_effect_rss():
                # First call (before): 100MB, Second call (after): 80MB
                if side_effect_rss.called:
                    return MagicMock(rss=80 * 1024 * 1024)
                side_effect_rss.called = True
                return MagicMock(rss=100 * 1024 * 1024)
            side_effect_rss.called = False
            
            mock_process.memory_info.side_effect = side_effect_rss
            
            response = await manual_cleanup()
            
            assert response["status"] == "ok"
            assert mock_gc.call_count >= 1
            assert response["memory_before_mb"] == 100.0
            assert response["memory_after_mb"] == 80.0
            assert response["released_mb"] == 20.0
            
            # Verify RAG collection pointers were cleared in the router
            assert rag_manager.kb_collection is None
            assert rag_manager.em_collection is None
        finally:
            rag_manager.kb_collection = orig_kb
            rag_manager.em_collection = orig_em
            sys.modules.pop("psutil", None)
