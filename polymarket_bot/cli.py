import asyncio
import sys
import typer
import uvicorn
import structlog
from typing import Optional
from polymarket_bot.config import settings
from polymarket_bot.db.session import init_db
from polymarket_bot.watcher.wallet_watcher import TargetWalletWatcher
from polymarket_bot.engine.copy_engine import CopyEngine
from polymarket_bot.engine.order_executor import OrderExecutor

app = typer.Typer(help="Polymarket Copy-Trading Bot CLI")
logger = structlog.get_logger(__name__)


async def run_bot_core():
    """
    Main loop that orchestrates watcher, engine, and executor.
    """
    await init_db()
    
    event_queue = asyncio.Queue()
    order_queue = asyncio.Queue()
    
    watcher = TargetWalletWatcher(event_queue)
    engine = CopyEngine(order_queue)
    executor = OrderExecutor()
    
    logger.info("bot_core_started", targets=settings.TARGET_WALLETS, paper_mode=settings.PAPER_MODE)
    
    # Start the watcher in the background
    watcher_task = asyncio.create_task(watcher.start())
    
    # Main processing loop
    try:
        while True:
            # 1. Check for incoming trade events
            try:
                event = await asyncio.wait_for(event_queue.get(), timeout=1.0)
                await engine.process_event(event)
            except asyncio.TimeoutError:
                pass
                
            # 2. Check for outgoing order requests
            try:
                order_req = await asyncio.wait_for(order_queue.get(), timeout=1.0)
                await executor.execute_copy_order(order_req)
            except asyncio.TimeoutError:
                pass
                
    except asyncio.CancelledError:
        logger.info("shutting_down_bot")
        await watcher.stop()
        watcher_task.cancel()
    except Exception as e:
        logger.error("fatal_loop_error", error=str(e))
        raise


@app.command()
def live():
    """Starts the bot in live (or paper) mode as configured in .env"""
    logger.info("starting_live_mode")
    
    async def main():
        # Run API server and Bot core concurrently
        config = uvicorn.Config(
            "polymarket_bot.api.app:app", 
            host=settings.API_HOST, 
            port=settings.API_PORT, 
            log_level="info"
        )
        server = uvicorn.Server(config)
        
        await asyncio.gather(
            server.serve(),
            run_bot_core()
        )

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


@app.command()
def paper():
    """Override settings to run in paper mode specifically"""
    settings.PAPER_MODE = True
    logger.info("starting_paper_mode_override")
    live()


@app.command()
def run_paper_live_test(duration: int = 60, wallets: str = ""):
    """Runs a live paper-trading test for a set duration"""
    from tests.test_live_paper_copy import run_paper_live_test as core_test
    
    wallet_list = [w.strip() for w in wallets.split(",") if w.strip()]
    if not wallet_list:
        wallet_list = settings.TARGET_WALLETS
        
    logger.info("launching_paper_live_test_cli", duration=duration, wallets=wallet_list)
    
    try:
        asyncio.run(core_test(duration, wallet_list))
    except KeyboardInterrupt:
        pass


@app.command()
def paper_live():
    """Starts the continuous paper-live trading runner with monitoring dashboard"""
    from polymarket_bot.engine.paper_runner import PaperLiveRunner
    
    settings.PAPER_LIVE_TEST = True
    settings.PAPER_MODE = True
    
    async def main():
        runner = PaperLiveRunner(settings.INITIAL_CAPITAL_USD, settings.PAPER_LOG_DIR)
        
        # Run API server and Bot core concurrently
        config = uvicorn.Config(
            "polymarket_bot.api.app:app", 
            host=settings.API_HOST, 
            port=settings.API_PORT, 
            log_level="info"
        )
        server = uvicorn.Server(config)
        
        await asyncio.gather(
            server.serve(),
            runner.run()
        )

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


@app.command()
def backfill(wallet: str, days: int = 7):
    """Backfills history for a wallet and analyzes performance (Stub)"""
    typer.echo(f"Analyzing history for {wallet} over last {days} days...")
    # Implementation would involve DataClient.get_trade_history and simulation logic
    typer.echo("Done. No trades found (Stub).")


if __name__ == "__main__":
    app()
