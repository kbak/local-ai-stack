"""Poll loop: for each account, scan inbox, match vendor, extract, append to sheet, archive, notify."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from . import audit, state as state_mod
from .backends import load_backend
from .config import (
    DRY_RUN,
    INITIAL_LOOKBACK_HOURS,
    Account,
    Vendor,
    load_accounts,
    load_vendors,
)
from .extract import Receipt, extract
from .notify import notify
from .sheets import SheetsClient
from .vendor_match import match as match_vendor

log = logging.getLogger(__name__)


def poll_once() -> None:
    accounts = load_accounts()
    vendors = load_vendors()
    st = state_mod.load()

    sheets_client: SheetsClient | None = None
    if not DRY_RUN:
        try:
            sheets_client = SheetsClient()
        except Exception:
            log.exception("Sheets client init failed — will retry next poll")
            notify("[receipt-watcher] Sheets client init failed — no rows written this cycle")
            return

    for account in accounts:
        try:
            _poll_account(account, vendors, st, sheets_client)
        except Exception:
            log.exception("Account %s: poll failed", account.name)
    state_mod.save(st)


def _poll_account(
    account: Account,
    vendors: list[Vendor],
    st: state_mod.State,
    sheets_client: SheetsClient | None,
) -> None:
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

        _process(account, backend, hdrs, vendor, receipt, sheets_client, acct_state)
        latest_date = max(latest_date, hdrs.date)

    acct_state.last_seen = latest_date.isoformat()


def _process(
    account: Account,
    backend,
    hdrs,
    vendor: Vendor,
    receipt: Receipt,
    sheets_client: SheetsClient | None,
    acct_state: state_mod.AccountState,
) -> None:
    vendor_name = vendor.key.title()
    subject = hdrs.subject

    if not receipt.is_receipt:
        log.info("[%s] skip (not-a-receipt) vendor=%s subject=%r", account.name, vendor.key, subject)
        audit.append({
            "account": account.name, "vendor": vendor.key, "action": "skip_not_receipt",
            "subject": subject, "message_id": hdrs.message_id,
        })
        if hdrs.message_id:
            acct_state.mark_processed(hdrs.message_id)
        return

    if receipt.confidence == "low" or receipt.amount is None or not receipt.date:
        log.info("[%s] skip (low-confidence) vendor=%s subject=%r", account.name, vendor.key, subject)
        notify(f"⚠️ {vendor_name}: couldn't parse receipt ({subject!r}) — left in inbox for review")
        audit.append({
            "account": account.name, "vendor": vendor.key, "action": "skip_low_confidence",
            "subject": subject, "message_id": hdrs.message_id, "raw": receipt.raw,
        })
        # Do NOT mark processed — we want to retry if the user later reads+re-unreads it? No — leaving in
        # inbox IS the marker. But if we don't mark processed, next poll will re-notify every 5 min until
        # the user opens it. Mark it so we don't spam.
        if hdrs.message_id:
            acct_state.mark_processed(hdrs.message_id)
        return

    # Resolve payment method.
    payment_method = _resolve_payment_method(sheets_client, account, vendor_name, receipt)
    if not payment_method:
        log.info("[%s] skip (no payment method) vendor=%s subject=%r", account.name, vendor.key, subject)
        notify(
            f"⚠️ {vendor_name} ${receipt.amount:.2f}: no prior payment method for this vendor and none "
            f"stated in email — left in inbox for review"
        )
        audit.append({
            "account": account.name, "vendor": vendor.key, "action": "skip_no_payment_method",
            "subject": subject, "message_id": hdrs.message_id, "amount": receipt.amount,
        })
        if hdrs.message_id:
            acct_state.mark_processed(hdrs.message_id)
        return

    if DRY_RUN or sheets_client is None:
        log.info(
            "DRY-RUN [%s] would-add row: vendor=%s amount=%.2f date=%s period=%s pm=%s details=%r",
            account.name, vendor_name, receipt.amount, receipt.date, receipt.period, payment_method, receipt.details,
        )
        audit.append({
            "account": account.name, "vendor": vendor.key, "action": "dry_run_would_add",
            "subject": subject, "message_id": hdrs.message_id,
            "vendor_name": vendor_name, "amount": receipt.amount, "date": receipt.date,
            "period": receipt.period, "category": vendor.category, "payment_method": payment_method,
            "details": receipt.details,
        })
        if hdrs.message_id:
            acct_state.mark_processed(hdrs.message_id)
        return

    # Live path: append then archive. Never archive if append fails.
    try:
        result = sheets_client.append_receipt(
            account.sheet, vendor_name, vendor.category, payment_method, receipt,
        )
    except Exception as e:
        log.exception("[%s] Sheets append failed for vendor=%s subject=%r", account.name, vendor.key, subject)
        notify(f"❌ {vendor_name} ${receipt.amount:.2f}: Sheets append failed ({type(e).__name__}) — left in inbox, will retry")
        audit.append({
            "account": account.name, "vendor": vendor.key, "action": "append_failed",
            "subject": subject, "message_id": hdrs.message_id, "error": repr(e),
        })
        # NOT marked processed — next poll retries.
        return

    log.info(
        "[%s] ADDED vendor=%s amount=%.2f row=%s", account.name, vendor_name, receipt.amount, result.row_number,
    )

    # Archive. A failure here is noisy but we've already written the row, so we
    # DO mark the message processed to avoid a duplicate row on retry.
    try:
        backend.archive(hdrs.ref)
        archived = True
    except Exception as e:
        log.exception("[%s] archive failed for uid=%s", account.name, hdrs.ref.backend_id)
        notify(
            f"✅ {vendor_name} ${receipt.amount:.2f} → row {result.row_number}  "
            f"(⚠️ archive failed: {type(e).__name__})"
        )
        archived = False
    else:
        notify(f"✅ {vendor_name} ${receipt.amount:.2f} → row {result.row_number}")

    audit.append({
        "account": account.name, "vendor": vendor.key, "action": "added",
        "subject": subject, "message_id": hdrs.message_id,
        "vendor_name": vendor_name, "amount": receipt.amount, "date": receipt.date,
        "period": receipt.period, "category": vendor.category, "payment_method": payment_method,
        "details": receipt.details, "row_number": result.row_number, "archived": archived,
    })

    if hdrs.message_id:
        acct_state.mark_processed(hdrs.message_id)


def _resolve_payment_method(
    sheets_client: SheetsClient | None,
    account: Account,
    vendor_name: str,
    receipt: Receipt,
) -> str:
    """Resolve payment method with fallback chain: last row for vendor → email body → skip."""
    if sheets_client is not None:
        try:
            last = sheets_client.last_payment_method_for_vendor(account.sheet, vendor_name)
            if last:
                return last
        except Exception:
            log.exception("Sheets lookup for last payment method failed — falling back to email body")
    # Dry-run or no prior row: try the email body.
    return receipt.payment_method_from_email.strip()
