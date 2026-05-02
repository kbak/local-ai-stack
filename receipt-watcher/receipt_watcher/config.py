"""Load env + account/vendor YAML config."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import yaml

POLL_INTERVAL_MINUTES: int = int(os.environ.get("POLL_INTERVAL_MINUTES", "5"))
DRY_RUN: bool = os.environ.get("DRY_RUN", "true").strip().lower() != "false"

# LLM base_url / api_key / model are resolved by stack_shared helpers at
# call time; no need to pin them here. See stack_shared/llm_model.py.

SIGNAL_API_URL: str = os.environ.get("SIGNAL_API_URL", "http://signal-api:8080")
SIGNAL_NUMBER: str | None = os.environ.get("SIGNAL_NUMBER")
BRIEFING_RECIPIENT: str | None = os.environ.get("BRIEFING_RECIPIENT")

INITIAL_LOOKBACK_HOURS = 72
ACCOUNTS_FILE = "/app/accounts.yaml"
VENDORS_FILE = "/app/vendors.yaml"
STATE_FILE = "/data/receipt_state.json"
SHEETS_KEY_FILE = "/app/secrets/sheets-key.json"
AUDIT_LOG_FILE = "/data/receipts.jsonl"


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
class ViaRule:
    """A trusted billing-platform path for receipts that don't come from the
    vendor's own domain (e.g. Fly.io billing via Stripe). All three checks
    must pass for the rule to match — otherwise a Stripe employee with a
    spoofed display name would be enough to forge a vendor.
    """
    sender_domain: str
    sender_local_part_prefix: str  # regex, anchored at start of local-part
    from_name_contains: str        # substring, case-insensitive


@dataclass
class Vendor:
    key: str
    domains: list[str]
    category: str
    currency_hint: str | None
    via: list[ViaRule]


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
        via_rules: list[ViaRule] = []
        for v in raw.get("via", []) or []:
            via_rules.append(
                ViaRule(
                    sender_domain=v["sender_domain"].lower(),
                    sender_local_part_prefix=v["sender_local_part_prefix"],
                    from_name_contains=v["from_name_contains"],
                )
            )
        out.append(
            Vendor(
                key=key,
                domains=[d.lower() for d in raw.get("domains", [])],
                category=raw.get("category", ""),
                currency_hint=raw.get("currency_hint"),
                via=via_rules,
            )
        )
    return out
