"""Playwright/Chrome rendering backend."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import html
import io
import logging
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from PIL import Image
import psutil

from .downloads import DownloadHistory
from .egress import PublicSocksProxy
from .fixtures import SELF_TEST_ORIGIN, fixture_for_url
from .policy import NavigationBlocked, resolve_public_host, validate_navigation_url
from .protocol import (
    ClipboardAction,
    DialogKind,
    DownloadRecord,
    DownloadStatus,
    Favorite,
    Frame,
    MessageType,
    PeerInfo,
    StatusKind,
    encode_text,
)

LOG = logging.getLogger(__name__)

POPUP_REDIRECT_SCRIPT = r"""
(() => {
  const retarget = root => {
    if (!root.querySelectorAll) return;
    for (const element of root.querySelectorAll('a[target], form[target]')) {
      if (element.target && element.target.toLowerCase() !== '_self') element.target = '_self';
    }
  };
  const install = () => {
    retarget(document);
    new MutationObserver(records => {
      for (const record of records) for (const node of record.addedNodes) retarget(node);
    }).observe(document.documentElement, {subtree: true, childList: true});
  };
  if (document.documentElement) install();
  else document.addEventListener('DOMContentLoaded', install, {once: true});
  window.open = function(url) {
    if (url) window.location.assign(String(url));
    return window;
  };
})();
"""

CLIPBOARD_SCRIPT = r"""
({operation}) => {
  const active = document.activeElement;
  let text = '';
  if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA') &&
      typeof active.selectionStart === 'number') {
    const start = active.selectionStart;
    const end = active.selectionEnd;
    text = active.value.slice(start, end);
    if (operation === 'cut' && end > start) {
      active.setRangeText('', start, end, 'start');
      active.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'deleteByCut'}));
    }
  } else {
    const selection = window.getSelection();
    text = selection ? selection.toString() : '';
    if (operation === 'cut' && text) document.execCommand('delete');
  }
  return text;
}
"""

VIRTUAL_KEYS: dict[int, tuple[str, str]] = {
    0x08: ("Backspace", "Backspace"),
    0x09: ("Tab", "Tab"),
    0x0D: ("Enter", "Enter"),
    0x1B: ("Escape", "Escape"),
    0x20: (" ", "Space"),
    0x21: ("PageUp", "PageUp"),
    0x22: ("PageDown", "PageDown"),
    0x23: ("End", "End"),
    0x24: ("Home", "Home"),
    0x25: ("ArrowLeft", "ArrowLeft"),
    0x26: ("ArrowUp", "ArrowUp"),
    0x27: ("ArrowRight", "ArrowRight"),
    0x28: ("ArrowDown", "ArrowDown"),
    0x2D: ("Insert", "Insert"),
    0x2E: ("Delete", "Delete"),
}
for _number in range(1, 13):
    VIRTUAL_KEYS[0x6F + _number] = (f"F{_number}", f"F{_number}")


@dataclass(frozen=True)
class BrowserFrame:
    frame: Frame
    cdp_session_id: int


class ChromeSession:
    """One ephemeral Chrome page for one authenticated guest."""

    def __init__(
        self,
        width: int,
        height: int,
        *,
        headed: bool = False,
        max_fps: int = 5,
        self_test: bool = False,
        download_dir: Path | None = None,
        max_download_bytes: int = 100 * 1024 * 1024,
        guard_egress: bool = True,
        download_history: DownloadHistory | None = None,
    ):
        self.width = width
        self.height = height
        self.headed = headed
        self.max_fps = max_fps
        self.self_test = self_test
        self.download_dir = download_dir
        self.max_download_bytes = max_download_bytes
        self.download_history = download_history or DownloadHistory()
        self.guard_egress = guard_egress
        self.frames: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1)
        self.statuses: asyncio.Queue[tuple[StatusKind, str]] = asyncio.Queue(maxsize=16)
        self.events: asyncio.Queue[tuple[MessageType, bytes]] = asyncio.Queue(maxsize=32)
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._cdp: Any = None
        self._sequence = 0
        self._last_frame_at = 0.0
        self._closing = False
        self._favorites: list[Favorite] = []
        self._peer_info: PeerInfo | None = None
        self._is_home = True
        self._dialog_sequence = 0
        self._dialog_waiters: dict[int, asyncio.Future[tuple[bool, str]]] = {}
        self._dialog_idle = asyncio.Event()
        self._dialog_idle.set()
        self._download_tasks: set[asyncio.Task[None]] = set()
        self._egress: PublicSocksProxy | None = None
        self._profile_dir: Path | None = None
        self._restoring_safe_page = False

    @property
    def dialog_idle(self) -> asyncio.Event:
        return self._dialog_idle

    async def start(self) -> None:
        from playwright.async_api import async_playwright

        launch_arguments = [
            "--disable-extensions",
            "--disable-sync",
            "--no-first-run",
            "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
        ]
        if self.guard_egress:
            self._egress = PublicSocksProxy()
            await self._egress.start()
            launch_arguments.extend(
                [
                    f"--proxy-server=socks5://127.0.0.1:{self._egress.port}",
                    "--proxy-bypass-list=<-loopback>",
                ]
            )
        self._playwright = await async_playwright().start()
        self._profile_dir = Path(tempfile.mkdtemp(prefix="retrobridge98-chrome-"))
        launch_options: dict[str, Any] = {
            "user_data_dir": str(self._profile_dir),
            "headless": not self.headed,
            "args": launch_arguments,
            "viewport": {"width": self.width, "height": self.height},
            "accept_downloads": self.download_dir is not None,
            "service_workers": "block",
        }
        if self.headed:
            # Native headed diagnostics use the user's stable Chrome. Normal
            # managed operation uses Playwright's isolated headless Chromium.
            launch_options["channel"] = "chrome"
        self._context = await self._playwright.chromium.launch_persistent_context(
            **launch_options
        )
        self._browser = self._context.browser
        await self._context.add_init_script(POPUP_REDIRECT_SCRIPT)
        await self._context.route("**/*", self._route_request)
        self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        self._page.on("popup", self._on_popup)
        self._page.on("dialog", self._on_dialog)
        self._page.on("download", self._on_download)
        self._page.on("load", lambda: self._put_status(StatusKind.LOADING, "0"))
        self._page.on("domcontentloaded", self._on_dom_content_loaded)
        self._page.on("framenavigated", self._on_frame_navigated)
        self._cdp = await self._context.new_cdp_session(self._page)
        self._cdp.on("Page.screencastFrame", self._on_screencast_frame)
        await self._cdp.send("Page.enable")
        await self._cdp.send(
            "Page.startScreencast",
            {
                "format": "jpeg",
                "quality": 55,
                "maxWidth": self.width,
                "maxHeight": self.height,
                "everyNthFrame": 1,
            },
        )
        if self.self_test:
            self._is_home = False
            await self._page.goto(SELF_TEST_ORIGIN, wait_until="domcontentloaded")
        else:
            await self._show_home()
        self._put_status(StatusKind.INFO, "Chrome renderer ready")

    async def _route_request(self, route: Any, request: Any) -> None:
        if self.self_test:
            fixture = fixture_for_url(request.url)
            if fixture is not None:
                await route.fulfill(
                    status=fixture.status,
                    content_type=fixture.content_type,
                    headers=fixture.headers,
                    body=fixture.body,
                )
                return
        scheme = urlsplit(request.url).scheme.lower()
        if scheme in {"data", "blob", "about"}:
            await route.continue_()
            return
        try:
            url = validate_navigation_url(request.url)
            await resolve_public_host(url)
        except NavigationBlocked:
            await route.abort("blockedbyclient")
            return
        await route.continue_()

    async def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        for task in self._download_tasks:
            task.cancel()
        if self._download_tasks:
            with contextlib.suppress(Exception):
                await asyncio.gather(*self._download_tasks, return_exceptions=True)
        for waiter in self._dialog_waiters.values():
            if not waiter.done():
                waiter.set_result((False, ""))
        self._dialog_waiters.clear()
        if self._cdp is not None:
            with contextlib.suppress(Exception):
                await self._cdp.send("Page.stopScreencast")
        if self._context is not None:
            with contextlib.suppress(Exception):
                await self._context.close()
        if self._browser is not None:
            with contextlib.suppress(Exception):
                await self._browser.close()
        if self._playwright is not None:
            with contextlib.suppress(Exception):
                await self._playwright.stop()
        await self._terminate_profile_processes()
        if self._egress is not None:
            with contextlib.suppress(Exception):
                await self._egress.close()
            self._egress = None
        self._cdp = self._page = self._context = self._browser = self._playwright = None
        self._remove_profile_directory()

    async def abort(self) -> None:
        """Kill only this session's Playwright driver after graceful cleanup stalls."""

        playwright = self._playwright
        transport = None
        if playwright is not None:
            with contextlib.suppress(Exception):
                transport = playwright._impl_obj._connection._transport
        process = getattr(transport, "_proc", None)
        await self._terminate_profile_processes()
        if playwright is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(playwright.stop(), timeout=2)
        if process is not None and process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(process.wait(), timeout=2)
        self._cdp = self._page = self._context = self._browser = self._playwright = None
        if self._egress is not None:
            with contextlib.suppress(Exception):
                await self._egress.close()
            self._egress = None
        self._remove_profile_directory()
        self._closing = True

    def _owned_profile_pids(self) -> list[int]:
        if self._profile_dir is None:
            return []
        marker = f"--user-data-dir={self._profile_dir}"
        pids: list[int] = []
        for process in psutil.process_iter(("pid", "cmdline")):
            try:
                if marker in " ".join(process.info["cmdline"] or ()):
                    pids.append(int(process.info["pid"]))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return pids

    async def _terminate_profile_processes(self) -> None:
        pids = self._owned_profile_pids()
        if not pids:
            return
        LOG.warning("Terminating %d Chrome processes owned by the renderer session", len(pids))
        for pid in reversed(pids):
            with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                psutil.Process(pid).terminate()
        for _ in range(20):
            if not self._owned_profile_pids():
                return
            await asyncio.sleep(0.1)
        for pid in reversed(self._owned_profile_pids()):
            with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                psutil.Process(pid).kill()

    def _remove_profile_directory(self) -> None:
        profile = self._profile_dir
        self._profile_dir = None
        if profile is not None:
            shutil.rmtree(profile, ignore_errors=True)

    def _put_status(self, kind: StatusKind, text: str) -> None:
        if self.statuses.full():
            try:
                self.statuses.get_nowait()
            except asyncio.QueueEmpty:
                pass
        self.statuses.put_nowait((kind, text))

    def _put_event(self, kind: MessageType, payload: bytes) -> None:
        if self.events.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                self.events.get_nowait()
        self.events.put_nowait((kind, payload))

    def _render_home(self) -> str:
        peer = self._peer_info
        version = "Legacy / not reported"
        if peer is not None:
            version = f"{peer.major}.{peer.minor}.{peer.patch}"

        favorite_items = "".join(
            f"<li><a href='{html.escape(item.url, quote=True)}'>{html.escape(item.title)}</a></li>"
            for item in self._favorites
        )
        if not favorite_items:
            favorite_items = "<li><em>Add a Favorite from the guest menu.</em></li>"

        recent = list(reversed(self.download_history.load()))[:8]
        download_items = "".join(
            "<li>"
            f"<strong>{html.escape(item.name)}</strong> "
            f"<span class='small'>{html.escape(item.status.name.title())}, "
            f"{item.size:,} bytes, "
            f"{datetime.fromtimestamp(item.timestamp).strftime('%Y-%m-%d %H:%M')}</span>"
            "</li>"
            for item in recent
        )
        if not download_items:
            download_items = "<li><em>No downloads recorded yet.</em></li>"

        return (
            "<!doctype html><html><head><meta charset='windows-1252'><title>RetroBridge98 Home</title>"
            "<style>body{margin:0;background:#008080;color:#000;font:14px Arial,sans-serif}"
            ".desk{padding:14px}.title{background:#000080;color:#fff;font-weight:bold;padding:6px 8px}"
            ".window{background:#c0c0c0;border:2px outset #fff;max-width:760px;margin:auto}"
            ".body{padding:12px}.grid{display:flex;gap:10px;flex-wrap:wrap}.panel{background:#fff;"
            "border:2px inset #ddd;padding:8px;box-sizing:border-box;flex:1;min-width:250px}"
            "h1{font-size:21px;margin:0 0 5px}h2{font-size:16px;color:#000080;margin:0 0 6px}"
            "ul{margin:4px 0;padding-left:20px}li{margin:4px 0}.small{font-size:11px;color:#555}"
            ".buttons a{display:inline-block;background:#c0c0c0;border:2px outset #fff;padding:4px 8px;"
            "margin:2px;color:#000;text-decoration:none}.footer{margin-top:10px;font-size:11px}</style>"
            "</head><body><div class='desk'><div class='window'><div class='title'>RetroBridge98 Home</div>"
            "<div class='body'><h1>Welcome to the Retro Station</h1>"
            "<p>Type an address above to begin.</p>"
            "<div class='buttons'><a href='https://www.google.com/'>Google</a>"
            "<a href='https://en.wikipedia.org/'>Wikipedia</a>"
            "<a href='https://archive.org/'>Internet Archive</a></div><div class='grid'>"
            f"<div class='panel'><h2>Favorites</h2><ul>{favorite_items}</ul></div>"
            f"<div class='panel'><h2>Recent downloads</h2><ul>{download_items}</ul></div>"
            "<div class='panel'><h2>Connection</h2>"
            f"<p>Guest: RetroBridge98 {html.escape(version)}<br>Renderer: 0.3.0<br>"
            "Transport: RGB565/LZ4</p></div></div>"
            "<p class='footer'>Modern pages use a disposable isolated Chromium profile on the host. "
            "Downloads stay in the host inbox. Do not enter sensitive credentials.</p>"
            "</div></div></div></body></html>"
        )

    async def _show_home(self) -> None:
        self._is_home = True
        await self._page.set_content(self._render_home())
        self._put_status(StatusKind.URL, "")

    async def _refresh_home(self) -> None:
        if self._is_home and self._page is not None:
            await self._page.set_content(self._render_home())
            self._put_status(StatusKind.URL, "")

    async def update_peer_info(self, peer: PeerInfo) -> None:
        self._peer_info = peer
        await self._refresh_home()

    async def update_favorites(self, favorites: list[Favorite]) -> None:
        accepted: list[Favorite] = []
        seen: set[str] = set()
        for favorite in favorites:
            url = validate_navigation_url(favorite.url)
            key = url.casefold()
            if key in seen:
                continue
            seen.add(key)
            accepted.append(Favorite(favorite.title[:128], url))
        self._favorites = accepted
        await self._refresh_home()

    def download_records(self) -> list[DownloadRecord]:
        return self.download_history.load()

    def _on_popup(self, popup: Any) -> None:
        asyncio.create_task(self._redirect_popup(popup))

    async def _redirect_popup(self, popup: Any) -> None:
        try:
            await popup.wait_for_load_state("domcontentloaded", timeout=5_000)
            url = popup.url
        except Exception:
            url = popup.url
        finally:
            with contextlib.suppress(Exception):
                await popup.close()
        if url and url != "about:blank":
            await self.navigate(url)

    def _on_dialog(self, dialog: Any) -> None:
        asyncio.create_task(self._handle_dialog(dialog))

    async def _handle_dialog(self, dialog: Any) -> None:
        kinds = {"alert": DialogKind.ALERT, "confirm": DialogKind.CONFIRM, "prompt": DialogKind.PROMPT}
        kind = kinds.get(dialog.type)
        if kind is None:
            await dialog.dismiss()
            return
        self._dialog_idle.clear()
        self._dialog_sequence = (self._dialog_sequence + 1) & 0xFFFFFFFF
        dialog_id = self._dialog_sequence
        future: asyncio.Future[tuple[bool, str]] = asyncio.get_running_loop().create_future()
        self._dialog_waiters[dialog_id] = future
        message = dialog.message[:2048]
        default = (dialog.default_value or "")[:1024]
        payload = (
            dialog_id.to_bytes(4, "little")
            + bytes((int(kind),))
            + encode_text(message)
            + b"\0"
            + encode_text(default)
        )
        self._put_event(MessageType.DIALOG, payload)
        try:
            accepted, response = await asyncio.wait_for(future, timeout=120)
            if accepted:
                await dialog.accept(response if kind is DialogKind.PROMPT else None)
            else:
                await dialog.dismiss()
        except asyncio.TimeoutError:
            await dialog.dismiss()
            self._put_status(StatusKind.ERROR, "Page dialog timed out")
        finally:
            self._dialog_waiters.pop(dialog_id, None)
            self._dialog_idle.set()

    async def dialog_reply(self, payload: bytes) -> None:
        if len(payload) < 5:
            raise ValueError("dialog reply is too short")
        dialog_id = int.from_bytes(payload[:4], "little")
        waiter = self._dialog_waiters.get(dialog_id)
        if waiter is not None and not waiter.done():
            waiter.set_result((bool(payload[4]), payload[5:].decode("cp1252", "replace")))

    def _on_download(self, download: Any) -> None:
        task = asyncio.create_task(self._save_download(download))
        self._download_tasks.add(task)
        task.add_done_callback(self._download_tasks.discard)

    @staticmethod
    def _safe_download_name(name: str) -> str:
        name = re.sub(r"[\x00-\x1f/\\:]", "_", Path(name).name).strip(" .")
        return name[:180] or "download.bin"

    async def _save_download(self, download: Any) -> None:
        if self.download_dir is None:
            with contextlib.suppress(Exception):
                await download.cancel()
            self._put_event(MessageType.DOWNLOAD, b"blocked\0Downloads are disabled")
            self.download_history.append(DownloadStatus.BLOCKED, "Downloads are disabled")
            await self._refresh_home()
            return
        directory = self.download_dir.expanduser()
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        name = self._safe_download_name(download.suggested_filename)
        with tempfile.TemporaryDirectory(prefix=".retrobridge-", dir=directory) as temporary:
            staged = Path(temporary) / name
            try:
                await download.save_as(staged)
                size = staged.stat().st_size
                if size > self.max_download_bytes:
                    self._put_event(MessageType.DOWNLOAD, encode_text(f"oversize\0{name}"))
                    self.download_history.append(DownloadStatus.OVERSIZE, name, size)
                    await self._refresh_home()
                    return
                target = directory / name
                stem, suffix = target.stem, target.suffix
                index = 1
                while target.exists() or target.is_symlink():
                    target = directory / f"{stem} ({index}){suffix}"
                    index += 1
                os.replace(staged, target)
                target.chmod(0o600)
                self._put_event(
                    MessageType.DOWNLOAD,
                    encode_text(f"complete\0{target.name}\0{size}"),
                )
                self.download_history.append(DownloadStatus.COMPLETE, target.name, size)
                await self._refresh_home()
                self._put_status(StatusKind.INFO, f"Downloaded to host: {target.name}")
            except Exception as exc:
                self._put_event(MessageType.DOWNLOAD, encode_text(f"failed\0{name}"))
                self.download_history.append(DownloadStatus.FAILED, name)
                await self._refresh_home()
                self._put_status(StatusKind.ERROR, f"Download failed: {exc}")

    def _on_dom_content_loaded(self) -> None:
        if self._page is not None:
            asyncio.create_task(self._publish_title())

    async def _publish_title(self) -> None:
        try:
            self._put_status(StatusKind.TITLE, await self._page.title())
        except Exception:
            return

    def _on_frame_navigated(self, frame: Any) -> None:
        if self._page is not None and frame == self._page.main_frame:
            scheme = urlsplit(frame.url).scheme.lower()
            if scheme in {"http", "https"} or frame.url == "about:blank":
                if scheme in {"http", "https"}:
                    self._is_home = False
                self._put_status(StatusKind.URL, "" if frame.url == "about:blank" else frame.url)
            elif not self._restoring_safe_page:
                asyncio.create_task(self._restore_safe_page(frame.url))

    async def _restore_safe_page(self, blocked_url: str) -> None:
        self._restoring_safe_page = True
        try:
            self._put_status(StatusKind.ERROR, "Internal browser page blocked")
            await self._page.goto("about:blank", wait_until="domcontentloaded", timeout=5_000)
            await self._show_home()
            LOG.warning("Blocked renderer navigation to %s", blocked_url)
        except Exception:
            LOG.exception("Failed to leave blocked renderer page %s", blocked_url)
        finally:
            self._restoring_safe_page = False

    def _on_screencast_frame(self, params: dict[str, Any]) -> None:
        if self.frames.full():
            try:
                stale = self.frames.get_nowait()
                asyncio.create_task(self.ack_cdp(int(stale["sessionId"])))
            except asyncio.QueueEmpty:
                pass
        self.frames.put_nowait(params)

    async def next_frame(self) -> BrowserFrame:
        while True:
            await self._dialog_idle.wait()
            params = await self.frames.get()
            if self._dialog_idle.is_set():
                break
            await self.ack_cdp(int(params["sessionId"]))
        delay = (1.0 / self.max_fps) - (time.monotonic() - self._last_frame_at)
        if delay > 0:
            await asyncio.sleep(delay)
        image_bytes = base64.b64decode(params["data"], validate=True)
        with Image.open(io.BytesIO(image_bytes)) as image:
            image = image.convert("RGB")
            if image.size != (self.width, self.height):
                image = image.resize((self.width, self.height))
            red_green_blue = image.tobytes()
        bgr = bytearray(len(red_green_blue))
        bgr[0::3] = red_green_blue[2::3]
        bgr[1::3] = red_green_blue[1::3]
        bgr[2::3] = red_green_blue[0::3]
        self._sequence = (self._sequence + 1) & 0xFFFFFFFF
        self._last_frame_at = time.monotonic()
        return BrowserFrame(
            Frame(self._sequence, self.width, self.height, self.width * 3, bytes(bgr)),
            int(params["sessionId"]),
        )

    async def ack_cdp(self, session_id: int) -> None:
        if self._cdp is not None:
            await self._cdp.send("Page.screencastFrameAck", {"sessionId": session_id})

    async def navigate(self, raw_url: str) -> None:
        url = validate_navigation_url(raw_url)
        if not (self.self_test and url.startswith(SELF_TEST_ORIGIN)):
            await resolve_public_host(url)
        self._put_status(StatusKind.LOADING, "1")
        self._is_home = False
        try:
            await self._page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        except Exception as exc:
            if "download is starting" in str(exc).lower():
                await self._show_home()
                self._put_status(StatusKind.LOADING, "0")
                return
            await self._show_error_page("Navigation failed", str(exc))
            self._put_status(StatusKind.LOADING, "0")

    async def _show_error_page(self, title: str, detail: str) -> None:
        self._put_status(StatusKind.ERROR, title)
        await self._page.set_content(
            "<html><body style='font:17px sans-serif;background:#fff4f4;padding:24px'>"
            f"<h2>{html.escape(title)}</h2><p>{html.escape(detail)[:2000]}</p>"
            "<p>Correct the address or press Reload to try again.</p></body></html>"
        )

    async def control(self, action: int) -> None:
        if action == 1:
            await self._page.go_back(wait_until="domcontentloaded", timeout=15_000)
        elif action == 2:
            await self._page.go_forward(wait_until="domcontentloaded", timeout=15_000)
        elif action == 3:
            await self._page.reload(wait_until="domcontentloaded", timeout=30_000)
        elif action == 4:
            await self._cdp.send("Page.stopLoading")
        elif action == 5:
            await self._show_home()

    async def pointer(self, x: int, y: int, action: int, button: int, wheel: int) -> None:
        button_names = {0: "none", 1: "left", 2: "right", 3: "middle"}
        event_types = {1: "mouseMoved", 2: "mousePressed", 3: "mouseReleased", 4: "mouseWheel"}
        click_count = max(1, button >> 4) if action in (2, 3) else 0
        button &= 0x0F
        button_bits = {1: 1, 2: 2, 3: 4}.get(button, 0)
        payload: dict[str, Any] = {
            "type": event_types[action],
            "x": min(max(x, 0), self.width - 1),
            "y": min(max(y, 0), self.height - 1),
            "button": button_names.get(button, "none"),
            "buttons": button_bits,
        }
        if action in (2, 3):
            payload["clickCount"] = click_count
        if action == 4:
            payload["deltaX"] = 0
            payload["deltaY"] = -wheel
        await self._cdp.send("Input.dispatchMouseEvent", payload)

    async def key(self, virtual_key: int, action: int, modifiers: int, character: int) -> None:
        cdp_modifiers = 0
        if modifiers & 1:
            cdp_modifiers |= 8
        if modifiers & 2:
            cdp_modifiers |= 2
        if modifiers & 4:
            cdp_modifiers |= 1
        if action == 3:
            text = bytes((character,)).decode("cp1252", errors="replace")
            await self._cdp.send("Input.dispatchKeyEvent", {"type": "char", "text": text})
            return
        if modifiers & (2 | 4) and not (modifiers == 2 and virtual_key == 0x41):
            if action == 1:
                self._put_status(StatusKind.ERROR, "Browser shortcut blocked")
            return
        event_type = "keyDown" if action == 1 else "keyUp"
        key, code = VIRTUAL_KEYS.get(virtual_key, ("", ""))
        if 0x41 <= virtual_key <= 0x5A:
            key = chr(virtual_key).lower()
            code = f"Key{chr(virtual_key)}"
        elif 0x30 <= virtual_key <= 0x39:
            key = chr(virtual_key)
            code = f"Digit{chr(virtual_key)}"
        payload: dict[str, Any] = {
            "type": event_type,
            "windowsVirtualKeyCode": virtual_key,
            "nativeVirtualKeyCode": virtual_key,
            "modifiers": cdp_modifiers,
        }
        if key:
            payload["key"] = key
            payload["code"] = code
        await self._cdp.send(
            "Input.dispatchKeyEvent",
            payload,
        )

    async def find(self, payload: bytes) -> None:
        if not payload:
            raise ValueError("find request is empty")
        flags = payload[0]
        query = payload[1:].decode("cp1252", "replace")
        if not query:
            return
        found = await self._page.evaluate(
            "([text, backwards, matchCase]) => window.find(text, matchCase, backwards, true, false, false, false)",
            [query, bool(flags & 1), bool(flags & 2)],
        )
        self._put_status(StatusKind.INFO, "Match found" if found else "Text not found")

    async def clipboard(self, payload: bytes) -> bytes | None:
        if not payload:
            raise ValueError("clipboard request is empty")
        action = ClipboardAction(payload[0])
        if action in {ClipboardAction.COPY, ClipboardAction.CUT}:
            text = await self._page.evaluate(
                CLIPBOARD_SCRIPT,
                {"operation": "cut" if action is ClipboardAction.CUT else "copy"},
            )
            return bytes((int(ClipboardAction.RESULT),)) + encode_text(str(text)[:65535])
        if action is ClipboardAction.PASTE:
            text = payload[1:65536].decode("cp1252", "replace")
            await self._cdp.send("Input.insertText", {"text": text})
            return None
        raise ValueError("unexpected clipboard action")


class TestPatternSession:
    """Renderer-free continuous frame source used for the framebuffer gate."""

    capabilities = 0

    def __init__(self, width: int, height: int, *, max_fps: int = 5, **_: Any):
        self.width = width
        self.height = height
        self.max_fps = max_fps
        self.statuses: asyncio.Queue[tuple[StatusKind, str]] = asyncio.Queue()
        self.events: asyncio.Queue[tuple[MessageType, bytes]] = asyncio.Queue()
        self._sequence = 0
        self._started = 0.0
        self._last_frame_at = 0.0

    async def start(self) -> None:
        self._started = time.monotonic()
        self.statuses.put_nowait((StatusKind.INFO, "Animated test pattern"))

    async def close(self) -> None:
        return

    async def abort(self) -> None:
        return

    async def next_frame(self) -> BrowserFrame:
        delay = (1.0 / self.max_fps) - (time.monotonic() - self._last_frame_at)
        if self._last_frame_at and delay > 0:
            await asyncio.sleep(delay)
        self._last_frame_at = time.monotonic()
        self._sequence += 1
        phase = int((time.monotonic() - self._started) * 80) % self.width
        stride = self.width * 3
        pixels = bytearray(stride * self.height)
        blue = bytes((x + phase) & 255 for x in range(self.width))
        red = bytearray(b"\x28" * self.width)
        bar_start = max(0, phase - 11)
        bar_end = min(self.width, phase + 12)
        red[bar_start:bar_end] = b"\xdc" * (bar_end - bar_start)
        for y in range(self.height):
            offset = y * stride
            end = offset + stride
            pixels[offset:end:3] = blue
            pixels[offset + 1 : end : 3] = bytes(((y + phase) & 255,)) * self.width
            pixels[offset + 2 : end : 3] = red
        return BrowserFrame(
            Frame(self._sequence, self.width, self.height, stride, bytes(pixels)),
            self._sequence,
        )

    async def ack_cdp(self, session_id: int) -> None:
        return

    async def navigate(self, raw_url: str) -> None:
        self.statuses.put_nowait((StatusKind.URL, raw_url))

    async def control(self, action: int) -> None:
        return

    async def pointer(self, x: int, y: int, action: int, button: int, wheel: int) -> None:
        self.statuses.put_nowait((StatusKind.INFO, f"Pointer {x},{y}"))

    async def key(self, virtual_key: int, action: int, modifiers: int, character: int) -> None:
        return

    async def find(self, payload: bytes) -> None:
        return

    async def clipboard(self, payload: bytes) -> bytes | None:
        return None

    async def dialog_reply(self, payload: bytes) -> None:
        return
