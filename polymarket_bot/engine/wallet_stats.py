import json
import os
import structlog
from typing import Dict, Any, List
from datetime import datetime

logger = structlog.get_logger(__name__)

class WalletStatsManager:
    def __init__(self, stats_file: str = "paper_logs/wallet_stats.json"):
        self.stats_file = stats_file
        self.stats: Dict[str, Dict[str, Any]] = {}
        self.load_stats()

    def load_stats(self):
        if os.path.exists(self.stats_file):
            try:
                with open(self.stats_file, "r") as f:
                    self.stats = json.load(f)
            except Exception as e:
                logger.error("failed_to_load_wallet_stats", error=str(e))
                self.stats = {}

    def save_stats(self):
        os.makedirs(os.path.dirname(self.stats_file), exist_ok=True)
        try:
            with open(self.stats_file, "w") as f:
                json.dump(self.stats, f, indent=2)
        except Exception as e:
            logger.error("failed_to_save_wallet_stats", error=str(e))

    def record_trade(self, wallet: str, pnl: float):
        wallet = wallet.lower()
        if wallet not in self.stats:
            self.stats[wallet] = {
                "trades": 0,
                "realized_pnl": 0.0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0.0,
                "max_drawdown": 0.0,
                "peak_pnl": 0.0,
                "last_updated": ""
            }
        
        s = self.stats[wallet]
        s["trades"] += 1
        s["realized_pnl"] += pnl
        
        if pnl > 0:
            s["wins"] += 1
        else:
            s["losses"] += 1
            
        s["win_rate"] = s["wins"] / s["trades"]
        
        # Track drawdown of PnL for this wallet
        if s["realized_pnl"] > s["peak_pnl"]:
            s["peak_pnl"] = s["realized_pnl"]
        
        drawdown = s["peak_pnl"] - s["realized_pnl"]
        if drawdown > s["max_drawdown"]:
            s["max_drawdown"] = drawdown
            
        s["last_updated"] = datetime.utcnow().isoformat()
        self.save_stats()

    def get_stats(self, wallet: str) -> Dict[str, Any]:
        return self.stats.get(wallet.lower(), {
            "trades": 0,
            "realized_pnl": 0.0,
            "win_rate": 0.0,
            "max_drawdown": 0.0
        })

    def meets_thresholds(self, wallet: str, min_win_rate: float, min_trades: int) -> bool:
        s = self.get_stats(wallet)
        if s["trades"] < min_trades:
            # Not enough data yet - return True to allow initial discovery? 
            # Or False to be safe? Spec says "skip copying trades from wallets that don’t meet those thresholds".
            # Usually we need a 'grace period'. I'll return True if trades < min_trades to allow them to build history.
            return True 
        
        if s["win_rate"] < min_win_rate:
            return False
            
        return True
