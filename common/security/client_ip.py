"""The client's IP address. X-Forwarded-For is believed only when the request comes from a trusted
proxy."""

import ipaddress
from collections.abc import Collection


def _parse(value: str | None) -> str | None:
    try:
        return ipaddress.ip_address((value or "").strip()).compressed
    except ValueError:
        return None


def client_ip(
    remote_addr: str | None, forwarded_for: str | None, trusted_proxies: Collection[str]
) -> str | None:
    remote = _parse(remote_addr)
    trusted = {ip for ip in (_parse(p) for p in trusted_proxies) if ip}
    if remote is None or remote not in trusted or not forwarded_for:
        return remote
    # Walk the chain from the proxy end: the first address that is not one of our proxies is the
    # client.
    for entry in reversed(forwarded_for.split(",")):
        address = _parse(entry)
        if address is None:
            return remote  # a malformed chain is not believed
        if address not in trusted:
            return address
    return remote
