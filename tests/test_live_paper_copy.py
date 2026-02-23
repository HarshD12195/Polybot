import asyncio
import os
import sys
import time
from datetime import datetime, timedelta
import structlog
from sqlalchemy import select
from polymarket_bot.config import settings
from polymarket_bot.db.session import init_db, AsyncSessionLocal
from polymarket_bot.db.models import TargetTrade, PaperTrade
from polymarket_bot.watcher.wallet_watcher import TargetWalletWatcher
from polymarket_bot.engine.copy_engine import CopyEngine
from polymarket_bot.engine.order_executor import OrderExecutor

logger = structlog.get_logger(__name__)

async def run_paper_live_test(duration_minutes: int, wallets: list[str]):
    """
    Runs a live paper-trading test for a fixed duration.
    """
    # 1. Setup Live Paper Config
    settings.PAPER_LIVE_TEST = True
    settings.TARGET_WALLETS = wallets
    settings.PAPER_MODE = True # Enforce paper mode
    
    await init_db()
    
    event_queue = asyncio.Queue()
    order_queue = asyncio.Queue()
    
    watcher = TargetWalletWatcher(event_queue)
    engine = CopyEngine(order_queue)
    executor = OrderExecutor()
    
    logger.info("starting_live_paper_test", duration=duration_minutes, wallets=wallets)
    
    # 2. Start core tasks
    watcher_task = asyncio.create_task(watcher.start())
    
    start_time = datetime.utcnow()
    end_time = start_time + timedelta(minutes=duration_minutes)
    
    trades_detected = 0
    orders_simulated = 0
    
    try:
        while datetime.utcnow() < end_time:
            # Process events
            try:
                event = await asyncio.wait_for(event_queue.get(), timeout=1.0)
                trades_detected += 1
                await engine.process_event(event)
            except asyncio.TimeoutError:
                pass
                
            # Process orders
            try:
                order_req = await asyncio.wait_for(order_queue.get(), timeout=1.0)
                orders_simulated += 1
                await executor.execute_copy_order(order_req)
            except asyncio.TimeoutError:
                pass
                
            # Log progress every minute
            if int((datetime.utcnow() - start_time).total_seconds()) % 60 == 0:
                logger.info("test_progress", elapsed=str(datetime.utcnow() - start_time), detected=trades_detected, simulated=orders_simulated)

    except Exception as e:
        logger.error("test_error", error=str(e))
    finally:
        await watcher.stop()
        watcher_task.cancel()
        
    # 3. Summary & Assertions
    await print_summary(wallets)

async def print_summary(targets: list[str]):
    async with AsyncSessionLocal() as session:
        # Detected trades
        stmt_t = select(TargetTrade)
        res_t = await session.execute(stmt_t)
        all_detected = res_t.scalars().all()
        
        # Simulated trades
        stmt_p = select(PaperTrade)
        res_p = await session.execute(stmt_p)
        all_paper = res_p.scalars().all()
        
        print("\n" + "="*50)
        print("LIVE PAPER TEST SUMMARY")
        print("="*50)
        print(f"Target Wallets: {', '.join(targets)}")
        print(f"Total Target Trades Detected: {len(all_detected)}")
        print(f"Total Paper Trades Filled: {len(all_paper)}")
        
        if all_paper:
            total_filled_usd = sum(p.filled_size * p.fill_price for p in all_paper)
            print(f"Total Volume Simulated: ${total_filled_usd:.2f}")
            
            # Simple PnL check would require current prices, but we show entry details
            for p in all_paper:
                print(f"- {p.side} {p.clob_token_id}: {p.filled_size} @ {p.fill_price} (Spread: {p.spread_bps:.1f} BPS)")
        
        print("="*50)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=int, default=60)
    parser.add_argument("--wallets", type=str, required=True)
    args = parser.parse_args()
    
    wallets = [w.strip() for w in args.wallets.split(",") if w.strip()]
    asyncio.run(run_paper_live_test(args.duration, wallets))
