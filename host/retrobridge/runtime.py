"""Managed native-host process state for the RetroBridge renderer."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import psutil

from .platforms import PATHS, secure_directory, secure_file

APP_SUPPORT = PATHS.application_support
LOG_DIRECTORY = PATHS.log_directory
STATE_FILE = PATHS.state_file
LOG_FILE = PATHS.log_file
TOKEN_FILE = PATHS.token_file
GUEST_INI_FILE = PATHS.guest_ini_file
DOWNLOAD_DIRECTORY = PATHS.download_directory
SETTINGS_FILE = PATHS.settings_file
CONNECTION_STATE_FILE = PATHS.connection_state_file
BROWSER_PROFILE_DIRECTORY = PATHS.browser_profile_directory


@dataclass(frozen=True)
class RuntimeState:
    pid: int
    host: str
    port: int
    log_file: str
    download_dir: str
    token_file: str
    self_test: bool = False
    test_pattern: bool = False
    browser_mode: str = "private-chromium"


@dataclass(frozen=True)
class ConnectionState:
    listening: bool
    connected: bool
    peer: str | None
    updated_at: float


def ensure_directories() -> None:
    secure_directory(APP_SUPPORT)
    secure_directory(LOG_DIRECTORY)


def write_state(state: RuntimeState, path: Path = STATE_FILE) -> None:
    secure_directory(path.parent)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(state), indent=2) + "\n", encoding="utf-8")
    secure_file(temporary)
    os.replace(temporary, path)
    secure_file(path)


def load_state(path: Path = STATE_FILE) -> RuntimeState | None:
    try:
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return RuntimeState(
            pid=int(payload["pid"]),
            host=str(payload["host"]),
            port=int(payload["port"]),
            log_file=str(payload["log_file"]),
            download_dir=str(payload["download_dir"]),
            token_file=str(payload["token_file"]),
            self_test=bool(payload.get("self_test", False)),
            test_pattern=bool(payload.get("test_pattern", False)),
            browser_mode=str(payload.get("browser_mode", "private-chromium")),
        )
    except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def write_connection_state(
    *,
    listening: bool,
    connected: bool,
    peer: str | None = None,
    path: Path = CONNECTION_STATE_FILE,
) -> None:
    secure_directory(path.parent)
    temporary = path.with_suffix(".tmp")
    payload = ConnectionState(listening, connected, peer, time.time())
    temporary.write_text(json.dumps(asdict(payload), indent=2) + "\n", encoding="utf-8")
    secure_file(temporary)
    os.replace(temporary, path)
    secure_file(path)


def load_connection_state(path: Path = CONNECTION_STATE_FILE) -> ConnectionState | None:
    try:
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return ConnectionState(
            listening=bool(payload["listening"]),
            connected=bool(payload["connected"]),
            peer=None if payload.get("peer") is None else str(payload["peer"]),
            updated_at=float(payload["updated_at"]),
        )
    except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def clear_connection_state(path: Path = CONNECTION_STATE_FILE) -> None:
    path.unlink(missing_ok=True)


def process_command(pid: int) -> str:
    try:
        return " ".join(psutil.Process(pid).cmdline())
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return ""


def process_is_owned(pid: int) -> bool:
    command = process_command(pid)
    if not command:
        return False

    normalized = command.casefold()
    return "retrobridge" in normalized and (
        " serve" in normalized or " console" in normalized
    )


def process_is_running(pid: int) -> bool:
    try:
        process = psutil.Process(pid)
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False


def descendant_pids(parent: int) -> list[int]:
    try:
        return [child.pid for child in psutil.Process(parent).children(recursive=True)]
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return []


def remove_state_if_owned(pid: int, path: Path = STATE_FILE) -> None:
    state = load_state(path)
    if state is not None and state.pid == pid:
        path.unlink(missing_ok=True)


def stop_owned_process(state: RuntimeState, timeout: float = 20.0) -> bool:
    if not process_is_running(state.pid):
        remove_state_if_owned(state.pid)
        return True
    if not process_is_owned(state.pid):
        raise RuntimeError(f"PID {state.pid} no longer belongs to RetroBridge")
    try:
        parent = psutil.Process(state.pid)
        children = parent.children(recursive=True)
        parent.terminate()
        _, alive = psutil.wait_procs([parent], timeout=timeout)
        if not alive:
            remove_state_if_owned(state.pid)
            return True
        targets = children + alive
        for process in reversed(targets):
            try:
                process.terminate()
            except psutil.NoSuchProcess:
                pass
        _, alive = psutil.wait_procs(targets, timeout=0.5)
        for process in reversed(alive):
            try:
                process.kill()
            except psutil.NoSuchProcess:
                pass
        psutil.wait_procs(alive, timeout=2)
    except psutil.NoSuchProcess:
        pass
    remove_state_if_owned(state.pid)
    return False
