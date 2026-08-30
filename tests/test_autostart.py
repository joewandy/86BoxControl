from pathlib import Path

from retrobridge import autostart


def test_windows_autostart_dispatches_to_task_scheduler(monkeypatch) -> None:
    calls: list[tuple[list[str], bool]] = []
    monkeypatch.setattr(autostart, "host_kind", lambda: "windows")
    monkeypatch.setattr(
        autostart.windows_tasks,
        "install",
        lambda arguments, force=False: calls.append((arguments, force)) or True,
    )
    monkeypatch.setattr(autostart.windows_tasks, "start", lambda: None)
    changed = autostart.install(
        [r"C:\RetroBridge\python.exe", "-m", "retrobridge.cli", "serve"],
        working_directory=Path(r"C:\ignored-for-windows"),
        force=True,
    )
    assert changed
    assert calls == [
        ([r"C:\RetroBridge\python.exe", "-m", "retrobridge.cli", "serve"], True)
    ]


def test_linux_autostart_is_not_misrepresented(monkeypatch) -> None:
    monkeypatch.setattr(autostart, "host_kind", lambda: "linux")
    assert not autostart.installed()
    assert not autostart.loaded()
    assert autostart.location() == "unsupported"
