import csv
import os
from typing import List, Dict, Any
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response, FileResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
import structlog
from polymarket_bot.db.session import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from polymarket_bot.config import settings

logger = structlog.get_logger(__name__)

app = FastAPI(title="Polymarket Copy-Trading Bot API")

# Mount static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)

app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
async def root():
    return FileResponse(os.path.join(static_dir, "index.html"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    try:
        # Check DB connectivity
        await db.execute(text("SELECT 1"))
        return {"status": "ok", "db": "connected"}
    except Exception as e:
        logger.error("health_check_failed", error=str(e))
        return Response(content='{"status": "error", "db": "disconnected"}', status_code=503)


@app.get("/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/api/portfolio/stats")
async def get_portfolio_stats():
    # Read the last line of paper_portfolio_timeseries.csv
    file_path = os.path.join(settings.PAPER_LOG_DIR, "paper_portfolio_timeseries.csv")
    if not os.path.exists(file_path):
        return {"cash": 100.0, "total_value": 100.0, "roi": 0.0, "drawdown": 0.0}
    
    with open(file_path, "r") as f:
        lines = [line.strip() for line in f.readlines() if line.strip()]
        if len(lines) < 2:
            return {"cash": 100.0, "total_value": 100.0, "roi": 0.0, "drawdown": 0.0}
        
        header = lines[0].split(",")
        last_line = lines[-1].split(",")
        data = dict(zip(header, last_line))
        
        total_val = float(data.get("equity_usd", 100))
        roi = (total_val - 100.0) / 100.0
        
        return {
            "cash": float(data.get("cash_usd", 100)),
            "total_value": total_val,
            "realized_pnl": float(data.get("realized_pnl_usd", 0)),
            "unrealized_pnl": float(data.get("unrealized_pnl_usd", 0)),
            "roi": roi,
            "drawdown": float(data.get("max_drawdown_usd", 0))
        }

@app.get("/api/portfolio/history")
async def get_portfolio_history():
    file_path = os.path.join(settings.PAPER_LOG_DIR, "paper_portfolio_timeseries.csv")
    if not os.path.exists(file_path):
        return []
    
    history = []
    with open(file_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            history.append({
                "timestamp": row["timestamp"],
                "value": float(row["equity_usd"])
            })
    return history

@app.get("/api/trades")
async def get_trades():
    file_path = os.path.join(settings.PAPER_LOG_DIR, "paper_trades.csv")
    if not os.path.exists(file_path):
        return []
    
    trades = []
    with open(file_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            trades.append(row)
    return trades[::-1] # Newest first

@app.get("/api/portfolio/positions")
async def get_portfolio_positions():
    file_path = os.path.join(settings.PAPER_LOG_DIR, "positions.json")
    if not os.path.exists(file_path):
        return []
    
    import json
    try:
        with open(file_path, "r") as f:
            return json.load(f)
    except:
        return []

@app.get("/status")
async def status():
    # In a real bot, we'd pull from a shared state or DB
    return {
        "bot_running": True,
        "paper_mode": settings.PAPER_MODE,
        "active_targets": len(settings.TARGET_WALLETS),
    }
