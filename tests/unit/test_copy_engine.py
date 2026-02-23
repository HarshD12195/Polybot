import os
import asyncio
import pytest

# Set dummy env vars before importing anything from polymarket_bot
os.environ["PRIVATE_KEY"] = "0x0000000000000000000000000000000000000000000000000000000000000001"
os.environ["POLY_FUNDER_ADDRESS"] = "0x0000000000000000000000000000000000000000"

from unittest.mock import AsyncMock, MagicMock
from polymarket_bot.engine.copy_engine import CopyEngine
from polymarket_bot.config import settings

@pytest.fixture
def mock_queues():
    return asyncio.Queue()

@pytest.mark.asyncio
async def test_copy_engine_filters():
    order_queue = AsyncMock()
    engine = CopyEngine(order_queue)
    
    # Mock Gamma client
    engine.gamma_client.get_market = AsyncMock(return_value={
        "id": "m1",
        "tags": ["Politics"],
        "volume24hr": 50000
    })
    
    # Mock CLOB client
    engine.clob_client.get_orderbook = AsyncMock(return_value={
        "asks": [{"price": "0.51", "size": "1000"}],
        "bids": [{"price": "0.50", "size": "1000"}]
    })
    
    # Test Event
    event = {
        "target_wallet": "0x123",
        "market_id": "m1",
        "trade_id": "t1",
        "clob_token_id": "tok1",
        "side": "BUY",
        "size": 100,
        "price": 0.505
    }
    
    # Set settings
    settings.ALLOWED_TAGS = ["Politics"]
    settings.MIN_24H_VOLUME_USDC = 10000
    settings.MAX_SPREAD_BPS = 500 # 2% spread allowed
    
    await engine.process_event(event)
    
    # Should have queued an order
    order_queue.put.assert_called_once()
    order_call = order_queue.put.call_args[0][0]
    assert order_call["token_id"] == "tok1"
    assert order_call["size"] == 25.0 # default 0.25 multiplier
    assert order_call["decision_reason"] == "Criteria met"

@pytest.mark.asyncio
async def test_copy_engine_rejection_volume():
    order_queue = AsyncMock()
    engine = CopyEngine(order_queue)
    
    # Mock Gamma client with low volume
    engine.gamma_client.get_market = AsyncMock(return_value={
        "id": "m1",
        "tags": ["Politics"],
        "volume24hr": 100
    })
    
    # Mock orderbook
    engine.clob_client.get_orderbook = AsyncMock(return_value={
        "asks": [{"price": "0.51", "size": "1000"}],
        "bids": [{"price": "0.50", "size": "1000"}]
    })
    
    settings.MIN_24H_VOLUME_USDC = 1000
    
    event = {
        "target_wallet": "0x123",
        "market_id": "m1",
        "trade_id": "t1",
        "clob_token_id": "tok1",
        "side": "BUY",
        "size": 100,
        "price": 0.505
    }
    
    await engine.process_event(event)
    
    # Should NOT have queued an order
    order_queue.put.assert_not_called()
import asyncio
