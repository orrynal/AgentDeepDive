import sys
import pytest
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine

print("\n--- DEBUG PATHS ---")
print("sys.path:", sys.path)
import src
print("src package file:", getattr(src, "__file__", "no file"))
print("-------------------\n")

from src.config import settings
from src.database import engine as global_engine

@pytest.fixture(scope="session")
def event_loop():
    """Create a session-scoped event loop to run all tests in the same loop."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session", autouse=True)
async def cleanup_db_connections():
    """Ensure database engine connection pool is disposed at the end of the test session."""
    yield
    await global_engine.dispose()
