"""Hardcoded private-IP obfuscation for outbound API payloads.

Relays must not report internal peers (for example a block producer on
RFC1918 space) to the backend. Matching addresses are replaced with
``0.0.0.0``. Operators can add extra exact addresses via config.
"""

from __future__ import annotations

from collections.abc import Iterable
from ipaddress import ip_address

OBFUSCATED_IP = "0.0.0.0"


def _normalize_extra(extra_ips: Iterable[str] | None) -> set[str]:
    normalized: set[str] = set()
    for raw in extra_ips or ():
        value = str(raw).strip()
        if not value:
            continue
        try:
            normalized.add(str(ip_address(value)))
        except ValueError:
            normalized.add(value)
    return normalized


def should_obfuscate_ip(addr: str | None, extra_ips: Iterable[str] | None = None) -> bool:
    """Return True when ``addr`` must not be sent to the backend."""
    if addr is None:
        return False
    value = str(addr).strip()
    if not value:
        return False

    extras = _normalize_extra(extra_ips)
    try:
        parsed = ip_address(value)
    except ValueError:
        return value in extras

    if str(parsed) in extras:
        return True
    # Private (RFC1918 / ULA), loopback, and link-local are never reported.
    return bool(parsed.is_private or parsed.is_loopback or parsed.is_link_local)


def obfuscate_ip(addr: str | None, extra_ips: Iterable[str] | None = None) -> str:
    """Return ``0.0.0.0`` for private/extra IPs, otherwise the original address."""
    if addr is None:
        return OBFUSCATED_IP
    value = str(addr).strip()
    if should_obfuscate_ip(value, extra_ips):
        return OBFUSCATED_IP
    return value
