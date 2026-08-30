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


def test_disabled_matching_task_is_re_registered_to_enable_it(
    monkeypatch, tmp_path: Path
) -> None:
    arguments = [r"C:\RetroBridge\python.exe", "-m", "retrobridge.cli", "serve"]
    config = tmp_path / "autostart.json"
    config.write_text(json.dumps({"task_name": windows_tasks.TASK_NAME, "program_arguments": arguments}))
    registered: list[tuple[list[str], str]] = []
    monkeypatch.setattr(windows_tasks, "installed", lambda: True)
    monkeypatch.setattr(windows_tasks, "enabled", lambda: False)
    monkeypatch.setattr(
        windows_tasks,
        "_register_task",
        lambda values, user: registered.append((values, user)),
    )
    monkeypatch.setenv("USERDOMAIN", "TEST-PC")
    monkeypatch.setenv("USERNAME", "joe")

    assert windows_tasks.install(arguments, config_path=config)
    assert registered == [(arguments, r"TEST-PC\joe")]


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


def test_enabled_reads_task_xml_instead_of_running_state(monkeypatch) -> None:
    monkeypatch.setattr(
        windows_tasks,
        "_run",
        lambda *arguments, check=False: SimpleNamespace(
            returncode=0,
            stdout=(
                '<?xml version="1.0" encoding="UTF-16"?>'
                '<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">'
                '<Settings><Enabled>false</Enabled></Settings></Task>'
            ),
        ),
    )
    assert not windows_tasks.enabled()


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
