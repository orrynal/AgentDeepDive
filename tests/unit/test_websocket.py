import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from src.api.main import app
from src.config import settings

pytestmark = pytest.mark.integration

def test_websocket_anonymous_access_when_no_api_key(monkeypatch):
    """If no API key is configured, anonymous connections without token must succeed."""
    monkeypatch.setattr(settings, "api_key", "")
    
    client = TestClient(app)
    with client.websocket_connect("/api/v1/ws") as websocket:
        websocket.send_text("ping")
        data = websocket.receive_text()
        assert data == "pong"



def test_websocket_blocked_when_api_key_configured_but_missing(monkeypatch):
    """If API key is configured, anonymous connections without key must be rejected."""
    monkeypatch.setattr(settings, "api_key", "secret-test-api-key")
    
    client = TestClient(app)
    with pytest.raises(Exception):
        with client.websocket_connect("/api/v1/ws") as websocket:
            websocket.send_text("ping")


def test_websocket_access_via_query_token(monkeypatch):
    """If API key is configured, connection is allowed when token is provided in query string."""
    monkeypatch.setattr(settings, "api_key", "secret-test-api-key")
    
    client = TestClient(app)
    with client.websocket_connect("/api/v1/ws?token=secret-test-api-key") as websocket:
        websocket.send_text("ping")
        data = websocket.receive_text()
        assert data == "pong"


def test_websocket_access_via_query_api_key(monkeypatch):
    """If API key is configured, connection is allowed when api_key is provided in query string."""
    monkeypatch.setattr(settings, "api_key", "secret-test-api-key")
    
    client = TestClient(app)
    with client.websocket_connect("/api/v1/ws?api_key=secret-test-api-key") as websocket:
        websocket.send_text("ping")
        data = websocket.receive_text()
        assert data == "pong"


def test_websocket_access_via_headers(monkeypatch):
    """If API key is configured, connection is allowed when X-API-Key is provided in headers."""
    monkeypatch.setattr(settings, "api_key", "secret-test-api-key")
    
    client = TestClient(app)
    with client.websocket_connect("/api/v1/ws", headers={"X-API-Key": "secret-test-api-key"}) as websocket:
        websocket.send_text("ping")
        data = websocket.receive_text()
        assert data == "pong"
