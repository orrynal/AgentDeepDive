import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from src.core.governance.ssrf import is_safe_url
from src.api.main import app
from tests.unit.test_api_routes import client, mock_db

def test_is_safe_url_restricted():
    # Loopback and private IP blocks should be blocked
    assert is_safe_url("http://127.0.0.1") is False
    assert is_safe_url("https://localhost/callback") is False
    assert is_safe_url("http://192.168.1.100") is False
    assert is_safe_url("http://10.0.0.1") is False
    assert is_safe_url("http://172.16.0.1") is False
    assert is_safe_url("http://[::1]") is False
    assert is_safe_url("ftp://google.com") is False  # Invalid protocol
    assert is_safe_url("") is False

def test_is_safe_url_public():
    # Valid public domain names or public IPs should be accepted
    # We mock DNS lookup for stability in offline test environments
    with patch("socket.getaddrinfo") as mock_getaddrinfo:
        # Resolve to a public IP
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", ("8.8.8.8", 0))
        ]
        assert is_safe_url("https://n8n.io/webhook") is True
        assert is_safe_url("http://8.8.8.8") is True

@pytest.mark.anyio
async def test_trigger_webhook_ssrf_validation(client, monkeypatch):
    headers = {"X-API-Key": "test_api_key"}
    
    # Unsafe URL should result in a 400 Bad Request
    payload_unsafe = {
        "event": "jira_bug",
        "task_description": "Fix a spelling error in README",
        "callback_url": "http://127.0.0.1:8000/internal-callback"
    }
    resp = await client.post("/api/v1/webhooks/n8n", json=payload_unsafe, headers=headers)
    assert resp.status_code == 400
    assert "Invalid callback_url" in resp.json()["detail"]

    # Safe URL should be accepted (200 status code)
    # We mock is_safe_url to bypass external network calls during tests
    monkeypatch.setattr("src.core.governance.ssrf.is_safe_url", lambda url: True)
    
    # Mock split_task and execute to prevent actual DAG execution
    async def mock_run_n8n_flow(*args, **kwargs):
        pass
    monkeypatch.setattr("src.api.routes.webhooks.run_n8n_flow_in_background", mock_run_n8n_flow)

    payload_safe = {
        "event": "jira_bug",
        "task_description": "Fix a spelling error in README",
        "callback_url": "https://external-n8n.example.com/callback"
    }
    resp = await client.post("/api/v1/webhooks/n8n", json=payload_safe, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"
