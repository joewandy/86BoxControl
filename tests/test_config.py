import json
from pathlib import Path

import pytest

from retrobridge.config import (
    BrowserMode,
    SettingsValidationError,
    default_settings,
    load_settings,
    save_settings,
    settings_from_dict,
    settings_to_dict,
)


def test_settings_round_trip_is_private_and_secret_free(tmp_path: Path) -> None:
    path = tmp_path / "state" / "settings.json"
    settings = default_settings()
    save_settings(settings, path)
    assert load_settings(path) == settings
    assert path.stat().st_mode & 0o777 == 0o600
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["browser"]["mode"] == BrowserMode.PRIVATE_CHROMIUM.value
    assert "token" not in path.read_text(encoding="utf-8").casefold()


def test_settings_reject_non_loopback_listener() -> None:
    payload = settings_to_dict(default_settings())
    payload["network"]["listen"] = "0.0.0.0"  # type: ignore[index]
    with pytest.raises(SettingsValidationError) as raised:
        settings_from_dict(payload)
    assert raised.value.issues[0].field == "network.listen"


def test_settings_reject_unknown_future_schema() -> None:
    payload = settings_to_dict(default_settings())
    payload["schema_version"] = 99
    with pytest.raises(SettingsValidationError) as raised:
        settings_from_dict(payload)
    assert any(issue.code == "unsupported_schema" for issue in raised.value.issues)


def test_loading_known_schema_zero_backs_up_then_migrates(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    payload = settings_to_dict(default_settings())
    payload["schema_version"] = 0
    payload.pop("startup")
    original = (json.dumps(payload) + "\n").encode()
    path.write_bytes(original)

    migrated = load_settings(path)

    assert migrated is not None
    assert migrated.schema_version == 1
    assert not migrated.startup.start_with_windows
    assert (tmp_path / "settings.json.schema-0.bak").read_bytes() == original
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 1
    assert (tmp_path / "settings.json.schema-0.bak").stat().st_mode & 0o777 == 0o600


def test_loading_future_schema_never_overwrites_it(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    payload = settings_to_dict(default_settings())
    payload["schema_version"] = 99
    original = json.dumps(payload, indent=2).encode()
    path.write_bytes(original)

    with pytest.raises(SettingsValidationError):
        load_settings(path)

    assert path.read_bytes() == original
    assert not list(tmp_path.glob("*.bak"))


def test_settings_save_uses_atomic_replace(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    replacements: list[tuple[Path, Path]] = []
    real_replace = __import__("os").replace

    def recording_replace(source: str | Path, destination: str | Path) -> None:
        replacements.append((Path(source), Path(destination)))
        real_replace(source, destination)

    monkeypatch.setattr("retrobridge.config.os.replace", recording_replace)
    save_settings(default_settings(), path)

    assert replacements == [(path.with_suffix(".tmp"), path)]
    assert load_settings(path) == default_settings()


def test_settings_accept_distinct_personal_modes() -> None:
    payload = settings_to_dict(default_settings())
    payload["browser"]["mode"] = "edge-personal"  # type: ignore[index]
    assert settings_from_dict(payload).browser.mode is BrowserMode.EDGE_PERSONAL
    payload["browser"]["mode"] = "chrome-personal"  # type: ignore[index]
    assert settings_from_dict(payload).browser.mode is BrowserMode.CHROME_PERSONAL
