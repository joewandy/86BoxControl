import socket

import pytest

from retrobridge.policy import NavigationBlocked, resolve_public_host, validate_navigation_url


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "chrome://settings",
        "http://localhost:8000",
        "http://service.localhost",
        "http://127.0.0.1",
        "http://10.0.2.2",
        "http://192.168.1.10",
        "http://169.254.169.254",
        "http://[::1]",
        "https://user:secret@example.com",
    ],
)
def test_dangerous_navigation_is_blocked(url: str) -> None:
    with pytest.raises(NavigationBlocked):
        validate_navigation_url(url)


def test_https_is_added_to_bare_hostname() -> None:
    assert validate_navigation_url("example.com/path") == "https://example.com/path"


def test_normal_public_urls_are_allowed() -> None:
    assert validate_navigation_url("https://example.com/") == "https://example.com/"


async def test_dns_rebinding_to_private_address_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_getaddrinfo(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.4", 443))]

    loop = __import__("asyncio").get_running_loop()
    monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(NavigationBlocked, match="private"):
        await resolve_public_host("https://example.com")
