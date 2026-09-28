"""Bounded, stateless feed/HTML readers. No page scripts are ever executed."""
from __future__ import annotations

import ipaddress
import re
import socket
import unicodedata
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import feedparser
import httpx
from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from stack_shared.rss_fetch import _parse_date

MAX_BYTES = 2_000_000
MAX_ITEMS = 40
DATE_RE = re.compile(r"\b(?:20\d{2}-\d{2}-\d{2}|\d{2}/\d{2}/\d{2}|[A-Z][a-z]{2,8} \d{1,2}, 20\d{2})\b")


def plain_text(value: str, limit: int = 1600) -> str:
    soup = BeautifulSoup(value, "html.parser")
    for node in soup.select("script, style, iframe, object, embed, svg, template, noscript, [hidden], [aria-hidden=true]"):
        node.decompose()
    text = soup.get_text(" ", strip=True)
    text = "".join(c for c in text if not unicodedata.category(c).startswith("C") or c in "\n\t")
    return " ".join(text.split())[:limit]


def safe_url(url: str, allowed_hosts: set[str]) -> str:
    p = urlsplit(url)
    if (p.scheme != "https" or p.hostname not in allowed_hosts or p.username
            or p.password or p.port not in (None, 443)
            or any(ord(c) < 33 or ord(c) > 126 for c in url) or "\\" in url):
        raise ValueError("URL outside configured HTTPS hosts")
    return urlunsplit((p.scheme, p.netloc, p.path, p.query, ""))


def fetch(url: str, allowed_hosts: set[str]) -> str:
    """Validate every redirect; pin public DNS results to prevent DNS rebinding.

    The original hostname is retained for TLS certificate verification and Host.
    Response size is limited after decompression. Environment proxies are disabled.
    """
    with httpx.Client(timeout=20, trust_env=False, follow_redirects=False) as client:
        for _ in range(5):
            url = safe_url(url, allowed_hosts)
            host = urlsplit(url).hostname
            addresses = {item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
            if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
                raise ValueError("Non-public DNS address")
            # Prefer IPv4 on hosts without routed IPv6.
            ip = sorted(addresses, key=lambda a: (":" in a, a))[0]
            target = httpx.URL(url).copy_with(host=ip)
            with client.stream("GET", target, headers={"Host": host, "User-Agent": "WeeklyBlogBrief/1.0"},
                               extensions={"sni_hostname": host}) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers["location"])
                    continue
                response.raise_for_status()
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise ValueError("Response exceeds size limit")
                    chunks.append(chunk)
                return b"".join(chunks).decode("utf-8", errors="replace")
    raise ValueError("Too many redirects")


def dated(value: str, tz: ZoneInfo) -> datetime | None:
    match = DATE_RE.search(value)
    if not match:
        return None
    try:
        return parse_date(match.group(), dayfirst=False, yearfirst=False).replace(tzinfo=tz)
    except (ValueError, OverflowError):
        return None


def html_entries(html: str, source: dict, tz: ZoneInfo) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    entries = []
    for card in soup.select(source["cards"]):
        title = card.select_one(source.get("title", "h2, h3"))
        date_node = card.select_one(source["date"]) if source.get("date") else card
        if title is None or date_node is None:
            continue
        pub = dated(date_node.get("datetime", date_node.get_text(" ", strip=True)), tz)
        if pub is None:
            continue
        link = card if card.name == "a" else card.select_one(source.get("link", "a[href]"))
        # Meeting rows have external speaker/media links, not permalinks.
        href = source["url"] if source.get("homepage_links") else urljoin(source["url"], link.get("href", "") if link else "")
        summary = card.select_one(source["summary"]) if source.get("summary") else None
        entries.append({"title": str(title), "link": href, "summary": str(summary or ""), "published": pub})
    if not entries:
        raise ValueError("No dated entries found; page selectors may need updating")
    return entries


def intent_entries(html: str, source: dict, tz: ZoneInfo, getter=fetch) -> list[dict]:
    """Read Intent Lab's public metadata literals without evaluating JavaScript."""
    soup = BeautifulSoup(html, "html.parser")
    assets = [n.get("href", "") for n in soup.select("link[rel=modulepreload]")]
    asset = next((a for a in assets if re.fullmatch(r"/assets/news-items-[\w-]+\.js", a)), None)
    if not asset:
        raise ValueError("Intent Lab metadata asset not found")
    data = getter(urljoin(source["url"], asset), set(source["hosts"]))
    # Only static strings are accepted. Template interpolation/expressions fail closed.
    field = re.compile(r'(title|dateTime|to|description):(`[^`]*`|"[^"\\]*"|\'[^\'\\]*\')')
    entries = []
    for block in re.findall(r"\{([^{}]*)\}", data):
        values = {key: value[1:-1] for key, value in field.findall(block)}
        if not {"title", "dateTime", "to"} <= values.keys() or any("${" in v for v in values.values()):
            continue
        pub = dated(values["dateTime"], tz)
        if pub:
            entries.append({"title": values["title"], "link": urljoin(source["url"], values["to"]),
                            "summary": values.get("description", ""), "published": pub})
    if not entries:
        raise ValueError("No static Intent Lab blog metadata found")
    return entries


def fetch_source(source: dict, *, now: datetime, tz: ZoneInfo, getter=fetch) -> list[dict]:
    hosts = set(source["hosts"])
    data = getter(source.get("feed", source["url"]), hosts)
    kind = source.get("kind", "html")
    if kind == "feed":
        feed = feedparser.parse(data)
        if not feed.version or (feed.bozo and not feed.entries):
            raise ValueError("Invalid RSS/Atom feed")
        entries = [{"title": e.get("title", ""), "link": urljoin(source["url"], e.get("link", "")),
                    "summary": e.get("summary", e.get("description", "")), "published": _parse_date(e)}
                   for e in feed.entries]
    elif kind == "intent":
        entries = intent_entries(data, source, tz, getter)
    elif kind == "html":
        entries = html_entries(data, source, tz)
    else:
        raise ValueError(f"Unknown source kind: {kind}")
    cutoff = now - timedelta(days=7)
    result, seen = [], set()
    for entry in entries:
        pub = entry["published"]
        if pub is None or not cutoff <= pub <= now:
            continue
        title = plain_text(entry["title"], 240)
        try:
            link = safe_url(entry["link"], hosts)
        except ValueError:
            continue
        identity = (link, title, pub.isoformat())
        if not title or identity in seen:
            continue
        seen.add(identity)
        result.append({"title": title, "link": link, "summary": plain_text(entry["summary"]),
                       "published": pub.astimezone(timezone.utc).isoformat()})
    result.sort(key=lambda e: e["published"], reverse=True)
    if len(result) > MAX_ITEMS:
        raise ValueError("Too many recent entries; refusing to silently truncate coverage")
    return result
