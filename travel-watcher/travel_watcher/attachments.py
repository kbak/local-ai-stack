from __future__ import annotations

import hashlib
from pathlib import Path

from icalendar import Calendar
from stack_shared.mcp_client import call_mcp

from .config import ATTACHMENT_DIR, PDF_MCP_URL
from .mail import Attachment


def extract_attachment_text(attachments: list[Attachment]) -> str:
    chunks: list[str] = []
    root = Path(ATTACHMENT_DIR)
    root.mkdir(parents=True, exist_ok=True)
    for attachment in attachments:
        name = attachment.filename.lower()
        if attachment.mime_type == "application/pdf" or name.endswith(".pdf"):
            digest = hashlib.sha256(attachment.content).hexdigest()
            path = root / f"{digest}.pdf"
            path.write_bytes(attachment.content)
            try:
                text = call_mcp(PDF_MCP_URL, "read_pdf", {"source": str(path)}, timeout=120)
                chunks.append(f"PDF {attachment.filename}:\n{text[:30000]}")
            finally:
                path.unlink(missing_ok=True)
        elif attachment.mime_type in ("text/calendar", "application/ics") or name.endswith(".ics"):
            try:
                cal = Calendar.from_ical(attachment.content)
                lines = []
                for event in cal.walk("VEVENT"):
                    lines.append(" | ".join(
                        f"{key}={event.get(key, '')}" for key in
                        ("SUMMARY", "DTSTART", "DTEND", "LOCATION", "DESCRIPTION")
                    ))
                chunks.append(f"ICS {attachment.filename}:\n" + "\n".join(lines))
            except Exception:
                continue
    return "\n\n".join(chunks)
