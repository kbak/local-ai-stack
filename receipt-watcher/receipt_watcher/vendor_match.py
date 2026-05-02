"""Match a sender email address to a whitelisted vendor.

Two paths:
  1. Direct: sender's domain is on the vendor's `domains` whitelist (or a
     subdomain of one). This is the strong, simple case.
  2. Via billing-platform: vendor declares `via:` rules naming a trusted
     billing platform (e.g. Stripe, Orb). All three checks must pass —
     sender domain match, local-part prefix regex, and From-display-name
     substring — so a person at the billing platform with a spoofed display
     name (or a vendor's-name display from an unrelated domain) can't forge
     a match.
"""

from __future__ import annotations

import re

from .config import Vendor

_ADDR_PATTERN = re.compile(r"<([^>]+)>")
_NAME_PATTERN = re.compile(r"^\s*\"?([^\"<]+?)\"?\s*<[^>]+>\s*$")


def extract_address(from_header: str) -> str:
    """Pull the bare email out of a From header ("Name <a@b.com>" → "a@b.com")."""
    if not from_header:
        return ""
    m = _ADDR_PATTERN.search(from_header)
    if m:
        return m.group(1).strip().lower()
    return from_header.strip().lower()


def extract_display_name(from_header: str) -> str:
    """Pull the display name out of a From header. Returns "" if none."""
    if not from_header:
        return ""
    m = _NAME_PATTERN.match(from_header)
    if m:
        return m.group(1).strip()
    return ""


def domain_of(address: str) -> str:
    _, _, dom = address.rpartition("@")
    return dom.lower()


def local_part_of(address: str) -> str:
    local, _, _ = address.rpartition("@")
    return local.lower()


def _domain_matches(dom: str, listed: str) -> bool:
    return dom == listed or dom.endswith("." + listed)


def match(from_header: str, vendors: list[Vendor]) -> Vendor | None:
    """Return the matching Vendor, or None if the sender isn't on any list."""
    addr = extract_address(from_header)
    dom = domain_of(addr)
    local = local_part_of(addr)
    display = extract_display_name(from_header).lower()
    if not dom:
        return None

    # Path 1: direct domain match.
    for v in vendors:
        for listed in v.domains:
            if _domain_matches(dom, listed):
                return v

    # Path 2: via-rule match. Requires sender domain + local-part prefix +
    # display-name substring, all per a single rule.
    for v in vendors:
        for rule in v.via:
            if not _domain_matches(dom, rule.sender_domain):
                continue
            if not re.match(rule.sender_local_part_prefix, local, re.IGNORECASE):
                continue
            if rule.from_name_contains.lower() not in display:
                continue
            return v
    return None
