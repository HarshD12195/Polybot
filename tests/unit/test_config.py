import os
import pytest

# Set dummy env vars before importing settings
os.environ["PRIVATE_KEY"] = "0x0000000000000000000000000000000000000000000000000000000000000001"
os.environ["POLY_FUNDER_ADDRESS"] = "0x0000000000000000000000000000000000000000"

from polymarket_bot.config import Settings

def test_settings_parsing():
    params = {
        "PRIVATE_KEY": "0x123",
        "POLY_FUNDER_ADDRESS": "0xabc",
        "TARGET_WALLETS": "0x1, 0x2, 0x3 ",
        "SIZE_MULTIPLIER_CONFIG": '{"default": 0.5, "0x1": 1.0}'
    }
    settings = Settings(**params)
    
    assert settings.TARGET_WALLETS == ["0x1", "0x2", "0x3"]
    assert settings.SIZE_MULTIPLIER_CONFIG["default"] == 0.5
    assert settings.SIZE_MULTIPLIER_CONFIG["0x1"] == 1.0
    assert settings.get_multiplier("0x1") == 1.0
    assert settings.get_multiplier("0x2") == 0.5
    assert settings.get_multiplier("unknown") == 0.5

def test_settings_invalid_multiplier():
    params = {
        "PRIVATE_KEY": "0x123",
        "POLY_FUNDER_ADDRESS": "0xabc",
        "SIZE_MULTIPLIER_CONFIG": "invalid-json"
    }
    settings = Settings(**params)
    # Should fallback to default
    assert settings.SIZE_MULTIPLIER_CONFIG == {"default": 0.25}
