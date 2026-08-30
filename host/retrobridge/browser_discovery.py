"""Windows browser discovery and dedicated RetroBridge profile ownership."""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Mapping

import psutil

from .config import BrowserMode
from .platforms import PATHS, host_kind, secure_directory


class BrowserSelectionError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class BrowserInfo:
    mode: BrowserMode
    name: str
    available: bool
    executable: str | None
    source: str

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["mode"] = self.mode.value
        return payload


@dataclass(frozen=True)
class BrowserSelection:
    mode: BrowserMode
    executable: Path | None
    profile_directory: Path | None
    persistent: bool
    headed: bool


_BROWSER_NAMES = {
    BrowserMode.PRIVATE_CHROMIUM: "Private Chromium",
    BrowserMode.EDGE_PERSONAL: "Microsoft Edge Personal",
    BrowserMode.CHROME_PERSONAL: "Google Chrome Personal",
}


def profile_directory(mode: BrowserMode) -> Path | None:
    if mode is BrowserMode.EDGE_PERSONAL:
        return PATHS.browser_profile_directory / "edge-personal"
    if mode is BrowserMode.CHROME_PERSONAL:
        return PATHS.browser_profile_directory / "chrome-personal"
    return None


def _registry_candidates(executable_name: str) -> Iterable[tuple[Path, str]]:
    if host_kind() != "windows":
        return ()
    try:
        import winreg
    except ImportError:
        return ()
    candidates: list[tuple[Path, str]] = []
    key_name = rf"Software\Microsoft\Windows\CurrentVersion\App Paths\{executable_name}"
    for hive, hive_name in ((winreg.HKEY_CURRENT_USER, "HKCU"), (winreg.HKEY_LOCAL_MACHINE, "HKLM")):
        for view in (0, winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, key_name, 0, winreg.KEY_READ | view) as key:
                    value, _ = winreg.QueryValueEx(key, None)
            except OSError:
                continue
            if isinstance(value, str) and value:
                candidates.append((Path(value.strip('"')), f"registry:{hive_name}"))
    return candidates


def _filesystem_candidates(
    mode: BrowserMode,
    environ: Mapping[str, str],
) -> Iterable[tuple[Path, str]]:
    roots = {
        key: Path(value)
        for key in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")
        if (value := environ.get(key))
    }
    if mode is BrowserMode.EDGE_PERSONAL:
        suffix = Path("Microsoft/Edge/Application/msedge.exe")
    else:
        suffix = Path("Google/Chrome/Application/chrome.exe")
    return ((root / suffix, f"standard:{key}") for key, root in roots.items())


def _find_browser(
    mode: BrowserMode,
    *,
    environ: Mapping[str, str] | None = None,
) -> BrowserInfo:
    environ = os.environ if environ is None else environ
    executable_name = "msedge.exe" if mode is BrowserMode.EDGE_PERSONAL else "chrome.exe"
    candidates = [
        *_registry_candidates(executable_name),
        *_filesystem_candidates(mode, environ),
    ]
    seen: set[str] = set()
    for candidate, source in candidates:
        key = str(candidate).casefold()
        if key in seen:
            continue
        seen.add(key)
        if candidate.is_file():
            return BrowserInfo(mode, _BROWSER_NAMES[mode], True, str(candidate), source)
    return BrowserInfo(mode, _BROWSER_NAMES[mode], False, None, "not-found")


def detect_browsers(*, environ: Mapping[str, str] | None = None) -> list[BrowserInfo]:
    return [
        BrowserInfo(
            BrowserMode.PRIVATE_CHROMIUM,
            _BROWSER_NAMES[BrowserMode.PRIVATE_CHROMIUM],
            True,
            None,
            "playwright",
        ),
        _find_browser(BrowserMode.EDGE_PERSONAL, environ=environ),
        _find_browser(BrowserMode.CHROME_PERSONAL, environ=environ),
    ]


def profile_processes(profile: Path) -> list[int]:
    marker = f"--user-data-dir={profile}"
    normalized_marker = marker.casefold()
    found: list[int] = []
    for process in psutil.process_iter(("pid", "cmdline")):
        try:
            command = " ".join(process.info["cmdline"] or ())
            if normalized_marker in command.casefold():
                found.append(int(process.info["pid"]))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return found


def resolve_browser(mode: BrowserMode) -> BrowserSelection:
    if mode is BrowserMode.PRIVATE_CHROMIUM:
        return BrowserSelection(mode, None, None, False, False)
    info = next(item for item in detect_browsers() if item.mode is mode)
    if not info.available or info.executable is None:
        raise BrowserSelectionError(
            "browser_missing",
            f"{info.name} was not found. Install it or choose another browser.",
        )
    profile = profile_directory(mode)
    assert profile is not None
    active = profile_processes(profile)
    if active:
        raise BrowserSelectionError(
            "profile_locked",
            f"The dedicated {info.name} profile is already open. Close it and try again.",
        )
    return BrowserSelection(mode, Path(info.executable), profile, True, True)


def open_sign_in_profile(mode: BrowserMode) -> None:
    if mode is BrowserMode.PRIVATE_CHROMIUM:
        raise BrowserSelectionError(
            "settings_invalid",
            "Private Chromium does not keep a sign-in profile.",
        )
    selection = resolve_browser(mode)
    assert selection.executable is not None and selection.profile_directory is not None
    secure_directory(PATHS.browser_profile_directory)
    secure_directory(selection.profile_directory)
    command = [
        str(selection.executable),
        f"--user-data-dir={selection.profile_directory}",
        "--disable-extensions",
        "--no-first-run",
        "--new-window",
        "about:blank",
    ]
    options: dict[str, object] = {}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    process = subprocess.Popen(command, **options)
    observed = False
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if profile_processes(selection.profile_directory):
            observed = True
            break
        if process.poll() not in (None, 0):
            raise BrowserSelectionError(
                "browser_launch_failed",
                f"{_BROWSER_NAMES[mode]} exited before opening its dedicated profile.",
            )
        time.sleep(0.2)
    if not observed and not profile_processes(selection.profile_directory):
        raise BrowserSelectionError(
            "browser_launch_failed",
            f"{_BROWSER_NAMES[mode]} did not open its dedicated profile.",
        )
    while profile_processes(selection.profile_directory):
        time.sleep(0.5)
