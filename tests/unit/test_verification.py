import os
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.core.orchestrator.models import DAGDefinition, DAGNode
from src.core.verification.invariants import verify_invariants
from src.core.verification.e2e_runner import run_e2e_tests
from src.core.verification.vlm_auditor import verify_visuals_with_vlm

@pytest.mark.asyncio
async def test_verify_invariants_success():
    dag = DAGDefinition(name="Test DAG")
    node = DAGNode(
        node_id="node-1",
        constraints={
            "verification": {
                "invariants": [
                    "node.node_id == 'node-1'",
                    "result.get('status') == 'ok'"
                ]
            }
        },
        result={"status": "ok"}
    )
    
    res = await verify_invariants(dag, node)
    assert res["success"] is True
    assert "passed successfully" in res["details"]

@pytest.mark.asyncio
async def test_verify_invariants_failure():
    dag = DAGDefinition(name="Test DAG")
    node = DAGNode(
        node_id="node-1",
        constraints={
            "verification": {
                "invariants": [
                    "result.get('score') > 10"
                ]
            }
        },
        result={"score": 5}
    )
    
    res = await verify_invariants(dag, node)
    assert res["success"] is False
    assert "evaluated to False" in res["details"]

@pytest.mark.asyncio
async def test_verify_invariants_syntax_check():
    dag = DAGDefinition(name="Test DAG")
    # Correct syntax
    node_ok = DAGNode(
        node_id="node-ok",
        result={"output": "Here is the code:\n```python\nprint('hello')\n```"}
    )
    res_ok = await verify_invariants(dag, node_ok)
    assert res_ok["success"] is True

    # Incorrect syntax
    node_bad = DAGNode(
        node_id="node-bad",
        result={"output": "Here is broken code:\n```python\nif True\n    print('hello')\n```"}
    )
    res_bad = await verify_invariants(dag, node_bad)
    assert res_bad["success"] is False
    assert "compilation check" in res_bad["details"]

@pytest.mark.asyncio
async def test_run_e2e_tests_skipped():
    dag = DAGDefinition(name="Test DAG")
    node = DAGNode(node_id="node-1", constraints={})
    
    res = await run_e2e_tests(dag, node)
    assert res["success"] is True
    assert "No E2E test scripts defined." in res["details"]

@pytest.mark.asyncio
@patch("src.core.verification.e2e_runner.async_playwright")
async def test_run_e2e_tests_mocked(mock_playwright):
    # Mocking playwright browser and page behavior
    mock_browser = AsyncMock()
    mock_context = AsyncMock()
    mock_page = AsyncMock()
    
    mock_context.new_page.return_value = mock_page
    mock_browser.new_context.return_value = mock_context
    
    # Mock playwright context manager
    playwright_instance = MagicMock()
    playwright_instance.chromium.launch = AsyncMock(return_value=mock_browser)
    
    # Configure mock_playwright async context manager
    mock_playwright.return_value.__aenter__.return_value = playwright_instance
    
    dag = DAGDefinition(name="Test DAG")
    node = DAGNode(
        node_id="node-1",
        constraints={
            "verification": {
                "e2e": "tests/test_ui.py",
                "app_url": "http://localhost:5174",
                "steps": [
                    {"action": "click", "selector": "#btn-test"},
                    {"action": "type", "selector": "#input-test", "value": "test value"},
                    {"action": "wait", "selector": "#result-div"}
                ]
            }
        }
    )
    
    # Mock screenshot existence
    with patch("pathlib.Path.exists", return_value=True):
        res = await run_e2e_tests(dag, node)
        
    assert res["success"] is True
    assert "/verification/screenshot-" in res["screenshot_path"]
    assert "Clicked selector" in res["details"]
    assert "Typed" in res["details"]

@pytest.mark.asyncio
@patch("src.core.verification.vlm_auditor.litellm.acompletion")
@patch("src.core.verification.vlm_auditor.encode_image")
async def test_verify_visuals_with_vlm_mocked(mock_encode, mock_acompletion):
    # Mock image encoder to return a dummy string
    mock_encode.return_value = "dummybase64data"
    
    # Mock LiteLLM vision completion response
    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_message = MagicMock()
    mock_message.content = '{"success": true, "details": "Visual rules verified successfully."}'
    mock_choice.message = mock_message
    mock_response.choices = [mock_choice]
    mock_acompletion.return_value = mock_response
    
    dag = DAGDefinition(name="Test DAG")
    node = DAGNode(
        node_id="node-1",
        constraints={
            "verification": {
                "vlm_checks": [
                    {"prompt": "Is the snake visible?", "expect": "yes"}
                ]
            }
        }
    )
    
    # Mock file path validation check
    with patch("pathlib.Path.exists", return_value=True):
        res = await verify_visuals_with_vlm(dag, node, "/verification/screenshot-test.png")
        
    assert res["success"] is True
    assert "verified successfully" in res["details"]
