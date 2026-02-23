import asyncio
from datetime import datetime
import structlog
from typing import List, Optional
from polymarket_bot.config import settings
from polymarket_bot.clients.data_client import DataClient
from polymarket_bot.watcher.deduplication import Deduplicator

logger = structlog.get_logger(__name__)


class TargetWalletWatcher:
    def __init__(self, event_queue: asyncio.Queue):
        self.event_queue = event_queue
        self.data_client = DataClient()
        self.deduplicator = Deduplicator()
        self.targets = settings.TARGET_WALLETS
        self._running = False

    async def start(self):
        self._running = True
        logger.info("starting_wallet_watcher", targets=self.targets)
        
        # We start both polling and (optionally) websocket tasks
        tasks = [
            asyncio.create_task(self._poll_loop()),
        ]
        
        if settings.PAPER_LIVE_TEST:
            tasks.append(asyncio.create_task(self._ws_loop()))
        
        await asyncio.gather(*tasks)

    async def stop(self):
        self._running = False
        await self.data_client.close()

    async def _poll_loop(self):
        """
        Polls the Data API for new trades from target wallets.
        """
        while self._running:
            for wallet in self.targets:
                try:
                    trades = await self.data_client.get_trade_history(wallet, limit=10)
                    logger.debug("fetched_trades", wallet=wallet, count=len(trades))
                    for trade in trades:
                        trade_id = trade.get("transactionHash") or trade.get("id")
                        if not trade_id:
                            continue
                        logger.debug("processing_fetched_trade", wallet=wallet, trade_id=trade_id)
                        
                        if await self.deduplicator.is_new(trade_id):
                            # Map Data API schema to our TradeEvent internal model
                            raw_ts = trade.get("timestamp")
                            if isinstance(raw_ts, str):
                                ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
                            elif isinstance(raw_ts, (int, float)):
                                ts = datetime.fromtimestamp(raw_ts)
                            else:
                                ts = datetime.utcnow()

                            event = {
                                "target_wallet": wallet,
                                "trade_id": trade_id,
                                "market_id": trade.get("conditionId"),
                                "clob_token_id": trade.get("asset"),
                                "side": trade.get("side"),
                                "size": float(trade.get("size", 0)),
                                "price": float(trade.get("price", 0)),
                                "ts": ts
                            }
                            
                            # Record to DB first to ensure absolute dedup across restarts
                            await self.deduplicator.record_trade(event)
                            
                            # Put into processing queue
                            await self.event_queue.put(event)
                            logger.info("new_trade_detected", wallet=wallet, trade_id=trade_id)
                except Exception as e:
                    logger.error("polling_error", wallet=wallet, error=str(e))
            
            # Poll every 15 seconds to stay within rate limits and avoid noise
            await asyncio.sleep(15)

    async def _ws_loop(self):
        """
        Connects to Polymarket CLOB WebSocket and filters for target wallet trades.
        """
        import json
        import websockets
        
        uri = settings.CLOB_WS_URL
        while self._running:
            try:
                async with websockets.connect(uri) as websocket:
                    # Subscribe to all trades? 
                    # Usually you subscribe per market. For this test, we'll assume 
                    # we subscribe to a 'trades' topic that might include all or we
                    # subscribe to the markets we are interested in.
                    # For filtering target wallets, we listen and check maker/taker.
                    
                    subscribe_msg = {
                        "type": "subscribe",
                        "topic": "trades",
                        # "market_ids": ["..."] # Ideally list of active markets from Gamma
                    }
                    await websocket.send(json.dumps(subscribe_msg))
                    logger.info("ws_subscribed_to_trades")

                    async for message in websocket:
                        if not self._running:
                            break
                        
                        data = json.loads(message)
                        # Expecting a trade event: {topic: 'trades', data: [{...}]}
                        if data.get("topic") == "trades":
                            for trade in data.get("data", []):
                                maker = trade.get("maker_address", "").lower()
                                taker = trade.get("taker_address", "").lower()
                                
                                target = None
                                if maker in [w.lower() for w in self.targets]:
                                    target = maker
                                elif taker in [w.lower() for w in self.targets]:
                                    target = taker
                                
                                if target:
                                    trade_id = trade.get("id")
                                    if await self.deduplicator.is_new(trade_id):
                                        event = {
                                            "target_wallet": target,
                                            "trade_id": trade_id,
                                            "market_id": trade.get("market_id"),
                                            "clob_token_id": trade.get("clob_token_id"),
                                            "side": trade.get("side"),
                                            "size": trade.get("size"),
                                            "price": trade.get("price"),
                                            "ts": datetime.utcnow()
                                        }
                                        await self.deduplicator.record_trade(event)
                                        await self.event_queue.put(event)
                                        logger.info("ws_target_trade_detected", wallet=target, trade_id=trade_id)

            except Exception as e:
                logger.error("ws_error", error=str(e))
                await asyncio.sleep(5) # Backoff
