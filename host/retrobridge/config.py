"""Versioned, validated RetroBridge98 user settings."""

from __future__ import annotations

import ipaddress
import json
import os
from copy import deepcopy
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path, PureWindowsPath
from typing import Any

from .platforms import PATHS, host_kind, secure_directory, secure_file

SCHEMA_VERSION = 1
KNOWN_OLDER_SCHEMA_VERSIONS = frozenset({0})


class BrowserMode(StrEnum):
    PRIVATE_CHROMIUM = "private-chromium"
    EDGE_PERSONAL = "edge-personal"
    CHROME_PERSONAL = "chrome-personal"


@dataclass(frozen=True)
class BrowserSettings:
    mode: BrowserMode = BrowserMode.PRIVATE_CHROMIUM


@dataclass(frozen=True)
class NetworkSettings:
    listen: str = "127.0.0.1"
    port: int = 9866
    guest_address: str = "10.0.2.2"


@dataclass(frozen=True)
class DownloadSettings:
    directory: str
    max_megabytes: int = 100


@dataclass(frozen=True)
class StartupSettings:
    start_with_windows: bool = False


@dataclass(frozen=True)
class Settings:
    schema_version: int
    browser: BrowserSettings
    network: NetworkSettings
    downloads: DownloadSettings
    startup: StartupSettings


@dataclass(frozen=True)
class SettingsIssue:
    code: str
    field: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


class SettingsValidationError(ValueError):
    def __init__(self, issues: list[SettingsIssue]):
        super().__init__(issues[0].message if issues else "Invalid settings")
        self.issues = issues


def default_settings(*, start_with_windows: bool = False) -> Settings:
    return Settings(
        schema_version=SCHEMA_VERSION,
        browser=BrowserSettings(),
        network=NetworkSettings(),
        downloads=DownloadSettings(str(PATHS.download_directory)),
        startup=StartupSettings(start_with_windows),
    )


def settings_to_dict(settings: Settings) -> dict[str, object]:
    return {
        "schema_version": settings.schema_version,
        "browser": {"mode": settings.browser.mode.value},
        "network": asdict(settings.network),
        "downloads": asdict(settings.downloads),
        "startup": asdict(settings.startup),
    }


def _object(payload: Any, field: str, issues: list[SettingsIssue]) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    issues.append(SettingsIssue("settings_invalid", field, f"{field} must be an object"))
    return {}


def _integer(payload: Any, field: str, issues: list[SettingsIssue]) -> int | None:
    if isinstance(payload, int) and not isinstance(payload, bool):
        return payload
    issues.append(SettingsIssue("settings_invalid", field, f"{field} must be an integer"))
    return None


def settings_from_dict(payload: Any) -> Settings:
    payload, _, _ = migrate_settings_payload(payload)
    issues: list[SettingsIssue] = []
    root = _object(payload, "settings", issues)
    schema_version = _integer(root.get("schema_version"), "schema_version", issues)
    if schema_version is not None and schema_version != SCHEMA_VERSION:
        code = "unsupported_schema" if schema_version > SCHEMA_VERSION else "settings_invalid"
        issues.append(
            SettingsIssue(
                code,
                "schema_version",
                f"Settings schema {schema_version} is not supported by this version",
            )
        )

    browser = _object(root.get("browser"), "browser", issues)
    raw_mode = browser.get("mode")
    try:
        mode = BrowserMode(raw_mode)
    except (TypeError, ValueError):
        mode = BrowserMode.PRIVATE_CHROMIUM
        issues.append(
            SettingsIssue(
                "settings_invalid",
                "browser.mode",
                "Choose Private Chromium, Edge Personal, or Chrome Personal",
            )
        )

    network = _object(root.get("network"), "network", issues)
    listen = network.get("listen")
    if listen != "127.0.0.1":
        issues.append(
            SettingsIssue(
                "settings_invalid",
                "network.listen",
                "The settings application only permits the loopback listener 127.0.0.1",
            )
        )
        listen = "127.0.0.1"
    port = _integer(network.get("port"), "network.port", issues)
    if port is not None and not 1 <= port <= 65535:
        issues.append(
            SettingsIssue(
                "settings_invalid",
                "network.port",
                "Port must be between 1 and 65535",
            )
        )
    guest_address = network.get("guest_address")
    try:
        guest_address = str(ipaddress.IPv4Address(guest_address))
    except (ipaddress.AddressValueError, TypeError):
        issues.append(
            SettingsIssue(
                "settings_invalid",
                "network.guest_address",
                "Guest address must be an IPv4 address",
            )
        )
        guest_address = "10.0.2.2"

    downloads = _object(root.get("downloads"), "downloads", issues)
    directory = downloads.get("directory")
    if not isinstance(directory, str) or not directory.strip():
        issues.append(
            SettingsIssue(
                "settings_invalid",
                "downloads.directory",
                "Choose a download directory",
            )
        )
        directory = str(PATHS.download_directory)
    elif not (Path(directory).expanduser().is_absolute() or PureWindowsPath(directory).is_absolute()):
        issues.append(
            SettingsIssue(
                "settings_invalid",
                "downloads.directory",
                "Download directory must be an absolute path",
            )
        )
    max_megabytes = _integer(downloads.get("max_megabytes"), "downloads.max_megabytes", issues)
    if max_megabytes is not None and not 1 <= max_megabytes <= 10240:
        issues.append(
            SettingsIssue(
                "settings_invalid",
                "downloads.max_megabytes",
                "Download limit must be between 1 and 10240 MiB",
            )
        )

    startup = _object(root.get("startup"), "startup", issues)
    start_with_windows = startup.get("start_with_windows")
    if not isinstance(start_with_windows, bool):
        issues.append(
            SettingsIssue(
                "settings_invalid",
                "startup.start_with_windows",
                "Start with Windows must be true or false",
            )
        )
        start_with_windows = False

    if issues:
        raise SettingsValidationError(issues)
    assert schema_version is not None and port is not None and max_megabytes is not None
    return Settings(
        schema_version=schema_version,
        browser=BrowserSettings(mode),
        network=NetworkSettings(listen, port, guest_address),
        downloads=DownloadSettings(directory, max_megabytes),
        startup=StartupSettings(start_with_windows),
    )


def settings_from_json(text: str) -> Settings:
    return settings_from_dict(_parse_json(text))


def _parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SettingsValidationError(
            [SettingsIssue("settings_invalid", "settings", f"Settings JSON is invalid: {exc.msg}")]
        ) from exc


def migrate_settings_payload(payload: Any) -> tuple[Any, bool, int | None]:
    """Migrate a known legacy document in memory without weakening validation."""
    if not isinstance(payload, dict):
        return payload, False, None
    version = payload.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool):
        return payload, False, None
    if version not in KNOWN_OLDER_SCHEMA_VERSIONS:
        return payload, False, version
    if version == 0:
        migrated = deepcopy(payload)
        migrated["schema_version"] = SCHEMA_VERSION
        migrated.setdefault("startup", {"start_with_windows": False})
        return migrated, True, version
    return payload, False, version


def load_settings(path: Path = PATHS.settings_file) -> Settings | None:
    try:
        original = path.read_bytes()
    except FileNotFoundError:
        return None
    try:
        text = original.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SettingsValidationError(
            [SettingsIssue("settings_invalid", "settings", "Settings must use UTF-8 encoding")]
        ) from exc
    payload = _parse_json(text)
    migrated_payload, migrated, previous_version = migrate_settings_payload(payload)
    settings = settings_from_dict(migrated_payload)
    if migrated:
        assert previous_version is not None
        _backup_legacy_settings(original, path, previous_version)
        save_settings(settings, path)
    return settings


def _backup_legacy_settings(original: bytes, path: Path, version: int) -> Path:
    backup = path.with_name(f"{path.name}.schema-{version}.bak")
    if backup.exists():
        return backup
    secure_directory(path.parent)
    temporary = backup.with_suffix(f"{backup.suffix}.tmp")
    temporary.write_bytes(original)
    secure_file(temporary)
    try:
        temporary.replace(backup)
    finally:
        temporary.unlink(missing_ok=True)
    secure_file(backup)
    return backup


def save_settings(settings: Settings, path: Path = PATHS.settings_file) -> None:
    # Re-validate the serialized representation so every write passes through the
    # same authoritative rules used by the CLI contract.
    settings = settings_from_dict(settings_to_dict(settings))
    secure_directory(path.parent)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(settings_to_dict(settings), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    secure_file(temporary)
    os.replace(temporary, path)
    secure_file(path)


def restore_settings_bytes(previous: bytes | None, path: Path = PATHS.settings_file) -> None:
    if previous is None:
        path.unlink(missing_ok=True)
        return
    secure_directory(path.parent)
    temporary = path.with_suffix(".rollback.tmp")
    temporary.write_bytes(previous)
    secure_file(temporary)
    os.replace(temporary, path)
    secure_file(path)


def settings_path_is_native(path: Path = PATHS.settings_file) -> bool:
    if host_kind() != "windows":
        return True
    rendered = str(path).casefold()
    return "\\\\wsl" not in rendered and not rendered.startswith("/mnt/")
