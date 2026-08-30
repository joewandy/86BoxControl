"""Opt-in per-user LaunchAgent management for RetroBridge98."""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import Any

from .runtime import LOG_DIRECTORY, ensure_directories

LABEL = "com.retrobridge98.renderer"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
LAUNCHER_LOG_FILE = LOG_DIRECTORY / "launcher.log"


def domain() -> str:
    return f"gui/{os.getuid()}"


def target() -> str:
    return f"{domain()}/{LABEL}"


def build_plist(
    program_arguments: list[str],
    *,
    working_directory: Path,
) -> dict[str, Any]:
    if not program_arguments or not Path(program_arguments[0]).is_absolute():
        raise ValueError("LaunchAgent executable must be an absolute path")
    if not working_directory.is_absolute():
        raise ValueError("LaunchAgent working directory must be absolute")
    return {
        "Label": LABEL,
        "ProgramArguments": program_arguments,
        "WorkingDirectory": str(working_directory),
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ProcessType": "Background",
        "ThrottleInterval": 5,
        "StandardOutPath": str(LAUNCHER_LOG_FILE),
        "StandardErrorPath": str(LAUNCHER_LOG_FILE),
    }


def write_plist(payload: dict[str, Any], *, force: bool = False, path: Path = PLIST_PATH) -> bool:
    encoded = plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=True)
    try:
        existing = path.read_bytes()
    except FileNotFoundError:
        existing = None
    if existing == encoded:
        return False
    if existing is not None and not force:
        raise FileExistsError(f"LaunchAgent already exists with different settings: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(encoded)
    temporary.chmod(0o644)
    os.replace(temporary, path)
    return True


def installed(path: Path = PLIST_PATH) -> bool:
    return path.is_file()


def loaded() -> bool:
    result = subprocess.run(
        ["launchctl", "print", target()],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def bootstrap(path: Path = PLIST_PATH) -> None:
    ensure_directories()
    if loaded():
        return
    subprocess.run(["launchctl", "bootstrap", domain(), str(path)], check=True)


def bootout() -> None:
    if loaded():
        subprocess.run(["launchctl", "bootout", target()], check=True)


def kickstart(*, restart: bool = False) -> None:
    command = ["launchctl", "kickstart"]
    if restart:
        command.append("-k")
    command.append(target())
    subprocess.run(command, check=True)


def remove(path: Path = PLIST_PATH) -> bool:
    bootout()
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    return True


def executable_is_available(path: Path = PLIST_PATH) -> bool:
    try:
        payload = plistlib.loads(path.read_bytes())
        executable = Path(payload["ProgramArguments"][0])
    except (FileNotFoundError, KeyError, TypeError, ValueError, plistlib.InvalidFileException):
        return False
    return executable.is_file() and os.access(executable, os.X_OK)


def current_python() -> str:
    # Do not resolve the virtualenv symlink: its directory selects the environment
    # that contains RetroBridge and its dependencies.
    return str(Path(sys.executable).absolute())
