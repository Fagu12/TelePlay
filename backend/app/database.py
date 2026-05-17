"""
Database setup with SQLAlchemy async support.
Optimized for Railway's internal PostgreSQL service (postgres.railway.internal).
"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.engine import make_url
from .config import get_settings

settings = get_settings()

# Parse and convert database URL for async drivers
url = make_url(settings.database_url)

# Prepare connection arguments based on database type
connect_args = {}

if url.drivername == "postgresql":
    # Convert to asyncpg driver (async-compatible PostgreSQL driver)
    url = url.set(drivername="postgresql+asyncpg")
    
    # Remove 'schema' from query params if present
    if "schema" in url.query:
        query = dict(url.query)
        del query["schema"]
        url = url.set(query=query)
    
    # Railway internal service: NO SSL needed for internal connections
    # Use simple configuration
    connect_args = {
        "timeout": 30,
        "command_timeout": 30,
    }

elif url.drivername == "sqlite":
    url = url.set(drivername="sqlite+aiosqlite")
    connect_args = {"timeout": 30}

# Create async engine
engine = create_async_engine(
    url,
    echo=False,
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_size=10,
    max_overflow=5,
    connect_args=connect_args,
)

# Create async session factory
async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


async def get_db():
    """
    Dependency for getting database session.
    Used in FastAPI routes: async def route(db: AsyncSession = Depends(get_db))
    """
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """
    Initialize database tables.
    Called during FastAPI startup (lifespan context manager).
    """
    try:
        print("[DB] Attempting to initialize database...")
        print(f"[DB] Database type: {url.drivername}")
        print(f"[DB] Database host: {url.host}")
        print(f"[DB] Database port: {url.port}")
        print(f"[DB] Database name: {url.database}")
        
        # Create all tables defined in Base.metadata
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        print("[DB] ✓ Database initialized successfully")
    except Exception as e:
        print(f"[DB] ✗ Error initializing database: {e}")
        print(f"[DB] Error type: {type(e).__name__}")
        import traceback
        traceback.print_exc()
        raise


async def dispose_db():
    """
    Properly dispose of the engine and close all connections.
    Called during FastAPI shutdown (lifespan context manager in main.py).
    """
    try:
        print("[DB] Disposing database connections...")
        await engine.dispose()
        print("[DB] ✓ Database disposed successfully")
    except Exception as e:
        print(f"[DB] ✗ Error disposing database: {e}")
        raise
