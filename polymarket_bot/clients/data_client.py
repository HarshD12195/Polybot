import httpx
import structlog
from typing import Any, Dict, List, Optional
from polymarket_bot.config import settings

logger = structlog.get_logger(__name__)


class DataClient:
    def __init__(self):
        self.base_url = settings.DATA_API_URL
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=10.0,
            headers={"Accept": "application/json"}
        )

    async def get_trade_history(
        self, 
        wallet: str, 
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Fetches recent trades for a specific wallet from the Data API.
        """
        try:
            # Note: actual endpoint might vary, poly-docs mention Data API for portfolio and trades.
            # Using typical /trades structure as a placeholder for the actual Polymarket Data API schema.
            response = await self.client.get(f"/trades", params={"address": wallet, "limit": limit})
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error("failed_to_get_trade_history", wallet=wallet, error=str(e))
            return []

    async def get_balance(self, wallet: str) -> float:
        """
        Fetches USDC balance for the wallet.
        """
        try:
            response = await self.client.get(f"/balance", params={"address": wallet})
            response.raise_for_status()
            data = response.json()
            return float(data.get("balance", 0.0))
        except Exception as e:
            logger.error("failed_to_get_balance", wallet=wallet, error=str(e))
            return 0.0

    async def get_portfolio_value(self, wallet: str) -> float:
        """
        Fetches total portfolio value (Cash + Market Value) for the wallet.
        """
        try:
            # Data API /portfolio endpoint
            response = await self.client.get(f"/portfolio", params={"address": wallet})
            if response.status_code == 404:
                # Fallback to balance if portfolio is not available
                return await self.get_balance(wallet)
            response.raise_for_status()
            data = response.json()
            # Polymarket Data API usually returns 'total_value' or 'net_worth'
            return float(data.get("total_value") or data.get("net_worth") or 0.0)
        except Exception as e:
            logger.error("failed_to_get_portfolio_value", wallet=wallet, error=str(e))
            # Safe fallback
            return await self.get_balance(wallet)

    async def close(self):
        await self.client.aclose()
