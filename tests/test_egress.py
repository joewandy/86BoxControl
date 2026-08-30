import asyncio
import socket
import struct

import pytest

from retrobridge.egress import EgressBlocked, PublicSocksProxy, require_public_address


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.0.2.2", "192.168.1.1", "169.254.169.254", "::1", "fe80::1"],
)
def test_non_public_egress_addresses_are_blocked(address: str) -> None:
    with pytest.raises(EgressBlocked):
        require_public_address(address)


def test_public_egress_addresses_are_allowed() -> None:
    assert require_public_address("93.184.216.34") == "93.184.216.34"
    assert require_public_address("2606:2800:220:1:248:1893:25c8:1946")


async def test_socks_proxy_rejects_loopback_connect() -> None:
    proxy = PublicSocksProxy()
    await proxy.start()
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", proxy.port)
        writer.write(b"\x05\x01\x00")
        await writer.drain()
        assert await reader.readexactly(2) == b"\x05\x00"
        writer.write(b"\x05\x01\x00\x01" + socket.inet_aton("127.0.0.1") + struct.pack("!H", 80))
        await writer.drain()
        assert (await reader.readexactly(10))[1] != 0
        writer.close()
        await writer.wait_closed()
    finally:
        await proxy.close()
