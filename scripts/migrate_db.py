import asyncio
import sys
import os

# Add src to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from src.config import settings

async def migrate():
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as conn:
        print("Checking/Altering skills table...")
        # Add column if not exists
        await conn.execute(text(
            "ALTER TABLE skills ADD COLUMN IF NOT EXISTS workspace_path VARCHAR(512) DEFAULT NULL;"
        ))
        print("Migration complete.")
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(migrate())
