import plistlib
import sys
from pathlib import Path

import pytest

from retrobridge.launchd import (
    LABEL,
    build_plist,
    current_python,
    executable_is_available,
    write_plist,
)


def test_launch_agent_has_safe_explicit_lifecycle(tmp_path: Path) -> None:
    executable = tmp_path / "python"
    executable.write_text("#!/bin/sh\n", encoding="ascii")
    executable.chmod(0o700)
    payload = build_plist(
        [str(executable), "-m", "retrobridge.cli", "serve", "--managed"],
        working_directory=tmp_path,
    )
    assert payload["Label"] == LABEL
    assert payload["RunAtLoad"] is True
    assert payload["KeepAlive"] == {"SuccessfulExit": False}
    assert payload["ProgramArguments"][0] == str(executable)


def test_launch_agent_write_is_idempotent_and_refuses_implicit_replacement(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "python"
    executable.write_text("#!/bin/sh\n", encoding="ascii")
    executable.chmod(0o700)
    path = tmp_path / "LaunchAgents" / "retrobridge.plist"
    payload = build_plist([str(executable), "-m", "retrobridge.cli"], working_directory=tmp_path)
    assert write_plist(payload, path=path)
    assert not write_plist(payload, path=path)
    changed = dict(payload, ThrottleInterval=10)
    with pytest.raises(FileExistsError):
        write_plist(changed, path=path)
    assert write_plist(changed, force=True, path=path)
    assert plistlib.loads(path.read_bytes())["ThrottleInterval"] == 10


def test_launch_agent_reports_missing_executable(tmp_path: Path) -> None:
    path = tmp_path / "retrobridge.plist"
    payload = build_plist([str(tmp_path / "missing")], working_directory=tmp_path)
    write_plist(payload, path=path)
    assert not executable_is_available(path)


def test_current_python_preserves_the_active_environment_path() -> None:
    assert current_python() == str(Path(sys.executable).absolute())
