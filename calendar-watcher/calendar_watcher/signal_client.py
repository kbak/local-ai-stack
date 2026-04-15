"""Re-export from shared for backwards compatibility within this package."""

from stack_shared.signal_client import send_message as _send_message

from .config import CALENDAR_BRIEFING_RECIPIENT, SIGNAL_API_URL, SIGNAL_NUMBER


def send_message(text: str) -> None:
    _send_message(
        text,
        signal_api_url=SIGNAL_API_URL,
        signal_number=SIGNAL_NUMBER,
        recipient=CALENDAR_BRIEFING_RECIPIENT,
    )
