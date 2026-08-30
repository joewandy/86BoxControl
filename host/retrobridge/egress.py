"""Loopback SOCKS5 guard that prevents the renderer reaching private networks."""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import logging
import socket
import struct

LOG = logging.getLogger(__name__)


class EgressBlocked(ConnectionError):
    """Raised when Chrome asks the guard to reach a non-public destination."""


def require_public_address(address: str) -> str:
    candidate = ipaddress.ip_address(address)
    if not candidate.is_global:
        raise EgressBlocked(f"non-public destination blocked: {address}")
    return str(candidate)


class PublicSocksProxy:
    def __init__(self) -> None:
        self._server: asyncio.Server | None = None
        self._connections: set[asyncio.Task[None]] = set()

    @property
    def port(self) -> int:
        if self._server is None or not self._server.sockets:
            raise RuntimeError("egress proxy is not running")
        return int(self._server.sockets[0].getsockname()[1])

    async def start(self) -> None:
        if self._server is not None:
            return
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
        connections = tuple(self._connections)
        for task in connections:
            task.cancel()
        if connections:
            await asyncio.gather(*connections, return_exceptions=True)
        self._connections.clear()
        if self._server is not None:
            await asyncio.wait_for(self._server.wait_closed(), timeout=2)
            self._server = None

    async def _resolve(self, host: str, port: int) -> tuple[str, int]:
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        if literal is not None:
            return require_public_address(str(literal)), literal.version
        try:
            answers = await asyncio.get_running_loop().getaddrinfo(
                host,
                port,
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as exc:
            raise EgressBlocked(f"destination could not be resolved: {host}") from exc
        public: list[tuple[str, int]] = []
        for family, _, _, _, sockaddr in answers:
            address = sockaddr[0]
            try:
                require_public_address(address)
            except EgressBlocked:
                raise EgressBlocked(f"destination resolved to a non-public address: {host}")
            public.append((address, 6 if family == socket.AF_INET6 else 4))
        if not public:
            raise EgressBlocked(f"destination could not be resolved: {host}")
        return public[0]

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._connections.add(task)
        upstream_writer: asyncio.StreamWriter | None = None
        try:
            version, method_count = await asyncio.wait_for(reader.readexactly(2), timeout=5)
            methods = await reader.readexactly(method_count)
            if version != 5 or 0 not in methods:
                writer.write(b"\x05\xff")
                await writer.drain()
                return
            writer.write(b"\x05\x00")
            await writer.drain()
            version, command, reserved, address_type = await reader.readexactly(4)
            if version != 5 or command != 1 or reserved != 0:
                await self._reply(writer, 7)
                return
            if address_type == 1:
                host = socket.inet_ntoa(await reader.readexactly(4))
            elif address_type == 3:
                length = (await reader.readexactly(1))[0]
                host = (await reader.readexactly(length)).decode("idna")
            elif address_type == 4:
                host = socket.inet_ntop(socket.AF_INET6, await reader.readexactly(16))
            else:
                await self._reply(writer, 8)
                return
            port = struct.unpack("!H", await reader.readexactly(2))[0]
            try:
                address, version = await self._resolve(host, port)
                family = socket.AF_INET6 if version == 6 else socket.AF_INET
                upstream_reader, upstream_writer = await asyncio.wait_for(
                    asyncio.open_connection(address, port, family=family),
                    timeout=15,
                )
            except (EgressBlocked, OSError, asyncio.TimeoutError) as exc:
                LOG.info("Egress denied for %s:%s: %s", host, port, exc)
                await self._reply(writer, 2)
                return
            await self._reply(writer, 0)
            await asyncio.gather(
                self._pump(reader, upstream_writer),
                self._pump(upstream_reader, writer),
            )
        except (asyncio.IncompleteReadError, ConnectionError, asyncio.TimeoutError):
            return
        finally:
            if upstream_writer is not None:
                upstream_writer.close()
                with contextlib.suppress(Exception):
                    await upstream_writer.wait_closed()
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
            if task is not None:
                self._connections.discard(task)

    @staticmethod
    async def _reply(writer: asyncio.StreamWriter, result: int) -> None:
        writer.write(bytes((5, result, 0, 1)) + b"\0\0\0\0\0\0")
        await writer.drain()

    @staticmethod
    async def _pump(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while chunk := await reader.read(64 * 1024):
                writer.write(chunk)
                await writer.drain()
        except (ConnectionError, asyncio.CancelledError):
            return
