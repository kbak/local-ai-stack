"""HTTP transports for untrusted URLs: public addresses only, pinned at connect.

Control-plane clients must not use these transports. Redirects receive the same
connection checks as the initial URL; DNS is never resolved again after approval.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
import ssl

import httpcore
import httpx
from httpcore._backends.auto import AutoBackend
from httpcore._backends.sync import SyncBackend


def public_addresses(host: str, port: int) -> list[str]:
    addresses = list(dict.fromkeys(
        item[4][0] for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    ))
    if not addresses:
        raise ValueError("No destination addresses")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global or ip.is_multicast or ip.is_reserved or (isinstance(ip, ipaddress.IPv6Address) and (
            ip.is_site_local or ip.ipv4_mapped is not None or ip.sixtofour is not None or ip.teredo is not None
            or ip in ipaddress.ip_network("64:ff9b::/96")
            or ip in ipaddress.ip_network("64:ff9b:1::/48")
        )):
            raise ValueError("Untrusted URL resolves to a non-public destination")
    return addresses


class PublicBackend(SyncBackend):
    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        address = public_addresses(host, port)[0]
        return super().connect_tcp(address, port, timeout, local_address, socket_options)


class AsyncPublicBackend(AutoBackend):
    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        address = (await asyncio.to_thread(public_addresses, host, port))[0]
        return await super().connect_tcp(address, port, timeout, local_address, socket_options)


class PublicHTTPTransport(httpx.HTTPTransport):
    def __init__(self):
        # HTTPX exposes transports, while HTTPCore exposes network backends.
        self._pool = httpcore.ConnectionPool(
            ssl_context=ssl.create_default_context(), network_backend=PublicBackend(),
        )


class AsyncPublicHTTPTransport(httpx.AsyncHTTPTransport):
    def __init__(self):
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl.create_default_context(), network_backend=AsyncPublicBackend(),
        )
