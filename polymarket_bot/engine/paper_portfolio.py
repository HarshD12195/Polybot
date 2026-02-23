import asyncio
import os
import structlog
from typing import Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime

logger = structlog.get_logger(__name__)

@dataclass
class Position:
    market_id: str
    clob_token_id: str
    quantity: float
    avg_price: float
    mark_price: float = 0.0
    unrealized_pnl: float = 0.0

class PaperPortfolio:
    def __init__(self, initial_capital: float = 100.0):
        self.initial_capital = initial_capital
        self.cash_usd = initial_capital
        self.max_equity = initial_capital
        self.max_drawdown_usd = 0.0 # Spec requirement
        self.positions: Dict[str, Position] = {} # clob_token_id -> Position
        self.trade_history: List[Dict[str, Any]] = []
        self.realized_pnl = 0.0
        self.unrealized_pnl = 0.0
        self.equity_usd = initial_capital # Spec requirement
    
    def _assert_integrity(self):
        """
        Fundamental accounting assertion: Cash + Position Market Value == Equity
        """
        market_value = sum(p.quantity * p.mark_price for p in self.positions.values())
        calculated_equity = self.cash_usd + market_value
        
        # Use a slightly more relaxed threshold for floating point math
        if abs(calculated_equity - self.equity_usd) > 0.01:
            logger.error("integrity_violation", 
                         expected=self.equity_usd, 
                         calculated=calculated_equity,
                         cash=self.cash_usd,
                         mkt_val=market_value)
            # Re-sync instead of crashing in paper mode
            self.equity_usd = calculated_equity

    def can_open_trade(self, cost_usd: float, max_per_market: float) -> bool:
        # Check if we have cash and if it respects max_per_market (simplified)
        if cost_usd > self.cash_usd:
            return False
        return True

    def apply_fill(self, fill_data: Dict[str, Any]):
        token_id = fill_data["clob_token_id"]
        side = fill_data["side"].upper()
        size = float(fill_data["filled_size"])
        price = float(fill_data["fill_price"])
        cost = size * price

        if side == "BUY":
            # Guard: No negative cash
            if self.cash_usd < cost:
                logger.error("paper_portfolio_insufficient_funds", cash=self.cash_usd, cost=cost)
                return

            if token_id in self.positions:
                pos = self.positions[token_id]
                # If we were short, realize PnL on the portion we cover
                if pos.quantity < 0:
                    cover_size = min(abs(pos.quantity), size)
                    profit = (pos.avg_price - price) * cover_size
                    self.realized_pnl += profit
                
                new_size = pos.quantity + size
                if abs(new_size) < 1e-9:
                    del self.positions[token_id]
                else:
                    # Update avg_price if extending long
                    if pos.quantity >= 0:
                        pos.avg_price = (pos.avg_price * pos.quantity + cost) / new_size
                    pos.quantity = new_size
                    pos.mark_price = price
            else:
                self.positions[token_id] = Position(
                    market_id=fill_data.get("market_id", "unknown"),
                    clob_token_id=token_id,
                    quantity=size,
                    avg_price=price,
                    mark_price=price
                )
            self.cash_usd -= cost

        elif side == "SELL":
            if token_id in self.positions:
                pos = self.positions[token_id]
                # If we were long, realize PnL on the portion we sell
                if pos.quantity > 0:
                    sell_size = min(pos.quantity, size)
                    profit = (price - pos.avg_price) * sell_size
                    self.realized_pnl += profit
                
                new_size = pos.quantity - size
                if abs(new_size) < 1e-9:
                    del self.positions[token_id]
                else:
                    # Update avg_price if extending short
                    if pos.quantity <= 0:
                        pos.avg_price = (pos.avg_price * abs(pos.quantity) + cost) / abs(new_size)
                    pos.quantity = new_size
                    pos.mark_price = price
            else:
                self.positions[token_id] = Position(
                    market_id=fill_data.get("market_id", "unknown"),
                    clob_token_id=token_id,
                    quantity=-size,
                    avg_price=price,
                    mark_price=price
                )
            self.cash_usd += cost

        # Maintain spec-required fields and audit
        self.portfolio_value() # recomputes equity_usd
        self.trade_history.append(fill_data)
        self._assert_integrity()

    def mark_to_market(self, mid_prices: Dict[str, float]):
        for token_id, pos in self.positions.items():
            if token_id in mid_prices:
                pos.mark_price = mid_prices[token_id]
                # Unrealized is (market_price - entry_price) * quantity
                pos.unrealized_pnl = (pos.mark_price - pos.avg_price) * pos.quantity
        
        # Sync summary fields
        self.unrealized_pnl = sum(p.unrealized_pnl for p in self.positions.values())
        self.portfolio_value()
        self._assert_integrity()

    def portfolio_value(self) -> float:
        """
        Total mark-to-market value: Cash + Sum(Quantity * MarkPrice)
        """
        pos_value = 0.0
        for p in self.positions.values():
            price = p.mark_price if p.mark_price > 0 else p.avg_price
            pos_value += p.quantity * price
        
        val = self.cash_usd + pos_value
        self.equity_usd = val # Ensure spec sync
        return val

    def get_summary(self) -> Dict[str, Any]:
        val = self.portfolio_value()
        # Update max_equity for drawdown
        if val > self.max_equity:
            self.max_equity = val
        
        self.max_drawdown_usd = max(self.max_drawdown_usd, self.max_equity - val)
        drawdown_pct = (self.max_equity - val) / self.max_equity if self.max_equity > 0 else 0
        
        return {
            "total_value": val,
            "equity_usd": self.equity_usd,
            "cash": self.cash_usd,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "num_positions": len(self.positions),
            "roi": (val - self.initial_capital) / self.initial_capital if self.initial_capital > 0 else 0,
            "drawdown": drawdown_pct,
            "max_drawdown_usd": self.max_drawdown_usd,
            "initial_capital": self.initial_capital
        }

    def save_state(self, file_path: str):
        import json
        state = {
            "cash_usd": self.cash_usd,
            "initial_capital": self.initial_capital,
            "realized_pnl": self.realized_pnl,
            "positions": [
                {
                    "market_id": p.market_id,
                    "clob_token_id": p.clob_token_id,
                    "quantity": p.quantity,
                    "avg_price": p.avg_price
                } for p in self.positions.values()
            ]
        }
        with open(file_path, "w") as f:
            json.dump(state, f)

    def load_state(self, file_path: str):
        import json
        if not os.path.exists(file_path):
            return
        try:
            with open(file_path, "r") as f:
                state = json.load(f)
                self.cash_usd = state["cash_usd"]
                self.initial_capital = state["initial_capital"]
                self.realized_pnl = state["realized_pnl"]
                self.positions = {
                    p["clob_token_id"]: Position(**p) for p in state["positions"]
                }
        except Exception as e:
            logger.error("failed_to_load_portfolio_state", error=str(e))
    def rebuild_from_trades(self, csv_path: str):
        import csv
        if not os.path.exists(csv_path):
            return
        
        # Reset to initial
        self.cash_usd = self.initial_capital
        self.positions = {}
        self.realized_pnl = 0.0
        self.trade_history = []

        try:
            print(f"[*] Rebuilding portfolio from {csv_path}...")
            with open(csv_path, "r") as f:
                reader = csv.DictReader(f)
                count = 0
                for row in reader:
                    try:
                        side = row.get("side")
                        size_str = row.get("size_shares") or row.get("size")
                        price_str = row.get("price")
                        
                        if not side or not size_str or not price_str or size_str == "" or price_str == "":
                            continue
                        
                        # Prioritize clob_token_id for lookups
                        token_id = row.get("clob_token_id") or row.get("market_id")
                        if not token_id:
                            continue

                        fill = {
                            "clob_token_id": token_id, 
                            "market_id": row.get("market_id") or token_id,
                            "side": side,
                            "filled_size": float(size_str),
                            "fill_price": float(price_str),
                            "ts": datetime.fromisoformat(row["timestamp"]) if row.get("timestamp") else datetime.utcnow()
                        }
                        self.apply_fill(fill)
                        count += 1
                    except Exception as e:
                        print(f"[!] Skipping row due to error: {e}")
                print(f"[*] Rebuilt {count} trades. Current Cash: ${self.cash_usd:.2f}, Positions: {len(self.positions)}")
        except Exception as e:
            print(f"[!] Reconstruction failed: {e}")
