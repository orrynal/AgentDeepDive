import pytest
from unittest.mock import patch, MagicMock
from src.cli.context import CLIMode, CLIContext

def test_cli_context_force_mode():
    ctx = CLIContext(mode=CLIMode.LOCAL)
    assert ctx.resolved_mode == CLIMode.LOCAL

    ctx = CLIContext(mode=CLIMode.REMOTE)
    assert ctx.resolved_mode == CLIMode.REMOTE

@patch("httpx.Client.get")
def test_cli_context_detect_remote(mock_get):
    # Mock health endpoint returning 200 OK
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_get.return_value = mock_resp

    ctx = CLIContext(mode=CLIMode.AUTO)
    assert ctx.resolved_mode == CLIMode.REMOTE
    mock_get.assert_called_once_with("http://localhost:8000/health")

@patch("httpx.Client.get")
def test_cli_context_detect_local_failure(mock_get):
    # Mock health endpoint raising an exception
    mock_get.side_effect = Exception("Connection refused")

    ctx = CLIContext(mode=CLIMode.AUTO)
    assert ctx.resolved_mode == CLIMode.LOCAL

@patch("httpx.AsyncClient.get")
@pytest.mark.asyncio
async def test_cli_context_detect_remote_async(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_get.return_value = mock_resp

    ctx = CLIContext(mode=CLIMode.AUTO)
    mode = await ctx.detect_mode_async()
    assert mode == CLIMode.REMOTE

@patch("httpx.AsyncClient.get")
@pytest.mark.asyncio
async def test_cli_context_detect_local_async_failure(mock_get):
    mock_get.side_effect = Exception("Connection refused")

    ctx = CLIContext(mode=CLIMode.AUTO)
    mode = await ctx.detect_mode_async()
    assert mode == CLIMode.LOCAL
