import asyncio
from typing import Any

import lz4.block
import pytest

from retrobridge.protocol import (
    APP_VERSION,
    CAPABILITIES,
    DEFAULT_CAPABILITIES,
    FRAME_ACK,
    FRAME_PREFIX,
    HELLO,
    KEY,
    PIXEL_BGR24,
    PIXEL_RGB565_LZ4,
    WELCOME,
    DownloadRecord,
    DownloadStatus,
    Favorite,
    Frame,
    MessageType,
    PeerInfo,
    StatusKind,
    encode_packet,
    decode_download_history,
    decode_peer_info,
    encode_favorites,
    encode_peer_info,
    read_packet,
)
from retrobridge.server import RetroBridgeServer

TOKEN = "0123456789abcdef0123456789abcdef"


class FakeSession:
    instances: list["FakeSession"] = []

    def __init__(self, width: int, height: int, **kwargs: Any):
        self.width = width
        self.height = height
        self.statuses: asyncio.Queue[tuple[StatusKind, str]] = asyncio.Queue()
        self.events: asyncio.Queue[tuple[MessageType, bytes]] = asyncio.Queue()
        self.frame_ready = asyncio.Event()
        self.closed = False
        self.acks: list[int] = []
        self.navigations: list[str] = []
        self.peer_info = None
        self.favorites: list[Favorite] = []
        FakeSession.instances.append(self)

    async def start(self) -> None:
        self.statuses.put_nowait((StatusKind.INFO, "fake ready"))

    async def close(self) -> None:
        self.closed = True

    async def next_frame(self):
        await self.frame_ready.wait()
        from retrobridge.browser import BrowserFrame

        return BrowserFrame(Frame(1, self.width, self.height, self.width * 3, b"\0" * (self.width * self.height * 3)), 44)

    async def ack_cdp(self, session_id: int) -> None:
        self.acks.append(session_id)

    async def navigate(self, url: str) -> None:
        self.navigations.append(url)

    async def control(self, action: int) -> None:
        return

    async def pointer(self, *args: Any) -> None:
        return

    async def key(self, *args: Any) -> None:
        return

    async def find(self, payload: bytes) -> None:
        return

    async def clipboard(self, payload: bytes) -> bytes | None:
        return None

    async def dialog_reply(self, payload: bytes) -> None:
        return

    async def update_peer_info(self, peer) -> None:
        self.peer_info = peer

    async def update_favorites(self, favorites: list[Favorite]) -> None:
        self.favorites = favorites

    def download_records(self) -> list[DownloadRecord]:
        return [DownloadRecord(DownloadStatus.COMPLETE, 123, 456, "saved.zip")]


class HangingCloseSession(FakeSession):
    def __init__(self, width: int, height: int, **kwargs: Any):
        super().__init__(width, height, **kwargs)
        self.close_started = asyncio.Event()
        self.aborted = False

    async def close(self) -> None:
        self.close_started.set()
        await asyncio.Event().wait()

    async def abort(self) -> None:
        self.aborted = True


class NoCapabilitySession(FakeSession):
    capabilities = 0


async def open_test_server():
    bridge = RetroBridgeServer(TOKEN, host="127.0.0.1", port=0, session_factory=FakeSession)
    listener = await asyncio.start_server(bridge._handle_client, "127.0.0.1", 0)
    port = listener.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    return listener, reader, writer


async def test_authenticated_handshake_status_and_frame_ack() -> None:
    listener, reader, writer = await open_test_server()
    try:
        writer.write(encode_packet(MessageType.HELLO, HELLO.pack(TOKEN.encode(), 160, 120, PIXEL_BGR24)))
        await writer.drain()
        packets = {
            packet.message_type: packet
            for packet in [await read_packet(reader), await read_packet(reader), await read_packet(reader)]
        }
        assert WELCOME.unpack(packets[MessageType.WELCOME].payload) == (160, 120, PIXEL_BGR24, 5)
        assert CAPABILITIES.unpack(packets[MessageType.CAPABILITIES].payload) == (
            DEFAULT_CAPABILITIES,
        )
        assert packets[MessageType.STATUS].payload.endswith(b"fake ready")
        session = FakeSession.instances[-1]
        session.frame_ready.set()
        frame = await read_packet(reader)
        assert frame.message_type is MessageType.FRAME
        writer.write(encode_packet(MessageType.FRAME_ACK, FRAME_ACK.pack(1)))
        await writer.drain()
        await asyncio.sleep(0.05)
        assert session.acks == [44]
    finally:
        writer.close()
        await writer.wait_closed()
        listener.close()
        await listener.wait_closed()


async def test_rgb565_lz4_handshake_sends_a_compressed_frame() -> None:
    listener, reader, writer = await open_test_server()
    try:
        writer.write(
            encode_packet(
                MessageType.HELLO,
                HELLO.pack(TOKEN.encode(), 160, 120, PIXEL_RGB565_LZ4),
            )
        )
        await writer.drain()
        packets = {
            packet.message_type: packet
            for packet in [await read_packet(reader), await read_packet(reader), await read_packet(reader)]
        }
        assert WELCOME.unpack(packets[MessageType.WELCOME].payload) == (
            160,
            120,
            PIXEL_RGB565_LZ4,
            5,
        )
        session = FakeSession.instances[-1]
        session.frame_ready.set()
        frame = await read_packet(reader)
        sequence, width, height, stride, pixel_format = FRAME_PREFIX.unpack(
            frame.payload[: FRAME_PREFIX.size]
        )
        assert (sequence, width, height, stride, pixel_format) == (
            1,
            160,
            120,
            320,
            PIXEL_RGB565_LZ4,
        )
        assert lz4.block.decompress(
            frame.payload[FRAME_PREFIX.size :],
            uncompressed_size=stride * height,
        ) == b"\0" * (stride * height)
        writer.write(encode_packet(MessageType.FRAME_ACK, FRAME_ACK.pack(sequence)))
        await writer.drain()
        await asyncio.sleep(0.05)
        assert session.acks == [44]
    finally:
        writer.close()
        await writer.wait_closed()
        listener.close()
        await listener.wait_closed()


async def test_session_can_disable_browser_capabilities() -> None:
    bridge = RetroBridgeServer(
        TOKEN,
        host="127.0.0.1",
        port=0,
        session_factory=NoCapabilitySession,
    )
    listener = await asyncio.start_server(bridge._handle_client, "127.0.0.1", 0)
    port = listener.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(
            encode_packet(
                MessageType.HELLO,
                HELLO.pack(TOKEN.encode(), 160, 120, PIXEL_BGR24),
            )
        )
        await writer.drain()
        packets = [await read_packet(reader), await read_packet(reader), await read_packet(reader)]
        capability_packet = next(
            packet for packet in packets if packet.message_type is MessageType.CAPABILITIES
        )
        assert CAPABILITIES.unpack(capability_packet.payload) == (0,)
    finally:
        writer.close()
        await writer.wait_closed()
        listener.close()
        await listener.wait_closed()


async def test_negotiated_appliance_messages_round_trip() -> None:
    listener, reader, writer = await open_test_server()
    try:
        writer.write(
            encode_packet(
                MessageType.HELLO,
                HELLO.pack(TOKEN.encode(), 160, 120, PIXEL_BGR24),
            )
        )
        await writer.drain()
        for _ in range(3):
            await read_packet(reader)
        writer.write(encode_packet(MessageType.PEER_INFO, encode_peer_info(APP_VERSION)))
        writer.write(
            encode_packet(
                MessageType.FAVORITES_STATE,
                encode_favorites([Favorite("Example", "https://example.com/")]),
            )
        )
        writer.write(encode_packet(MessageType.DOWNLOAD_HISTORY_REQUEST))
        await writer.drain()
        replies = [await read_packet(reader), await read_packet(reader)]
        peer_reply = next(item for item in replies if item.message_type is MessageType.PEER_INFO)
        history_reply = next(
            item for item in replies if item.message_type is MessageType.DOWNLOAD_HISTORY
        )
        assert decode_peer_info(peer_reply.payload).minor == 3
        assert decode_download_history(history_reply.payload)[0].name == "saved.zip"
        session = FakeSession.instances[-1]
        for _ in range(50):
            if session.peer_info is not None and session.favorites:
                break
            await asyncio.sleep(0.01)
        assert session.peer_info == PeerInfo(0, 3, 0)
        assert session.favorites == [Favorite("Example", "https://example.com/")]
    finally:
        writer.close()
        await writer.wait_closed()
        listener.close()
        await listener.wait_closed()


async def test_wrong_token_is_rejected_before_session_creation() -> None:
    FakeSession.instances.clear()
    listener, reader, writer = await open_test_server()
    try:
        wrong = b"f" * 32
        writer.write(encode_packet(MessageType.HELLO, HELLO.pack(wrong, 640, 480, PIXEL_BGR24)))
        await writer.drain()
        packet = await read_packet(reader)
        assert packet.message_type is MessageType.ERROR
        assert not FakeSession.instances
    finally:
        writer.close()
        await writer.wait_closed()
        listener.close()
        await listener.wait_closed()


async def test_network_probe_is_echoed_without_starting_browser() -> None:
    FakeSession.instances.clear()
    listener, reader, writer = await open_test_server()
    try:
        writer.write(b"RB98NET1")
        await writer.drain()
        assert await reader.readexactly(8) == b"RB98NET1"
        assert not FakeSession.instances
    finally:
        writer.close()
        await writer.wait_closed()
        listener.close()
        await listener.wait_closed()


async def test_hung_browser_cleanup_cannot_hold_guest_slot_forever() -> None:
    bridge = RetroBridgeServer(
        TOKEN,
        session_factory=HangingCloseSession,
        session_cleanup_timeout=0.01,
    )
    session = HangingCloseSession(160, 120)
    async with bridge._client_lock:
        await bridge._close_session(session)
    assert session.close_started.is_set()
    assert session.aborted
    assert not bridge._client_lock.locked()


def test_server_rejects_non_positive_frame_ack_timeout() -> None:
    with pytest.raises(ValueError, match="frame ACK timeout"):
        RetroBridgeServer(TOKEN, frame_ack_timeout=0)


async def test_frame_ack_timeout_pauses_while_page_dialog_is_open() -> None:
    bridge = RetroBridgeServer(TOKEN, frame_ack_timeout=0.05)
    acknowledgements: asyncio.Queue[int] = asyncio.Queue()
    dialog_idle = asyncio.Event()
    waiting = asyncio.create_task(bridge._wait_for_frame_ack(acknowledgements, dialog_idle))
    await asyncio.sleep(0.1)
    assert not waiting.done()
    dialog_idle.set()
    acknowledgements.put_nowait(7)
    assert await asyncio.wait_for(waiting, timeout=1) == 7


class FailingStartSession(FakeSession):
    async def start(self) -> None:
        raise RuntimeError("Chrome failed to start")


async def test_partially_started_browser_is_closed() -> None:
    bridge = RetroBridgeServer(TOKEN, session_factory=FailingStartSession)
    session = FailingStartSession(160, 120)
    bridge.session_factory = lambda *args, **kwargs: session
    reader = asyncio.StreamReader()

    class Writer:
        def write(self, data: bytes) -> None:
            return

        async def drain(self) -> None:
            return

    with pytest.raises(RuntimeError, match="failed to start"):
        await bridge._run_session(reader, Writer(), 160, 120, PIXEL_BGR24)  # type: ignore[arg-type]
    assert session.closed


class DialogBlockingInputSession(FakeSession):
    def __init__(self, width: int, height: int, **kwargs: Any):
        super().__init__(width, height, **kwargs)
        self.key_started = asyncio.Event()
        self.dialog_replied = asyncio.Event()
        self.key_completed = asyncio.Event()

    async def key(self, *args: Any) -> None:
        self.key_started.set()
        await self.dialog_replied.wait()
        self.key_completed.set()

    async def dialog_reply(self, payload: bytes) -> None:
        self.dialog_replied.set()


async def test_dialog_reply_is_read_while_triggering_key_command_is_waiting() -> None:
    bridge = RetroBridgeServer(
        TOKEN,
        host="127.0.0.1",
        port=0,
        session_factory=DialogBlockingInputSession,
    )
    listener = await asyncio.start_server(bridge._handle_client, "127.0.0.1", 0)
    port = listener.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(encode_packet(MessageType.HELLO, HELLO.pack(TOKEN.encode(), 160, 120, PIXEL_BGR24)))
        await writer.drain()
        await read_packet(reader)
        session = DialogBlockingInputSession.instances[-1]
        writer.write(encode_packet(MessageType.KEY, KEY.pack(ord("A"), 1, 0, 0)))
        await writer.drain()
        await asyncio.wait_for(session.key_started.wait(), timeout=1)
        writer.write(encode_packet(MessageType.DIALOG_REPLY, b"reply"))
        await writer.drain()
        await asyncio.wait_for(session.key_completed.wait(), timeout=1)
    finally:
        writer.close()
        await writer.wait_closed()
        listener.close()
        await listener.wait_closed()


async def wait_for_listener(bridge: RetroBridgeServer) -> int:
    for _ in range(100):
        if bridge._server is not None and bridge._server.sockets:
            return int(bridge._server.sockets[0].getsockname()[1])
        await asyncio.sleep(0.01)
    raise AssertionError("RetroBridge listener did not start")


async def test_shutdown_closes_listener_and_active_guest() -> None:
    bridge = RetroBridgeServer(TOKEN, host="127.0.0.1", port=0, session_factory=FakeSession)
    service = asyncio.create_task(bridge.serve())
    port = await wait_for_listener(bridge)
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(encode_packet(MessageType.HELLO, HELLO.pack(TOKEN.encode(), 160, 120, PIXEL_BGR24)))
    await writer.drain()
    await read_packet(reader)

    await bridge.shutdown()
    await asyncio.gather(service, return_exceptions=True)

    assert FakeSession.instances[-1].closed
    assert not bridge._writers
    assert not bridge._client_tasks
    with pytest.raises(OSError):
        await asyncio.open_connection("127.0.0.1", port)


async def test_one_hundred_guest_reconnects_release_every_session() -> None:
    FakeSession.instances.clear()
    bridge = RetroBridgeServer(TOKEN, host="127.0.0.1", port=0, session_factory=FakeSession)
    service = asyncio.create_task(bridge.serve())
    port = await wait_for_listener(bridge)
    try:
        for expected in range(1, 101):
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(
                encode_packet(
                    MessageType.HELLO,
                    HELLO.pack(TOKEN.encode(), 160, 120, PIXEL_BGR24),
                )
            )
            await writer.drain()
            await read_packet(reader)
            writer.close()
            await writer.wait_closed()
            for _ in range(100):
                if len(FakeSession.instances) == expected and FakeSession.instances[-1].closed:
                    break
                await asyncio.sleep(0.01)
            assert len(FakeSession.instances) == expected
            assert FakeSession.instances[-1].closed
        assert len(FakeSession.instances) == 100
        assert all(session.closed for session in FakeSession.instances)
    finally:
        await bridge.shutdown()
        await asyncio.gather(service, return_exceptions=True)
