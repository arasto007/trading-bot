"""Dashboard HTA wiring + launcher bat integrity tests."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HTA = ROOT / "live_dashboard.hta"

DASHBOARD_BATS = {
    "btnGoLive": "start/START_BOT.bat",
    "btnStop": "start/5_stop_bot.bat",
    "btnPrepare": "start/GO_LIVE_FULL.bat",
    "btnCheck": "start/1_check_setup.bat",
    "btnStatus": "start/6_status.bat",
    "btnDailyReport": "start/16_daily_report.bat",
}


@pytest.fixture(scope="module")
def hta_text() -> str:
    assert HTA.is_file(), "live_dashboard.hta missing at project root"
    return HTA.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def shell_vbs() -> str:
    return (ROOT / "scripts" / "hta_shell.vbs").read_text(encoding="utf-8")


@pytest.mark.parametrize("btn_id,bat_rel", list(DASHBOARD_BATS.items()))
def test_dashboard_bat_targets_exist(btn_id: str, bat_rel: str):
    bat = ROOT / bat_rel.replace("/", "\\")
    assert bat.is_file(), f"missing launcher for {btn_id}: {bat}"


@pytest.mark.parametrize("btn_id", list(DASHBOARD_BATS.keys()) + ["btnRefresh"])
def test_hta_has_button_ids(btn_id: str, hta_text: str):
    assert f'id="{btn_id}"' in hta_text


@pytest.mark.parametrize("btn_id", list(DASHBOARD_BATS.keys()) + ["btnRefresh"])
def test_shell_has_vbs_handlers(btn_id: str, shell_vbs: str):
    assert f"Sub {btn_id}_OnClick" in shell_vbs


def test_hta_script_after_dom(hta_text: str):
    status_pos = hta_text.index('id="status"')
    script_pos = hta_text.index('<script language="VBScript">')
    assert script_pos > status_pos, "VBScript must load after status element"


def test_hta_no_parse_time_boot(shell_vbs: str):
    assert "BootDashboard" in shell_vbs
    assert shell_vbs.strip().splitlines()[-1] != "BootDashboard"


def test_hta_iframe_shell(hta_text: str):
    assert 'id="liveframe"' in hta_text
    assert "dashboard_live.html" in hta_text
    assert "v9.1.0" in hta_text


def test_shell_async_snapshot(shell_vbs: str):
    assert "RunSnapshotAsync" in shell_vbs
    assert "sh.Run cmd, 0, False" in shell_vbs


def test_shell_refresh_logic(shell_vbs: str):
    assert "Sub RefreshAll" in shell_vbs
    assert "Sub Window_OnLoad" in shell_vbs
    assert "Sub FinishRefresh" in shell_vbs


def test_snapshot_launcher_exists():
    assert (ROOT / "start" / "0_hta_snapshot.bat").is_file()
    assert (ROOT / "scripts" / "status_snapshot.py").is_file()


def test_run_dashboard_bat_uses_python_server():
    bat = (ROOT / "RUN_DASHBOARD.bat").read_text(encoding="utf-8")
    assert "dashboard_server.py" in bat
    assert "v10.0.0" in bat


def test_build_hta_shell_script_exists():
    assert (ROOT / "scripts" / "build_hta_shell.py").is_file()
    assert (ROOT / "scripts" / "hta_shell.vbs").is_file()


def test_hta_vbscript_is_ascii_only(hta_text: str):
    start = hta_text.index('<script language="VBScript">')
    end = hta_text.index("</script>", start)
    block = hta_text[start:end]
    for ch in block:
        assert ord(ch) < 128, f"non-ASCII in VBScript: U+{ord(ch):04X}"
