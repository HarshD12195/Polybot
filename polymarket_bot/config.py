import json
from typing import Any, Dict, List, Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # --- Polymarket Trading Credentials ---
    PRIVATE_KEY: str
    POLY_FUNDER_ADDRESS: str

    # --- Copy Trading Targets ---
    TARGET_WALLETS: List[str] = Field(default_factory=list)

    @field_validator("TARGET_WALLETS", mode="before")
    @classmethod
    def parse_target_wallets(cls, v: Any) -> List[str]:
        if isinstance(v, str):
            if v.startswith("[") or v.startswith("{"):
                try:
                    return json.loads(v)
                except: pass
            return [x.strip() for x in v.split(",") if x.strip()]
        return v

    # --- Risk & Sizing ---
    MAX_CAPITAL_USDC: float = 1000.0
    MAX_PER_MARKET_USDC: float = 200.0
    
    # Can be a JSON string like {"default": 0.25, "0x...": 0.5}
    SIZE_MULTIPLIER_CONFIG: Dict[str, float] = Field(default_factory=lambda: {"default": 0.25})

    @field_validator("SIZE_MULTIPLIER_CONFIG", mode="before")
    @classmethod
    def parse_multipliers(cls, v: Any) -> Dict[str, float]:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return {"default": 0.25}
        return v

    MIN_24H_VOLUME_USDC: float = 10000.0
    MAX_SPREAD_BPS: int = 100

    # --- Network & Data ---
    GAMMA_API_URL: str = "https://gamma-api.polymarket.com"
    CLOB_API_URL: str = "https://clob.polymarket.com"
    CLOB_WS_URL: str = "wss://ws-subscriptions-clob.polymarket.com"
    DATA_API_URL: str = "https://data-api.polymarket.com"

    # --- Bot Settings ---
    PAPER_MODE: bool = True
    # --- Paper Live Test Settings ---
    PAPER_LIVE_TEST: bool = False
    INITIAL_CAPITAL_USD: float = 100.0
    PAPER_LOG_DIR: str = "./paper_logs"
    MAX_RISK_PER_TRADE_PCT: float = 5.0
    GLOBAL_MAX_DRAWDOWN_PCT: float = 0.20 # 20%
    
    # --- Wallet Quality Thresholds ---
    MIN_WALLET_WIN_RATE: float = 0.40
    MIN_WALLET_TRADES: int = 5
    
    # --- Paper Trading Realism ---
    TRADING_FEE_PCT: float = 0.001  # 0.1% fee
    EXECUTION_DELAY_SECONDS: float = 0.5
    SLIPPAGE_BPS: int = 5
    
    LOG_LEVEL: str = "INFO"
    DATABASE_URL: str = "sqlite+aiosqlite:///./polybot_live.db"
    ALLOWED_TAGS: List[str] = Field(default_factory=list)

    @field_validator("ALLOWED_TAGS", mode="before")
    @classmethod
    def parse_tags(cls, v: Any) -> List[str]:
        if isinstance(v, str):
            if v.startswith("[") or v.startswith("{"):
                try:
                    return json.loads(v)
                except: pass
            return [x.strip() for x in v.split(",") if x.strip()]
        return v

    # --- Monitoring ---
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000

    def get_wallet_config(self, wallet: str) -> Dict[str, Any]:
        """
        Returns the risk configuration for a specific wallet, 
        merging YAML overrides with global defaults.
        """
        import os
        import yaml
        
        config_path = os.path.join(os.path.dirname(__file__), "config", "wallets.yaml")
        wallets_config = {}
        global_defaults = {
            "size_multiplier": self.SIZE_MULTIPLIER_CONFIG.get("default", 0.25),
            "max_per_market_usdc": self.MAX_PER_MARKET_USDC,
            "max_drawdown": self.GLOBAL_MAX_DRAWDOWN_PCT,
            "category_preferences": []
        }

        if os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    data = yaml.safe_load(f)
                    wallets_list = data.get("wallets", [])
                    wallets_config = {w["address"].lower(): w for w in wallets_list}
                    # Update global defaults from YAML if present
                    if "global_defaults" in data:
                        global_defaults.update(data["global_defaults"])
            except Exception as e:
                import structlog
                structlog.get_logger(__name__).error("failed_to_load_wallets_yaml", error=str(e))

        wallet_data = wallets_config.get(wallet.lower(), {})
        # Merge wallet-specific config into defaults
        merged = {**global_defaults, **wallet_data}
        return merged

    def get_multiplier(self, wallet: str) -> float:
        # Fallback to current SIZE_MULTIPLIER_CONFIG if no YAML
        return self.get_wallet_config(wallet).get("size_multiplier", self.SIZE_MULTIPLIER_CONFIG.get(wallet, self.SIZE_MULTIPLIER_CONFIG.get("default", 0.0)))


settings = Settings()
