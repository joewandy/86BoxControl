import asyncio
from pathlib import Path

import pytest

from retrobridge.browser import ChromeSession
from retrobridge.downloads import DownloadHistory
from retrobridge.fixtures import SELF_TEST_ORIGIN
from retrobridge.protocol import (
    ClipboardAction,
    DialogKind,
    Favorite,
    MessageType,
    PeerInfo,
)
from retrobridge.server import RetroBridgeServer


@pytest.fixture
async def chrome_session():
    session = ChromeSession(420, 240, max_fps=30, self_test=True)
    await session.start()
    try:
        yield session
    finally:
        await asyncio.wait_for(session.close(), timeout=10)


async def test_real_chrome_fixture_accepts_pointer_link_click(chrome_session: ChromeSession) -> None:
    assert chrome_session._page.url == SELF_TEST_ORIGIN + "/"
    await chrome_session.pointer(80, 68, 2, 1, 0)
    await chrome_session.pointer(80, 68, 3, 1, 0)
    await chrome_session._page.wait_for_url(SELF_TEST_ORIGIN + "/next")
    assert await chrome_session._page.title() == "RetroBridge QA Next"


async def test_real_chrome_fixture_accepts_text_and_button_click(
    chrome_session: ChromeSession,
) -> None:
    await chrome_session.navigate(SELF_TEST_ORIGIN)
    await chrome_session.pointer(80, 118, 2, 1, 0)
    await chrome_session.pointer(80, 118, 3, 1, 0)
    for character in b"Win98":
        await chrome_session.key(0, 3, 0, character)
    await chrome_session.pointer(260, 120, 2, 1, 0)
    await chrome_session.pointer(260, 120, 3, 1, 0)
    await chrome_session._page.wait_for_function("document.title === 'Typed: Win98'")
    assert await chrome_session._page.locator("#result").text_content() == "Typed: Win98"


async def test_headless_scrollbar_is_visible_and_clickable(
    chrome_session: ChromeSession,
) -> None:
    await chrome_session.navigate(SELF_TEST_ORIGIN + "/scroll")
    assert await chrome_session._page.evaluate("window.scrollY") == 0
    await chrome_session.pointer(417, 220, 2, 1, 0)
    await chrome_session.pointer(417, 220, 3, 1, 0)
    await chrome_session._page.wait_for_function("window.scrollY > 0")
    assert await chrome_session._page.evaluate("window.scrollY") > 0


async def test_popup_target_is_redirected_into_the_current_page(
    chrome_session: ChromeSession,
) -> None:
    await chrome_session.navigate(SELF_TEST_ORIGIN)
    await chrome_session.pointer(280, 68, 2, 1, 0)
    await chrome_session.pointer(280, 68, 3, 1, 0)
    await chrome_session._page.wait_for_url(SELF_TEST_ORIGIN + "/popup")
    assert len(chrome_session._context.pages) == 1


async def test_find_and_text_clipboard_do_not_touch_the_mac_clipboard(
    chrome_session: ChromeSession,
) -> None:
    await chrome_session.navigate(SELF_TEST_ORIGIN)
    await chrome_session.find(bytes((0,)) + b"deterministic QA")
    assert (await chrome_session.statuses.get())[0].value >= 1
    await chrome_session._page.locator("#name").fill("copy me")
    await chrome_session._page.locator("#name").evaluate(
        "element => element.setSelectionRange(0, element.value.length)"
    )
    copied = await chrome_session.clipboard(bytes((ClipboardAction.COPY,)))
    assert copied == bytes((ClipboardAction.RESULT,)) + b"copy me"
    await chrome_session._page.locator("#name").fill("")
    await chrome_session._page.locator("#name").focus()
    await chrome_session.clipboard(bytes((ClipboardAction.PASTE,)) + b"pasted")
    assert await chrome_session._page.locator("#name").input_value() == "pasted"


async def test_javascript_dialog_round_trip_uses_protocol_event(
    chrome_session: ChromeSession,
) -> None:
    await chrome_session.navigate(SELF_TEST_ORIGIN + "/dialog")
    message_type, payload = await asyncio.wait_for(chrome_session.events.get(), timeout=5)
    assert message_type is MessageType.DIALOG
    assert payload[4] == DialogKind.CONFIRM
    await chrome_session.dialog_reply(payload[:4] + b"\x01")
    await chrome_session._page.wait_for_function(
        "document.querySelector('#result').textContent === 'Confirmed'"
    )


async def test_javascript_prompt_accepts_edited_text(chrome_session: ChromeSession) -> None:
    await chrome_session.navigate(SELF_TEST_ORIGIN)
    clicking = asyncio.create_task(chrome_session._page.locator("#prompt").click())
    message_type, payload = await asyncio.wait_for(chrome_session.events.get(), timeout=5)
    assert message_type is MessageType.DIALOG
    assert payload[4] == DialogKind.PROMPT
    assert payload.endswith(b"Win98")
    await chrome_session.dialog_reply(payload[:4] + b"\x01Retro Station")
    await clicking
    await chrome_session._page.wait_for_function(
        "document.querySelector('#result').textContent === 'Prompt: Retro Station'"
    )


async def test_javascript_prompt_can_be_cancelled(chrome_session: ChromeSession) -> None:
    await chrome_session.navigate(SELF_TEST_ORIGIN)
    clicking = asyncio.create_task(chrome_session._page.locator("#prompt").click())
    _, payload = await asyncio.wait_for(chrome_session.events.get(), timeout=5)
    await chrome_session.dialog_reply(payload[:4] + b"\x00")
    await clicking
    await chrome_session._page.wait_for_function(
        "document.querySelector('#result').textContent === 'Prompt cancelled'"
    )


async def test_dashboard_refreshes_with_guest_favorites(tmp_path) -> None:
    session = ChromeSession(
        420,
        240,
        max_fps=30,
        guard_egress=False,
        download_history=DownloadHistory(tmp_path / "downloads.json"),
    )
    await session.start()
    try:
        await session.update_peer_info(
            PeerInfo(0, 3, 0)
        )
        await session.update_favorites([Favorite("Example dashboard link", "https://example.com/")])
        assert await session._page.locator("text=Example dashboard link").count() == 1
        assert await session._page.locator("text=Guest: RetroBridge98 0.3.0").count() == 1
        assert await session._page.locator("text=Isolation check").count() == 0
    finally:
        await asyncio.wait_for(session.close(), timeout=10)


async def test_fixture_download_is_saved_with_a_safe_name(tmp_path) -> None:
    session = ChromeSession(
        420,
        240,
        max_fps=30,
        self_test=True,
        download_dir=tmp_path,
        download_history=DownloadHistory(tmp_path / "downloads.json"),
    )
    await session.start()
    try:
        await session.navigate(SELF_TEST_ORIGIN)
        await session._page.locator("#download").click()
        message_type, payload = await asyncio.wait_for(session.events.get(), timeout=5)
        assert message_type is MessageType.DOWNLOAD
        assert payload.startswith(b"complete\0retrobridge-qa.txt\0")
        assert (tmp_path / "retrobridge-qa.txt").read_bytes().startswith(b"RetroBridge98")
        assert (tmp_path / "retrobridge-qa.txt").stat().st_mode & 0o777 == 0o600
    finally:
        await asyncio.wait_for(session.close(), timeout=10)


async def test_direct_download_navigation_returns_to_dashboard(tmp_path) -> None:
    session = ChromeSession(
        420,
        240,
        max_fps=30,
        self_test=True,
        download_dir=tmp_path,
        download_history=DownloadHistory(tmp_path / "downloads.json"),
    )
    await session.start()
    try:
        await session.navigate(SELF_TEST_ORIGIN + "/download.bin")
        message_type, payload = await asyncio.wait_for(session.events.get(), timeout=5)
        assert message_type is MessageType.DOWNLOAD
        assert payload.startswith(b"complete\0retrobridge-qa.txt\0")
        await session._page.wait_for_selector("text=Recent downloads")
        assert await session._page.locator("text=retrobridge-qa.txt").count() == 1
    finally:
        await asyncio.wait_for(session.close(), timeout=10)


async def test_forced_cleanup_terminates_only_the_owned_chrome_profile() -> None:
    session = ChromeSession(320, 200, max_fps=30, self_test=True)
    await session.start()
    profile = session._profile_dir
    assert profile is not None
    assert session._owned_profile_pids()

    async def stalled_close() -> None:
        await asyncio.Event().wait()

    session.close = stalled_close  # type: ignore[method-assign]
    bridge = RetroBridgeServer(
        "0123456789abcdef0123456789abcdef",
        session_cleanup_timeout=0.01,
    )
    try:
        await bridge._close_session(session)
        assert not session._owned_profile_pids()
        assert not Path(profile).exists()
    finally:
        await session.abort()


async def test_internal_renderer_page_is_replaced_by_safe_home(
    chrome_session: ChromeSession,
) -> None:
    await chrome_session._page.goto("data:text/plain,blocked")
    await chrome_session._page.wait_for_selector("text=Type an address above to begin.")
    assert chrome_session._page.url == "about:blank"
