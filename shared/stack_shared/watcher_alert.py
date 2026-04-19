"""Signal alerts for watcher failures — auth expired, network dead, etc.

Usage:

    from stack_shared.watcher_alert import alert_on_failure

    @alert_on_failure("tg-watcher")
    def run_summary() -> None:
        ...

Catches any exception, posts a plain text message to the briefing recipient,
then re-raises so apscheduler still logs the traceback.
"""

from __future__ import annotations

import functools
import logging
import os
import traceback
from typing import Callable, TypeVar

from .signal_client import send_message

log = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., object])


def _alert(watcher_name: str, err: BaseException) -> None:
    try:
        signal_api_url = os.environ.get("SIGNAL_API_URL", "http://signal-api:8080")
        signal_number = os.environ["SIGNAL_NUMBER"]
        recipient = os.environ["BRIEFING_RECIPIENT"]
    except KeyError:
        log.warning("Signal env missing — cannot send failure alert for %s", watcher_name)
        return

    # Last line of the traceback is usually the most informative (the actual exception).
    last = traceback.format_exception_only(type(err), err)[-1].strip()
    body = f"[{watcher_name}] failed: {last}"
    try:
        send_message(body, signal_api_url=signal_api_url, signal_number=signal_number, recipient=recipient)
    except Exception:
        log.exception("Failed to send failure alert for %s", watcher_name)


def alert_on_failure(watcher_name: str) -> Callable[[F], F]:
    """Decorator: on exception, post a Signal alert before re-raising."""

    def decorate(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):  # type: ignore[no-untyped-def]
            try:
                return fn(*args, **kwargs)
            except BaseException as e:
                _alert(watcher_name, e)
                raise

        return wrapper  # type: ignore[return-value]

    return decorate
