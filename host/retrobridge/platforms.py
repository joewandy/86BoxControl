"""Host-platform paths and security helpers for RetroBridge98."""

from __future__ import annotations

import csv
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class RuntimePaths:
    application_support: Path
    log_directory: Path
    state_file: Path
    log_file: Path
    token_file: Path
    guest_ini_file: Path
    download_directory: Path
    autostart_config_file: Path


def host_kind(platform_name: str | None = None) -> str:
    platform_name = sys.platform if platform_name is None else platform_name
    if platform_name == "darwin":
        return "macos"
    if platform_name == "win32":
        return "windows"
    return "linux"


def runtime_paths(
    *,
    platform_name: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> RuntimePaths:
    environ = os.environ if environ is None else environ
    home = Path.home() if home is None else home
    kind = host_kind(platform_name)
    if kind == "macos":
        support = home / "Library" / "Application Support" / "RetroBridge98"
        logs = home / "Library" / "Logs" / "RetroBridge98"
    elif kind == "windows":
        local_app_data = environ.get("LOCALAPPDATA")
        support = (
            Path(local_app_data) / "RetroBridge98"
            if local_app_data
            else home / "AppData" / "Local" / "RetroBridge98"
        )
        logs = support / "Logs"
    else:
        state_home = Path(environ.get("XDG_STATE_HOME", home / ".local" / "state"))
        support = state_home / "RetroBridge98"
        logs = support / "logs"
    return RuntimePaths(
        application_support=support,
        log_directory=logs,
        state_file=support / "runtime.json",
        log_file=logs / "retrobridge.log",
        token_file=support / "retrobridge.token",
        guest_ini_file=support / "pairing" / "retrobridge.ini",
        download_directory=home / "Downloads" / "RetroBridge98",
        autostart_config_file=support / "autostart.json",
    )


PATHS = runtime_paths()


def ensure_supported_runtime(platform_name: str | None = None) -> None:
    if host_kind(platform_name) == "linux":
        raise RuntimeError(
            "The live RetroBridge renderer must run natively on Windows or macOS. "
            "Use WSL/Linux only for source development, tests, and guest-media builds."
        )


def _windows_current_sid() -> str:
    result = subprocess.run(
        ["whoami.exe", "/user", "/fo", "csv", "/nh"],
        check=True,
        capture_output=True,
        text=True,
    )
    row = next(csv.reader([result.stdout.strip()]))
    if len(row) < 2 or not row[1].startswith("S-1-"):
        raise RuntimeError("Could not determine the current Windows user SID")
    return row[1]


def _apply_windows_acl(path: Path, *, directory: bool) -> None:
    suffix = "(OI)(CI)F" if directory else "F"
    grants = [
        f"*{_windows_current_sid()}:{suffix}",
        f"*S-1-5-18:{suffix}",
        f"*S-1-5-32-544:{suffix}",
    ]
    subprocess.run(
        [
            "icacls.exe",
            str(path),
            "/inheritance:r",
            "/grant:r",
            *grants,
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def secure_directory(path: Path, *, platform_name: str | None = None) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if host_kind(platform_name) == "windows":
        _apply_windows_acl(path, directory=True)
    else:
        path.chmod(0o700)


def secure_file(path: Path, *, platform_name: str | None = None) -> None:
    if host_kind(platform_name) == "windows":
        _apply_windows_acl(path, directory=False)
    else:
        path.chmod(0o600)
