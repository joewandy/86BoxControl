"""Authenticated single-guest RetroBridge TCP server."""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import logging
from collections.abc import Callable
from typing import Any

from .browser import ChromeSession
from .policy import NavigationBlocked
from .protocol import (
    APP_VERSION,
    CAPABILITIES,
    CAP_DOWNLOAD_HISTORY,
    CAP_FAVORITES_SYNC,
    CAP_PEER_INFO,
    DEFAULT_CAPABILITIES,
    FRAME_ACK,
    KEY,
    POINTER,
    PING,
    WELCOME,
    Control,
    KeyAction,
    MessageType,
    PointerAction,
    ProtocolError,
    decode_favorites,
    decode_hello,
    decode_peer_info,
    decode_text,
    encode_download_history,
    encode_packet,
    encode_peer_info,
    encode_status,
    read_packet,
)

LOG = logging.getLogger(__name__)
NETWORK_PROBE = b"RB98NET1"


class RetroBridgeServer:
    def __init__(
        self,
        token: str,
        *,
        host: str = "127.0.0.1",
        port: int = 9866,
        headed: bool = False,
        session_factory: Callable[..., Any] = ChromeSession,
        session_cleanup_timeout: float = 5.0,
        session_start_timeout: float = 20.0,
        frame_ack_timeout: float = 10.0,
    ):
        if len(token) != 32 or any(c not in "0123456789abcdef" for c in token):
            raise ValueError("token must be exactly 32 lowercase hexadecimal characters")
        self.token = token
        self.host = host
        self.port = port
        self.headed = headed
        self.session_factory = session_factory
        if session_cleanup_timeout <= 0:
            raise ValueError("session cleanup timeout must be positive")
        if session_start_timeout <= 0:
            raise ValueError("session start timeout must be positive")
        if frame_ack_timeout <= 0:
            raise ValueError("frame ACK timeout must be positive")
        self.session_cleanup_timeout = session_cleanup_timeout
        self.session_start_timeout = session_start_timeout
        self.frame_ack_timeout = frame_ack_timeout
        self._client_lock = asyncio.Lock()
        self._server: asyncio.Server | None = None
        self._client_tasks: set[asyncio.Task[Any]] = set()
        self._writers: set[asyncio.StreamWriter] = set()

    async def serve(self) -> None:
        self._server = await asyncio.start_server(self._handle_client, self.host, self.port)
        addresses = ", ".join(str(sock.getsockname()) for sock in self._server.sockets or [])
        LOG.info("RetroBridge listening on %s", addresses)
        try:
            async with self._server:
                await self._server.serve_forever()
        finally:
            self._server.close()
            await self._server.wait_closed()

    async def shutdown(self) -> None:
        """Stop accepting guests and release every active renderer session."""

        if self._server is not None:
            self._server.close()
        for writer in tuple(self._writers):
            writer.close()
        tasks = tuple(self._client_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=(self.session_cleanup_timeout * 3) + 2,
                )
            except asyncio.TimeoutError:
                LOG.error("Timed out while shutting down active guest sessions")
        if self._server is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._server.wait_closed(), timeout=2)

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._client_tasks.add(task)
        self._writers.add(writer)
        peer = writer.get_extra_info("peername")
        LOG.info("Guest connected from %s", peer)
        try:
            prefix = await asyncio.wait_for(reader.readexactly(len(NETWORK_PROBE)), timeout=10)
            if prefix == NETWORK_PROBE:
                writer.write(NETWORK_PROBE)
                await writer.drain()
                LOG.info("Network probe passed from %s", peer)
                return
            hello = await asyncio.wait_for(read_packet(reader, prefix=prefix), timeout=10)
            if hello.message_type is not MessageType.HELLO:
                raise ProtocolError("first message must be HELLO")
            token, width, height, pixel_format = decode_hello(hello.payload)
            if not hmac.compare_digest(token, self.token):
                await self._write(writer, MessageType.ERROR, b"Authentication failed")
                return
            if self._client_lock.locked():
                await self._write(writer, MessageType.ERROR, b"Another guest is connected")
                return
            async with self._client_lock:
                await self._run_session(reader, writer, width, height, pixel_format)
        except (asyncio.IncompleteReadError, ConnectionError):
            LOG.info("Guest disconnected: %s", peer)
        except (ProtocolError, asyncio.TimeoutError) as exc:
            LOG.warning("Protocol error from %s: %s", peer, exc)
            with contextlib.suppress(Exception):
                await self._write(writer, MessageType.ERROR, str(exc).encode("cp1252", "replace"))
        finally:
            self._writers.discard(writer)
            if task is not None:
                self._client_tasks.discard(task)
            writer.close()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(
                    writer.wait_closed(),
                    timeout=self.session_cleanup_timeout,
                )

    async def _run_session(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        width: int,
        height: int,
        pixel_format: int,
    ) -> None:
        session = self.session_factory(width, height, headed=self.headed, max_fps=5)
        capabilities = getattr(session, "capabilities", DEFAULT_CAPABILITIES)
        write_lock = asyncio.Lock()
        acknowledgements: asyncio.Queue[int] = asyncio.Queue(maxsize=1)
        commands: asyncio.Queue[tuple[str, Callable[[], Any], float]] = asyncio.Queue(maxsize=128)
        tasks: list[asyncio.Task[Any]] = []

        async def recoverable(label: str, operation: Any, timeout: float = 35) -> None:
            try:
                await asyncio.wait_for(operation, timeout=timeout)
            except NavigationBlocked as exc:
                LOG.info("Guest command %s blocked: %s", label, exc)
                await self._write(
                    writer,
                    MessageType.ERROR,
                    str(exc).encode("cp1252", "replace"),
                    write_lock,
                )
            except (ValueError, RuntimeError) as exc:
                LOG.info("Guest command %s failed: %s", label, exc)
                await self._write(
                    writer,
                    MessageType.ERROR,
                    f"{label} failed: {exc}".encode("cp1252", "replace"),
                    write_lock,
                )
            except asyncio.TimeoutError:
                LOG.warning("Guest command %s timed out", label)
                await self._write(
                    writer,
                    MessageType.ERROR,
                    f"{label} timed out".encode("cp1252"),
                    write_lock,
                )

        async def command_worker() -> None:
            while True:
                label, factory, timeout = await commands.get()
                try:
                    if label == "Navigation":
                        LOG.info("Starting guest navigation")
                    await recoverable(label, factory(), timeout)
                    if label == "Navigation":
                        LOG.info("Finished guest navigation")
                finally:
                    commands.task_done()

        async def enqueue(label: str, factory: Callable[[], Any], timeout: float = 35) -> None:
            try:
                commands.put_nowait((label, factory, timeout))
            except asyncio.QueueFull as exc:
                raise ProtocolError("browser command queue is full") from exc

        async def receive() -> None:
            while True:
                packet = await read_packet(reader)
                if packet.message_type is MessageType.FRAME_ACK:
                    if len(packet.payload) != FRAME_ACK.size:
                        raise ProtocolError("FRAME_ACK has an invalid size")
                    sequence = FRAME_ACK.unpack(packet.payload)[0]
                    if acknowledgements.full():
                        acknowledgements.get_nowait()
                    acknowledgements.put_nowait(sequence)
                elif packet.message_type is MessageType.NAVIGATE:
                    target = decode_text(packet.payload)
                    LOG.info("Guest requested navigation")
                    await enqueue("Navigation", lambda target=target: session.navigate(target))
                elif packet.message_type is MessageType.CONTROL:
                    if len(packet.payload) != 1:
                        raise ProtocolError("CONTROL has an invalid size")
                    try:
                        action = Control(packet.payload[0])
                    except ValueError as exc:
                        raise ProtocolError("CONTROL has an invalid action") from exc
                    await enqueue(
                        "Browser control",
                        lambda action=action: session.control(int(action)),
                    )
                elif packet.message_type is MessageType.POINTER:
                    if len(packet.payload) != POINTER.size:
                        raise ProtocolError("POINTER has an invalid size")
                    x, y, raw_action, button, wheel = POINTER.unpack(packet.payload)
                    try:
                        action = PointerAction(raw_action)
                    except ValueError as exc:
                        raise ProtocolError("POINTER has an invalid action") from exc
                    await enqueue(
                        "Pointer input",
                        lambda x=x, y=y, action=action, button=button, wheel=wheel: session.pointer(
                            x, y, int(action), button, wheel
                        ),
                        130,
                    )
                elif packet.message_type is MessageType.KEY:
                    if len(packet.payload) != KEY.size:
                        raise ProtocolError("KEY has an invalid size")
                    vkey, raw_action, modifiers, character = KEY.unpack(packet.payload)
                    try:
                        action = KeyAction(raw_action)
                    except ValueError as exc:
                        raise ProtocolError("KEY has an invalid action") from exc
                    await enqueue(
                        "Keyboard input",
                        lambda vkey=vkey, action=action, modifiers=modifiers, character=character: session.key(
                            vkey, int(action), modifiers, character
                        ),
                        130,
                    )
                elif packet.message_type is MessageType.FIND:
                    payload = packet.payload
                    await enqueue("Find", lambda payload=payload: session.find(payload))
                elif packet.message_type is MessageType.CLIPBOARD:
                    try:
                        response = await asyncio.wait_for(session.clipboard(packet.payload), timeout=10)
                    except (ValueError, RuntimeError, asyncio.TimeoutError) as exc:
                        await self._write(
                            writer,
                            MessageType.ERROR,
                            f"Clipboard failed: {exc}".encode("cp1252", "replace"),
                            write_lock,
                        )
                    else:
                        if response is not None:
                            await self._write(writer, MessageType.CLIPBOARD, response, write_lock)
                elif packet.message_type is MessageType.DIALOG_REPLY:
                    await recoverable("Dialog reply", session.dialog_reply(packet.payload))
                elif packet.message_type is MessageType.PEER_INFO:
                    if not capabilities & CAP_PEER_INFO:
                        raise ProtocolError("PEER_INFO was not negotiated")
                    peer = decode_peer_info(packet.payload)
                    await self._write(
                        writer,
                        MessageType.PEER_INFO,
                        encode_peer_info(APP_VERSION),
                        write_lock,
                    )
                    update_peer_info = getattr(session, "update_peer_info", None)
                    if update_peer_info is not None:
                        await enqueue(
                            "Peer information",
                            lambda peer=peer: update_peer_info(peer),
                            10,
                        )
                elif packet.message_type is MessageType.FAVORITES_STATE:
                    if not capabilities & CAP_FAVORITES_SYNC:
                        raise ProtocolError("FAVORITES_STATE was not negotiated")
                    favorites = decode_favorites(packet.payload)
                    update_favorites = getattr(session, "update_favorites", None)
                    if update_favorites is not None:
                        await enqueue(
                            "Favorites update",
                            lambda favorites=favorites: update_favorites(favorites),
                            10,
                        )
                elif packet.message_type is MessageType.DOWNLOAD_HISTORY_REQUEST:
                    if not capabilities & CAP_DOWNLOAD_HISTORY:
                        raise ProtocolError("DOWNLOAD_HISTORY was not negotiated")
                    if packet.payload:
                        raise ProtocolError("DOWNLOAD_HISTORY_REQUEST must be empty")
                    download_records = getattr(session, "download_records", None)
                    records = download_records() if download_records is not None else []
                    await self._write(
                        writer,
                        MessageType.DOWNLOAD_HISTORY,
                        encode_download_history(records),
                        write_lock,
                    )
                elif packet.message_type is MessageType.PING:
                    if len(packet.payload) != PING.size:
                        raise ProtocolError("PING has an invalid size")
                    await self._write(writer, MessageType.PONG, packet.payload, write_lock)
                else:
                    raise ProtocolError(f"unexpected guest message: {packet.message_type.name}")

        async def send_frames() -> None:
            displayed = 0
            wire_bytes = 0
            started = asyncio.get_running_loop().time()
            try:
                while True:
                    browser_frame = await session.next_frame()
                    sequence = browser_frame.frame.sequence
                    encoded_frame = browser_frame.frame.encode(pixel_format)
                    await self._write(
                        writer,
                        MessageType.FRAME,
                        encoded_frame,
                        write_lock,
                    )
                    try:
                        ack = await self._wait_for_frame_ack(
                            acknowledgements,
                            getattr(session, "dialog_idle", None),
                        )
                    except asyncio.TimeoutError as exc:
                        raise ProtocolError("guest stopped acknowledging frames") from exc
                    if ack != sequence:
                        raise ProtocolError(f"expected frame ACK {sequence}, received {ack}")
                    await session.ack_cdp(browser_frame.cdp_session_id)
                    displayed += 1
                    wire_bytes += len(encoded_frame)
                    if displayed % 50 == 0:
                        elapsed = asyncio.get_running_loop().time() - started
                        LOG.info(
                            "Frame stream displayed %d frames in %.1fs "
                            "(%.2f FPS, %.1f KiB/frame)",
                            displayed,
                            elapsed,
                            displayed / elapsed,
                            wire_bytes / displayed / 1024,
                        )
            finally:
                if displayed:
                    elapsed = asyncio.get_running_loop().time() - started
                    LOG.info(
                        "Frame stream ended after %d frames in %.1fs "
                        "(%.2f FPS, %.1f KiB/frame)",
                        displayed,
                        elapsed,
                        displayed / elapsed,
                        wire_bytes / displayed / 1024,
                    )

        async def send_statuses() -> None:
            while True:
                kind, text = await session.statuses.get()
                await self._write(writer, MessageType.STATUS, encode_status(kind, text), write_lock)

        async def send_events() -> None:
            events = getattr(session, "events", None)
            if events is None:
                await asyncio.Event().wait()
            while True:
                message_type, payload = await events.get()
                await self._write(writer, message_type, payload, write_lock)

        try:
            await asyncio.wait_for(session.start(), timeout=self.session_start_timeout)
            await self._write(
                writer,
                MessageType.WELCOME,
                WELCOME.pack(width, height, pixel_format, 5),
                write_lock,
            )
            await self._write(
                writer,
                MessageType.CAPABILITIES,
                CAPABILITIES.pack(capabilities),
                write_lock,
            )
            tasks = [
                asyncio.create_task(receive()),
                asyncio.create_task(command_worker()),
                asyncio.create_task(send_frames()),
                asyncio.create_task(send_statuses()),
                asyncio.create_task(send_events()),
            ]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
            for task in done:
                exception = task.exception()
                if exception is not None:
                    raise exception
        finally:
            for task in tasks:
                task.cancel()
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=self.session_cleanup_timeout,
                )
            except asyncio.TimeoutError:
                LOG.warning("Guest task cleanup timed out")
            await self._close_session(session)

    async def _wait_for_frame_ack(
        self,
        acknowledgements: asyncio.Queue[int],
        dialog_idle: asyncio.Event | None,
    ) -> int:
        remaining = self.frame_ack_timeout
        while remaining > 0:
            if dialog_idle is not None and not dialog_idle.is_set():
                await dialog_idle.wait()
                continue
            started = asyncio.get_running_loop().time()
            try:
                return await asyncio.wait_for(
                    acknowledgements.get(),
                    timeout=min(0.25, remaining),
                )
            except asyncio.TimeoutError:
                if dialog_idle is None or dialog_idle.is_set():
                    remaining -= asyncio.get_running_loop().time() - started
        raise asyncio.TimeoutError

    async def _close_session(self, session: Any) -> None:
        try:
            await asyncio.wait_for(session.close(), timeout=self.session_cleanup_timeout)
        except asyncio.TimeoutError:
            LOG.warning("Browser cleanup timed out; releasing the guest slot")
            abort = getattr(session, "abort", None)
            if abort is not None:
                try:
                    await asyncio.wait_for(
                        abort(),
                        timeout=max(8.0, self.session_cleanup_timeout),
                    )
                except asyncio.TimeoutError:
                    LOG.error("Forced browser cleanup timed out")
                except Exception:
                    LOG.exception("Forced browser cleanup failed")
        except Exception:
            LOG.exception("Browser cleanup failed")

    @staticmethod
    async def _write(
        writer: asyncio.StreamWriter,
        message_type: MessageType,
        payload: bytes = b"",
        lock: asyncio.Lock | None = None,
    ) -> None:
        if lock is None:
            writer.write(encode_packet(message_type, payload))
            await writer.drain()
            return
        async with lock:
            writer.write(encode_packet(message_type, payload))
            await writer.drain()
