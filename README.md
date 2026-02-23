# Polymarket Copy-Trading Bot

A production-grade auto-trading service for Polymarket that monitors target wallets and replicates their trades with configurable risk logic and scaling.

## Features

- **Near Real-Time Monitoring**: Tracks a list of target wallets via the Polymarket Data API.
- **Deduplication**: Ensures no trade is copied twice, even after restarts.
- **Risk Management**:
  - Filter by market tags (e.g., only "Politics" or "Crypto").
  - Minimum 24h volume threshold.
  - Maximum bid/ask spread (BPS) check.
  - Max exposure per market and total capital limits.
- **Flexible Execution**:
  - **Live Mode**: Places actual limit orders via the Polymarket CLOB.
  - **Paper Mode**: Simulates fills against the current orderbook for testing.
- **Monitoring**: Simple FastAPI endpoint for health checks and Prometheus metrics.
- **Docker Ready**: Easy deployment with PostgreSQL and the bot service.

## Setup

1. **Clone & Install**:
   ```bash
   pip install -e .
   ```

2. **Configuration**:
   Copy `.env.example` to `.env` and fill in your details:
   - `PRIVATE_KEY`: Your Polymarket account private key.
   - `POLY_FUNDER_ADDRESS`: Your wallet address.
   - `TARGET_WALLETS`: Comma-separated list of addresses to watch.
   - `PAPER_MODE`: Set to `false` for real trading.

3. **Run with Docker (Recommended)**:
   ```bash
   docker compose up --build
   ```

4. **Run Manually**:
   ```bash
   # Start the bot in paper mode
   poly-bot paper
   
   # Start the bot in live mode
   poly-bot live
   ```

## Monitoring

- **Health Check**: `curl http://localhost:8000/health`
- **Prometheus Metrics**: `curl http://localhost:8000/metrics`

## Project Structure

- `polymarket_bot/clients/`: API clients for Gamma, CLOB, and Data APIs.
- `polymarket_bot/watcher/`: Logic for detecting trades from target wallets.
- `polymarket_bot/engine/`: Decision logic, risk filters, and sizing.
- `polymarket_bot/db/`: Database models and session management.

## Disclaimer

This bot is provided for educational and experimental purposes. Trading on prediction markets involves significant risk. Always test in **Paper Mode** before using real capital. Better safe than sorry.
