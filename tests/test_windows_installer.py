from pathlib import Path


INSTALLER = Path(__file__).parents[1] / "host" / "install-windows-host.ps1"


def test_installer_requires_settings_publish_and_creates_both_shortcuts() -> None:
    source = INSTALLER.read_text(encoding="utf-8")
    assert "$SettingsPublishDirectory" in source
    assert "RetroBridge98 Settings.lnk" in source
    assert "$shortcut.TargetPath = $settingsExecutable" in source
    assert "$shortcut.Arguments = '--launch'" in source


def test_installer_does_not_enable_or_run_scheduled_task() -> None:
    source = INSTALLER.read_text(encoding="utf-8").casefold()
    assert "register-scheduledtask" not in source
    assert "schtasks" not in source
