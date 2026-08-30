import asyncio
import base64
import io
from pathlib import Path

from PIL import Image

from retrobridge.browser import ChromeSession, TestPatternSession as PatternSession
from retrobridge.downloads import DownloadHistory
from retrobridge.protocol import Favorite, PIXEL_RGB565_LZ4, PeerInfo


async def test_stale_screencast_frame_is_acked_and_replaced() -> None:
    session = ChromeSession(2, 1, max_fps=1000)
    acknowledgements: list[int] = []

    async def fake_ack(session_id: int) -> None:
        acknowledgements.append(session_id)

    session.ack_cdp = fake_ack  # type: ignore[method-assign]
    session._on_screencast_frame({"sessionId": 10, "data": "unused"})
    session._on_screencast_frame({"sessionId": 11, "data": "newest"})
    await asyncio.sleep(0)
    assert acknowledgements == [10]
    assert (await session.frames.get())["sessionId"] == 11


async def test_jpeg_is_decoded_to_guest_bgr24_on_the_host() -> None:
    image = Image.new("RGB", (2, 1))
    image.putdata([(255, 0, 0), (0, 128, 255)])
    encoded = io.BytesIO()
    image.save(encoded, format="PNG")
    session = ChromeSession(2, 1, max_fps=1000)
    session.frames.put_nowait(
        {"sessionId": 7, "data": base64.b64encode(encoded.getvalue()).decode("ascii")}
    )
    frame = await session.next_frame()
    assert frame.cdp_session_id == 7
    assert frame.frame.pixels == bytes((0, 0, 255, 255, 128, 0))


async def test_pointer_preserves_drag_button_and_double_click_count() -> None:
    session = ChromeSession(640, 480)
    events: list[dict] = []

    class CDP:
        async def send(self, method: str, payload: dict) -> None:
            assert method == "Input.dispatchMouseEvent"
            events.append(payload)

    session._cdp = CDP()
    await session.pointer(20, 30, 1, 1, 0)
    await session.pointer(20, 30, 2, 1 | (2 << 4), 0)
    assert events[0]["buttons"] == 1
    assert events[1]["button"] == "left"
    assert events[1]["clickCount"] == 2


async def test_browser_level_control_and_alt_shortcuts_are_not_forwarded() -> None:
    session = ChromeSession(640, 480)
    events: list[tuple[str, dict]] = []

    class CDP:
        async def send(self, method: str, payload: dict) -> None:
            events.append((method, payload))

    session._cdp = CDP()
    await session.key(ord("W"), 1, 2, 0)
    await session.key(ord("E"), 1, 4, 0)
    assert not events
    assert (await session.statuses.get())[1] == "Browser shortcut blocked"


async def test_performance_pattern_has_a_small_compressed_wire_frame() -> None:
    session = PatternSession(640, 480, max_fps=1000)
    await session.start()
    frame = (await session.next_frame()).frame
    encoded = frame.encode(PIXEL_RGB565_LZ4)
    assert len(encoded) < 100_000
    assert session.capabilities == 0


async def test_home_dashboard_escapes_guest_data_and_shows_connection(tmp_path) -> None:
    session = ChromeSession(
        640,
        480,
        download_history=DownloadHistory(tmp_path / "downloads.json"),
    )
    await session.update_peer_info(PeerInfo(0, 3, 0))
    await session.update_favorites([Favorite("<unsafe>", "https://example.com/?a=1&b=2")])
    rendered = session._render_home()
    assert "&lt;unsafe&gt;" in rendered
    assert "a=1&amp;b=2" in rendered
    assert "Guest: RetroBridge98 0.3.0" in rendered


async def test_home_dashboard_rejects_private_favorite(tmp_path) -> None:
    session = ChromeSession(
        640,
        480,
        download_history=DownloadHistory(tmp_path / "downloads.json"),
    )
    import pytest

    with pytest.raises(ValueError, match="Private"):
        await session.update_favorites([Favorite("Router", "http://192.168.1.1/")])


def test_personal_profile_is_preserved_while_private_profile_is_removed(tmp_path: Path) -> None:
    personal = tmp_path / "edge-personal"
    personal.mkdir()
    personal_session = ChromeSession(
        640,
        480,
        browser_mode="edge-personal",
        profile_dir=personal,
    )
    personal_session._profile_dir = personal
    personal_session._delete_profile_on_close = False
    personal_session._remove_profile_directory()
    assert personal.exists()

    private = tmp_path / "temporary"
    private.mkdir()
    private_session = ChromeSession(640, 480)
    private_session._profile_dir = private
    private_session._remove_profile_directory()
    assert not private.exists()
