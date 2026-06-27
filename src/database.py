"""Database connection and session management."""

import json
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator, TEXT
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
from src.config import settings

class Base(DeclarativeBase):
    """Shared Declarative Base class for all ORM models."""
    pass

class LazyEngineProxy:
    def __init__(self):
        self._engine = None
        self._current_url = None

    def _get_engine(self):
        url = settings.database_url
        if self._engine is None or self._current_url != url:
            if url.startswith("sqlite"):
                self._engine = create_async_engine(
                    url,
                    echo=settings.debug,
                )
            else:
                self._engine = create_async_engine(
                    url,
                    echo=settings.debug,
                    pool_size=10,
                    max_overflow=20,
                    pool_pre_ping=True,
                )
            self._current_url = url
        return self._engine

    def __getattr__(self, name):
        return getattr(self._get_engine(), name)

class LazyAsyncSessionmaker:
    def __init__(self, engine_proxy):
        self._engine_proxy = engine_proxy
        self._maker = None
        self._current_url = None

    def _get_maker(self):
        url = settings.database_url
        if self._maker is None or self._current_url != url:
            self._maker = async_sessionmaker(
                self._engine_proxy._get_engine(),
                class_=AsyncSession,
                expire_on_commit=False
            )
            self._current_url = url
        return self._maker

    def __call__(self, *args, **kwargs):
        return self._get_maker()(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._get_maker(), name)

engine = LazyEngineProxy()
async_session = LazyAsyncSessionmaker(engine)


class CompatibleArray(TypeDecorator):
    """A SQLite-compatible array type that serializes/deserializes lists to JSON strings on SQLite,
    while using the native PostgreSQL ARRAY type on PostgreSQL.
    """
    impl = TEXT
    cache_ok = True

    def __init__(self, item_type):
        super().__init__()
        self.item_type = item_type
        self.pg_array = PG_ARRAY(item_type)

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(self.pg_array)
        else:
            return dialect.type_descriptor(TEXT())

    def process_bind_param(self, value, dialect):
        if dialect.name == "postgresql":
            # Delegate to postgresql array bind
            return self.pg_array.bind_processor(dialect)(value) if self.pg_array.bind_processor(dialect) else value
        else:
            if value is None:
                return None
            return json.dumps(value)

    def process_result_value(self, value, dialect):
        if dialect.name == "postgresql":
            # Delegate to postgresql array result
            return self.pg_array.result_processor(dialect, TEXT())(value) if self.pg_array.result_processor(dialect, TEXT()) else value
        else:
            if value is None:
                return []
            if isinstance(value, list):
                return value
            try:
                return json.loads(value)
            except Exception:
                return []


async def get_db() -> AsyncSession:
    """FastAPI dependency: yields a database session."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def close_db_connections():
    """Dispose of the global SQLAlchemy async engine."""
    if engine._engine is not None:
        await engine._engine.dispose()
        engine._engine = None


# ── Global Multi-Tenant Query Filter Listener ──
from sqlalchemy import event
from sqlalchemy.orm import with_loader_criteria, Session

@event.listens_for(Session, "do_orm_execute")
def _do_orm_execute(orm_execute_state):
    """Automatically apply tenant_id isolation filter to ORM SELECT queries."""
    if orm_execute_state.is_column_load or not orm_execute_state.is_select:
        return

    from src.core.auth.context import current_tenant_id
    tenant_id = current_tenant_id.get()

    if tenant_id is not None:
        # Disable compilation cache to prevent tenant ID caching leaks
        orm_execute_state.update_execution_options(compiled_cache=None)
        orm_execute_state.statement = orm_execute_state.statement.options(
            with_loader_criteria(
                Base,
                lambda cls, tenant_id=tenant_id: cls.tenant_id == tenant_id if hasattr(cls, "tenant_id") and cls.__name__ != "UserModel" else True,
                include_aliases=True,
                propagate_to_loaders=True
            )
        )

