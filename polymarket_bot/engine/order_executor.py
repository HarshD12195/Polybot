import asyncio
from datetime import datetime
import structlog
from typing import Any, Dict
from polymarket_bot.config import settings
from polymarket_bot.clients.clob_client import ClobTradingClient
from polymarket_bot.db.models import MyTrade
from polymarket_bot.db.session import AsyncSessionLocal

logger = structlog.get_logger(__name__)


class OrderExecutor:
    def __init__(self):
        self.clob_client = ClobTradingClient()
        self.paper_executor = PaperOrderExecutor()

    async def execute_copy_order(self, req: Dict[str, Any]):
        """
        Takes an order request and executes it against the CLOB.
        """
        if settings.PAPER_MODE or settings.PAPER_LIVE_TEST:
            await self.paper_executor.execute_paper_order(req)
            return

        # Hard Guard
        if settings.PAPER_MODE:
            logger.error("safety_guard_triggered", message="Attempted live order in paper mode!")
            raise RuntimeError("CRITICAL SAFETY: Attempted live order in paper mode!")

        token_id = req["clob_token_id"]
        side = req["side"]
        price = req["price"]
        size = req["size"]
        source_trade_id = req["source_trade_id"]

        logger.info("executing_order", side=side, price=price, size=size, token_id=token_id)
        # ... rest of the existing code ...
        try:
            # 1. Place the order
            resp = await self.clob_client.place_order(
                token_id=token_id,
                side=side,
                price=price,
                size=size
            )

            order_id = resp.get("orderID", "unknown")
            status = "PLACED" if resp.get("success") else "FAILED"

            # 2. Persist to DB
            async with AsyncSessionLocal() as session:
                my_trade = MyTrade(
                    order_id=order_id,
                    target_trade_id=source_trade_id,
                    side=side,
                    size=float(size),
                    price=float(price),
                    status=status,
                    ts=datetime.utcnow()
                )
                session.add(my_trade)
                await session.commit()

            if status == "FAILED":
                logger.error("order_execution_failed", error=resp.get("error"))
            else:
                logger.info("order_execution_success", order_id=order_id)

        except Exception as e:
            logger.error("executor_critical_error", error=str(e))


class PaperOrderExecutor:
    def __init__(self, portfolio=None):
        self.clob_client = ClobTradingClient()
        self.portfolio = portfolio

    async def execute_paper_order(self, req: Dict[str, Any]):
        token_id = req["clob_token_id"]
        side = req["side"].upper()
        limit_price = req["price"]
        requested_size = req["size"]
        
        logger.info("paper_execution_attempt", side=side, price=limit_price, size=requested_size)

        # 1. Simulate execution delay
        if settings.EXECUTION_DELAY_SECONDS > 0:
            await asyncio.sleep(settings.EXECUTION_DELAY_SECONDS)

        # 2. Fetch current orderbook
        orderbook = await self.clob_client.get_orderbook(token_id)
        
        fill_price = limit_price
        filled_size = requested_size
        spread_bps = 0.0
        slippage_applied = 0.0

        if not orderbook.get("asks") or not orderbook.get("bids"):
            logger.info("paper_order_fallback_fill", reason="Missing orderbook, using limit_price")
            # Apply fixed slippage in paper mode when book is missing
            if side == "BUY":
                fill_price = limit_price * (1 + (settings.SLIPPAGE_BPS / 10000))
            else:
                fill_price = limit_price * (1 - (settings.SLIPPAGE_BPS / 10000))
            slippage_applied = settings.SLIPPAGE_BPS
        else:
            best_ask = float(orderbook["asks"][0]["price"])
            best_bid = float(orderbook["bids"][0]["price"])
            
            # More realistic fill: 
            # BUY: Fill at best_ask or limit, whichever is worse for us? 
            # Actually, BUY at best_ask if best_ask <= limit. 
            # If best_ask > limit, we might not fill, but for copy-trading we usually ignore limit if we want to follow.
            # We'll use the limit_price from the event but apply slippage.
            
            if side == "BUY":
                fill_price = max(limit_price, best_ask) * (1 + (settings.SLIPPAGE_BPS / 10000))
            else:
                fill_price = min(limit_price, best_bid) * (1 - (settings.SLIPPAGE_BPS / 10000))
            
            spread_bps = (best_ask - best_bid) / best_bid * 10000
            slippage_applied = settings.SLIPPAGE_BPS

        # 3. Apply to portfolio
        fill_event = {
            **req,
            "filled_size": filled_size,
            "fill_price": fill_price,
            "spread_bps": spread_bps,
            "slippage_bps": slippage_applied,
            "ts": datetime.now()
        }
        
        equity_before = 0.0
        if self.portfolio:
            equity_before = self.portfolio.equity_usd
            self.portfolio.apply_fill(fill_event)
            # 4. Recalculate portfolio via mark_to_market
            if orderbook.get("asks") and orderbook.get("bids"):
                await self.sync_portfolio_mark_to_market(token_id, float(orderbook["asks"][0]["price"]), float(orderbook["bids"][0]["price"]))

        # 5. Enrich request for logging
        req.update({
            "filled_size": filled_size,
            "fill_price": fill_price,
            "spread_bps": spread_bps,
            "executed_at": fill_event["ts"],
            "equity_before": equity_before,
            "equity_after": self.portfolio.equity_usd if self.portfolio else 0.0
        })

        # Persist to DB
        async with AsyncSessionLocal() as session:
            try:
                from polymarket_bot.db.models import PaperTrade
                paper_trade = PaperTrade(
                    target_trade_id=req.get("source_trade_id", "unknown"),
                    clob_token_id=token_id,
                    side=side,
                    requested_size=float(requested_size),
                    filled_size=float(filled_size),
                    fill_price=float(fill_price),
                    spread_bps=float(spread_bps),
                    ts=datetime.utcnow(),
                    decision_reason=req.get("decision_reason")
                )
                session.add(paper_trade)
                await session.commit()
                
                # Terminal clarity
                print(f"[PAPER FILL] {side} {filled_size:.2f} @ {fill_price:.4f} | Equity: ${self.portfolio.equity_usd:.2f}")
                
                logger.info("paper_order_filled", filled_size=filled_size, fill_price=fill_price)
            except Exception as e:
                logger.error("failed_to_persist_paper_trade", error=str(e))
                await session.rollback()

    async def sync_portfolio_mark_to_market(self, token_id: str, best_ask: float, best_bid: float):
        if not self.portfolio: return
        mid_price = (best_ask + best_bid) / 2
        self.portfolio.mark_to_market({token_id: mid_price})

    def calculate_fill(self, limit_price: float, size: float, side: str, orderbook: Dict[str, Any]) -> tuple[float, float, float]:
        # Legacy: Keeping for compatibility but execute_paper_order now does its own simple logic
        return size, limit_price, 0.0
