"""Tests for legacy config loader."""

from __future__ import annotations

import os
import unittest
from unittest import mock


class TestLegacyLoaderMerge(unittest.TestCase):
    def test_empty_live_mt5_does_not_wipe_engine_defaults(self) -> None:
        from tradingbot.adapters import legacy_loader

        fake_base = {
            "MT5_LOGIN": 90816536,
            "MT5_PASSWORD": "engine-pass",
            "MT5_SERVER": "Engine-Server",
            "SYMBOLS": ["XAUUSD"],
        }
        fake_live = {
            "MT5_LOGIN": None,
            "MT5_PASSWORD": "",
            "MT5_SERVER": "",
            "MAX_POSITIONS": 3,
        }

        class FakeEngine:
            @staticmethod
            def get_config():
                return dict(fake_base)

        with mock.patch.object(legacy_loader, "ensure_engine_path"), mock.patch(
            "tradingbot.config.engine_settings.config", FakeEngine()
        ), mock.patch(
            "tradingbot.config.live.LIVE_TRADING_CONFIG", fake_live
        ), mock.patch(
            "tradingbot.config.price_action.PRICE_ACTION_CONFIG", {}
        ), mock.patch.dict(os.environ, {}, clear=True):
            merged = legacy_loader.load_legacy_config()

        self.assertEqual(merged["MT5_LOGIN"], 90816536)
        self.assertEqual(merged["MT5_PASSWORD"], "engine-pass")
        self.assertEqual(merged["MT5_SERVER"], "Engine-Server")
        self.assertEqual(merged["MAX_POSITIONS"], 3)


if __name__ == "__main__":
    unittest.main()
