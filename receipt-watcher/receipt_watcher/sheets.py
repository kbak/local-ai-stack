"""Google Sheets writer. Appends rows to the expenses sheet and looks up the
most recent payment method per vendor.

Column layout (matches the existing sheet):
    Date | Vendor | Amount | Period | Category | Payment Method | Reimbursed | Details

Formats:
- Date: dd/mm/yyyy (e.g. 07/02/2026)
- Amount: $NN.NN
- Reimbursed: always blank (manual workflow)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from google.oauth2 import service_account
from googleapiclient.discovery import build

from .config import SHEETS_KEY_FILE, SheetTarget
from .extract import Receipt

log = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Column order in the sheet. Keep in sync with the header row.
COLUMNS = ["Date", "Vendor", "Amount", "Period", "Category", "Payment Method", "Reimbursed", "Details"]


@dataclass
class AppendResult:
    appended: bool
    row_number: int | None      # 1-based row number of the new row, if appended
    reason: str                 # human-readable, used in Signal confirmation


class SheetsClient:
    def __init__(self) -> None:
        creds = service_account.Credentials.from_service_account_file(
            SHEETS_KEY_FILE, scopes=_SCOPES,
        )
        self._svc = build("sheets", "v4", credentials=creds, cache_discovery=False)

    def _values(self):
        return self._svc.spreadsheets().values()

    def _read_all(self, target: SheetTarget) -> list[list[str]]:
        resp = self._values().get(
            spreadsheetId=target.id,
            range=target.tab,
            valueRenderOption="FORMATTED_VALUE",
        ).execute()
        return resp.get("values", []) or []

    def last_payment_method_for_vendor(self, target: SheetTarget, vendor_name: str) -> str:
        """Return the Payment Method from the most recent row matching this vendor.

        Empty string if no prior row exists for this vendor.
        """
        rows = self._read_all(target)
        if not rows:
            return ""
        header = rows[0]
        try:
            v_idx = header.index("Vendor")
            pm_idx = header.index("Payment Method")
        except ValueError:
            log.warning("Sheet header missing Vendor or Payment Method column: %r", header)
            return ""

        vendor_lower = vendor_name.strip().lower()
        for row in reversed(rows[1:]):
            if len(row) <= v_idx:
                continue
            if row[v_idx].strip().lower() == vendor_lower:
                return row[pm_idx].strip() if len(row) > pm_idx else ""
        return ""

    def append_receipt(
        self,
        target: SheetTarget,
        vendor_name: str,
        category: str,
        payment_method: str,
        receipt: Receipt,
    ) -> AppendResult:
        row = _build_row(vendor_name, category, payment_method, receipt)
        resp = self._values().append(
            spreadsheetId=target.id,
            range=target.tab,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()

        # `updates.updatedRange` looks like "'NonceArt'!A42:H42" — pull the row number.
        updated_range = (resp.get("updates", {}) or {}).get("updatedRange", "")
        row_num = _parse_row_number(updated_range)
        return AppendResult(appended=True, row_number=row_num, reason="")


def _build_row(vendor_name: str, category: str, payment_method: str, r: Receipt) -> list[str]:
    return [
        _fmt_date(r.date),
        vendor_name,
        _fmt_amount(r.amount),
        r.period,
        category,
        payment_method,
        "",                 # Reimbursed — always blank
        r.details,
    ]


def _fmt_date(iso: str) -> str:
    """Convert YYYY-MM-DD to dd/mm/yyyy. Return original string on failure."""
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return iso


def _fmt_amount(amount: float | None) -> str:
    if amount is None:
        return ""
    return f"${amount:.2f}"


def _parse_row_number(updated_range: str) -> int | None:
    # e.g. "'NonceArt'!A42:H42"  →  42
    if "!" not in updated_range:
        return None
    _, cells = updated_range.split("!", 1)
    # cells like "A42:H42" or "A42"
    first = cells.split(":", 1)[0]
    digits = "".join(ch for ch in first if ch.isdigit())
    try:
        return int(digits) if digits else None
    except ValueError:
        return None
