import pytest
from src.core.agent.tools import Tool, ToolRegistry

def test_tool_schema_and_execution():
    # Define a simple test function
    def add_numbers(a: int, b: int) -> int:
        return a + b

    # Create a Tool instance
    tool = Tool(
        name="add_numbers",
        description="Add two numbers together",
        func=add_numbers,
        parameters={
            "type": "object",
            "properties": {
                "a": {"type": "integer"},
                "b": {"type": "integer"}
            },
            "required": ["a", "b"]
        }
    )

    # 1. Test LLM Schema conversion
    schema = tool.to_llm_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "add_numbers"
    assert "a" in schema["function"]["parameters"]["properties"]

@pytest.mark.anyio
async def test_tool_execution_success():
    def add_numbers(a: int, b: int) -> int:
        return a + b

    tool = Tool("add_numbers", "Add two numbers", add_numbers)
    res = await tool.execute(a=5, b=10)
    assert res["status"] == "success"
    assert res["output"] == 15

@pytest.mark.anyio
async def test_tool_execution_failure():
    def divide_numbers(a: int, b: int) -> float:
        return a / b

    tool = Tool("divide_numbers", "Divide two numbers", divide_numbers)
    res = await tool.execute(a=5, b=0)
    assert res["status"] == "error"
    assert "division by zero" in res["error"]

def test_tool_registry():
    registry = ToolRegistry()
    
    # Verify built-in tools are registered
    assert registry.get("file_read") is not None
    assert registry.get("shell_exec") is not None

    # Verify custom tool registration
    def dummy_func():
        return "dummy"
    
    dummy_tool = Tool("dummy", "Dummy description", dummy_func)
    registry.register(dummy_tool)
    
    assert registry.get("dummy") is dummy_tool
