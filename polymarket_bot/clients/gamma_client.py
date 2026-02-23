import httpx
import structlog
from typing import Any, Dict, List, Optional
from polymarket_bot.config import settings

logger = structlog.get_logger(__name__)


class GammaClient:
    def __init__(self):
        self.base_url = settings.GAMMA_API_URL
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=10.0,
            headers={"Accept": "application/json"}
        )

    async def list_markets(
        self, 
        tags: Optional[List[str]] = None, 
        active_only: bool = True, 
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        params = {
            "active": str(active_only).lower(),
            "limit": limit,
        }
        if tags:
            params["tag"] = tags

        try:
            response = await self.client.get("/markets", params=params)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error("failed_to_list_markets", error=str(e))
            return []

    async def get_market(self, market_id: str) -> Optional[Dict[str, Any]]:
        try:
            # First try as a direct ID
            response = await self.client.get(f"/markets/{market_id}")
            if response.status_code == 200:
                return response.json()
                
            # If 404/422, it might be a conditionId
            return await self.get_market_by_condition_id(market_id)
        except Exception as e:
            logger.error("failed_to_get_market", market_id=market_id, error=str(e))
            return None

    async def get_market_by_condition_id(self, condition_id: str) -> Optional[Dict[str, Any]]:
        try:
            response = await self.client.get("/markets", params={"condition_id": condition_id})
            response.raise_for_status()
            markets = response.json()
            if markets and len(markets) > 0:
                return markets[0]
            return None
        except Exception as e:
            logger.debug("failed_to_get_market_by_condition", condition_id=condition_id, error=str(e))
            return None

    async def get_market_by_token_id(self, token_id: str) -> Optional[Dict[str, Any]]:
        try:
            # Gamma /markets endpoint filtered by clob_token_id
            response = await self.client.get("/markets", params={"clob_token_id": token_id})
            response.raise_for_status()
            markets = response.json()
            if markets and len(markets) > 0:
                return markets[0]
            return None
        except Exception as e:
            logger.error("failed_to_get_market_by_token", token_id=token_id, error=str(e))
            return None

    async def close(self):
        await self.client.aclose()
