import asyncio
import csv
import os
import structlog
from datetime import datetime
from typing import List, Dict, Any
from polymarket_bot.config import settings
from polymarket_bot.engine.paper_portfolio import PaperPortfolio
from polymarket_bot.engine.copy_engine import CopyEngine
from polymarket_bot.engine.order_executor import OrderExecutor, PaperOrderExecutor
from polymarket_bot.watcher.wallet_watcher import TargetWalletWatcher
from polymarket_bot.db.session import init_db

logger = structlog.get_logger(__name__)

class PaperLiveRunner:
    def __init__(self, initial_capital: float = 100.0, log_dir: str = "./paper_logs"):
        self.portfolio = PaperPortfolio(initial_capital)
        self.log_dir = log_dir
        self.event_queue = asyncio.Queue()
        self.order_queue = asyncio.Queue()
        
        # Setup Logger Files
        os.makedirs(log_dir, exist_ok=True)
        self.trades_file = os.path.join(log_dir, "paper_trades.csv")
        self.timeseries_file = os.path.join(log_dir, "paper_portfolio_timeseries.csv")
        self._init_csv_headers()

    def _init_csv_headers(self):
        if not os.path.exists(self.trades_file):
            with open(self.trades_file, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "timestamp", "target_wallet", "market_id", "outcome", "side", "price", 
                    "size_shares", "target_notional_usd", "bot_notional_usd", 
                    "bot_size_pct_of_target", "realized_pnl_usd", "equity_before", 
                    "equity_after", "mode"
                ])
        
        if not os.path.exists(self.timeseries_file):
            with open(self.timeseries_file, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "timestamp", "cash_usd", "positions_value_usd", "equity_usd", 
                    "realized_pnl_usd", "unrealized_pnl_usd", "max_drawdown_usd", 
                    "num_open_positions", "num_trades", "mode"
                ])

    async def log_trade(self, order_req: Dict[str, Any]):
        summary = self.portfolio.get_summary()
        with open(self.trades_file, "a", newline="") as f:
            writer = csv.writer(f)
            # bot_notional = size * price
            bot_notional = float(order_req.get("filled_size", 0) or 0) * float(order_req.get("fill_price", 0) or 0)
            target_size = float(order_req.get("target_size", 0) or 0)
            target_price = float(order_req.get("price", 0) or 0)
            target_notional = target_size * target_price
            
            writer.writerow([
                datetime.now().isoformat(),
                order_req.get("target_wallet"),
                order_req.get("market_id"),
                order_req.get("outcome", "binary"),
                order_req.get("side"),
                order_req.get("fill_price"),
                order_req.get("filled_size"),
                target_notional,
                bot_notional,
                order_req.get("proportional_pct", 0),
                order_req.get("pnl_realized", 0.0), # This might need per-fill calc
                order_req.get("equity_before"),
                order_req.get("equity_after"),
                "test_paper_100"
            ])

    async def log_timeseries(self):
        summary = self.portfolio.get_summary()
        pos_val = summary["total_value"] - summary["cash"]
        with open(self.timeseries_file, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().isoformat(),
                summary["cash"],
                pos_val,
                summary["total_value"],
                summary["realized_pnl"],
                summary["unrealized_pnl"],
                summary["max_drawdown_usd"],
                summary["num_positions"],
                len(self.portfolio.trade_history),
                "test_paper_100"
            ])
    async def run(self):
        print(f"\n[*] Starting Polymarket Paper-Live Bot with ${self.portfolio.cash_usd:.2f} virtual balance")
        print(f"Targeting: {', '.join(settings.TARGET_WALLETS)}")
        print("Logs directory:", self.log_dir)
        print("="*60)

        await init_db()
        
        # Rebuild from CSV logs if they exist to maintain consistency
        self.portfolio.rebuild_from_trades(self.trades_file)
        
        # Load persistent state if exists (can override or complement)
        state_file = os.path.join(self.log_dir, "portfolio_state.json")
        self.portfolio.load_state(state_file)
        
        watcher = TargetWalletWatcher(self.event_queue)
        engine = CopyEngine(self.order_queue)
        # Pass the portfolio to the executor so it can apply fills
        paper_executor = PaperOrderExecutor(portfolio=self.portfolio)
        
        # We override the main executor's behavior in this runner
        class MockExecutor:
            async def execute_copy_order(self, req):
                await paper_executor.execute_paper_order(req)

        executor = MockExecutor()

        # Start tasks
        tasks = [
            asyncio.create_task(watcher.start()),
            asyncio.create_task(self._monitor_loop())
        ]

        try:
            from polymarket_bot.clients.data_client import DataClient
            data_client = DataClient()
            
            try:
                # Initial equity log
                await self.log_timeseries()
                
                while True:
                    # Process Events -> Engine
                    try:
                        try:
                            event = await asyncio.wait_for(self.event_queue.get(), timeout=0.1)
                        except asyncio.TimeoutError:
                            event = None

                        if event:
                            # Proportional Sizing: Fetch Target & Our Equity
                            target_wallet = event.get("target_wallet")
                            if target_wallet:
                                target_equity = await data_client.get_portfolio_value(target_wallet)
                                my_equity = self.portfolio.equity_usd
                                
                                event.update({
                                    "target_portfolio_value": target_equity,
                                    "my_portfolio_value": my_equity
                                })
                                
                                await engine.process_event(event)
                            else:
                                logger.warning("skipped_event_no_wallet", event=event)
                    except Exception as e:
                        logger.error("error_processing_event", error=str(e))

                    # Process Orders -> Executor
                    try:
                        try:
                            order_req = await asyncio.wait_for(self.order_queue.get(), timeout=0.1)
                        except asyncio.TimeoutError:
                            order_req = None

                        if order_req:
                            await executor.execute_copy_order(order_req)
                            
                            # Save state immediately on fill
                            self.portfolio.save_state(os.path.join(self.log_dir, "portfolio_state.json"))
                            
                            # Log to CSVs (Spec aligned)
                            await self.log_trade(order_req)
                            await self.log_timeseries()
                    except Exception as e:
                        logger.error("error_executing_paper_order", error=str(e))
            finally:
                await data_client.close()
                
        except asyncio.CancelledError:
            print("\nShutting down paper bot...")
        except KeyboardInterrupt:
            print("\nStopped by user.")
        finally:
            for t in tasks: t.cancel()
            await watcher.stop()

    async def _monitor_loop(self):
        """Periodically logs portfolio state and prints to console"""
        # Get engine for price lookups (we reuse the runner's engine or clob_client)
        from polymarket_bot.clients.clob_client import ClobTradingClient
        clob = ClobTradingClient()
        
        while True:
            # 1. Update Mark-to-Market prices
            positions = self.portfolio.positions
            if positions:
                mid_prices = {}
                for token_id in list(positions.keys()):
                    try:
                        # Use get_orderbook to get best bid/ask and use mid-market price
                        ob = await clob.get_orderbook(token_id)
                        if ob.get("asks") and ob.get("bids"):
                            best_ask = float(ob["asks"][0]["price"])
                            best_bid = float(ob["bids"][0]["price"])
                            mid_prices[token_id] = (best_ask + best_bid) / 2
                        elif ob.get("asks"): # Fallback to best ask/bid if one is missing
                            mid_prices[token_id] = float(ob["asks"][0]["price"])
                        elif ob.get("bids"):
                            mid_prices[token_id] = float(ob["bids"][0]["price"])
                    except Exception as e:
                        logger.debug("failed_to_mark_token", token_id=token_id, error=str(e))
                
                if mid_prices:
                    self.portfolio.mark_to_market(mid_prices)

            await self.log_timeseries()
            summary = self.portfolio.get_summary()
            
            # Export to JSON for Dashboard API
            import json
            state = {
                "summary": summary,
                "positions": [
                    {
                        "token_id": p.clob_token_id,
                        "market_id": p.market_id,
                        "quantity": p.quantity,
                        "avg_price": p.avg_price,
                        "mark_price": p.mark_price,
                        "unrealized_pnl": p.unrealized_pnl
                    } for p in positions.values()
                ],
                "last_updated": datetime.now().isoformat()
            }
            with open(os.path.join(self.log_dir, "positions.json"), "w") as f:
                json.dump(state, f)
            
            # Persistent state
            self.portfolio.save_state(os.path.join(self.log_dir, "portfolio_state.json"))

            print(f"[{datetime.now().strftime('%H:%M:%S')}] Val: ${summary['total_value']:.2f} | Cash: ${summary['cash']:.2f} | PnL: ${summary['realized_pnl'] + summary['unrealized_pnl']:.2f} ({summary['roi']*100:.2f}%) | Pos: {summary['num_positions']}")
            await asyncio.sleep(10) # Log every 10s

if __name__ == "__main__":
    runner = PaperLiveRunner(settings.INITIAL_CAPITAL_USD, settings.PAPER_LOG_DIR)
    asyncio.run(runner.run())
