import pytest
import os
import ssl
from unittest.mock import patch, MagicMock
from src.config import Settings
from src.core.redis_pool import get_redis_client, get_async_redis_client, close_redis_connections

def test_redis_settings_env_fallback(monkeypatch):
    monkeypatch.setenv("REDIS_PASSWORD", "test-pass-123")
    monkeypatch.setenv("REDIS_SSL", "true")
    monkeypatch.setenv("REDIS_SSL_CERT_REQS", "required")
    
    # Instantiate new settings to check initialization
    new_settings = Settings()
    assert new_settings.redis_password == "test-pass-123"
    assert new_settings.redis_ssl is True
    assert new_settings.redis_ssl_cert_reqs == "required"

@pytest.mark.anyio
async def test_redis_client_ssl_options(monkeypatch):
    # Setup test settings
    monkeypatch.setattr("src.config.settings.redis_ssl", True)
    monkeypatch.setattr("src.config.settings.redis_ssl_cert_reqs", "required")
    monkeypatch.setattr("src.config.settings.redis_host", "localhost")
    monkeypatch.setattr("src.config.settings.redis_port", 6379)
    monkeypatch.setattr("src.config.settings.redis_password", "securepwd")
    
    # Ensure connections are closed first
    await close_redis_connections()
    
    # Mock redis from_url methods
    mock_sync_from_url = MagicMock()
    
    from unittest.mock import AsyncMock
    mock_async_client = MagicMock()
    mock_async_client.aclose = AsyncMock()
    mock_async_from_url = MagicMock(return_value=mock_async_client)
    
    monkeypatch.setattr("redis.Redis.from_url", mock_sync_from_url)
    monkeypatch.setattr("redis.asyncio.from_url", mock_async_from_url)
    
    # Call client getters
    get_redis_client()
    get_async_redis_client()
    
    # Verify sync call args
    mock_sync_from_url.assert_called_once()
    args, kwargs = mock_sync_from_url.call_args
    assert kwargs.get("ssl_cert_reqs") == ssl.CERT_REQUIRED
    assert "rediss://" in args[0]
    assert ":securepwd@" in args[0]
    
    # Verify async call args
    mock_async_from_url.assert_called_once()
    args_async, kwargs_async = mock_async_from_url.call_args
    assert kwargs_async.get("ssl_cert_reqs") == ssl.CERT_REQUIRED
    assert "rediss://" in args_async[0]
    assert ":securepwd@" in args_async[0]
    
    # Clean up global client states
    await close_redis_connections()
