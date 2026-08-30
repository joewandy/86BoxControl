"""Platform-neutral opt-in login service management."""

from __future__ import annotations

import sys
from pathlib import Path

from . import launchd, windows_tasks
from .platforms import host_kind


def current_python() -> str:
    return str(Path(sys.executable).absolute())


def installed() -> bool:
    kind = host_kind()
    if kind == "macos":
        return launchd.installed()
    if kind == "windows":
        return windows_tasks.installed()
    return False


def loaded() -> bool:
    kind = host_kind()
    if kind == "macos":
        return launchd.loaded()
    if kind == "windows":
        return windows_tasks.running()
    return False


def enabled() -> bool:
    kind = host_kind()
    if kind == "macos":
        return launchd.installed()
    if kind == "windows":
        return windows_tasks.enabled()
    return False


def executable_is_available() -> bool:
    kind = host_kind()
    if kind == "macos":
        return launchd.executable_is_available()
    if kind == "windows":
        return windows_tasks.executable_is_available()
    return False


def install(
    program_arguments: list[str],
    *,
    working_directory: Path,
    force: bool = False,
) -> bool:
    kind = host_kind()
    if kind == "macos":
        payload = launchd.build_plist(program_arguments, working_directory=working_directory)
        changed = launchd.write_plist(payload, force=force)
        if force and launchd.loaded():
            launchd.bootout()
        launchd.bootstrap()
        launchd.kickstart(restart=True)
        return changed
    if kind == "windows":
        changed = windows_tasks.install(program_arguments, force=force)
        windows_tasks.start()
        return changed
    raise RuntimeError("Autostart is supported only on Windows and macOS")


def start() -> None:
    kind = host_kind()
    if kind == "macos":
        launchd.bootstrap()
        launchd.kickstart()
        return
    if kind == "windows":
        windows_tasks.start()
        return
    raise RuntimeError("Autostart is supported only on Windows and macOS")


def remove() -> bool:
    kind = host_kind()
    if kind == "macos":
        return launchd.remove()
    if kind == "windows":
        return windows_tasks.remove()
    return False


def location() -> str:
    kind = host_kind()
    if kind == "macos":
        return str(launchd.PLIST_PATH)
    if kind == "windows":
        return f"Task Scheduler: {windows_tasks.TASK_NAME}"
    return "unsupported"


def service_label() -> str:
    return "LaunchAgent" if host_kind() == "macos" else "scheduled task"
