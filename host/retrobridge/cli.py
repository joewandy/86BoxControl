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

from . import autostart
from .browser import ChromeSession, TestPatternSession
from .platforms import ensure_supported_runtime, secure_directory, secure_file
from .runtime import (
    DOWNLOAD_DIRECTORY,
    GUEST_INI_FILE,
    LOG_FILE,
    STATE_FILE,
    TOKEN_FILE,
    RuntimeState,
    ensure_directories,
    load_state,
    process_is_owned,
    process_is_running,
    remove_state_if_owned,
    stop_owned_process,
    write_state,
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
    print(f"Created host token: {token_path}")
    print(f"Created guest configuration: {ini_path}")


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
    subparsers.add_parser("stop", help="stop the managed renderer")
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
    autostart_subparsers.add_parser(
        "remove", help="stop and remove the per-user login service"
    )
    autostart_status = autostart_subparsers.add_parser(
        "status", help="show login-service installation status"
    )
    autostart_status.add_argument("--json", action="store_true", dest="as_json")
    return parser


def start_managed(args: argparse.Namespace) -> None:
    state = load_state()
    if state is not None and process_is_running(state.pid) and process_is_owned(state.pid):
        raise SystemExit(f"RetroBridge is already running as PID {state.pid}")
    if autostart.installed():
        if args.self_test or args.test_pattern or args.headed:
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
    )
    write_state(runtime)
    time.sleep(0.3)
    if process.poll() is not None:
        remove_state_if_owned(process.pid)
        raise SystemExit(f"RetroBridge failed to start; inspect {LOG_FILE}")
    print(f"RetroBridge started as PID {process.pid}")
    print(f"Log: {LOG_FILE}")


def stop_managed() -> None:
    state = load_state()
    if state is None:
        print("RetroBridge is not running")
        return
    graceful = stop_owned_process(state)
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
        "autostart_installed": autostart.installed(),
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
        "autostart_installed",
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
        pair(args.token_file, args.guest_ini, args.force, args.server, args.port)
        return
    try:
        ensure_supported_runtime()
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    if args.command == "doctor":
        asyncio.run(doctor())
        return
    if args.command == "start":
        start_managed(args)
        return
    if args.command == "stop":
        stop_managed()
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
        )
    kwargs = {}
    if factory is not None:
        kwargs["session_factory"] = factory
    server = RetroBridgeServer(
        _read_token(args.token_file),
        host=args.listen,
        port=args.port,
        headed=args.headed,
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
        if console_mode:
            print("\nRetroBridge stopped. It is safe to close this window.", flush=True)


if __name__ == "__main__":
    main()
