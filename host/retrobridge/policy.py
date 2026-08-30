"""Navigation and network policy for the isolated host browser."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit


class NavigationBlocked(ValueError):
    """Raised when a URL is not safe for the isolated browser."""


def _blocked_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return not ip.is_global


def validate_navigation_url(url: str) -> str:
    candidate = url.strip()
    if not candidate:
        raise NavigationBlocked("The address is empty")
    if "://" not in candidate:
        candidate = "https://" + candidate
    parsed = urlsplit(candidate)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise NavigationBlocked("Only http and https addresses are allowed")
    if not parsed.hostname or parsed.username or parsed.password:
        raise NavigationBlocked("The address has an invalid host")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost"):
        raise NavigationBlocked("Localhost addresses are blocked")
    try:
        literal_ip = ipaddress.ip_address(host)
    except ValueError:
        literal_ip = None
    if literal_ip is not None and not literal_ip.is_global:
        raise NavigationBlocked("Private and local addresses are blocked")
    return candidate


async def resolve_public_host(url: str) -> None:
    """Reject hostnames that currently resolve to a non-public address."""

    parsed = urlsplit(url)
    host = parsed.hostname
    if not host:
        raise NavigationBlocked("The address has no host")
    try:
        addresses = await asyncio.get_running_loop().getaddrinfo(
            host,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise NavigationBlocked(f"The host could not be resolved: {host}") from exc
    if not addresses:
        raise NavigationBlocked(f"The host could not be resolved: {host}")
    for result in addresses:
        address = result[4][0]
        if _blocked_ip(address):
            raise NavigationBlocked("The address resolves to a private or local network")
