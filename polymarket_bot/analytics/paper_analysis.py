import pandas as pd
import os
from pathlib import Path

def analyze_session(log_dir="./paper_logs"):
    """
    Placeholder for post-session analytics.
    Loads trades.csv and portfolio_timeseries.csv and computes key performance metrics.
    """
    trades_path = Path(log_dir) / "trades.csv"
    timeseries_path = Path(log_dir) / "portfolio_timeseries.csv"

    if not trades_path.exists():
        print(f"No trades log found at {trades_path}")
        return

    trades = pd.read_csv(trades_path)
    print(f"\n--- Trade Analysis ---")
    print(f"Total Trades: {len(trades)}")
    if len(trades) > 0:
        # Example metrics
        win_rate = (trades['realized_pnl_usd'] > 0).mean() if 'realized_pnl_usd' in trades.columns else 0
        print(f"Win Rate: {win_rate:.2%}")
    
    if timeseries_path.exists():
        ts = pd.read_csv(timeseries_path)
        print(f"\n--- Portfolio Analysis ---")
        if not ts.empty:
            start_val = ts['portfolio_value_usd'].iloc[0]
            end_val = ts['portfolio_value_usd'].iloc[-1]
            total_return = (end_val - start_val) / start_val
            print(f"Total Return: {total_return:.2%}")
            print(f"Max Drawdown: {ts['max_drawdown_usd'].max():.2f} USD")

if __name__ == "__main__":
    analyze_session()
