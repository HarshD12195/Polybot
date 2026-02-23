import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from polymarket_bot.db.models import TargetTrade
from polymarket_bot.db.session import AsyncSessionLocal

logger = structlog.get_logger(__name__)


class Deduplicator:
    def __init__(self):
        pass

    async def is_new(self, trade_id: str) -> bool:
        """
        Checks if a trade ID is already in the database.
        Returns True if it's a new trade, False otherwise.
        """
        async with AsyncSessionLocal() as session:
            try:
                stmt = select(TargetTrade).where(TargetTrade.trade_id == trade_id)
                res = await session.execute(stmt)
                if res.scalar():
                    logger.debug("trade_already_known", trade_id=trade_id)
                    return False
                logger.debug("trade_is_new", trade_id=trade_id)
                return True
            except Exception as e:
                logger.error("deduplication_lookup_failed", error=str(e), trade_id=trade_id)
                return False

    async def record_trade(self, trade_event: dict):
        """
        Records the target trade to the database to ensure it's not copied again.
        """
        async with AsyncSessionLocal() as session:
            try:
                new_trade = TargetTrade(
                    target_wallet=trade_event["target_wallet"],
                    trade_id=trade_event["trade_id"],
                    market_id=trade_event["market_id"],
                    side=trade_event["side"],
                    size=float(trade_event["size"]),
                    price=float(trade_event["price"]),
                    ts=trade_event["ts"]
                )
                session.add(new_trade)
                await session.commit()
            except Exception as e:
                logger.error("failed_to_record_target_trade", error=str(e), trade_id=trade_event.get("trade_id"))
                await session.rollback()
