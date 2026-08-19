"""Tests for dashboard support scripts (verify, snapshot)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def _load_script(name: str):
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestVerifyMlLiveReady:
    def test_dataset_staleness_no_name_error(self):
        mod = _load_script("verify_ml_live_ready")
        fake_orch = MagicMock()
        fake_orch.measure_dataset_lag.return_value = {
            "dataset_exists": True,
            "lag_hours": 72.0,
            "dataset_max_utc": "2026-01-01T00:00:00+00:00",
            "live_max_utc": "2026-01-04T00:00:00+00:00",
        }
        fake_orch.refresh_threshold_hours.return_value = 48.0
        with patch.object(mod, "_load_orchestrator_module", return_value=fake_orch):
            line, meta = mod._dataset_staleness_warning(max_lag_hours=48.0)
        assert line is not None
        assert "DATASET_STALE" in line
        assert meta["lag_hours"] == 72.0

    def test_dataset_fresh_message(self):
        mod = _load_script("verify_ml_live_ready")
        fake_orch = MagicMock()
        fake_orch.measure_dataset_lag.return_value = {
            "dataset_exists": True,
            "lag_hours": 12.0,
        }
        fake_orch.refresh_threshold_hours.return_value = 48.0
        with patch.object(mod, "_load_orchestrator_module", return_value=fake_orch):
            line, _ = mod._dataset_staleness_warning(max_lag_hours=48.0)
        assert line == "DATASET_FRESH|OK|lag 12.0h"

    def test_main_returns_zero_when_ml_off(self, monkeypatch):
        mod = _load_script("verify_ml_live_ready")
        monkeypatch.setenv("USE_ML_KERNEL", "false")
        with patch("tradingbot.ml.integration.config.is_ml_kernel_enabled", return_value=False):
            rc = mod.main()
        assert rc == 0


class TestStatusSnapshot:
    def test_ascii_safe_strips_non_ascii(self):
        mod = _load_script("status_snapshot")
        assert mod._ascii_safe("hello") == "hello"
        assert "?" in mod._ascii_safe("سلام")

    def test_process_state_empty(self):
        mod = _load_script("status_snapshot")
        with patch("subprocess.check_output", side_effect=RuntimeError("no ps")):
            state = mod._process_state()
        assert state["kernel_running"] is False
        assert state["watchdog_running"] is False

    def test_latest_backtest_line_from_reports(self, tmp_path, monkeypatch):
        mod = _load_script("status_snapshot")
        reports = tmp_path / "reports"
        reports.mkdir()
        payload = {
            "results": [
                {"range_trades": 3, "range_metrics": {"net_profit": 10.5}},
                {"range_trades": 2, "range_metrics": {"net_profit": -4.0}},
            ]
        }
        import json

        (reports / "backtest_range_20260101_XAUUSD.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
        monkeypatch.setattr(mod, "ROOT", tmp_path)
        line = mod._latest_backtest_line()
        assert line is not None
        assert "trades=5" in line
        assert "net=6.5" in line

    def test_account_line_from_live_cache(self, tmp_path, monkeypatch):
        mod = _load_script("status_snapshot")
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True)
        import json
        from datetime import datetime, timezone

        (data_dir / "live_account.json").write_text(
            json.dumps(
                {
                    "balance": 794.32,
                    "equity": 794.32,
                    "profit": 0.0,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(mod, "ROOT", tmp_path)
        line = mod._account_line_from_live_cache()
        assert line == "ACCOUNT|794.32|794.32|0.0"

    def test_account_line_from_report(self, tmp_path, monkeypatch):
        mod = _load_script("status_snapshot")
        startup = tmp_path / "data" / "startup"
        startup.mkdir(parents=True)
        import json
        from datetime import datetime, timezone

        (startup / "startup_report.json").write_text(
            json.dumps(
                {
                    "startup_timestamp": datetime.now(timezone.utc).isoformat(),
                    "account_balance": 500.0,
                    "account_equity": 512.5,
                    "mt5_connected": True,
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(mod, "ROOT", tmp_path)
        line = mod._account_line_from_report()
        assert line == "ACCOUNT|500.0|512.5|-"

    def test_main_body_emits_core_lines(self, monkeypatch):
        mod = _load_script("status_snapshot")
        monkeypatch.setattr(
            mod,
            "_process_state",
            lambda: {
                "kernel_running": False,
                "kernel_watchdog": False,
                "kernel_bot": False,
                "watchdog_running": False,
                "bot_running": False,
                "watchdog_pid": None,
                "bot_pid": None,
            },
        )
        monkeypatch.setattr(
            mod,
            "_account_line",
            lambda kernel_mt5_ok=False, bot_running=False: None,
        )
        monkeypatch.setattr(mod, "_mt5_alerts", lambda kernel_mt5_ok=False: [])
        monkeypatch.setattr(mod, "_journal_alerts", lambda: [])
        monkeypatch.setattr(mod, "_alerts_log_alerts", lambda **kw: [])
        monkeypatch.setattr(mod, "_watchdog_restart_alerts", lambda: [])
        monkeypatch.setattr(mod, "_engine_dashboard_lines", lambda: [])
        monkeypatch.setattr(mod, "_router_signal_lines", lambda *a, **k: [])
        monkeypatch.setattr(mod, "_demo_note_line", lambda: None)
        monkeypatch.setattr(
            mod,
            "_automation_lines",
            lambda proc: ["TASK|watchdog|OFF|pid=-"],
        )

        import io

        buf = io.StringIO()
        with patch.object(sys, "stdout", buf):
            with patch("tradingbot.ml.integration.config.is_ml_kernel_enabled", return_value=False):
                with patch("tradingbot.ml.phase15a.config.trend_rf_model_path", return_value=Path("x")):
                    with patch("tradingbot.ml.data.paths.phase9_9_model_path", return_value=Path("y")):
                        with patch("tradingbot.services.meta_labeler.MODEL_DIR", Path("z")):
                            with patch.object(Path, "is_file", return_value=True):
                                rc = mod._main_body()
        out = buf.getvalue()
        assert rc == 0
        assert "STATE|STOPPED" in out
        assert "WATCHDOG|STOPPED" in out
        assert "BOT|STOPPED" in out
