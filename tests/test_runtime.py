from dataclasses import replace
from pathlib import Path

from retrobridge.runtime import RuntimeState, load_state, process_is_owned, write_state


def sample_state() -> RuntimeState:
    return RuntimeState(
        pid=123,
        host="127.0.0.1",
        port=9866,
        log_file="/tmp/retrobridge.log",
        download_dir="/tmp/downloads",
        token_file="/tmp/token",
    )


def test_runtime_state_round_trip_is_private_and_atomic(tmp_path: Path) -> None:
    path = tmp_path / "state" / "runtime.json"
    write_state(sample_state(), path)
    assert load_state(path) == sample_state()
    assert path.stat().st_mode & 0o777 == 0o600
    assert not path.with_suffix(".tmp").exists()


def test_invalid_runtime_state_is_treated_as_absent(tmp_path: Path) -> None:
    path = tmp_path / "runtime.json"
    path.write_text("not json", encoding="utf-8")
    assert load_state(path) is None


def test_legacy_runtime_state_defaults_to_normal_mode(tmp_path: Path) -> None:
    path = tmp_path / "runtime.json"
    path.write_text(
        '{"pid":123,"started_at":1,"host":"127.0.0.1","port":9866,'
        '"log_file":"/tmp/log","download_dir":"/tmp/downloads","token_file":"/tmp/token"}',
        encoding="utf-8",
    )
    state = load_state(path)
    assert state is not None
    assert not state.self_test
    assert not state.test_pattern


def test_runtime_state_preserves_test_pattern_mode(tmp_path: Path) -> None:
    path = tmp_path / "runtime.json"
    state = replace(sample_state(), test_pattern=True)
    write_state(state, path)
    assert load_state(path) == state


def test_process_ownership_accepts_retrobridge_serve_and_console(monkeypatch) -> None:
    monkeypatch.setattr(
        "retrobridge.runtime.process_command",
        lambda pid: "/venv/bin/python -m retrobridge.cli serve --managed",
    )
    assert process_is_owned(42)

    monkeypatch.setattr(
        "retrobridge.runtime.process_command",
        lambda pid: r'"C:\Program Files\RetroBridge98\retrobridge.exe" console',
    )
    assert process_is_owned(42)

    monkeypatch.setattr("retrobridge.runtime.process_command", lambda pid: "Google Chrome")
    assert not process_is_owned(42)
