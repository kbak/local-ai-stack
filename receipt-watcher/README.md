# receipt-watcher

Multi-account email → Google Sheets receipt pipeline. Scans a whitelist of
vendor senders across any IMAP mailbox (including Gmail via IMAP), extracts
structured receipt data via the local LLM instance, and (eventually) appends
rows to a Google Sheet + archives the source email.

## Current phase: scaffold / dry-run only

This first cut is **read-only**:
- Lists unread inbox messages per account.
- Filters to whitelisted vendor domains (`vendors.yaml`).
- Extracts structured receipt data with the LLM.
- **Logs** what it would write; does not touch Sheets, does not archive.

## Files

- `accounts.yaml` (copy from `accounts.yaml.example`, gitignored) — per-mailbox
  auth + sheet routing.
- `vendors.yaml` — global whitelist of vendor domains + category metadata.
- `receipt_watcher/` — service code.
  - `backends/imap.py` — IMAP backend (works for Gmail, Fastmail, iCloud, etc.)
  - `extract.py` — LLM prompt + receipt parsing.
  - `vendor_match.py` — sender-domain → vendor lookup.
  - `poller.py` — per-account scan loop.
  - `state.py` — persistent `last_seen` + processed-id dedupe.

## Setup

1. For each account, create an app-specific password with your mail provider.
   - **Gmail / Google Workspace**: https://myaccount.google.com/apppasswords
     (requires 2-Step Verification to be enabled). Host: `imap.gmail.com`, port 993.
   - **Fastmail**: Settings → Privacy & Security → App Passwords. Host:
     `imap.fastmail.com`, port 993.
   - **iCloud**: https://appleid.apple.com → Sign-In & Security → App-Specific
     Passwords. Host: `imap.mail.me.com`, port 993.
2. Put each app password in `D:/ai/Stack/receipt-watcher.env` (copy from
   `receipt-watcher.env.example` at the stack root) under the name referenced
   by the account's `password_env`, e.g. `WORK_IMAP_PASSWORD`.
3. Copy `accounts.yaml.example` to `accounts.yaml` and fill in hosts, usernames,
   and sheet IDs.

## Running locally (without Docker)

```
cd receipt-watcher
uv sync
DRY_RUN=true ACCOUNTS_FILE=accounts.yaml VENDORS_FILE=vendors.yaml \
STATE_FILE=./receipt_state.json \
python -m receipt_watcher.main
```

## Running in the stack

```
docker compose up -d --build receipt-watcher
docker logs -f receipt-watcher
```
