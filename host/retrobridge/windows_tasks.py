"""Opt-in per-user Task Scheduler management for RetroBridge98."""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path, PureWindowsPath

from .platforms import PATHS, secure_directory, secure_file

TASK_NAME = "RetroBridge98 Renderer"

_REGISTER_TASK_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$action = New-ScheduledTaskAction `
    -Execute $env:RETROBRIDGE_TASK_EXECUTABLE `
    -Argument $env:RETROBRIDGE_TASK_ARGUMENTS
$trigger = New-ScheduledTaskTrigger `
    -AtLogOn `
    -User $env:RETROBRIDGE_TASK_USER
$principal = New-ScheduledTaskPrincipal `
    -UserId $env:RETROBRIDGE_TASK_USER `
    -LogonType Interactive `
    -RunLevel Limited
Register-ScheduledTask `
    -TaskName $env:RETROBRIDGE_TASK_NAME `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Description 'RetroBridge98 native renderer' `
    -Force | Out-Null
"""

_UNREGISTER_TASK_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Unregister-ScheduledTask `
    -TaskName $env:RETROBRIDGE_TASK_NAME `
    -Confirm:$false
"""


def _run(*arguments: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["schtasks.exe", *arguments],
        check=check,
        capture_output=True,
        text=True,
    )


def _run_powershell(
    script: str,
    *,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    process_environment = os.environ.copy()
    process_environment.update(environment)
    return subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        check=True,
        capture_output=True,
        text=True,
        env=process_environment,
    )


def _register_task(program_arguments: list[str], current_user: str) -> None:
    _run_powershell(
        _REGISTER_TASK_SCRIPT,
        environment={
            "RETROBRIDGE_TASK_EXECUTABLE": program_arguments[0],
            "RETROBRIDGE_TASK_ARGUMENTS": subprocess.list2cmdline(
                program_arguments[1:]
            ),
            "RETROBRIDGE_TASK_USER": current_user,
            "RETROBRIDGE_TASK_NAME": TASK_NAME,
        },
    )


def _unregister_task() -> None:
    _run_powershell(
        _UNREGISTER_TASK_SCRIPT,
        environment={"RETROBRIDGE_TASK_NAME": TASK_NAME},
    )


def installed() -> bool:
    return _run("/Query", "/TN", TASK_NAME).returncode == 0


def running() -> bool:
    result = _run("/Query", "/TN", TASK_NAME, "/FO", "CSV", "/NH")
    if result.returncode != 0:
        return False
    try:
        row = next(csv.reader([result.stdout.strip()]))
    except (StopIteration, csv.Error):
        return False
    return len(row) >= 3 and row[2].strip().casefold() == "running"


def _desired_payload(program_arguments: list[str]) -> dict[str, object]:
    return {"task_name": TASK_NAME, "program_arguments": program_arguments}


def _load_payload(path: Path = PATHS.autostart_config_file) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def executable_is_available(path: Path = PATHS.autostart_config_file) -> bool:
    payload = _load_payload(path)
    arguments = payload.get("program_arguments") if payload else None
    return (
        isinstance(arguments, list)
        and bool(arguments)
        and isinstance(arguments[0], str)
        and Path(arguments[0]).is_file()
    )


def install(
    program_arguments: list[str],
    *,
    force: bool = False,
    config_path: Path = PATHS.autostart_config_file,
) -> bool:
    if not program_arguments or not (
        Path(program_arguments[0]).is_absolute()
        or PureWindowsPath(program_arguments[0]).is_absolute()
    ):
        raise ValueError("Task Scheduler executable must be an absolute path")
    desired = _desired_payload(program_arguments)
    existing = _load_payload(config_path)
    if installed() and existing == desired:
        return False
    if installed() and not force:
        raise FileExistsError("RetroBridge Task Scheduler entry already has different settings")
    current_user = "\\".join(
        part
        for part in (os.environ.get("USERDOMAIN"), os.environ.get("USERNAME"))
        if part
    )
    if not current_user:
        raise RuntimeError("Could not determine the current Windows user")
    _register_task(program_arguments, current_user)
    secure_directory(config_path.parent)
    temporary = config_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(desired, indent=2) + "\n", encoding="utf-8")
    secure_file(temporary)
    os.replace(temporary, config_path)
    secure_file(config_path)
    return True


def start() -> None:
    _run("/Run", "/TN", TASK_NAME, check=True)


def stop() -> None:
    if running():
        _run("/End", "/TN", TASK_NAME, check=True)


def remove(config_path: Path = PATHS.autostart_config_file) -> bool:
    if not installed():
        config_path.unlink(missing_ok=True)
        return False
    stop()
    _unregister_task()
    config_path.unlink(missing_ok=True)
    return True


def run_configured(config_path: Path = PATHS.autostart_config_file) -> int:
    payload = _load_payload(config_path)
    arguments = payload.get("program_arguments") if payload else None
    if not isinstance(arguments, list) or not all(
        isinstance(argument, str) for argument in arguments
    ):
        raise RuntimeError(f"Invalid RetroBridge autostart configuration: {config_path}")
    return subprocess.run(arguments, check=False).returncode


if __name__ == "__main__":
    if sys.argv[1:] != ["run"]:
        raise SystemExit("Usage: python -m retrobridge.windows_tasks run")
    raise SystemExit(run_configured())
