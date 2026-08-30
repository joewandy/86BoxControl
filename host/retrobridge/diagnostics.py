"""Machine-readable setup and runtime diagnostics."""

from __future__ import annotations

import configparser
import socket
from pathlib import Path
from typing import Any

import psutil

from . import autostart
from .browser_discovery import detect_browsers
from .config import (
    Settings,
    SettingsValidationError,
    default_settings,
    load_settings,
    settings_to_dict,
)
from .runtime import (
    GUEST_INI_FILE,
    LOG_FILE,
    SETTINGS_FILE,
    TOKEN_FILE,
    load_connection_state,
    load_state,
    process_command,
    process_is_owned,
    process_is_running,
)


def pairing_status(
    *, token_path: Path = TOKEN_FILE, ini_path: Path = GUEST_INI_FILE
) -> dict[str, object]:
    token = None
    try:
        candidate = token_path.read_text(encoding="ascii").strip()
        if len(candidate) == 32 and all(character in "0123456789abcdef" for character in candidate):
            token = candidate
    except (FileNotFoundError, OSError, UnicodeError):
        pass
    parser = configparser.ConfigParser(interpolation=None)
    ini_token = None
    server = None
    port = None
    try:
        parser.read_string(ini_path.read_text(encoding="ascii"))
        section = parser["RetroBridge"]
        ini_token = section.get("Token")
        server = section.get("Server")
        port = section.getint("Port")
    except (FileNotFoundError, OSError, UnicodeError, configparser.Error, ValueError, KeyError):
        pass
    token_ready = token is not None
    ini_ready = ini_token is not None and server is not None and port is not None
    return {
        "ready": token_ready and ini_ready and token == ini_token,
        "token_present": token_ready,
        "guest_ini_present": ini_ready,
        "matching": token_ready and ini_ready and token == ini_token,
        "guest_server": server,
        "guest_port": port,
        "token_file": str(token_path),
        "guest_ini_file": str(ini_path),
    }


def port_status(host: str, port: int) -> dict[str, object]:
    listeners: list[dict[str, object]] = []
    try:
        connections = psutil.net_connections(kind="tcp")
    except (psutil.AccessDenied, OSError):
        connections = []
    for connection in connections:
        if connection.status != psutil.CONN_LISTEN or not connection.laddr:
            continue
        address = getattr(connection.laddr, "ip", connection.laddr[0])
        bound_port = getattr(connection.laddr, "port", connection.laddr[1])
        if int(bound_port) != port:
            continue
        pid = connection.pid
        owned = bool(pid and process_is_owned(pid))
        listeners.append(
            {
                "address": str(address),
                "pid": pid,
                "owned_by_retrobridge": owned,
                "command": process_command(pid) if pid else "",
            }
        )
    if not listeners:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.bind((host, port))
            available = True
        except OSError:
            available = False
        finally:
            probe.close()
    else:
        available = False
    return {
        "available": available,
        "listeners": listeners,
        "owned_by_retrobridge": bool(listeners) and all(
            bool(listener["owned_by_retrobridge"]) for listener in listeners
        ),
    }


def _settings_status(path: Path) -> tuple[Settings | None, dict[str, object]]:
    try:
        settings = load_settings(path)
    except SettingsValidationError as exc:
        return None, {
            "exists": path.is_file(),
            "valid": False,
            "path": str(path),
            "values": None,
            "errors": [issue.to_dict() for issue in exc.issues],
        }
    return settings, {
        "exists": settings is not None,
        "valid": settings is not None,
        "path": str(path),
        "values": settings_to_dict(settings) if settings else settings_to_dict(default_settings()),
        "errors": [],
    }


def diagnostics(path: Path = SETTINGS_FILE) -> dict[str, Any]:
    settings, settings_payload = _settings_status(path)
    effective = settings or default_settings(start_with_windows=autostart.enabled())
    state = load_state()
    running = bool(state and process_is_running(state.pid) and process_is_owned(state.pid))
    connection = load_connection_state()
    connected = bool(running and connection and connection.connected)
    browsers = detect_browsers()
    selected_browser = next(item for item in browsers if item.mode is effective.browser.mode)
    pairing = pairing_status()
    port = port_status(effective.network.listen, effective.network.port)
    autostart_installed = autostart.installed()
    autostart_enabled = autostart.enabled()
    checks = [
        {
            "code": "settings",
            "ok": bool(settings_payload["valid"]),
            "message": "Settings are valid" if settings_payload["valid"] else "Setup is required",
        },
        {
            "code": "browser",
            "ok": selected_browser.available,
            "message": (
                f"{selected_browser.name} is available"
                if selected_browser.available
                else f"{selected_browser.name} is not installed"
            ),
        },
        {
            "code": "pairing",
            "ok": pairing["ready"],
            "message": "Pairing is ready" if pairing["ready"] else "Pairing is incomplete",
        },
        {
            "code": "port",
            "ok": port["available"] or port["owned_by_retrobridge"],
            "message": (
                "Port is available"
                if port["available"]
                else "Port is owned by RetroBridge"
                if port["owned_by_retrobridge"]
                else "Port is occupied by another process"
            ),
        },
        {
            "code": "autostart",
            "ok": autostart_enabled == effective.startup.start_with_windows,
            "message": (
                "Windows startup matches the saved preference"
                if autostart_enabled == effective.startup.start_with_windows
                else "Windows startup does not match the saved preference"
            ),
        },
        {
            "code": "guest",
            "ok": connected,
            "message": "Windows 98 guest is connected" if connected else "Waiting for the Windows 98 guest",
            "informational": True,
        },
    ]
    return {
        "settings": settings_payload,
        "browsers": [browser.to_dict() for browser in browsers],
        "pairing": pairing,
        "port": port,
        "runtime": {
            "running": running,
            "pid": state.pid if state else None,
            "browser_mode": state.browser_mode if state else None,
            "log_file": state.log_file if state else str(LOG_FILE),
            "guest_connected": connected,
            "guest_peer": connection.peer if connected and connection else None,
        },
        "autostart": {
            "installed": autostart_installed,
            "enabled": autostart_enabled,
            "loaded": autostart.loaded(),
            "executable_available": (
                autostart.executable_is_available() if autostart_installed else None
            ),
            "location": autostart.location(),
        },
        "checks": checks,
    }
