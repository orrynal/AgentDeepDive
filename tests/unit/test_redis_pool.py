import pytest
import asyncio
import redis
import redis.asyncio as aioredis
from src.core.redis_pool import get_redis_client, get_async_redis_client, close_redis_connections

@pytest.mark.anyio
async def test_redis_pool_clients():
    # 1. Test synchronous client
    sync_client = get_redis_client()
    assert isinstance(sync_client, redis.Redis)
    
    # 2. Test asynchronous client
    async_client = get_async_redis_client()
    assert isinstance(async_client, aioredis.Redis)
    
    # 3. Test loop detection
    loop1 = asyncio.get_running_loop()
    client1 = get_async_redis_client()
    
    # Create a separate loop to verify that loop detection recreates the client
    # (In pytest-anyio, running a separate coroutine or manually calling the function with mocked loop works)
    class FakeLoop:
        pass
        
    import src.core.redis_pool as rp
    original_loop = rp._async_redis_loop
    rp._async_redis_loop = FakeLoop()
    
    client2 = get_async_redis_client()
    assert client2 is not client1
    
    # Restore loop
    rp._async_redis_loop = original_loop

    # 4. Clean up
    await close_redis_connections()
    assert rp._async_redis_client is None
    assert rp._sync_redis_client is None


def test_redis_url_generation():
    from src.config import Settings
    
    # 1. Default (no ssl, no password)
    s = Settings()
    s.redis_host = "1.2.3.4"
    s.redis_port = 6379
    s.redis_db = 2
    s.redis_password = ""
    s.redis_ssl = False
    assert s.redis_url == "redis://1.2.3.4:6379/2"

    # 2. With password
    s.redis_password = "mypassword"
    assert s.redis_url == "redis://:mypassword@1.2.3.4:6379/2"

    # 3. With SSL
    s.redis_ssl = True
    assert s.redis_url == "rediss://:mypassword@1.2.3.4:6379/2"

    # 4. Raw URL bypass
    s.redis_host = "redis://user:pass@localhost:9999/5"
    assert s.redis_url == "redis://user:pass@localhost:9999/5"
    
    s.redis_host = "rediss://localhost:1234/0"
    assert s.redis_url == "rediss://localhost:1234/0"
