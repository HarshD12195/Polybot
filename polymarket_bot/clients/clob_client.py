import asyncio
import structlog
from typing import Any, Dict, List, Optional
from py_clob_client.client import ClobClient as PyClobClient
from py_clob_client.constants import POLYGON
from py_clob_client.clob_types import OrderArgs
from polymarket_bot.config import settings

logger = structlog.get_logger(__name__)


class ClobTradingClient:
    def __init__(self):
        self.host = settings.CLOB_API_URL
        self.key = settings.PRIVATE_KEY
        self.funder = settings.POLY_FUNDER_ADDRESS
        self.chain_id = 137  # Polygon Mainnet
        
        # We'll initialize the actual client lazily or in an async init method
        self._client: Optional[PyClobClient] = None
        self._semaphore = asyncio.Semaphore(10)  # Rate limiting

    async def _ensure_client(self):
        if self._client:
            return

        # Initialize py-clob-client
        # Note: In a real scenario, we'd handle credential derivation/storage
        try:
            # We initialize with private key and set GNOSIS_SAFE (2) signature type
            # Host, chain_id, key, funder, signature_type
            self._client = PyClobClient(
                host=self.host,
                key=self.key,
                chain_id=self.chain_id,
                funder=self.funder,
                signature_type=2 # GNOSIS_SAFE
            )
            
            # Derive API credentials if not already present
            # For simplicity, we assume we derive them every session if not cached
            # In a production bot, you'd store API_KEY, SECRET, PASSPHRASE in env
            # creds = self._client.create_or_derive_api_key()
            # self._client.set_api_credentials(creds)
            
            logger.info("clob_client_initialized", funder=self.funder)
        except Exception as e:
            logger.error("failed_to_init_clob_client", error=str(e))
            raise

    async def get_orderbook(self, token_id: str) -> Dict[str, Any]:
        await self._ensure_client()
        async with self._semaphore:
            try:
                # py-clob-client method is get_order_book
                res = await asyncio.to_thread(self._client.get_order_book, token_id)
                # If it's an OrderBookSummary object, convert to dict
                if hasattr(res, "bids") and hasattr(res, "asks"):
                    return {
                        "bids": [{"price": b.price, "size": b.size} for b in res.bids],
                        "asks": [{"price": a.price, "size": a.size} for a in res.asks]
                    }
                return res if isinstance(res, dict) else {"bids": [], "asks": []}
            except Exception as e:
                logger.error("failed_to_get_orderbook", token_id=token_id, error=str(e))
                return {"bids": [], "asks": []}

    async def place_order(
        self, 
        token_id: str, 
        side: str, 
        price: float, 
        size: float, 
        time_in_force: str = "GTC"
    ) -> Dict[str, Any]:
        """
        Places a limit order on the CLOB.
        """
        await self._ensure_client()
        
        order_args = OrderArgs(
            price=price,
            size=size,
            side=side.upper(),
            token_id=token_id,
            # time_in_force=time_in_force, # py-clob-client might have different args
        )
        
        async with self._semaphore:
            try:
                if settings.PAPER_MODE:
                    logger.info("paper_mode_simulating_order", side=side, price=price, size=size)
                    return {"orderID": "paper-order-id", "success": True}
                
                resp = await asyncio.to_thread(self._client.create_order, order_args)
                logger.info("order_placed", order_id=resp.get("orderID"), side=side, price=price, size=size)
                return resp
            except Exception as e:
                logger.error("failed_to_place_order", error=str(e))
                return {"success": False, "error": str(e)}

    async def cancel_order(self, order_id: str) -> bool:
        await self._ensure_client()
        async with self._semaphore:
            try:
                resp = await asyncio.to_thread(self._client.cancel_order, order_id)
                return resp.get("success", False)
            except Exception as e:
                logger.error("failed_to_cancel_order", order_id=order_id, error=str(e))
                return False

    async def get_my_trades(self, limit: int = 50) -> List[Dict[str, Any]]:
        await self._ensure_client()
        async with self._semaphore:
            try:
                return await asyncio.to_thread(self._client.get_trades, limit=limit)
            except Exception as e:
                logger.error("failed_to_get_my_trades", error=str(e))
                return []
