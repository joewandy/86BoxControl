from pathlib import Path

import pytest

from retrobridge.platforms import ensure_supported_runtime, host_kind, runtime_paths


def test_platform_kind_is_explicit() -> None:
    assert host_kind("darwin") == "macos"
    assert host_kind("win32") == "windows"
    assert host_kind("linux") == "linux"


def test_windows_runtime_paths_are_native_and_local() -> None:
    paths = runtime_paths(
        platform_name="win32",
        environ={"LOCALAPPDATA": r"C:\Users\Joe\AppData\Local"},
        home=Path(r"C:\Users\Joe"),
    )
    assert str(paths.application_support).endswith(r"AppData\Local/RetroBridge98")
    assert "wsl" not in str(paths.application_support).casefold()
    assert "mnt" not in str(paths.application_support).casefold()


def test_macos_runtime_paths_remain_compatible() -> None:
    paths = runtime_paths(platform_name="darwin", environ={}, home=Path("/Users/joe"))
    assert paths.application_support == Path(
        "/Users/joe/Library/Application Support/RetroBridge98"
    )
    assert paths.log_directory == Path("/Users/joe/Library/Logs/RetroBridge98")


def test_live_linux_runtime_is_rejected() -> None:
    with pytest.raises(RuntimeError, match="WSL/Linux only for source development"):
        ensure_supported_runtime("linux")


def test_native_runtimes_are_accepted() -> None:
    ensure_supported_runtime("win32")
    ensure_supported_runtime("darwin")
