"""Command line interface for pairing, diagnostics, and serving."""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import secrets
import signal
import subprocess
import sys
import textwrap
import time
from functools import partial
from pathlib import Path
from typing import Any

from . import autostart
from .browser import ChromeSession, TestPatternSession
from .browser_discovery import (
    BrowserSelectionError,
    detect_browsers,
    open_sign_in_profile,
    resolve_browser,
)
from .config import (
    BrowserMode,
    KNOWN_OLDER_SCHEMA_VERSIONS,
    SCHEMA_VERSION,
    Settings,
    SettingsIssue,
    SettingsValidationError,
    default_settings,
    load_settings,
    restore_settings_bytes,
    save_settings,
    settings_from_json,
    settings_to_dict,
)
from .diagnostics import diagnostics as collect_diagnostics
from .platforms import ensure_supported_runtime, host_kind, secure_directory, secure_file
from .runtime import (
    DOWNLOAD_DIRECTORY,
    GUEST_INI_FILE,
    LOG_FILE,
    SETTINGS_FILE,
    STATE_FILE,
    TOKEN_FILE,
    RuntimeState,
    ensure_directories,
    clear_connection_state,
    load_state,
    process_is_owned,
    process_is_running,
    remove_state_if_owned,
    stop_owned_process,
    write_state,
    write_connection_state,
)
from .server import RetroBridgeServer


def _read_token(path: Path) -> str:
    try:
        token = path.read_text(encoding="ascii").strip()
    except FileNotFoundError as exc:
        raise SystemExit(f"Token file not found: {path}. Run 'retrobridge pair' first.") from exc
    if len(token) != 32 or any(c not in "0123456789abcdef" for c in token):
        raise SystemExit(f"Invalid token file: {path}")
    return token


def pair(
    token_path: Path,
    ini_path: Path,
    force: bool,
    server: str = "10.0.2.2",
    port: int = 9866,
    as_json: bool = False,
) -> None:
    try:
        server = str(ipaddress.IPv4Address(server))
    except ipaddress.AddressValueError as exc:
        raise SystemExit(f"Guest server must be an IPv4 address: {server}") from exc
    if port < 1 or port > 65535:
        raise SystemExit(f"Guest port must be between 1 and 65535: {port}")
    for path in (token_path, ini_path):
        if path.exists() and not force:
            raise SystemExit(f"Refusing to overwrite {path}; pass --force to rotate pairing")
    token = secrets.token_hex(16)
    secure_directory(token_path.parent)
    secure_directory(ini_path.parent)
    token_temporary = token_path.with_name(f"{token_path.name}.tmp")
    ini_temporary = ini_path.with_name(f"{ini_path.name}.tmp")
    token_temporary.write_text(token + "\n", encoding="ascii")
    secure_file(token_temporary)
    ini_temporary.write_text(
        "[RetroBridge]\r\n"
        f"Server={server}\r\n"
        f"Port={port}\r\n"
        f"Token={token}\r\n",
        encoding="ascii",
        newline="",
    )
    secure_file(ini_temporary)
    os.replace(token_temporary, token_path)
    os.replace(ini_temporary, ini_path)
    secure_file(token_path)
    secure_file(ini_path)
    if as_json:
        _emit_json(
            True,
            {
                "token_file": str(token_path),
                "guest_ini_file": str(ini_path),
                "guest_server": server,
                "guest_port": port,
            },
        )
    else:
        print(f"Created host token: {token_path}")
        print(f"Created guest configuration: {ini_path}")


def _emit_json(
    ok: bool,
    data: Any = None,
    errors: list[SettingsIssue | dict[str, str]] | None = None,
) -> None:
    serialized_errors = [
        issue.to_dict() if isinstance(issue, SettingsIssue) else issue
        for issue in (errors or [])
    ]
    print(
        json.dumps(
            {
                "contract_version": 1,
                "ok": ok,
                "data": {} if data is None else data,
                "errors": serialized_errors,
            },
            sort_keys=True,
        )
    )


def _json_input(source: str) -> str:
    if source == "-":
        return sys.stdin.read()
    return Path(source).read_text(encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="retrobridge")
    subparsers = parser.add_subparsers(dest="command", required=True)
    pair_parser = subparsers.add_parser("pair", help="generate host token and guest INI")
    pair_parser.add_argument("--token-file", type=Path, default=TOKEN_FILE)
    pair_parser.add_argument(
        "--guest-ini",
        type=Path,
        default=GUEST_INI_FILE,
    )
    pair_parser.add_argument(
        "--server",
        default="10.0.2.2",
        help="host address reachable from the Windows 98 guest",
    )
    pair_parser.add_argument(
        "--port",
        type=int,
        default=9866,
        help="host TCP port reachable from the Windows 98 guest",
    )
    pair_parser.add_argument("--force", action="store_true")
    pair_parser.add_argument("--json", action="store_true", dest="as_json")

    serve_parser = subparsers.add_parser("serve", help="run the guest bridge")
    serve_parser.add_argument("--token-file", type=Path, default=TOKEN_FILE)
    serve_parser.add_argument("--listen", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=9866)
    serve_parser.add_argument("--headed", action="store_true")
    serve_parser.add_argument("--test-pattern", action="store_true")
    serve_parser.add_argument(
        "--download-dir",
        type=Path,
        default=DOWNLOAD_DIRECTORY,
    )
    serve_parser.add_argument("--max-download-mb", type=int, default=100)
    serve_parser.add_argument(
        "--self-test",
        action="store_true",
        help="enable authenticated deterministic browser fixtures",
    )
    serve_parser.add_argument("--managed", action="store_true", help=argparse.SUPPRESS)
    serve_parser.add_argument("--settings-file", type=Path)

    console_parser = subparsers.add_parser(
        "console", help="run the managed renderer in a friendly visible console"
    )
    console_parser.add_argument("--token-file", type=Path, default=TOKEN_FILE)
    console_parser.add_argument("--listen", default="127.0.0.1")
    console_parser.add_argument("--port", type=int, default=9866)
    console_parser.add_argument("--headed", action="store_true")
    console_parser.add_argument(
        "--download-dir",
        type=Path,
        default=DOWNLOAD_DIRECTORY,
    )
    console_parser.add_argument("--max-download-mb", type=int, default=100)
    console_parser.add_argument("--settings-file", type=Path)
    console_parser.set_defaults(
        managed=True,
        self_test=False,
        test_pattern=False,
    )
    subparsers.add_parser("doctor", help="launch isolated Chrome and capture one frame")

    start_parser = subparsers.add_parser("start", help="start one managed renderer")
    start_parser.add_argument("--token-file", type=Path, default=TOKEN_FILE)
    start_parser.add_argument("--listen", default="127.0.0.1")
    start_parser.add_argument("--port", type=int, default=9866)
    start_parser.add_argument("--headed", action="store_true")
    start_parser.add_argument(
        "--download-dir", type=Path, default=DOWNLOAD_DIRECTORY
    )
    start_parser.add_argument("--max-download-mb", type=int, default=100)
    start_parser.add_argument("--settings-file", type=Path)
    start_mode = start_parser.add_mutually_exclusive_group()
    start_mode.add_argument(
        "--self-test",
        action="store_true",
        help="start with authenticated deterministic browser fixtures",
    )
    start_mode.add_argument(
        "--test-pattern",
        action="store_true",
        help="start the renderer-free framebuffer performance pattern",
    )
    stop_parser = subparsers.add_parser("stop", help="stop the managed renderer")
    stop_parser.add_argument("--json", action="store_true", dest="as_json")
    status_parser = subparsers.add_parser("status", help="show managed renderer status")
    status_parser.add_argument("--json", action="store_true", dest="as_json")
    logs_parser = subparsers.add_parser("logs", help="show managed renderer logs")
    logs_parser.add_argument("--lines", type=int, default=100)

    autostart_parser = subparsers.add_parser(
        "autostart", help="manage the opt-in native per-user login service"
    )
    autostart_subparsers = autostart_parser.add_subparsers(
        dest="autostart_command", required=True
    )
    autostart_install = autostart_subparsers.add_parser(
        "install", help="install and start the per-user login service"
    )
    autostart_install.add_argument(
        "--token-file", type=Path, default=TOKEN_FILE
    )
    autostart_install.add_argument("--listen", default="127.0.0.1")
    autostart_install.add_argument("--port", type=int, default=9866)
    autostart_install.add_argument("--headed", action="store_true")
    autostart_install.add_argument(
        "--download-dir", type=Path, default=DOWNLOAD_DIRECTORY
    )
    autostart_install.add_argument("--max-download-mb", type=int, default=100)
    autostart_install.add_argument("--force", action="store_true")
    autostart_install.add_argument("--settings-file", type=Path)
    autostart_subparsers.add_parser(
        "remove", help="stop and remove the per-user login service"
    )
    autostart_status = autostart_subparsers.add_parser(
        "status", help="show login-service installation status"
    )
    autostart_status.add_argument("--json", action="store_true", dest="as_json")

    config_parser = subparsers.add_parser(
        "config", help="inspect, validate, and save versioned settings"
    )
    config_subparsers = config_parser.add_subparsers(
        dest="config_command", required=True
    )
    config_show = config_subparsers.add_parser("show")
    config_show.add_argument("--json", action="store_true", dest="as_json")
    config_show.add_argument("--settings-file", type=Path, default=SETTINGS_FILE)
    for command in ("validate", "apply"):
        config_command = config_subparsers.add_parser(command)
        config_command.add_argument("--json-input", required=True)
        config_command.add_argument("--settings-file", type=Path, default=SETTINGS_FILE)

    browsers_parser = subparsers.add_parser(
        "browsers", help="detect browsers and open dedicated sign-in profiles"
    )
    browsers_subparsers = browsers_parser.add_subparsers(
        dest="browsers_command", required=True
    )
    browser_detect = browsers_subparsers.add_parser("detect")
    browser_detect.add_argument("--json", action="store_true", dest="as_json")
    browser_sign_in = browsers_subparsers.add_parser("sign-in")
    browser_sign_in.add_argument(
        "--mode",
        required=True,
        choices=(BrowserMode.EDGE_PERSONAL.value, BrowserMode.CHROME_PERSONAL.value),
    )

    diagnostics_parser = subparsers.add_parser(
        "diagnostics", help="report setup and runtime readiness"
    )
    diagnostics_parser.add_argument("--json", action="store_true", dest="as_json")
    diagnostics_parser.add_argument("--settings-file", type=Path, default=SETTINGS_FILE)
    return parser


def _browser_validation_issue(settings: Settings) -> SettingsIssue | None:
    selected = next(
        browser for browser in detect_browsers() if browser.mode is settings.browser.mode
    )
    if selected.available:
        return None
    return SettingsIssue(
        "browser_missing",
        "browser.mode",
        f"{selected.name} was not found. Install it or choose another browser.",
    )


def show_config(path: Path) -> None:
    try:
        settings = load_settings(path)
    except SettingsValidationError as exc:
        _emit_json(
            False,
            {"exists": path.is_file(), "path": str(path), "settings": None},
            exc.issues,
        )
        return
    if settings is None:
        defaults = default_settings(start_with_windows=autostart.enabled())
        _emit_json(
            False,
            {
                "exists": False,
                "path": str(path),
                "settings": settings_to_dict(defaults),
            },
            [SettingsIssue("settings_missing", "settings", "First-run setup is required")],
        )
        return
    _emit_json(
        True,
        {"exists": True, "path": str(path), "settings": settings_to_dict(settings)},
    )


def validate_config(source: str) -> Settings:
    settings = settings_from_json(_json_input(source))
    issue = _browser_validation_issue(settings)
    if issue is not None:
        raise SettingsValidationError([issue])
    _emit_json(True, {"settings": settings_to_dict(settings)})
    return settings


def _configured_service_arguments(path: Path) -> list[str]:
    return [
        autostart.current_python(),
        "-m",
        "retrobridge.cli",
        "serve",
        "--managed",
        "--settings-file",
        str(path.resolve()),
    ]


def apply_config(source: str, path: Path) -> None:
    settings = settings_from_json(_json_input(source))
    issue = _browser_validation_issue(settings)
    if issue is not None:
        raise SettingsValidationError([issue])
    try:
        previous = path.read_bytes()
    except FileNotFoundError:
        previous = None
    if previous is not None:
        try:
            existing_payload = json.loads(previous.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            existing_payload = None
        if isinstance(existing_payload, dict):
            existing_version = existing_payload.get("schema_version")
            if (
                isinstance(existing_version, int)
                and not isinstance(existing_version, bool)
                and existing_version != SCHEMA_VERSION
            ):
                # Known legacy documents are backed up and migrated by the loader.
                # Unknown versions are rejected here so Apply can never replace a
                # document created by a newer or unsupported RetroBridge version.
                if existing_version in KNOWN_OLDER_SCHEMA_VERSIONS:
                    load_settings(path)
                    previous = path.read_bytes()
                else:
                    settings_from_json(previous.decode("utf-8"))
    save_settings(settings, path)
    try:
        if settings.startup.start_with_windows:
            if host_kind() == "linux":
                raise RuntimeError("Windows startup cannot be configured from Linux")
            autostart.install(
                _configured_service_arguments(path),
                working_directory=path.parent,
                force=True,
            )
        elif autostart.installed():
            autostart.remove()
    except Exception as exc:
        restore_settings_bytes(previous, path)
        raise SettingsValidationError(
            [
                SettingsIssue(
                    "autostart_mismatch",
                    "startup.start_with_windows",
                    f"Settings were not applied because Windows startup could not be updated: {exc}",
                )
            ]
        ) from exc
    _emit_json(
        True,
        {
            "path": str(path),
            "settings": settings_to_dict(settings),
            "autostart_installed": autostart.installed(),
        },
    )


def show_browsers() -> None:
    _emit_json(True, {"browsers": [browser.to_dict() for browser in detect_browsers()]})


def sign_in_browser(mode: str) -> None:
    browser_mode = BrowserMode(mode)
    open_sign_in_profile(browser_mode)
    _emit_json(True, {"mode": browser_mode.value, "closed": True})


def show_diagnostics(path: Path) -> None:
    _emit_json(True, collect_diagnostics(path))


def apply_runtime_settings(args: argparse.Namespace) -> object:
    settings_path = getattr(args, "settings_file", None)
    if settings_path is None:
        args.browser_mode = BrowserMode.PRIVATE_CHROMIUM
        return resolve_browser(BrowserMode.PRIVATE_CHROMIUM)
    try:
        settings = load_settings(settings_path)
    except SettingsValidationError as exc:
        raise SystemExit(exc.issues[0].message) from exc
    if settings is None:
        raise SystemExit(f"Settings file not found: {settings_path}")
    args.listen = settings.network.listen
    args.port = settings.network.port
    args.download_dir = Path(settings.downloads.directory)
    args.max_download_mb = settings.downloads.max_megabytes
    args.browser_mode = settings.browser.mode
    try:
        selection = resolve_browser(settings.browser.mode)
    except BrowserSelectionError as exc:
        raise SystemExit(str(exc)) from exc
    args.headed = bool(args.headed or selection.headed)
    return selection


def start_managed(args: argparse.Namespace) -> None:
    state = load_state()
    if state is not None and process_is_running(state.pid) and process_is_owned(state.pid):
        raise SystemExit(f"RetroBridge is already running as PID {state.pid}")
    if autostart.enabled():
        legacy_headed = args.headed and getattr(args, "settings_file", None) is None
        if args.self_test or args.test_pattern or legacy_headed:
            raise SystemExit(
                "The installed login service owns normal renderer settings; remove autostart "
                "before starting a headed or deterministic QA mode"
            )
        if not autostart.executable_is_available():
            raise SystemExit(
                "RetroBridge autostart points to a missing executable; reinstall it with "
                "'retrobridge autostart install --force'"
            )
        try:
            autostart.start()
        except subprocess.CalledProcessError as exc:
            raise SystemExit(f"Could not start RetroBridge through autostart: {exc}") from exc
        print("RetroBridge start requested through the installed login service")
        print(f"Log: {LOG_FILE}")
        return
    ensure_directories()
    if getattr(args, "settings_file", None) is not None:
        command = [
            sys.executable,
            "-m",
            "retrobridge.cli",
            "serve",
            "--managed",
            "--settings-file",
            str(args.settings_file.resolve()),
        ]
    else:
        command = [
            sys.executable,
            "-m",
            "retrobridge.cli",
            "serve",
            "--managed",
            "--token-file",
            str(args.token_file.resolve()),
            "--listen",
            args.listen,
            "--port",
            str(args.port),
            "--download-dir",
            str(args.download_dir.expanduser().resolve()),
            "--max-download-mb",
            str(args.max_download_mb),
        ]
    if args.headed:
        command.append("--headed")
    if args.self_test:
        command.append("--self-test")
    if args.test_pattern:
        command.append("--test-pattern")
    process_options: dict[str, object] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        process_options["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        )
    else:
        process_options["start_new_session"] = True
    process = subprocess.Popen(command, **process_options)
    runtime = RuntimeState(
        pid=process.pid,
        host=args.listen,
        port=args.port,
        log_file=str(LOG_FILE),
        download_dir=str(args.download_dir.expanduser().resolve()),
        token_file=str(args.token_file.resolve()),
        self_test=args.self_test,
        test_pattern=args.test_pattern,
        browser_mode=args.browser_mode.value,
    )
    write_state(runtime)
    time.sleep(0.3)
    if process.poll() is not None:
        remove_state_if_owned(process.pid)
        raise SystemExit(f"RetroBridge failed to start; inspect {LOG_FILE}")
    print(f"RetroBridge started as PID {process.pid}")
    print(f"Log: {LOG_FILE}")


def stop_managed(as_json: bool = False) -> None:
    state = load_state()
    if state is None:
        if as_json:
            _emit_json(True, {"running": False, "stopped": False})
        else:
            print("RetroBridge is not running")
        return
    graceful = stop_owned_process(state)
    clear_connection_state()
    if as_json:
        _emit_json(True, {"running": False, "stopped": True, "graceful": graceful})
    else:
        print("RetroBridge stopped" if graceful else "RetroBridge was force-stopped after timeout")


def show_status(as_json: bool) -> None:
    state = load_state()
    running = bool(state and process_is_running(state.pid) and process_is_owned(state.pid))
    payload = {
        "running": running,
        "pid": state.pid if state else None,
        "listen": f"{state.host}:{state.port}" if state else None,
        "log_file": state.log_file if state else str(LOG_FILE),
        "download_dir": state.download_dir if state else None,
        "mode": (
            None
            if state is None
            else "test-pattern"
            if state.test_pattern
            else "self-test"
            if state.self_test
            else "normal"
        ),
        "browser_mode": state.browser_mode if state else None,
        "autostart_installed": autostart.installed(),
        "autostart_enabled": autostart.enabled(),
        "autostart_loaded": autostart.loaded(),
        "autostart_executable_available": (
            autostart.executable_is_available() if autostart.installed() else None
        ),
    }
    if as_json:
        print(json.dumps(payload, sort_keys=True))
        return
    print("RetroBridge is running" if running else "RetroBridge is stopped")
    for key in (
        "pid",
        "listen",
        "log_file",
        "download_dir",
        "mode",
        "browser_mode",
        "autostart_installed",
        "autostart_enabled",
        "autostart_loaded",
        "autostart_executable_available",
    ):
        if payload[key] is not None:
            print(f"{key.replace('_', ' ').title()}: {payload[key]}")


def show_logs(lines: int) -> None:
    if lines <= 0:
        raise SystemExit("--lines must be positive")
    try:
        content = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        raise SystemExit(f"Log file not found: {LOG_FILE}") from None
    print("\n".join(content[-lines:]))


def _service_arguments(args: argparse.Namespace) -> list[str]:
    if getattr(args, "settings_file", None) is not None:
        return _configured_service_arguments(args.settings_file)
    command = [
        autostart.current_python(),
        "-m",
        "retrobridge.cli",
        "serve",
        "--managed",
        "--token-file",
        str(args.token_file.resolve()),
        "--listen",
        args.listen,
        "--port",
        str(args.port),
        "--download-dir",
        str(args.download_dir.expanduser().resolve()),
        "--max-download-mb",
        str(args.max_download_mb),
    ]
    if args.headed:
        command.append("--headed")
    return command


def install_autostart(args: argparse.Namespace) -> None:
    if args.max_download_mb <= 0:
        raise SystemExit("--max-download-mb must be positive")
    _read_token(args.token_file)
    state = load_state()
    if state is not None and process_is_running(state.pid) and process_is_owned(state.pid):
        stop_owned_process(state)
    ensure_directories()
    try:
        changed = autostart.install(
            _service_arguments(args),
            working_directory=Path(__file__).resolve().parents[2],
            force=args.force,
        )
    except FileExistsError as exc:
        raise SystemExit(f"{exc}; pass --force to replace it") from exc
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"Could not install RetroBridge autostart: {exc}") from exc
    print("RetroBridge autostart installed" if changed else "RetroBridge autostart already installed")
    print(f"Login service: {autostart.location()}")
    print(f"Log: {LOG_FILE}")


def remove_autostart() -> None:
    try:
        removed = autostart.remove()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"Could not remove RetroBridge autostart: {exc}") from exc
    state = load_state()
    if state is not None:
        if process_is_running(state.pid) and process_is_owned(state.pid):
            stop_owned_process(state)
        elif not process_is_running(state.pid):
            remove_state_if_owned(state.pid)
    print("RetroBridge autostart removed" if removed else "RetroBridge autostart was not installed")


def show_autostart_status(as_json: bool) -> None:
    payload = {
        "installed": autostart.installed(),
        "enabled": autostart.enabled(),
        "loaded": autostart.loaded(),
        "executable_available": (
            autostart.executable_is_available() if autostart.installed() else None
        ),
        "location": autostart.location(),
    }
    if as_json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print("RetroBridge autostart is installed" if payload["installed"] else "RetroBridge autostart is not installed")
        print(f"Enabled: {payload['enabled']}")
        print(f"Loaded: {payload['loaded']}")
        if payload["executable_available"] is not None:
            print(f"Executable available: {payload['executable_available']}")
        print(f"Login service: {payload['location']}")


def configure_logging(managed: bool, *, echo_to_console: bool = False) -> None:
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    if not managed:
        logging.basicConfig(level=logging.INFO, format=formatter._fmt)
        return
    ensure_directories()
    handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    if echo_to_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        root.addHandler(console_handler)
    root.setLevel(logging.INFO)


def console_banner(
    host: str,
    port: int,
    download_directory: Path,
    log_file: Path = LOG_FILE,
) -> str:
    guest_endpoint = (
        f"10.0.2.2:{port} (from the 86Box guest)"
        if host == "127.0.0.1"
        else f"{host}:{port}"
    )
    return textwrap.dedent(
        f"""
             ______________________________________
            /  RETROBRIDGE 98                     /|
           /______________________________________/ |
           |  [ modern web ] === [ Windows 98 ]  | |
           |______________________________________|/

           Ready to bridge the Windows 98 browser.

           Listening : {host}:{port}
           Guest     : {guest_endpoint}
           Downloads : {download_directory.expanduser().resolve()}
           Log       : {log_file}

           Waiting for the guest to connect...
           Press Ctrl+C to stop RetroBridge safely.
        """
    ).strip()


def prepare_console_launch() -> None:
    state = load_state()
    if state is None:
        return
    if process_is_running(state.pid) and process_is_owned(state.pid):
        raise SystemExit(f"RetroBridge is already running as PID {state.pid}")
    if process_is_running(state.pid):
        raise SystemExit(
            f"RetroBridge state refers to active unrelated PID {state.pid}; "
            f"remove stale state only after checking {STATE_FILE}"
        )
    remove_state_if_owned(state.pid)


async def run_managed_server(server: RetroBridgeServer) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    signal_handler_installed = False
    previous_handler: object | None = None
    try:
        loop.add_signal_handler(signal.SIGTERM, stop.set)
        signal_handler_installed = True
    except NotImplementedError:
        previous_handler = signal.signal(
            signal.SIGTERM,
            lambda _signum, _frame: loop.call_soon_threadsafe(stop.set),
        )
    service = asyncio.create_task(server.serve())
    stopped = asyncio.create_task(stop.wait())
    try:
        done, _ = await asyncio.wait((service, stopped), return_when=asyncio.FIRST_COMPLETED)
        if service in done:
            await service
            return
        service.cancel()
        await server.shutdown()
        await asyncio.gather(service, return_exceptions=True)
    finally:
        if signal_handler_installed:
            loop.remove_signal_handler(signal.SIGTERM)
        elif previous_handler is not None:
            signal.signal(signal.SIGTERM, previous_handler)
        stopped.cancel()
        await asyncio.gather(stopped, return_exceptions=True)


async def doctor() -> None:
    session = ChromeSession(320, 240, max_fps=5)
    try:
        await session.start()
        frame = await asyncio.wait_for(session.next_frame(), timeout=15)
        await session.ack_cdp(frame.cdp_session_id)
        print(
            f"Chrome smoke test passed: {frame.frame.width}x{frame.frame.height}, "
            f"{len(frame.frame.pixels)} BGR24 bytes"
        )
    finally:
        await session.close()


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "pair":
        pair(
            args.token_file,
            args.guest_ini,
            args.force,
            args.server,
            args.port,
            args.as_json,
        )
        return
    if args.command == "config":
        try:
            if args.config_command == "show":
                show_config(args.settings_file)
            elif args.config_command == "validate":
                validate_config(args.json_input)
            else:
                apply_config(args.json_input, args.settings_file)
        except SettingsValidationError as exc:
            _emit_json(False, errors=exc.issues)
            raise SystemExit(2) from None
        except (OSError, UnicodeError) as exc:
            _emit_json(
                False,
                errors=[
                    {
                        "code": "settings_invalid",
                        "field": "settings",
                        "message": str(exc),
                    }
                ],
            )
            raise SystemExit(2) from None
        return
    if args.command == "browsers" and args.browsers_command == "detect":
        show_browsers()
        return
    if args.command == "diagnostics":
        show_diagnostics(args.settings_file)
        return
    try:
        ensure_supported_runtime()
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    if args.command == "doctor":
        asyncio.run(doctor())
        return
    if args.command == "browsers":
        try:
            sign_in_browser(args.mode)
        except BrowserSelectionError as exc:
            _emit_json(
                False,
                errors=[{"code": exc.code, "field": "browser.mode", "message": str(exc)}],
            )
            raise SystemExit(2) from None
        return
    browser_selection = None
    if args.command in {"serve", "console", "start"} or (
        args.command == "autostart" and args.autostart_command == "install"
    ):
        browser_selection = apply_runtime_settings(args)
    if args.command == "start":
        start_managed(args)
        return
    if args.command == "stop":
        stop_managed(args.as_json)
        return
    if args.command == "status":
        show_status(args.as_json)
        return
    if args.command == "logs":
        show_logs(args.lines)
        return
    if args.command == "autostart":
        if args.autostart_command == "install":
            install_autostart(args)
        elif args.autostart_command == "remove":
            remove_autostart()
        else:
            show_autostart_status(args.as_json)
        return
    console_mode = args.command == "console"
    if console_mode:
        prepare_console_launch()
    configure_logging(args.managed, echo_to_console=console_mode)
    if args.test_pattern and args.self_test:
        raise SystemExit("--test-pattern and --self-test cannot be combined")
    if args.max_download_mb <= 0:
        raise SystemExit("--max-download-mb must be positive")
    factory = TestPatternSession if args.test_pattern else None
    if args.self_test:
        factory = partial(
            ChromeSession,
            self_test=True,
            download_dir=args.download_dir,
            max_download_bytes=args.max_download_mb * 1024 * 1024,
        )
    elif not args.test_pattern:
        factory = partial(
            ChromeSession,
            download_dir=args.download_dir,
            max_download_bytes=args.max_download_mb * 1024 * 1024,
            browser_mode=args.browser_mode,
            executable_path=getattr(browser_selection, "executable", None),
            profile_dir=getattr(browser_selection, "profile_directory", None),
        )
    kwargs = {}
    if factory is not None:
        kwargs["session_factory"] = factory
    server = RetroBridgeServer(
        _read_token(args.token_file),
        host=args.listen,
        port=args.port,
        headed=args.headed,
        connection_status=(
            lambda listening, connected, peer: write_connection_state(
                listening=listening, connected=connected, peer=peer
            )
            if args.managed
            else None
        ),
        **kwargs,
    )
    if args.managed:
        ensure_directories()
        write_state(
            RuntimeState(
                pid=os.getpid(),
                host=args.listen,
                port=args.port,
                log_file=str(LOG_FILE),
                download_dir=str(args.download_dir.expanduser().resolve()),
                token_file=str(args.token_file.resolve()),
                self_test=args.self_test,
                test_pattern=args.test_pattern,
                browser_mode=args.browser_mode.value,
            )
        )
    if console_mode:
        print(
            console_banner(args.listen, args.port, args.download_dir),
            flush=True,
        )
    try:
        if args.managed:
            asyncio.run(run_managed_server(server))
        else:
            asyncio.run(server.serve())
    except KeyboardInterrupt:
        pass
    finally:
        if args.managed:
            remove_state_if_owned(os.getpid())
            clear_connection_state()
        if console_mode:
            print("\nRetroBridge stopped. It is safe to close this window.", flush=True)


if __name__ == "__main__":
    main()
