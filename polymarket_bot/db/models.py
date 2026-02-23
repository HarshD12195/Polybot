from datetime import datetime
from typing import List, Optional
from sqlalchemy import BigInteger, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Market(Base):
    __tablename__ = "markets"

    market_id: Mapped[str] = mapped_column(String, primary_key=True)
    slug: Mapped[str] = mapped_column(String)
    clob_token_ids: Mapped[dict] = mapped_column(JSON)
    tags: Mapped[List[str]] = mapped_column(JSON)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TargetTrade(Base):
    __tablename__ = "target_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target_wallet: Mapped[str] = mapped_column(String, index=True)
    trade_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    market_id: Mapped[str] = mapped_column(String, index=True)
    side: Mapped[str] = mapped_column(String)  # BUY/SELL
    size: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)


class MyTrade(Base):
    __tablename__ = "my_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String, index=True)
    target_trade_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("target_trades.trade_id"))
    side: Mapped[str] = mapped_column(String)
    size: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String)  # PLACED, FILLED, CANCELLED, FAILED
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Position(Base):
    __tablename__ = "positions"

    market_id: Mapped[str] = mapped_column(String, primary_key=True)
    outcome_id: Mapped[str] = mapped_column(String, primary_key=True)
    size: Mapped[float] = mapped_column(Float)
    avg_price: Mapped[float] = mapped_column(Float)
    pnl_estimate: Mapped[float] = mapped_column(Float, default=0.0)


class ConfigSnapshot(Base):
    __tablename__ = "config_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    key: Mapped[str] = mapped_column(String)
    value: Mapped[str] = mapped_column(String)


class PaperTrade(Base):
    __tablename__ = "paper_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target_trade_id: Mapped[str] = mapped_column(String, index=True)
    clob_token_id: Mapped[str] = mapped_column(String, index=True)
    side: Mapped[str] = mapped_column(String)
    requested_size: Mapped[float] = mapped_column(Float)
    filled_size: Mapped[float] = mapped_column(Float)
    fill_price: Mapped[float] = mapped_column(Float)
    spread_bps: Mapped[float] = mapped_column(Float)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    decision_reason: Mapped[Optional[str]] = mapped_column(String)
