"""PDF MCP server using pdf-inspector (Rust) for robust Unicode and layout handling."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pdf_inspector
from fastmcp import FastMCP

log = logging.getLogger(__name__)

mcp = FastMCP("pdf-inspector")


def _is_url(source: str) -> bool:
    try:
        r = urlparse(source)
        return r.scheme in ("http", "https")
    except Exception:
        return False


def _fetch_pdf(url: str) -> Path:
    """Download a PDF from a URL to a temp file, return the path."""
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
    suffix = ".pdf"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(resp.content)
    tmp.close()
    return Path(tmp.name)


@mcp.tool()
def read_pdf(
    source: str,
    start_page: int = 1,
    end_page: int | None = None,
) -> str:
    """Extract text from a PDF as Markdown.

    source: absolute file path or HTTP/HTTPS URL to the PDF.
    start_page: first page to extract (1-indexed, default 1).
    end_page: last page inclusive (omit for all pages).
    """
    tmp_path: Path | None = None
    try:
        if _is_url(source):
            tmp_path = _fetch_pdf(source)
            pdf_path = str(tmp_path)
        else:
            pdf_path = source

        # Build pages list if a range is requested
        pages: list[int] | None = None
        if start_page > 1 or end_page is not None:
            # pdf-inspector uses 0-indexed pages
            classification = pdf_inspector.classify_pdf(pdf_path)
            total = classification.page_count
            end = min(end_page, total) if end_page else total
            pages = list(range(start_page - 1, end))

        result = pdf_inspector.process_pdf(pdf_path, pages=pages)

        if result.markdown:
            text = result.markdown
        else:
            # Scanned/image PDF — flag it clearly
            text = (
                f"[pdf-inspector: {result.pdf_type} PDF, "
                f"{result.page_count} pages — OCR required for text extraction]"
            )

        meta = []
        if result.pdf_type:
            meta.append(f"type={result.pdf_type}")
        if result.pages_needing_ocr:
            meta.append(f"pages_needing_ocr={result.pages_needing_ocr}")
        if result.has_encoding_issues:
            meta.append("has_encoding_issues=true")

        if meta:
            text = f"[{', '.join(meta)}]\n\n{text}"

        return text

    finally:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink()


if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8085"))
    log.info("Starting pdf-inspector MCP server on %s:%d", host, port)
    mcp.run(transport="streamable-http", host=host, port=port)
