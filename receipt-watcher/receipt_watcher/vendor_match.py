"""Match a sender email address to a whitelisted vendor by domain."""

from __future__ import annotations

import re

from .config import Vendor

_ADDR_PATTERN = re.compile(r"<([^>]+)>")


def extract_address(from_header: str) -> str:
    """Pull the bare email out of a From header ("Name <a@b.com>" → "a@b.com")."""
    if not from_header:
        return ""
    m = _ADDR_PATTERN.search(from_header)
    if m:
        return m.group(1).strip().lower()
    return from_header.strip().lower()


def domain_of(address: str) -> str:
    _, _, dom = address.rpartition("@")
    return dom.lower()


def match(from_header: str, vendors: list[Vendor]) -> Vendor | None:
    """Return the matching Vendor, or None if the sender isn't on the whitelist.

    Matching rules:
      - Exact domain match, or
      - Subdomain of a listed domain (e.g. "billing.anthropic.com" matches "anthropic.com").
    """
    dom = domain_of(extract_address(from_header))
    if not dom:
        return None
    for v in vendors:
        for listed in v.domains:
            if dom == listed or dom.endswith("." + listed):
                return v
    return None
