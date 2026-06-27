"""Unit tests for OPA policy hot-reload mechanism when workspace/tenant changes."""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from src.api.main import app
from src.core.workspace.manager import workspace_manager

@pytest.fixture
def client():
    # Disable verify_api_key security dependency for testing routes
    from src.api.security import verify_api_key
    app.dependency_overrides[verify_api_key] = lambda: "mock-api-key"
    yield TestClient(app)
    app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_workspace_activation_triggers_opa_hot_reload(client):
    """Test that switching active workspace triggers OPA policy upload/reload."""
    # Mock workspace_manager to avoid physical folder checks or side effects
    mock_wm = MagicMock()
    mock_wm.active_workspace = "/mock/path/new"
    mock_wm.workspaces = ["/mock/path/old", "/mock/path/new"]
    mock_wm.set_active_workspace = MagicMock()
    
    with patch("src.api.routes.workspaces.workspace_manager", mock_wm), \
         patch("src.core.governance.guardrails.GuardrailEngine._upload_policy_to_opa") as mock_upload:
         
        mock_upload.return_value = True
        
        # Call the switch active workspace API
        response = client.post(
            "/api/v1/workspaces/active",
            json={"path": "/mock/path/new"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["active_workspace"] == "/mock/path/new"
        
        # Verify that workspace_manager was called
        mock_wm.set_active_workspace.assert_called_once_with("/mock/path/new")
        # Verify that GuardrailEngine._upload_policy_to_opa was called for hot-reload
        mock_upload.assert_called_once()

@pytest.mark.asyncio
async def test_workspace_creation_triggers_opa_hot_reload(client):
    """Test that creating a new workspace triggers OPA policy upload/reload."""
    mock_wm = MagicMock()
    mock_wm.active_workspace = "/mock/path/created"
    mock_wm.workspaces = ["/mock/path/created"]
    mock_wm.set_active_workspace = MagicMock()
    
    # We patch os.makedirs, os.path.exists, open, subprocess.run to isolate disk / git logic
    with patch("src.api.routes.workspaces.workspace_manager", mock_wm), \
         patch("os.makedirs") as mock_makedirs, \
         patch("os.path.exists", return_value=True), \
         patch("src.core.governance.guardrails.GuardrailEngine._upload_policy_to_opa") as mock_upload:
         
        mock_upload.return_value = True
        
        # Call the create workspace API
        response = client.post(
            "/api/v1/workspaces",
            json={"path": "/mock/path/created"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["active_workspace"] == "/mock/path/created"
        
        # Verify OPA policy was hot-reloaded
        mock_upload.assert_called_once()

@pytest.mark.asyncio
async def test_workspace_switch_graceful_on_opa_error(client):
    """Test that switching workspace succeeds even if OPA reload raises an exception (graceful degradation)."""
    mock_wm = MagicMock()
    mock_wm.active_workspace = "/mock/path/new"
    mock_wm.workspaces = ["/mock/path/new"]
    mock_wm.set_active_workspace = MagicMock()
    
    with patch("src.api.routes.workspaces.workspace_manager", mock_wm), \
         patch("src.core.governance.guardrails.GuardrailEngine._upload_policy_to_opa", side_effect=Exception("OPA service unreachable")):
         
        # Switch workspace, which should NOT crash even though OPA reload fails
        response = client.post(
            "/api/v1/workspaces/active",
            json={"path": "/mock/path/new"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["active_workspace"] == "/mock/path/new"
        mock_wm.set_active_workspace.assert_called_once_with("/mock/path/new")
