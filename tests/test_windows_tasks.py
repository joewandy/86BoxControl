import json
from pathlib import Path
from types import SimpleNamespace

from retrobridge import windows_tasks


def test_task_action_is_registered_directly_without_schtasks_length_limit(
    monkeypatch, tmp_path: Path
) -> None:
    calls: list[tuple[list[str], str]] = []
    monkeypatch.setattr(windows_tasks, "installed", lambda: False)
    monkeypatch.setattr(
        windows_tasks,
        "_register_task",
        lambda arguments, user: calls.append((arguments, user)),
    )
    monkeypatch.setenv("USERDOMAIN", "TEST-PC")
    monkeypatch.setenv("USERNAME", "joe")
    config = tmp_path / "autostart.json"
    arguments = [
        r"C:\Native RetroBridge\python.exe",
        "-m",
        "retrobridge.cli",
        "serve",
        "--managed",
        "--token-file",
        r"C:\A very long path\retrobridge.token",
    ]
    assert windows_tasks.install(arguments, config_path=config)
    assert calls == [(arguments, r"TEST-PC\joe")]
    assert "New-ScheduledTaskAction" in windows_tasks._REGISTER_TASK_SCRIPT
    assert json.loads(config.read_text(encoding="utf-8"))["program_arguments"] == arguments


def test_running_reads_only_the_scheduler_status_field(monkeypatch) -> None:
    monkeypatch.setattr(
        windows_tasks,
        "_run",
        lambda *arguments, check=False: SimpleNamespace(
            returncode=0,
            stdout='"\\RetroBridge98 Renderer","N/A","Ready"\r\n',
        ),
    )
    assert not windows_tasks.running()

    monkeypatch.setattr(
        windows_tasks,
        "_run",
        lambda *arguments, check=False: SimpleNamespace(
            returncode=0,
            stdout='"\\RetroBridge98 Renderer","N/A","Running"\r\n',
        ),
    )
    assert windows_tasks.running()


def test_configured_runner_executes_saved_arguments(monkeypatch, tmp_path: Path) -> None:
    config = tmp_path / "autostart.json"
    arguments = [r"C:\RetroBridge\python.exe", "-m", "retrobridge.cli", "serve"]
    config.write_text(json.dumps({"program_arguments": arguments}), encoding="utf-8")
    captured: list[list[str]] = []
    monkeypatch.setattr(
        windows_tasks.subprocess,
        "run",
        lambda command, check=False: captured.append(command) or SimpleNamespace(returncode=7),
    )
    assert windows_tasks.run_configured(config) == 7
    assert captured == [arguments]
