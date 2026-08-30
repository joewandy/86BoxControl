import asyncio
import struct

import lz4.block
import pytest

from retrobridge.protocol import (
    APP_VERSION,
    CAPABILITIES,
    DEFAULT_CAPABILITIES,
    FRAME_PREFIX,
    HEADER,
    HELLO,
    MAGIC,
    MAX_PAYLOAD,
    PIXEL_BGR24,
    PIXEL_RGB565_LZ4,
    VERSION,
    DownloadRecord,
    DownloadStatus,
    Favorite,
    Frame,
    MessageType,
    ProtocolError,
    decode_hello,
    decode_download_history,
    decode_favorites,
    decode_peer_info,
    decode_text,
    encode_packet,
    encode_download_history,
    encode_favorites,
    encode_peer_info,
    encode_text,
    read_packet,
)


def reader_for(data: bytes) -> asyncio.StreamReader:
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()
    return reader


async def test_packet_round_trip() -> None:
    packet = await read_packet(reader_for(encode_packet(MessageType.NAVIGATE, b"example.com")))
    assert packet.message_type is MessageType.NAVIGATE
    assert packet.payload == b"example.com"


async def test_truncated_payload_is_not_accepted_as_a_packet() -> None:
    encoded = encode_packet(MessageType.NAVIGATE, b"example.com")
    with pytest.raises(asyncio.IncompleteReadError):
        await read_packet(reader_for(encoded[:-3]))


@pytest.mark.parametrize(
    "header, message",
    [
        (HEADER.pack(b"NOPE", VERSION, 1, 0), "magic"),
        (HEADER.pack(MAGIC, 99, 1, 0), "version"),
        (HEADER.pack(MAGIC, VERSION, 999, 0), "message type"),
        (HEADER.pack(MAGIC, VERSION, 1, MAX_PAYLOAD + 1), "exceeds"),
    ],
)
async def test_invalid_headers_are_rejected(header: bytes, message: str) -> None:
    with pytest.raises(ProtocolError, match=message):
        await read_packet(reader_for(header))


def test_hello_validation() -> None:
    token = "0123456789abcdef0123456789abcdef"
    payload = HELLO.pack(token.encode("ascii"), 640, 480, PIXEL_BGR24)
    assert decode_hello(payload) == (token, 640, 480, PIXEL_BGR24)


@pytest.mark.parametrize(
    "payload",
    [
        b"short",
        HELLO.pack(b"0" * 32, 100, 480, PIXEL_BGR24),
        HELLO.pack(b"0" * 32, 640, 480, 99),
    ],
)
def test_bad_hello_is_rejected(payload: bytes) -> None:
    with pytest.raises(ProtocolError):
        decode_hello(payload)


def test_frame_wire_shape() -> None:
    pixels = bytes(range(24))
    frame = Frame(7, 4, 2, 12, pixels)
    encoded = frame.encode()
    assert FRAME_PREFIX.unpack(encoded[: FRAME_PREFIX.size]) == (7, 4, 2, 12, PIXEL_BGR24)
    assert encoded[FRAME_PREFIX.size :] == pixels


def test_frame_rgb565_lz4_wire_shape_and_colours() -> None:
    pixels = bytes((0, 0, 255, 0, 255, 0, 255, 0, 0, 255, 255, 255))
    frame = Frame(8, 4, 1, 12, pixels)
    encoded = frame.encode(PIXEL_RGB565_LZ4)
    assert FRAME_PREFIX.unpack(encoded[: FRAME_PREFIX.size]) == (
        8,
        4,
        1,
        8,
        PIXEL_RGB565_LZ4,
    )
    assert lz4.block.decompress(encoded[FRAME_PREFIX.size :], uncompressed_size=8) == bytes(
        (0x00, 0xF8, 0xE0, 0x07, 0x1F, 0x00, 0xFF, 0xFF)
    )


def test_frame_rejects_wrong_pixel_count() -> None:
    with pytest.raises(ValueError, match="expected"):
        Frame(1, 2, 2, 6, b"too short").encode()


def test_frame_rejects_unknown_output_format() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        Frame(1, 1, 1, 3, b"\0\0\0").encode(99)


def test_rgb565_encoding_rejects_padded_source_rows() -> None:
    with pytest.raises(ValueError, match="packed"):
        Frame(1, 1, 1, 4, b"\0\0\0\0").encode(PIXEL_RGB565_LZ4)


def test_cp1252_is_explicit_and_lossy_outside_v1_character_set() -> None:
    assert decode_text(encode_text("café")) == "café"
    assert decode_text(encode_text("snowman ☃")) == "snowman ?"


def test_header_is_exactly_twelve_little_endian_bytes() -> None:
    raw = encode_packet(MessageType.PING, struct.pack("<I", 0x12345678))
    assert len(raw[: HEADER.size]) == 12
    assert raw[-4:] == b"\x78\x56\x34\x12"


def test_capabilities_are_a_fixed_little_endian_bitset() -> None:
    assert CAPABILITIES.pack(DEFAULT_CAPABILITIES) == b"\xff\x00\x00\x00"


def test_peer_info_round_trip_has_fixed_shape() -> None:
    payload = encode_peer_info(APP_VERSION)
    assert len(payload) == 10
    peer = decode_peer_info(payload)
    assert (peer.major, peer.minor, peer.patch) == (0, 3, 0)


def test_favorites_round_trip_is_bounded_cp1252() -> None:
    favorites = [Favorite("Café", "https://example.com/one"), Favorite("Two", "http://two.test/")]
    assert decode_favorites(encode_favorites(favorites)) == favorites


@pytest.mark.parametrize("payload", [b"", b"\x01", b"\x15", b"\x01\x01\x00\x01\x00x"])
def test_malformed_favorites_are_rejected(payload: bytes) -> None:
    with pytest.raises(ProtocolError):
        decode_favorites(payload)


def test_download_history_round_trip() -> None:
    records = [
        DownloadRecord(DownloadStatus.COMPLETE, 1_700_000_000, 1234, "manual.pdf"),
        DownloadRecord(DownloadStatus.FAILED, 1_700_000_001, 0, "bad.exe"),
    ]
    assert decode_download_history(encode_download_history(records)) == records


@pytest.mark.parametrize("payload", [b"", b"\x01", b"\x33", b"\x01\x09" + b"\0" * 10])
def test_malformed_download_history_is_rejected(payload: bytes) -> None:
    with pytest.raises(ProtocolError):
        decode_download_history(payload)
