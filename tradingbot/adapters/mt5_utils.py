"""
کمک‌توابع اعتبارنامه MT5 — نسخه‌ی تمیز و خودکفا (جایگزین engine.mt5_utils).

Phase 8.4 (MT5 disconnect fix):
  - File IPC lock (logs/mt5_ipc.lock): only ONE Python process owns MT5 at a time.
  - safe_attach() / attach_mt5_session() never shutdown() a connected GUI session.
  - ensure_mt5_connected() reuses healthy sessions; attach-only by default.
  - release_process_mt5_lock() replaces shutdown for long-running live processes.
  - Refresh cooldown marker (logs/mt5_refresh_marker.json) prevents duplicate pulls.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Generator, Iterator

logger = logging.getLogger(__name__)

DEFAULT_TERMINAL_CANDIDATES: tuple[str, ...] = (
    r"C:\Program Files\MetaTrader 5\terminal64.exe",
    r"C:\Program Files (x86)\MetaTrader 5\terminal64.exe",
)

_BROKER_TERMINAL_GLOBS: tuple[str, ...] = (
    r"C:\Program Files\LiteFinance*\terminal64.exe",
    r"C:\Program Files (x86)\LiteFinance*\terminal64.exe",
    r"C:\Program Files\*LiteFinance*\terminal64.exe",
)

DEFAULT_LOCK_TIMEOUT_SEC = float(os.environ.get("MT5_IPC_LOCK_TIMEOUT_SEC", "60"))
DEFAULT_LOCK_STALE_SEC = float(os.environ.get("MT5_IPC_LOCK_STALE_SEC", "300"))
DEFAULT_REFRESH_COOLDOWN_SEC = float(os.environ.get("MT5_REFRESH_COOLDOWN_SEC", "120"))
DEFAULT_RETRY_SLEEP_SEC = float(os.environ.get("MT5_CONNECT_RETRY_SLEEP_SEC", "5"))

_MT5_LOCK_FD: int | None = None
_process_lock_held: bool = False
_MT5_LOCK_DEPTH: int = 0


def _resolve_base_dir(config: dict[str, Any] | None = None) -> Path:
    if config:
        raw = config.get("BASE_DIR") or config.get("base_dir") or "."
        return Path(str(raw))
    return Path(os.environ.get("TRADINGBOT_BASE_DIR", "."))


def mt5_ipc_lock_path(config: dict[str, Any] | None = None) -> Path:
    return _resolve_base_dir(config) / "logs" / "mt5_ipc.lock"


def mt5_refresh_marker_path(config: dict[str, Any] | None = None) -> Path:
    return _resolve_base_dir(config) / "logs" / "mt5_refresh_marker.json"


def _is_process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
    except Exception:
        return False


def _read_lock_metadata(lock_path: Path) -> dict[str, Any]:
    try:
        lines = [ln.strip() for ln in lock_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if len(lines) < 1:
            return {}
        return {
            "pid": int(lines[0]),
            "acquired_at": float(lines[1]) if len(lines) > 1 else 0.0,
            "purpose": lines[2] if len(lines) > 2 else "unknown",
        }
    except Exception:
        return {}


def _remove_stale_lock(lock_path: Path, *, stale_sec: float) -> bool:
    if not lock_path.is_file():
        return True
    meta = _read_lock_metadata(lock_path)
    pid = int(meta.get("pid", 0) or 0)
    acquired_at = float(meta.get("acquired_at", 0) or 0)
    age = time.time() - acquired_at if acquired_at else stale_sec + 1
    if _is_process_alive(pid) and age < stale_sec:
        return False
    try:
        lock_path.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def is_mt5_lock_held_by_other(config: dict[str, Any] | None = None) -> bool:
    lock_path = mt5_ipc_lock_path(config)
    if not lock_path.is_file():
        return False
    meta = _read_lock_metadata(lock_path)
    pid = int(meta.get("pid", 0) or 0)
    if pid == os.getpid():
        return False
    if not _is_process_alive(pid):
        _remove_stale_lock(lock_path, stale_sec=0)
        return False
    return True


def release_mt5_lock() -> None:
    """Release IPC lock. Never calls mt5.shutdown()."""
    global _MT5_LOCK_FD, _process_lock_held
    fd = _MT5_LOCK_FD
    _MT5_LOCK_FD = None
    _process_lock_held = False
    lock_path = mt5_ipc_lock_path()
    if fd is not None:
        try:
            os.close(fd)
        except OSError:
            pass
    try:
        lock_path.unlink(missing_ok=True)
    except OSError:
        pass


@contextlib.contextmanager
def acquire_mt5_lock(
    config: dict[str, Any] | None = None,
    timeout_sec: float | None = None,
    *,
    purpose: str = "mt5",
) -> Generator[None, None, None]:
    """Cross-process file lock — only one Python process may touch MT5 IPC at a time."""
    global _MT5_LOCK_FD, _process_lock_held, _MT5_LOCK_DEPTH
    if _MT5_LOCK_FD is not None:
        _MT5_LOCK_DEPTH += 1
        try:
            yield
        finally:
            _MT5_LOCK_DEPTH -= 1
        return

    lock_path = mt5_ipc_lock_path(config)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    timeout = timeout_sec if timeout_sec is not None else DEFAULT_LOCK_TIMEOUT_SEC
    stale = DEFAULT_LOCK_STALE_SEC
    deadline = time.monotonic() + max(1.0, timeout)
    fd: int | None = None

    while time.monotonic() < deadline:
        meta = _read_lock_metadata(lock_path) if lock_path.is_file() else {}
        if meta.get("pid") == os.getpid() and _is_process_alive(os.getpid()):
            try:
                fd = os.open(str(lock_path), os.O_RDWR)
                break
            except OSError:
                pass
        if _remove_stale_lock(lock_path, stale_sec=stale):
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
                os.write(fd, f"{os.getpid()}\n{time.time()}\n{purpose}\n".encode())
                break
            except FileExistsError:
                pass
        time.sleep(0.25)
    else:
        raise TimeoutError(f"Could not acquire MT5 IPC lock within {timeout}s: {lock_path}")

    _MT5_LOCK_FD = fd
    _MT5_LOCK_DEPTH = 1
    try:
        yield
    finally:
        if not _process_lock_held:
            _MT5_LOCK_DEPTH -= 1
            if _MT5_LOCK_DEPTH <= 0:
                release_mt5_lock()


def hold_mt5_lock_for_process() -> None:
    """Keep IPC lock until release_process_mt5_lock() — for live runner lifetime."""
    global _process_lock_held
    _process_lock_held = True


def release_process_mt5_lock() -> None:
    """Release process-held IPC lock without disconnecting MT5 GUI."""
    global _process_lock_held
    _process_lock_held = False
    release_mt5_lock()


@contextlib.contextmanager
def mt5_ipc_lock(
    config: dict[str, Any] | None = None,
    *,
    timeout_sec: float | None = None,
    purpose: str = "mt5",
    hold: bool = False,
) -> Iterator[None]:
    with acquire_mt5_lock(config, timeout_sec=timeout_sec, purpose=purpose):
        if hold:
            hold_mt5_lock_for_process()
        yield
        if hold:
            release_process_mt5_lock()


def is_refresh_recent(
    config: dict[str, Any] | None = None,
    *,
    cooldown_sec: float | None = None,
) -> bool:
    marker_path = mt5_refresh_marker_path(config)
    if not marker_path.is_file():
        return False
    cooldown = cooldown_sec if cooldown_sec is not None else DEFAULT_REFRESH_COOLDOWN_SEC
    try:
        data = json.loads(marker_path.read_text(encoding="utf-8"))
        return (time.time() - float(data.get("completed_at", 0) or 0)) < cooldown
    except Exception:
        return False


def mark_refresh_done(
    config: dict[str, Any] | None = None,
    *,
    purpose: str = "refresh",
    extra: dict[str, Any] | None = None,
) -> None:
    marker_path = mt5_refresh_marker_path(config)
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "completed_at": time.time(),
        "completed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "pid": os.getpid(),
        "purpose": purpose,
    }
    if extra:
        payload.update(extra)
    marker_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


@dataclass
class Mt5ConnectionDiagnostics:
    python_package_version: str | None = None
    terminal_installed: bool = False
    terminal_path: str | None = None
    terminal_running: bool = False
    experts_api_enabled: bool | None = None
    saved_login: int | None = None
    saved_server: str | None = None
    config_login: int | None = None
    config_server: str | None = None
    init_result: bool = False
    last_error: tuple[int, str] | None = None
    terminal_info: dict[str, Any] | None = None
    account_info: dict[str, Any] | None = None
    hints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def get_mt5_credentials(
    config: dict[str, Any],
) -> tuple[int | None, str | None, str | None]:
    login = os.getenv("MT5_LOGIN") or config.get("MT5_LOGIN") or config.get("mt5_login") or config.get("login")
    password = (
        os.getenv("MT5_PASSWORD")
        or config.get("MT5_PASSWORD")
        or config.get("mt5_password")
        or config.get("password")
    )
    server = (
        os.getenv("MT5_SERVER")
        or config.get("MT5_SERVER")
        or config.get("mt5_server")
        or config.get("server")
    )
    if isinstance(login, str):
        try:
            login = int(login)
        except ValueError:
            pass
    return login, password, server


def has_valid_mt5_credentials(config: dict[str, Any]) -> bool:
    login, password, server = get_mt5_credentials(config)
    return login is not None and password is not None and server is not None


def _discover_branded_terminal(server: str | None = None) -> str | None:
    """Find broker-branded terminal64.exe (e.g. LiteFinance) when origin.txt is missing."""
    if server and "litefinance" in server.lower():
        import glob

        for pattern in _BROKER_TERMINAL_GLOBS:
            for path in glob.glob(pattern):
                if Path(path).is_file():
                    return path
    return None


def discover_terminal_path(config: dict[str, Any] | None = None) -> str | None:
    """Resolve terminal64.exe — prefer env, then login-matched data dir, then newest."""
    env_path = os.getenv("MT5_TERMINAL_PATH") or os.getenv("MT5_PATH")
    if env_path and Path(env_path).is_file():
        return str(Path(env_path))

    login, _, server = get_mt5_credentials(config or {})
    branded = _discover_branded_terminal(server)
    if login is not None:
        for data_dir in _terminal_data_dirs():
            hint = _read_common_ini_fields(data_dir / "config" / "common.ini")
            if hint.get("saved_login") != int(login):
                continue
            saved_server = str(hint.get("saved_server") or "")
            if server and saved_server and server.lower() not in saved_server.lower():
                continue
            path = _terminal_exe_from_data_dir(data_dir) or branded
            if path:
                logger.info(
                    "MT5 terminal matched login=%s server=%s path=%s",
                    login,
                    saved_server or server,
                    path,
                )
                return path
        if branded:
            logger.info("MT5 branded terminal for %s: %s", server, branded)
            return branded

    for data_dir in _terminal_data_dirs():
        path = _terminal_exe_from_data_dir(data_dir)
        if path:
            return path
    if branded:
        return branded
    for candidate in DEFAULT_TERMINAL_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    return None


def _terminal_exe_from_data_dir(data_dir: Path) -> str | None:
    origin = data_dir / "origin.txt"
    if not origin.is_file():
        return None
    try:
        for text in origin.read_text(encoding="utf-16-le", errors="ignore").splitlines():
            text = text.strip()
            if text.lower().endswith("terminal64.exe") and Path(text).is_file():
                return text
    except Exception:
        pass
    return None


def _read_common_ini_fields(ini: Path) -> dict[str, Any]:
    text = _read_ini_text(ini)
    if not text:
        return {}
    login = server = None
    experts_api: bool | None = None
    experts_enabled: bool | None = None
    section = ""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line.lower()
            continue
        if section == "[common]" and line.startswith("Login="):
            try:
                login = int(line.split("=", 1)[1])
            except ValueError:
                pass
        if section == "[common]" and line.startswith("Server="):
            server = line.split("=", 1)[1].strip()
        if section == "[experts]" and line.lower().startswith("api="):
            experts_api = line.split("=", 1)[1].strip() == "1"
        if section == "[experts]" and line.lower().startswith("enabled="):
            experts_enabled = line.split("=", 1)[1].strip() == "1"
    return {
        "saved_login": login,
        "saved_server": server,
        "experts_api_enabled": experts_api,
        "experts_algo_enabled": experts_enabled,
    }


def list_terminal_installations(config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """All known MT5 data dirs + exe path (for diagnostics)."""
    expected_login, _, expected_server = get_mt5_credentials(config or {})
    out: list[dict[str, Any]] = []
    for data_dir in _terminal_data_dirs():
        hint = _read_common_ini_fields(data_dir / "config" / "common.ini")
        exe = _terminal_exe_from_data_dir(data_dir)
        out.append(
            {
                "data_dir": str(data_dir),
                "terminal_exe": exe,
                "saved_login": hint.get("saved_login"),
                "saved_server": hint.get("saved_server"),
                "experts_api": hint.get("experts_api_enabled"),
                "experts_algo": hint.get("experts_algo_enabled"),
                "matches_config": bool(
                    expected_login is not None
                    and hint.get("saved_login") == int(expected_login)
                ),
            }
        )
    return out


def verify_attached_account(config: dict[str, Any], *, strict: bool = True) -> tuple[bool, str]:
    """Ensure Python IPC session matches configured MT5 login/server."""
    try:
        import MetaTrader5 as mt5
    except ImportError:
        return False, "MetaTrader5 not installed"
    if not is_mt5_session_connected():
        return False, "not connected"
    acc = mt5.account_info()
    if acc is None:
        return False, "account_info unavailable"
    login, _, server = get_mt5_credentials(config)
    if strict and login is not None and int(acc.login) != int(login):
        ti = mt5.terminal_info()
        path = getattr(ti, "path", "?") if ti else "?"
        return False, (
            f"wrong account attached login={acc.login} expected={login} "
            f"terminal={path} — set MT5_TERMINAL_PATH to LiteFinance terminal"
        )
    if strict and server and str(acc.server) != str(server):
        return False, f"wrong server attached {acc.server} expected={server}"
    return True, f"account_ok login={acc.login} server={acc.server}"


def _terminal_data_dirs() -> list[Path]:
    root = Path(os.environ.get("APPDATA", "")) / "MetaQuotes" / "Terminal"
    if not root.is_dir():
        return []
    dirs = [p for p in root.iterdir() if p.is_dir() and (p / "config" / "common.ini").is_file()]
    return sorted(dirs, key=lambda p: (p / "config" / "common.ini").stat().st_mtime, reverse=True)


def _read_ini_text(ini: Path) -> str | None:
    for encoding in ("utf-8", "utf-16-le", "utf-16"):
        try:
            text = ini.read_text(encoding=encoding)
            if "[Common]" in text or "[common]" in text or "Login=" in text:
                return text
        except Exception:
            continue
    return None


def read_terminal_session_hint() -> dict[str, Any]:
    for data_dir in _terminal_data_dirs():
        hint = _read_common_ini_fields(data_dir / "config" / "common.ini")
        if hint.get("saved_login") or hint.get("saved_server"):
            hint["data_dir"] = str(data_dir)
            return hint
    return {}


def _is_terminal_process_running(config: dict[str, Any] | None = None) -> bool:
    """True when configured terminal64.exe (or any terminal64) is running."""
    expected = discover_terminal_path(config)
    try:
        import subprocess

        ps = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-CimInstance Win32_Process -Filter \"Name='terminal64.exe'\" "
                "-ErrorAction SilentlyContinue).ExecutablePath",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        paths = [ln.strip() for ln in ps.stdout.splitlines() if ln.strip()]
        if not paths:
            out = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq terminal64.exe", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                check=False,
            )
            return "terminal64.exe" in out.stdout
        if not expected:
            return True
        expected_norm = str(Path(expected).resolve()).lower()
        for raw in paths:
            try:
                if str(Path(raw).resolve()).lower() == expected_norm:
                    return True
            except OSError:
                if raw.lower() == expected.lower():
                    return True
        return False
    except Exception:
        try:
            import subprocess

            out = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq terminal64.exe", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                check=False,
            )
            return "terminal64.exe" in out.stdout
        except Exception:
            return False


def _account_matches(
    account: Any,
    login: int | None,
    server: str | None,
    *,
    strict: bool,
) -> bool:
    if account is None:
        return False
    if not strict:
        return bool(getattr(account, "login", None))
    if login is not None and int(account.login) != int(login):
        return False
    if server and str(account.server) != str(server):
        return False
    return True


def _serialize_named_tuple(obj: Any) -> dict[str, Any] | None:
    if obj is None:
        return None
    try:
        return obj._asdict()  # type: ignore[attr-defined]
    except Exception:
        return None


def is_mt5_already_connected() -> bool:
    """Alias for is_mt5_session_connected — check before any initialize()."""
    return is_mt5_session_connected()


def is_mt5_session_connected() -> bool:
    try:
        import MetaTrader5 as mt5

        terminal = mt5.terminal_info()
        return bool(terminal and terminal.connected)
    except Exception:
        return False


def safe_attach(
    config: dict[str, Any],
    *,
    timeout_ms: int = 60_000,
    allow_start: bool = False,
) -> bool:
    """Attach to running MT5 (path only). Never auto-start terminal unless allow_start=True."""
    import MetaTrader5 as mt5  # noqa: E402

    if is_mt5_session_connected():
        ok, _msg = verify_attached_account(config, strict=True)
        if ok:
            return True
        logger.warning("MT5 session mismatch (%s) — reconnecting to configured terminal", _msg)
        try:
            mt5.shutdown()
        except Exception:
            pass

    if is_mt5_lock_held_by_other(config) and not is_mt5_session_connected():
        logger.warning(
            "MT5 IPC lock held by live bot — safe_attach skipped (do not steal session)"
        )
        return False

    if not _is_terminal_process_running(config):
        if not allow_start:
            logger.warning(
                "MT5 terminal64.exe not running — attach skipped (open MT5 manually, do not auto-start)"
            )
            return False
        logger.info("MT5 not running but allow_start=True — initializing terminal")

    timeout = int(config.get("MT5_TIMEOUT_MS", config.get("mt5_timeout_ms", timeout_ms)))
    terminal_path = discover_terminal_path(config)
    try:
        if terminal_path:
            initialized = bool(mt5.initialize(path=terminal_path, timeout=timeout))
        else:
            initialized = bool(mt5.initialize(timeout=timeout))
        if not initialized:
            return False
        ok, msg = verify_attached_account(config, strict=True)
        if not ok:
            logger.error("MT5 attach to wrong account: %s", msg)
            return False
        return True
    except Exception as exc:
        logger.warning("safe_attach failed: %s", exc)
        return False


def safe_release_mt5(*, force_shutdown: bool = False) -> None:
    """Release lock without kicking GUI. Shutdown only when disconnected or forced."""
    release_process_mt5_lock()
    if not force_shutdown and is_mt5_session_connected():
        return
    try:
        import MetaTrader5 as mt5  # noqa: E402

        terminal = mt5.terminal_info()
        if terminal is None or not terminal.connected:
            mt5.shutdown()
    except Exception:
        pass


def _safe_shutdown_if_disconnected() -> None:
    if is_mt5_session_connected():
        return
    try:
        import MetaTrader5 as mt5

        mt5.shutdown()
    except Exception:
        pass


def diagnose_mt5_connection(config: dict[str, Any] | None = None) -> Mt5ConnectionDiagnostics:
    from tradingbot.adapters.legacy_loader import load_legacy_config

    cfg = config or load_legacy_config()
    diag = Mt5ConnectionDiagnostics()
    login, _password, server = get_mt5_credentials(cfg)
    diag.config_login = int(login) if login is not None else None
    diag.config_server = server
    diag.terminal_path = discover_terminal_path()
    diag.terminal_installed = diag.terminal_path is not None
    diag.terminal_running = _is_terminal_process_running(cfg)
    session = read_terminal_session_hint()
    diag.saved_login = session.get("saved_login")
    diag.saved_server = session.get("saved_server")
    if "experts_api_enabled" in session:
        diag.experts_api_enabled = session.get("experts_api_enabled")

    try:
        import MetaTrader5 as mt5

        diag.python_package_version = getattr(mt5, "__version__", None)
    except ImportError:
        diag.hints.append("MetaTrader5 Python package not installed")
        return diag

    import MetaTrader5 as mt5  # noqa: E402

    with acquire_mt5_lock(cfg):
        connected = attach_mt5_session(cfg, strict_account=False)
    diag.init_result = connected
    diag.last_error = mt5.last_error()
    diag.terminal_info = _serialize_named_tuple(mt5.terminal_info())
    diag.account_info = _serialize_named_tuple(mt5.account_info())
    if connected and diag.account_info:
        diag.hints.append(
            f"Connected read-only to login={diag.account_info.get('login')} "
            f"server={diag.account_info.get('server')}"
        )
    return diag


def attach_mt5_session(
    config: dict[str, Any],
    *,
    symbols: list[str] | None = None,
    timeout_ms: int = 60_000,
    strict_account: bool = False,
    use_lock: bool = False,
) -> bool:
    """Read-only attach — never shutdown() connected GUI, never credential login."""
    import MetaTrader5 as mt5  # noqa: E402

    def _try() -> bool:
        login, _password, server = get_mt5_credentials(config)
        if is_mt5_session_connected():
            account = mt5.account_info()
            if _account_matches(
                account,
                login if strict_account else None,
                server if strict_account else None,
                strict=strict_account,
            ):
                return _select_symbols(mt5, config, symbols)
        if safe_attach(config, timeout_ms=timeout_ms):
            account = mt5.account_info()
            if _account_matches(
                account,
                login if strict_account else None,
                server if strict_account else None,
                strict=strict_account,
            ):
                return _select_symbols(mt5, config, symbols)
            if not strict_account:
                return _select_symbols(mt5, config, symbols)
        return False

    if not use_lock and is_mt5_lock_held_by_other(config) and not is_mt5_session_connected():
        logger.debug("MT5 IPC lock held by another process — attach skipped")
        return False

    if use_lock:
        with acquire_mt5_lock(config, purpose="attach_readonly"):
            return _try()
    return _try()


def ensure_mt5_connected(
    config: dict[str, Any],
    *,
    symbols: list[str] | None = None,
    strict_account: bool = True,
    timeout_ms: int = 60_000,
    attach_only: bool = True,
    use_lock: bool = True,
    hold_lock: bool = False,
) -> bool:
    """
    Establish read-only MT5 connection.

    Default attach_only=True: path attach only, no credential initialize/login.
    Never shutdown() on healthy connected sessions.
    """
    import MetaTrader5 as mt5  # noqa: E402

    login, password, server = get_mt5_credentials(config)
    retries = int(config.get("MT5_RETRIES", config.get("mt5_retries", 3)))
    retry_sleep = float(
        config.get("MT5_RETRY_SLEEP_SEC", config.get("mt5_retry_sleep_sec", DEFAULT_RETRY_SLEEP_SEC))
    )

    def _connected(strict: bool) -> bool:
        if not is_mt5_session_connected():
            return False
        account = mt5.account_info()
        return _account_matches(
            account,
            login if strict else None,
            server if strict else None,
            strict=strict,
        )

    def _connect_body() -> bool:
        if attach_mt5_session(config, symbols=symbols, timeout_ms=timeout_ms, strict_account=strict_account):
            return True
        if _connected(strict_account):
            return _select_symbols(mt5, config, symbols)

        for attempt in range(1, retries + 1):
            if is_mt5_session_connected() and _connected(strict_account):
                return _select_symbols(mt5, config, symbols)

            if safe_attach(config, timeout_ms=timeout_ms):
                if _connected(strict_account) or not strict_account:
                    return _select_symbols(mt5, config, symbols)
                if not attach_only and strict_account and login and password and server:
                    try:
                        mt5.login(int(login), password=password, server=server)
                    except Exception as exc:
                        logger.warning("mt5.login failed: %s", exc)
                    if _connected(strict_account):
                        return _select_symbols(mt5, config, symbols)

            if not attach_only and login and password and server:
                terminal_path = discover_terminal_path()
                timeout = int(config.get("MT5_TIMEOUT_MS", config.get("mt5_timeout_ms", timeout_ms)))
                init_kwargs: dict[str, Any] = {
                    "login": int(login),
                    "password": password,
                    "server": server,
                    "timeout": timeout,
                }
                if terminal_path:
                    init_kwargs["path"] = terminal_path
                if mt5.initialize(**init_kwargs) and _connected(strict_account):
                    return _select_symbols(mt5, config, symbols)

            logger.warning("MT5 connect attempt %d/%d failed: %s", attempt, retries, mt5.last_error())
            if attempt < retries:
                time.sleep(retry_sleep)
        return False

    if use_lock:
        with acquire_mt5_lock(config, purpose="ensure_connected"):
            if hold_lock:
                hold_mt5_lock_for_process()
            return _connect_body()
    return _connect_body()


@contextlib.contextmanager
def mt5_session_context(
    config: dict[str, Any],
    *,
    read_only: bool = True,
    symbols: list[str] | None = None,
    strict_account: bool = False,
) -> Generator[bool, None, None]:
    _ = read_only
    with acquire_mt5_lock(config):
        yield attach_mt5_session(config, symbols=symbols, strict_account=strict_account)


def _select_symbols(mt5: Any, config: dict[str, Any], symbols: list[str] | None) -> bool:
    from tradingbot.adapters.symbols import resolve_broker_symbol

    for sym in symbols or []:
        broker = resolve_broker_symbol(sym, config)
        if not mt5.symbol_select(broker, True):
            logger.warning("Failed to select %s in Market Watch", broker)
    return is_mt5_session_connected()
