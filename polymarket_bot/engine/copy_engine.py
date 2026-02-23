import asyncio
import structlog
from typing import Any, Dict, Optional
from polymarket_bot.config import settings
from polymarket_bot.clients.clob_client import ClobTradingClient
from polymarket_bot.clients.gamma_client import GammaClient

logger = structlog.get_logger(__name__)


from dataclasses import dataclass

@dataclass
class Decision:
    result: bool
    reason: str
    copy_size: float = 0.0
    limit_price: float = 0.0
    market_title: str = "Unknown"
    target_size: float = 0.0
    proportional_pct: float = 0.0

class CopyEngine:
    def __init__(self, order_queue: asyncio.Queue):
        self.order_queue = order_queue
        self.clob_client = ClobTradingClient()
        self.gamma_client = GammaClient()

    async def process_event(self, event: Dict[str, Any]):
        """
        Processes a TradeEvent and decides whether to place a copy order.
        """
        target_wallet = event["target_wallet"]
        trade_id = event["trade_id"]
        token_id = event["clob_token_id"]
        
        logger.info("processing_copy_decision", wallet=target_wallet, trade_id=trade_id)

        # 1. Fetch market metadata
        market = None
        if event.get("market_id"):
            market = await self.gamma_client.get_market(event["market_id"])
        
        if not market and event.get("clob_token_id"):
            market = await self.gamma_client.get_market_by_token_id(event["clob_token_id"])

        if not market:
            logger.warning("market_not_found", market_id=event.get("market_id"), token_id=event.get("clob_token_id"))
            return

        orderbook = await self.clob_client.get_orderbook(token_id)
        
        # 2. Pure decision logic
        decision = self.decide_copy(event, market, orderbook, settings)
        
        logger.info("decision_made", 
                    result=decision.result, 
                    reason=decision.reason, 
                    trade_id=trade_id, 
                    market_id=market.get("id"), 
                    clob_token_id=token_id)

        if not decision.result:
            return

        # 3. Emit Order Request
        order_request = {
            "clob_token_id": token_id,
            "market_id": market.get("id"),
            "market_title": decision.market_title,
            "side": event["side"],
            "price": decision.limit_price,
            "size": decision.copy_size,
            "source_trade_id": trade_id,
            "target_wallet": target_wallet,
            "target_size": decision.target_size,
            "proportional_pct": decision.proportional_pct,
            "decision_reason": decision.reason
        }
        
        await self.order_queue.put(order_request)
        logger.info("copy_order_queued", **order_request)

    @staticmethod
    def decide_copy(event: Dict[str, Any], market: Dict[str, Any], orderbook: Dict[str, Any], config) -> Decision:
        wallet = event["target_wallet"]
        wallet_config = config.get_wallet_config(wallet)
        
        # Tag filter
        if config.ALLOWED_TAGS:
            market_tags = set(market.get("tags", []))
            if not market_tags.intersection(config.ALLOWED_TAGS):
                return Decision(False, f"Filtered by tags: {list(market_tags)}")

        # Volume filter
        volume_24h = float(market.get("volume24hr", 0))
        if volume_24h < config.MIN_24H_VOLUME_USDC:
            return Decision(False, f"Low volume: {volume_24h}")

        # Orderbook Check (Spread)
        asks = orderbook.get("asks", [])
        bids = orderbook.get("bids", [])
        
        if not asks or not bids:
            # Paper mode fallback: if we can't get an orderbook, we assume 
            # we can fill at the target's price for simulation purposes.
            if config.PAPER_MODE:
                logger.info("paper_mode_empty_orderbook_fallback", trade_id=event.get("trade_id"))
            else:
                return Decision(False, "Empty orderbook (no liquidity on CLOB REST)")
        else:
            best_ask = float(asks[0]["price"])
            best_bid = float(bids[0]["price"])
            spread = (best_ask - best_bid) / best_bid * 10000 # BPS
            
            if spread > config.MAX_SPREAD_BPS:
                return Decision(False, f"Wide spread: {spread} BPS")

        # Sizing Logic: Proportional Scaling
        target_equity = event.get("target_portfolio_value", 0.0)
        my_equity = event.get("my_portfolio_value", 0.0)
        target_size = event.get("size", 0.0)
        
        proportional_pct = 0.0
        if target_equity > 0:
            proportional_pct = my_equity / target_equity
            raw_size = target_size * proportional_pct
        else:
            multiplier = wallet_config.get("size_multiplier", 0.001)
            raw_size = target_size * multiplier
            proportional_pct = multiplier

        # 3. New Spec: validate_trade_constraints & Capping
        limit_price = event["price"]
        notional_usd = raw_size * limit_price
        
        # Check 1: Max Risk per trade (5%) - CAP instead of SKIP
        max_risk_usd = my_equity * 0.05 # 5% hard limit for Test Paper 100
        if notional_usd > max_risk_usd:
            logger.info("capping_trade_to_risk_limit", 
                        original_notional=notional_usd, 
                        capped_notional=max_risk_usd)
            notional_usd = max_risk_usd
            raw_size = notional_usd / limit_price if limit_price > 0 else 0

        # Check 2: Max per market - CAP instead of SKIP
        max_market = wallet_config.get("max_per_market_usdc", config.MAX_PER_MARKET_USDC)
        if notional_usd > max_market:
            logger.info("capping_trade_to_market_limit", 
                        original_notional=notional_usd, 
                        capped_notional=max_market)
            notional_usd = max_market
            raw_size = notional_usd / limit_price if limit_price > 0 else 0

        copy_size = raw_size
        if copy_size <= 0:
            return Decision(False, f"Size too small: {copy_size}")

        market_title = market.get("question", "Unknown Market")

        return Decision(
            True, "Criteria met", 
            copy_size=copy_size, 
            limit_price=limit_price,
            market_title=market_title,
            target_size=target_size,
            proportional_pct=proportional_pct
        )
