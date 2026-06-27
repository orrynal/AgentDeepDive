import pytest
import json
import urllib.request
from unittest.mock import MagicMock
from fastapi import Request, HTTPException

from src.config import settings, Settings
from src.core.governance.guardrails import GuardrailEngine
from src.core.governance.api_auth import verify_opa_api_permission
from src.core.auth.models import UserModel

def test_guardrail_engine_multitenant_opa(monkeypatch):
    """Verify that GuardrailEngine correctly resolves tenant-specific workspace path and respects role constraints via OPA."""
    monkeypatch.setattr(settings, "opa_enabled", True)
    monkeypatch.setattr(settings, "opa_url", "http://localhost:8181")
    monkeypatch.setattr(Settings, "resolved_workspace_path", property(lambda self: "/workspace"))

    uploaded_policies = {}
    evaluated_inputs = []

    class MockResponse:
        def __init__(self, data, status=200):
            self.data = data
            self.status = status

        def read(self):
            return self.data

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    def mock_urlopen(req, timeout=None):
        url = req.full_url
        method = req.get_method()

        if method == "PUT" and "/v1/policies/" in url:
            policy_id = url.split("/v1/policies/")[-1]
            policy_data = req.data.decode("utf-8")
            uploaded_policies[policy_id] = policy_data
            return MockResponse(b"{}", 200)

        elif method == "POST" and "/v1/data/guardrails/risk_level" in url:
            input_payload = json.loads(req.data.decode("utf-8"))
            evaluated_inputs.append(input_payload)

            inp = input_payload["input"]
            tool_name = inp["tool_name"]
            role = inp["role"]
            target_path = inp["arguments"].get("target_path", "")
            workspace_path = inp["workspace_path"]

            decision = "L1"

            # Viewer role restriction mock (viewer cannot write or execute shell)
            if role == "viewer" and tool_name in ["file_write", "shell_exec"]:
                decision = "L4"
            # Directory list & read tools are L0
            elif tool_name in ["directory_list", "file_read"]:
                decision = "L0"
            # Path out of tenant workspace restriction
            elif tool_name in ["file_write", "file_read"] and target_path:
                if not target_path.startswith(workspace_path):
                    decision = "L4"

            return MockResponse(json.dumps({"result": decision}).encode("utf-8"), 200)

        return MockResponse(b"{}", 404)

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    engine = GuardrailEngine()

    # 1. Test tenant-specific path resolution
    # Tenant A (Workspace path should resolve to /workspace/tenants/tenant-a)
    # Target path inside tenant A workspace -> L1
    assert engine.evaluate("file_write", {"target_path": "/workspace/tenants/tenant-a/file.txt"}, tenant_id="tenant-a", role="developer") == "L1"
    # Target path outside tenant A workspace -> L4
    assert engine.evaluate("file_write", {"target_path": "/workspace/tenants/tenant-b/file.txt"}, tenant_id="tenant-a", role="developer") == "L4"

    # 2. Test viewer role restriction
    assert engine.evaluate("file_write", {"target_path": "/workspace/tenants/tenant-a/file.txt"}, tenant_id="tenant-a", role="viewer") == "L4"
    assert engine.evaluate("shell_exec", {"command": "ls"}, tenant_id="tenant-a", role="viewer") == "L4"

    # 3. Test policy files registration
    assert "guardrails" in uploaded_policies
    assert "api_auth" in uploaded_policies


@pytest.mark.anyio
async def test_api_auth_opa_dependency(monkeypatch):
    """Test verify_opa_api_permission FastAPI dependency behavior with OPA enabled."""
    monkeypatch.setattr(settings, "opa_enabled", True)

    # Mock evaluate_api_permission
    mock_evaluate = MagicMock()
    monkeypatch.setattr(GuardrailEngine, "evaluate_api_permission", mock_evaluate)

    # Helper function to create mock Request
    def make_mock_request(method: str, path: str, path_params: dict):
        req = MagicMock(spec=Request)
        req.method = method
        req.url = MagicMock()
        req.url.path = path
        req.path_params = path_params
        return req

    # 1. Admin user - allowed
    user_admin = UserModel(username="admin_user", tenant_id="tenant-123", role="admin")
    req_admin = make_mock_request("POST", "/api/v1/workspaces/tenant-123", {"workspace_id": "tenant-123"})
    mock_evaluate.return_value = True

    res = await verify_opa_api_permission(req_admin, user_admin)
    assert res == user_admin
    mock_evaluate.assert_called_with(
        method="POST",
        path="/api/v1/workspaces/tenant-123",
        tenant_id="tenant-123",
        role="admin",
        path_params={"workspace_id": "tenant-123"}
    )

    # 2. Viewer user tries POST - blocked (evaluate returns False)
    user_viewer = UserModel(username="viewer_user", tenant_id="tenant-123", role="viewer")
    req_viewer = make_mock_request("POST", "/api/v1/workspaces/tenant-123", {"workspace_id": "tenant-123"})
    mock_evaluate.return_value = False

    with pytest.raises(HTTPException) as exc_info:
        await verify_opa_api_permission(req_viewer, user_viewer)
    assert exc_info.value.status_code == 403
    assert "OPA Security Block" in exc_info.value.detail

    # 3. Cross-tenant access (Developer tries to access Tenant B workspace) - blocked
    user_dev = UserModel(username="dev_user", tenant_id="tenant-a", role="developer")
    req_cross = make_mock_request("GET", "/api/v1/workspaces/tenant-b", {"workspace_id": "tenant-b"})
    mock_evaluate.return_value = False

    with pytest.raises(HTTPException) as exc_info:
        await verify_opa_api_permission(req_cross, user_dev)
    assert exc_info.value.status_code == 403
    assert "OPA Security Block" in exc_info.value.detail
