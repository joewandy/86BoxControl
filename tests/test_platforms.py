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


@pytest.mark.parametrize(
    ("environ", "kernel_release"),
    [
        ({}, "6.6.87.2-microsoft-standard-WSL2"),
        ({}, "4.4.0-Microsoft"),
        ({"WSL_DISTRO_NAME": "Ubuntu"}, "6.8.0"),
        ({"WSL_INTEROP": "/run/WSL/123_interop"}, "6.8.0"),
    ],
)
def test_live_wsl_runtime_is_rejected(environ, kernel_release) -> None:
    with pytest.raises(RuntimeError, match="WSL only for source development"):
        ensure_supported_runtime("linux", environ=environ, kernel_release=kernel_release)


def test_native_linux_runtime_is_accepted() -> None:
    ensure_supported_runtime("linux", environ={}, kernel_release="6.17.0-generic")


def test_linux_paths_use_xdg_state_and_native_downloads() -> None:
    paths = runtime_paths(
        platform_name="linux", environ={"XDG_STATE_HOME": "/state"},
        home=Path("/home/joe"),
    )
    assert paths.application_support == Path("/state/RetroBridge98")
    assert paths.download_directory == Path("/home/joe/Downloads/RetroBridge98")


def test_native_runtimes_are_accepted() -> None:
    ensure_supported_runtime("win32")
    ensure_supported_runtime("darwin")


def test_installed_windows_python_defeats_redirected_local_app_data() -> None:
    paths = runtime_paths(
        platform_name="win32",
        environ={"LOCALAPPDATA": r"C:\Redirected\Package"},
        home=Path(r"C:\Users\Joe"),
        executable=Path("/uv-managed/python.exe"),
        prefix=Path("/native/RetroBridge98/venv"),
    )
    assert paths.application_support == Path("/native/RetroBridge98")
