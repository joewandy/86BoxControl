from pathlib import Path
from dataclasses import replace

from retrobridge import browser_discovery
from retrobridge.config import BrowserMode


def test_personal_profile_directories_are_never_shared(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        browser_discovery,
        "PATHS",
        replace(browser_discovery.PATHS, browser_profile_directory=tmp_path),
    )
    edge = browser_discovery.profile_directory(BrowserMode.EDGE_PERSONAL)
    chrome = browser_discovery.profile_directory(BrowserMode.CHROME_PERSONAL)
    assert edge == tmp_path / "edge-personal"
    assert chrome == tmp_path / "chrome-personal"
    assert edge != chrome


def test_standard_browser_paths_are_detected(monkeypatch, tmp_path: Path) -> None:
    edge = tmp_path / "Microsoft" / "Edge" / "Application" / "msedge.exe"
    chrome = tmp_path / "Google" / "Chrome" / "Application" / "chrome.exe"
    edge.parent.mkdir(parents=True)
    chrome.parent.mkdir(parents=True)
    edge.write_bytes(b"")
    chrome.write_bytes(b"")
    monkeypatch.setattr(browser_discovery, "_registry_candidates", lambda _name: ())
    detected = browser_discovery.detect_browsers(environ={"PROGRAMFILES": str(tmp_path)})
    assert detected[1].executable == str(edge)
    assert detected[2].executable == str(chrome)


def test_resolve_personal_browser_reports_locked_profile(monkeypatch, tmp_path: Path) -> None:
    executable = tmp_path / "msedge.exe"
    executable.write_bytes(b"")
    info = browser_discovery.BrowserInfo(
        BrowserMode.EDGE_PERSONAL,
        "Microsoft Edge Personal",
        True,
        str(executable),
        "test",
    )
    monkeypatch.setattr(
        browser_discovery,
        "detect_browsers",
        lambda: [
            browser_discovery.BrowserInfo(
                BrowserMode.PRIVATE_CHROMIUM, "Private Chromium", True, None, "test"
            ),
            info,
        ],
    )
    monkeypatch.setattr(browser_discovery, "profile_directory", lambda _mode: tmp_path / "profile")
    monkeypatch.setattr(browser_discovery, "profile_processes", lambda _path: [123])
    try:
        browser_discovery.resolve_browser(BrowserMode.EDGE_PERSONAL)
    except browser_discovery.BrowserSelectionError as exc:
        assert exc.code == "profile_locked"
    else:
        raise AssertionError("locked profile was accepted")
