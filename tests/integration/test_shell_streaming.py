import asyncio
import json
import pytest
from src.core.agent.tools import _shell_exec, current_task_id
from src.core.agent.pool import agent_bus

@pytest.mark.asyncio
async def test_shell_output_streaming():
    task_id = "test_stream_task:node_1"
    
    # We will subscribe to terminal_updates
    received_messages = []
    
    async def handle_terminal_update(msg):
        received_messages.append(msg.get("payload"))
        
    await agent_bus.subscribe("terminal_updates", handle_terminal_update)
    
    # We need to run _shell_exec. Since it blocks, we run it using asyncio.to_thread
    # to preserve context variables properly.
    def run_command_in_thread():
        token = current_task_id.set(task_id)
        try:
            return _shell_exec("echo 'hello streaming line'")
        finally:
            current_task_id.reset(token)

    # Run in thread
    res = await asyncio.to_thread(run_command_in_thread)
    assert "hello streaming line" in res
    
    # Wait a bit for pubsub messages to be processed
    await asyncio.sleep(0.5)
    
    # Unsubscribe
    await agent_bus.unsubscribe("terminal_updates", handle_terminal_update)
    
    # Assert we received the streamed line via pubsub
    assert len(received_messages) > 0
    combined_chunks = "".join([m.get("chunk", "") for m in received_messages])
    assert "hello streaming line" in combined_chunks
    assert all(m.get("task_id") == task_id for m in received_messages)
