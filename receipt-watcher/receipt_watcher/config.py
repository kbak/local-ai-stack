"""Load env + account/vendor YAML config."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import yaml

POLL_INTERVAL_MINUTES: int = int(os.environ.get("POLL_INTERVAL_MINUTES", "5"))
DRY_RUN: bool = os.environ.get("DRY_RUN", "true").strip().lower() != "false"

LLM_BASE_URL: str = os.environ["LLM_BASE_URL"]
LLM_API_KEY: str = os.environ.get("LLM_API_KEY", "sk-no-key-required")
LLM_MODEL: str = os.environ["LLM_MODEL"]

INITIAL_LOOKBACK_HOURS = 72
ACCOUNTS_FILE = "/app/accounts.yaml"
VENDORS_FILE = "/app/vendors.yaml"
STATE_FILE = "/data/receipt_state.json"


@dataclass
class SheetTarget:
    id: str
    tab: str


@dataclass
class Account:
    name: str
    auth: dict[str, Any]
    sheet: SheetTarget


@dataclass
class Vendor:
    key: str
    domains: list[str]
    category: str
    currency_hint: str | None


def load_accounts() -> list[Account]:
    with open(ACCOUNTS_FILE) as f:
        data = yaml.safe_load(f) or {}
    out: list[Account] = []
    for raw in data.get("accounts", []):
        out.append(
            Account(
                name=raw["name"],
                auth=raw.get("auth", {}) or {},
                sheet=SheetTarget(
                    id=raw["sheet"]["id"],
                    tab=raw["sheet"].get("tab", ""),
                ),
            )
        )
    return out


def load_vendors() -> list[Vendor]:
    with open(VENDORS_FILE) as f:
        data = yaml.safe_load(f) or {}
    out: list[Vendor] = []
    for key, raw in (data.get("vendors", {}) or {}).items():
        out.append(
            Vendor(
                key=key,
                domains=[d.lower() for d in raw.get("domains", [])],
                category=raw.get("category", ""),
                currency_hint=raw.get("currency_hint"),
            )
        )
    return out
