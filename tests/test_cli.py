from pathlib import Path
import json

import pytest

from types import SimpleNamespace

from retrobridge import cli
from retrobridge.cli import build_parser, pair
from retrobridge.config import default_settings, save_settings, settings_to_dict


def test_pair_creates_matching_untracked_credentials(tmp_path: Path) -> None:
    token_file = tmp_path / "output" / "retrobridge.token"
    ini_file = tmp_path / "media" / "RETROBRIDGE.INI"
    pair(token_file, ini_file, False)
    token = token_file.read_text(encoding="ascii").strip()
    assert len(token) == 32
    assert token in ini_file.read_text(encoding="ascii")
    assert "Server=10.0.2.2" in ini_file.read_text(encoding="ascii")
    assert "Port=9866" in ini_file.read_text(encoding="ascii")
    assert token_file.stat().st_mode & 0o777 == 0o600


def test_pair_refuses_to_rotate_implicitly(tmp_path: Path) -> None:
    token_file = tmp_path / "token"
    ini_file = tmp_path / "config.ini"
    pair(token_file, ini_file, False)
    with pytest.raises(SystemExit, match="Refusing to overwrite"):
        pair(token_file, ini_file, False)


def test_pair_accepts_guest_reachable_server_address(tmp_path: Path) -> None:
    token_file = tmp_path / "token"
    ini_file = tmp_path / "config.ini"
    pair(token_file, ini_file, False, "192.0.2.10")
    assert "Server=192.0.2.10" in ini_file.read_text(encoding="ascii")


def test_pair_accepts_guest_reachable_port(tmp_path: Path) -> None:
    token_file = tmp_path / "token"
    ini_file = tmp_path / "config.ini"
    pair(token_file, ini_file, False, port=19866)
    assert "Port=19866" in ini_file.read_text(encoding="ascii")


def test_pair_cli_exposes_guest_endpoint() -> None:
    args = build_parser().parse_args(
        ["pair", "--server", "192.0.2.10", "--port", "19866"]
    )
    assert (args.server, args.port) == ("192.0.2.10", 19866)


@pytest.mark.parametrize("port", [0, 65536])
def test_pair_rejects_invalid_port(tmp_path: Path, port: int) -> None:
    with pytest.raises(SystemExit, match="between 1 and 65535"):
        pair(tmp_path / "token", tmp_path / "config.ini", False, port=port)


def test_pair_rejects_server_that_win98_inet_addr_cannot_use(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="IPv4"):
        pair(tmp_path / "token", tmp_path / "config.ini", False, "renderer.local")


def test_managed_start_can_enable_deterministic_self_test_mode() -> None:
    args = build_parser().parse_args(["start", "--self-test"])
    assert args.command == "start"
    assert args.self_test


def test_console_mode_is_visible_managed_normal_mode() -> None:
    args = build_parser().parse_args(["console"])
    assert args.managed
    assert not args.self_test
    assert not args.test_pattern
    assert args.listen == "127.0.0.1"
    assert args.port == 9866


def test_console_banner_explains_endpoints_paths_and_shutdown(tmp_path: Path) -> None:
    banner = cli.console_banner(
        "127.0.0.1",
        9866,
        tmp_path / "Downloads",
        tmp_path / "retrobridge.log",
    )
    assert "RETROBRIDGE 98" in banner
    assert "127.0.0.1:9866" in banner
    assert "10.0.2.2:9866" in banner
    assert str((tmp_path / "Downloads").resolve()) in banner
    assert str(tmp_path / "retrobridge.log") in banner
    assert "Ctrl+C" in banner


def test_managed_start_can_enable_framebuffer_test_pattern() -> None:
    args = build_parser().parse_args(["start", "--test-pattern"])
    assert args.command == "start"
    assert args.test_pattern


def test_managed_start_modes_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["start", "--self-test", "--test-pattern"])


def test_autostart_install_is_explicit_and_defaults_to_safe_listener() -> None:
    args = build_parser().parse_args(["autostart", "install"])
    assert args.autostart_command == "install"
    assert args.listen == "127.0.0.1"
    assert not args.force


def test_autostart_status_can_be_machine_readable() -> None:
    args = build_parser().parse_args(["autostart", "status", "--json"])
    assert args.autostart_command == "status"
    assert args.as_json


def test_autostart_remove_stops_a_lingering_owned_process(monkeypatch) -> None:
    state = SimpleNamespace(pid=1234)
    stopped: list[object] = []
    monkeypatch.setattr(cli.autostart, "remove", lambda: True)
    monkeypatch.setattr(cli, "load_state", lambda: state)
    monkeypatch.setattr(cli, "process_is_running", lambda _pid: True)
    monkeypatch.setattr(cli, "process_is_owned", lambda _pid: True)
    monkeypatch.setattr(cli, "stop_owned_process", stopped.append)
    cli.remove_autostart()
    assert stopped == [state]


def test_enabled_autostart_refuses_to_misrepresent_qa_mode(monkeypatch) -> None:
    args = build_parser().parse_args(["start", "--test-pattern"])
    monkeypatch.setattr(cli, "load_state", lambda: None)
    monkeypatch.setattr(cli.autostart, "enabled", lambda: True)
    with pytest.raises(SystemExit, match="login service owns normal renderer settings"):
        cli.start_managed(args)


def test_machine_readable_setup_commands_are_exposed() -> None:
    config = build_parser().parse_args(["config", "show", "--json"])
    browsers = build_parser().parse_args(["browsers", "detect", "--json"])
    diagnostics = build_parser().parse_args(["diagnostics", "--json"])
    assert config.config_command == "show"
    assert browsers.browsers_command == "detect"
    assert diagnostics.as_json


def test_missing_config_returns_first_run_defaults(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(cli.autostart, "installed", lambda: False)
    cli.show_config(tmp_path / "settings.json")
    payload = json.loads(capsys.readouterr().out)
    assert not payload["ok"]
    assert payload["errors"][0]["code"] == "settings_missing"
    assert payload["data"]["settings"]["browser"]["mode"] == "private-chromium"
    assert not payload["data"]["settings"]["startup"]["start_with_windows"]


def test_config_validation_is_machine_readable(monkeypatch, tmp_path, capsys) -> None:
    payload = json.dumps(settings_to_dict(default_settings()))
    source = tmp_path / "settings-input.json"
    source.write_text(payload, encoding="utf-8")
    cli.validate_config(str(source))
    response = json.loads(capsys.readouterr().out)
    assert response["ok"]
    assert response["contract_version"] == 1


def test_config_apply_keeps_fresh_autostart_off(monkeypatch, tmp_path, capsys) -> None:
    settings_path = tmp_path / "settings.json"
    source = tmp_path / "input.json"
    source.write_text(json.dumps(settings_to_dict(default_settings())), encoding="utf-8")
    monkeypatch.setattr(cli.autostart, "installed", lambda: False)

    cli.apply_config(str(source), settings_path)

    response = json.loads(capsys.readouterr().out)
    assert response["ok"]
    assert not response["data"]["settings"]["startup"]["start_with_windows"]
    assert settings_path.is_file()


def test_config_apply_rolls_back_when_autostart_reconciliation_fails(
    monkeypatch, tmp_path
) -> None:
    settings_path = tmp_path / "settings.json"
    save_settings(default_settings(), settings_path)
    original = settings_path.read_bytes()
    payload = settings_to_dict(default_settings())
    payload["startup"]["start_with_windows"] = True  # type: ignore[index]
    source = tmp_path / "input.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(cli, "host_kind", lambda: "windows")
    monkeypatch.setattr(
        cli.autostart,
        "install",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("scheduler unavailable")),
    )

    with pytest.raises(cli.SettingsValidationError) as raised:
        cli.apply_config(str(source), settings_path)

    assert raised.value.issues[0].code == "autostart_mismatch"
    assert settings_path.read_bytes() == original


def test_config_apply_never_overwrites_future_schema(monkeypatch, tmp_path) -> None:
    settings_path = tmp_path / "settings.json"
    future = settings_to_dict(default_settings())
    future["schema_version"] = 99
    original = json.dumps(future).encode()
    settings_path.write_bytes(original)
    source = tmp_path / "input.json"
    source.write_text(json.dumps(settings_to_dict(default_settings())), encoding="utf-8")
    monkeypatch.setattr(cli.autostart, "installed", lambda: False)

    with pytest.raises(cli.SettingsValidationError) as raised:
        cli.apply_config(str(source), settings_path)

    assert any(issue.code == "unsupported_schema" for issue in raised.value.issues)
    assert settings_path.read_bytes() == original


def test_runtime_settings_resolve_saved_private_mode(tmp_path) -> None:
    path = tmp_path / "settings.json"
    save_settings(default_settings(), path)
    args = build_parser().parse_args(["console", "--settings-file", str(path)])
    selection = cli.apply_runtime_settings(args)
    assert args.listen == "127.0.0.1"
    assert args.browser_mode.value == "private-chromium"
    assert not selection.persistent


def test_json_stop_reports_already_stopped(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "load_state", lambda: None)
    cli.stop_managed(as_json=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"]
    assert not payload["data"]["running"]
