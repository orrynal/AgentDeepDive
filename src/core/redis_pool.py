import asyncio
import redis.asyncio as aioredis
import redis
from src.config import settings

# Global async Redis client and its loop reference
_async_redis_client: aioredis.Redis | None = None
_async_redis_loop: asyncio.AbstractEventLoop | None = None

# Global sync Redis client
_sync_redis_client: redis.Redis | None = None

def get_redis_client() -> redis.Redis:
    """Get or create the global synchronous Redis client."""
    global _sync_redis_client
    if _sync_redis_client is None:
        kwargs = {}
        if settings.redis_ssl:
            import ssl
            cert_reqs = ssl.CERT_NONE
            if settings.redis_ssl_cert_reqs == "required":
                cert_reqs = ssl.CERT_REQUIRED
            elif settings.redis_ssl_cert_reqs == "optional":
                cert_reqs = ssl.CERT_OPTIONAL
            kwargs["ssl_cert_reqs"] = cert_reqs

        _sync_redis_client = redis.Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            max_connections=10,
            **kwargs
        )
    return _sync_redis_client

def get_async_redis_client() -> aioredis.Redis:
    """Get or create the global asynchronous Redis client.
    Handles event loop changes gracefully.
    """
    global _async_redis_client, _async_redis_loop
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    if _async_redis_client is None or (current_loop is not None and _async_redis_loop != current_loop):
        kwargs = {}
        if settings.redis_ssl:
            import ssl
            cert_reqs = ssl.CERT_NONE
            if settings.redis_ssl_cert_reqs == "required":
                cert_reqs = ssl.CERT_REQUIRED
            elif settings.redis_ssl_cert_reqs == "optional":
                cert_reqs = ssl.CERT_OPTIONAL
            kwargs["ssl_cert_reqs"] = cert_reqs

        _async_redis_client = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            max_connections=500,
            **kwargs
        )
        _async_redis_loop = current_loop

    return _async_redis_client

async def close_redis_connections():
    """Close the global Redis client connections if they exist."""
    global _async_redis_client, _sync_redis_client, _async_redis_loop
    if _async_redis_client is not None:
        try:
            await _async_redis_client.aclose()
        except AttributeError:
            await _async_redis_client.close()
        _async_redis_client = None
    _async_redis_loop = None
    if _sync_redis_client is not None:
        _sync_redis_client.close()
        _sync_redis_client = None
