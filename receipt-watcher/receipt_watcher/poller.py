"""Poll loop: for each account, scan inbox, match vendor, extract, log."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from . import state as state_mod
from .backends import load_backend
from .config import (
    DRY_RUN,
    INITIAL_LOOKBACK_HOURS,
    Account,
    Vendor,
    load_accounts,
    load_vendors,
)
from .extract import extract
from .vendor_match import match as match_vendor

log = logging.getLogger(__name__)


def poll_once() -> None:
    accounts = load_accounts()
    vendors = load_vendors()
    st = state_mod.load()

    for account in accounts:
        try:
            _poll_account(account, vendors, st)
        except Exception:
            log.exception("Account %s: poll failed", account.name)
    state_mod.save(st)


def _poll_account(account: Account, vendors: list[Vendor], st: state_mod.State) -> None:
    acct_state = st.for_account(account.name)
    now = datetime.now(timezone.utc)

    if acct_state.last_seen:
        try:
            since = datetime.fromisoformat(acct_state.last_seen)
        except ValueError:
            since = now - timedelta(hours=INITIAL_LOOKBACK_HOURS)
    else:
        since = now - timedelta(hours=INITIAL_LOOKBACK_HOURS)

    backend = load_backend(account)

    log.info("Account %s: scanning since %s", account.name, since.isoformat())
    headers_list = backend.list_inbox(since=since, unread_only=True)
    log.info("Account %s: %d candidate message(s)", account.name, len(headers_list))

    latest_date = since
    for hdrs in headers_list:
        if hdrs.message_id and acct_state.has_processed(hdrs.message_id):
            continue

        vendor = match_vendor(hdrs.from_addr, vendors)
        if vendor is None:
            # Non-whitelisted sender — ignore silently, don't mark as processed
            # (a future vendor addition should pick it up on next run).
            latest_date = max(latest_date, hdrs.date)
            continue

        log.info(
            "Account %s: MATCH vendor=%s from=%r subject=%r date=%s",
            account.name, vendor.key, hdrs.from_addr, hdrs.subject, hdrs.date.isoformat(),
        )

        try:
            full = backend.fetch_full(hdrs.ref)
        except Exception:
            log.exception("Account %s: fetch_full failed for subject=%r", account.name, hdrs.subject)
            continue

        try:
            receipt = extract(full, vendor)
        except Exception:
            log.exception("Account %s: extract failed for subject=%r", account.name, hdrs.subject)
            continue

        _log_receipt(account, hdrs, vendor, receipt)

        # In dry-run we still record message-id so we don't re-log the same thing
        # every 5 minutes. Real writes/archival come in a later phase.
        if hdrs.message_id:
            acct_state.mark_processed(hdrs.message_id)

        latest_date = max(latest_date, hdrs.date)

    acct_state.last_seen = latest_date.isoformat()


def _log_receipt(account: Account, hdrs, vendor: Vendor, receipt) -> None:
    mode = "DRY-RUN" if DRY_RUN else "LIVE"
    action = "would-add" if DRY_RUN else "adding"
    if not receipt.is_receipt:
        log.info(
            "%s [%s] skip (not-a-receipt) vendor=%s subject=%r",
            mode, account.name, vendor.key, hdrs.subject,
        )
        return
    if receipt.confidence == "low":
        log.info(
            "%s [%s] skip (low-confidence) vendor=%s subject=%r notes=%r",
            mode, account.name, vendor.key, hdrs.subject, receipt.notes,
        )
        return
    log.info(
        "%s [%s] %s row: vendor=%s amount=%s %s date=%s invoice=%s desc=%r → sheet=%s/%s",
        mode, account.name, action,
        receipt.vendor, receipt.amount, receipt.currency,
        receipt.date, receipt.invoice_number, receipt.description,
        account.sheet.id, account.sheet.tab,
    )
