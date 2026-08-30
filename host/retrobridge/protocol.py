"""Versioned wire protocol shared by the native host and Windows 98 client."""

from __future__ import annotations

import asyncio
import enum
import struct
from dataclasses import dataclass

import lz4.block

MAGIC = b"RB98"
VERSION = 1
APP_VERSION = (0, 3, 0)
HEADER = struct.Struct("<4sHHI")
MAX_PAYLOAD = 2 * 1024 * 1024
TOKEN_LENGTH = 32
PIXEL_BGR24 = 1
PIXEL_RGB565_LZ4 = 2


class ProtocolError(Exception):
    """Raised when a peer sends an invalid protocol message."""


class MessageType(enum.IntEnum):
    HELLO = 1
    WELCOME = 2
    NAVIGATE = 3
    CONTROL = 4
    POINTER = 5
    KEY = 6
    FRAME = 7
    FRAME_ACK = 8
    STATUS = 9
    ERROR = 10
    PING = 11
    PONG = 12
    FIND = 13
    CLIPBOARD = 14
    DIALOG = 15
    DIALOG_REPLY = 16
    DOWNLOAD = 17
    CAPABILITIES = 18
    PEER_INFO = 19
    FAVORITES_STATE = 20
    DOWNLOAD_HISTORY_REQUEST = 21
    DOWNLOAD_HISTORY = 22


class Control(enum.IntEnum):
    BACK = 1
    FORWARD = 2
    RELOAD = 3
    STOP = 4
    HOME = 5


class PointerAction(enum.IntEnum):
    MOVE = 1
    DOWN = 2
    UP = 3
    WHEEL = 4


class KeyAction(enum.IntEnum):
    DOWN = 1
    UP = 2
    CHAR = 3


class StatusKind(enum.IntEnum):
    URL = 1
    TITLE = 2
    LOADING = 3
    INFO = 4
    ERROR = 5


class ClipboardAction(enum.IntEnum):
    COPY = 1
    CUT = 2
    PASTE = 3
    RESULT = 4


class DialogKind(enum.IntEnum):
    ALERT = 1
    CONFIRM = 2
    PROMPT = 3


class DownloadStatus(enum.IntEnum):
    COMPLETE = 1
    OVERSIZE = 2
    FAILED = 3
    BLOCKED = 4


CAP_FIND = 1 << 0
CAP_CLIPBOARD = 1 << 1
CAP_DIALOGS = 1 << 2
CAP_DOWNLOADS = 1 << 3
CAP_POPUP_REDIRECT = 1 << 4
CAP_PEER_INFO = 1 << 5
CAP_FAVORITES_SYNC = 1 << 6
CAP_DOWNLOAD_HISTORY = 1 << 7
DEFAULT_CAPABILITIES = (
    CAP_FIND
    | CAP_CLIPBOARD
    | CAP_DIALOGS
    | CAP_DOWNLOADS
    | CAP_POPUP_REDIRECT
    | CAP_PEER_INFO
    | CAP_FAVORITES_SYNC
    | CAP_DOWNLOAD_HISTORY
)


HELLO = struct.Struct("<32sHHB")
WELCOME = struct.Struct("<HHBB")
POINTER = struct.Struct("<HHBBh")
KEY = struct.Struct("<HBBB")
FRAME_PREFIX = struct.Struct("<IHHIB")
FRAME_ACK = struct.Struct("<I")
PING = struct.Struct("<I")
CAPABILITIES = struct.Struct("<I")
PEER_INFO = struct.Struct("<HHHI")
FAVORITE_PREFIX = struct.Struct("<HH")
DOWNLOAD_RECORD_PREFIX = struct.Struct("<BIIH")
MAX_FAVORITES = 20
MAX_FAVORITE_TITLE_BYTES = 128
MAX_FAVORITE_URL_BYTES = 1024
MAX_DOWNLOAD_HISTORY = 50
MAX_DOWNLOAD_NAME_BYTES = 180


@dataclass(frozen=True)
class Packet:
    message_type: MessageType
    payload: bytes


@dataclass(frozen=True)
class PeerInfo:
    major: int
    minor: int
    patch: int


@dataclass(frozen=True)
class Favorite:
    title: str
    url: str


@dataclass(frozen=True)
class DownloadRecord:
    status: DownloadStatus
    timestamp: int
    size: int
    name: str


@dataclass(frozen=True)
class Frame:
    sequence: int
    width: int
    height: int
    stride: int
    pixels: bytes

    def encode(self, pixel_format: int = PIXEL_BGR24) -> bytes:
        expected = self.stride * self.height
        if len(self.pixels) != expected:
            raise ValueError(f"frame has {len(self.pixels)} bytes, expected {expected}")
        if pixel_format == PIXEL_BGR24:
            stride = self.stride
            payload = self.pixels
        elif pixel_format == PIXEL_RGB565_LZ4:
            if self.stride != self.width * 3:
                raise ValueError("RGB565 encoding requires packed BGR24 source rows")
            stride = self.width * 2
            rgb565 = bytearray(self.width * self.height * 2)
            target = 0
            for source in range(0, len(self.pixels), 3):
                blue = self.pixels[source]
                green = self.pixels[source + 1]
                red = self.pixels[source + 2]
                value = ((red >> 3) << 11) | ((green >> 2) << 5) | (blue >> 3)
                rgb565[target] = value & 0xFF
                rgb565[target + 1] = value >> 8
                target += 2
            payload = lz4.block.compress(rgb565, store_size=False)
        else:
            raise ValueError(f"unsupported frame pixel format: {pixel_format}")
        return FRAME_PREFIX.pack(
            self.sequence,
            self.width,
            self.height,
            stride,
            pixel_format,
        ) + payload


def encode_packet(message_type: MessageType, payload: bytes = b"") -> bytes:
    if len(payload) > MAX_PAYLOAD:
        raise ProtocolError(f"payload is too large: {len(payload)}")
    return HEADER.pack(MAGIC, VERSION, int(message_type), len(payload)) + payload


async def read_packet(reader: asyncio.StreamReader, *, prefix: bytes = b"") -> Packet:
    if len(prefix) > HEADER.size:
        raise ProtocolError("packet prefix is larger than the header")
    raw_header = prefix + await reader.readexactly(HEADER.size - len(prefix))
    magic, version, raw_type, length = HEADER.unpack(raw_header)
    if magic != MAGIC:
        raise ProtocolError("invalid protocol magic")
    if version != VERSION:
        raise ProtocolError(f"unsupported protocol version: {version}")
    if length > MAX_PAYLOAD:
        raise ProtocolError(f"payload exceeds {MAX_PAYLOAD} bytes")
    try:
        message_type = MessageType(raw_type)
    except ValueError as exc:
        raise ProtocolError(f"unknown message type: {raw_type}") from exc
    payload = await reader.readexactly(length)
    return Packet(message_type, payload)


def encode_text(text: str) -> bytes:
    return text.encode("cp1252", errors="replace")


def decode_text(payload: bytes) -> str:
    return payload.decode("cp1252", errors="replace")


def encode_status(kind: StatusKind, text: str) -> bytes:
    return bytes((int(kind),)) + encode_text(text)


def encode_peer_info(version: tuple[int, int, int] = APP_VERSION) -> bytes:
    if any(part < 0 or part > 0xFFFF for part in version):
        raise ProtocolError("peer version component is outside uint16")
    return PEER_INFO.pack(*version, 0)


def decode_peer_info(payload: bytes) -> PeerInfo:
    if len(payload) != PEER_INFO.size:
        raise ProtocolError("PEER_INFO has an invalid size")
    major, minor, patch, _reserved = PEER_INFO.unpack(payload)
    return PeerInfo(major, minor, patch)


def encode_favorites(favorites: list[Favorite]) -> bytes:
    if len(favorites) > MAX_FAVORITES:
        raise ProtocolError(f"too many Favorites: {len(favorites)}")
    payload = bytearray((len(favorites),))
    for favorite in favorites:
        title = encode_text(favorite.title)
        url = encode_text(favorite.url)
        if len(title) > MAX_FAVORITE_TITLE_BYTES:
            raise ProtocolError("Favorite title is too long")
        if not title:
            raise ProtocolError("Favorite title is empty")
        if len(url) > MAX_FAVORITE_URL_BYTES:
            raise ProtocolError("Favorite URL is too long")
        if not url:
            raise ProtocolError("Favorite URL is empty")
        payload.extend(FAVORITE_PREFIX.pack(len(title), len(url)))
        payload.extend(title)
        payload.extend(url)
    return bytes(payload)


def decode_favorites(payload: bytes) -> list[Favorite]:
    if not payload:
        raise ProtocolError("FAVORITES_STATE is empty")
    count = payload[0]
    if count > MAX_FAVORITES:
        raise ProtocolError(f"too many Favorites: {count}")
    offset = 1
    favorites: list[Favorite] = []
    for _ in range(count):
        if len(payload) - offset < FAVORITE_PREFIX.size:
            raise ProtocolError("FAVORITES_STATE record is truncated")
        title_length, url_length = FAVORITE_PREFIX.unpack_from(payload, offset)
        offset += FAVORITE_PREFIX.size
        if not title_length or title_length > MAX_FAVORITE_TITLE_BYTES:
            raise ProtocolError("Favorite title length is invalid")
        if not url_length or url_length > MAX_FAVORITE_URL_BYTES:
            raise ProtocolError("Favorite URL length is invalid")
        end = offset + title_length + url_length
        if end > len(payload):
            raise ProtocolError("FAVORITES_STATE text is truncated")
        title = decode_text(payload[offset : offset + title_length])
        offset += title_length
        url = decode_text(payload[offset : offset + url_length])
        offset += url_length
        favorites.append(Favorite(title=title, url=url))
    if offset != len(payload):
        raise ProtocolError("FAVORITES_STATE has trailing bytes")
    return favorites


def encode_download_history(records: list[DownloadRecord]) -> bytes:
    if len(records) > MAX_DOWNLOAD_HISTORY:
        raise ProtocolError(f"too many download records: {len(records)}")
    payload = bytearray((len(records),))
    for record in records:
        name = encode_text(record.name)
        if not name or len(name) > MAX_DOWNLOAD_NAME_BYTES:
            raise ProtocolError("download name length is invalid")
        if record.timestamp < 0 or record.timestamp > 0xFFFFFFFF:
            raise ProtocolError("download timestamp is outside uint32")
        if record.size < 0 or record.size > 0xFFFFFFFF:
            raise ProtocolError("download size is outside uint32")
        payload.extend(
            DOWNLOAD_RECORD_PREFIX.pack(
                int(record.status), record.timestamp, record.size, len(name)
            )
        )
        payload.extend(name)
    return bytes(payload)


def decode_download_history(payload: bytes) -> list[DownloadRecord]:
    if not payload:
        raise ProtocolError("DOWNLOAD_HISTORY is empty")
    count = payload[0]
    if count > MAX_DOWNLOAD_HISTORY:
        raise ProtocolError(f"too many download records: {count}")
    offset = 1
    records: list[DownloadRecord] = []
    for _ in range(count):
        if len(payload) - offset < DOWNLOAD_RECORD_PREFIX.size:
            raise ProtocolError("DOWNLOAD_HISTORY record is truncated")
        raw_status, timestamp, size, name_length = DOWNLOAD_RECORD_PREFIX.unpack_from(
            payload, offset
        )
        offset += DOWNLOAD_RECORD_PREFIX.size
        try:
            status = DownloadStatus(raw_status)
        except ValueError as exc:
            raise ProtocolError("download status is invalid") from exc
        if not name_length or name_length > MAX_DOWNLOAD_NAME_BYTES:
            raise ProtocolError("download name length is invalid")
        end = offset + name_length
        if end > len(payload):
            raise ProtocolError("DOWNLOAD_HISTORY name is truncated")
        records.append(
            DownloadRecord(status, timestamp, size, decode_text(payload[offset:end]))
        )
        offset = end
    if offset != len(payload):
        raise ProtocolError("DOWNLOAD_HISTORY has trailing bytes")
    return records


def decode_hello(payload: bytes) -> tuple[str, int, int, int]:
    if len(payload) != HELLO.size:
        raise ProtocolError("HELLO has an invalid size")
    raw_token, width, height, pixel_format = HELLO.unpack(payload)
    try:
        token = raw_token.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ProtocolError("HELLO token is not ASCII") from exc
    if len(token) != TOKEN_LENGTH:
        raise ProtocolError("HELLO token has an invalid length")
    if width < 160 or width > 1024 or height < 120 or height > 768:
        raise ProtocolError("HELLO viewport is outside supported bounds")
    if pixel_format not in {PIXEL_BGR24, PIXEL_RGB565_LZ4}:
        raise ProtocolError("HELLO requests an unsupported pixel format")
    return token, width, height, pixel_format
