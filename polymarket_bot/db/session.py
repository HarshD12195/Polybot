from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from polymarket_bot.config import settings
from polymarket_bot.db.models import Base

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db():
    async with engine.begin() as conn:
        # In a real production app, one would use Alembic migrations.
        # For this bot, we'll create all tables if they don't exist.
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
