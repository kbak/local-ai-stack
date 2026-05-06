# receipt-watcher

Multi-account email → Google Sheets receipt pipeline. Scans a whitelist of
vendor senders across any IMAP mailbox (including Gmail via IMAP), extracts
structured receipt data via the local LLM, appends rows to a Google Sheet,
archives the source email, and posts a Signal confirmation.

## Pipeline

1. Poll each IMAP account (5 min interval).
2. List unread inbox messages since last `last_seen`.
3. Match sender domain against `vendors.yaml`. Non-matches are ignored silently.
4. For matches, fetch full body + attachments.
5. LLM extracts structured receipt JSON (amount, date, period, details).
6. Resolve payment method:
   1. Last row in the sheet for this vendor.
   2. Else, whatever the email body states.
   3. Else, skip (leave in inbox, Signal alert).
7. Append row to Google Sheet.
8. Archive email (Gmail: remove `\Inbox` label; other IMAP: `MOVE` to `Archive`).
9. Signal confirmation.

Ordering is strict: **sheet append before archive**. If the append fails, the
email stays in inbox and the next poll retries. If archive fails, a row was
already written, so we mark the message as processed to avoid duplicates.

## Setup

### 1. IMAP app passwords

For each account, create an app-specific password:
- **Gmail / Google Workspace**: https://myaccount.google.com/apppasswords
  (2-Step Verification must be on). Host: `imap.gmail.com`, port 993.
- **Fastmail**: Settings → Privacy & Security → App Passwords.
  Host: `imap.fastmail.com`, port 993.
- **iCloud**: https://appleid.apple.com → Sign-In & Security → App-Specific
  Passwords. Host: `imap.mail.me.com`, port 993.

Put each password in `receipt-watcher.env` (copy from
`receipt-watcher.env.example`) under the name referenced by the account's
`password_env`, e.g. `WORK_IMAP_PASSWORD`.

### 2. Google Sheets service account

1. Go to https://console.cloud.google.com/iam-admin/serviceaccounts — pick any
   project (or create one called `receipt-watcher`).
2. Create Service Account → name `receipt-watcher`, skip role grants, done.
3. Click the new account → Keys → Add Key → Create new key → JSON. Download.
4. Save as `receipt-watcher/secrets/sheets-key.json`.
5. Enable the Sheets API for the project:
   https://console.cloud.google.com/apis/library/sheets.googleapis.com
6. Open your expenses Google Sheet → Share → paste the service account's email
   address (looks like `receipt-watcher@your-project.iam.gserviceaccount.com`)
   → give it **Editor** access.

### 3. Account + vendor config

```
cp accounts.yaml.example accounts.yaml      # fill in hosts, usernames, sheet id, tab
cp vendors.yaml.example  vendors.yaml       # fill in your real vendor list
```

### 4. Run

```
MSYS_NO_PATHCONV=1 wsl.exe -d Ubuntu-24.04 -- docker compose -f /mnt/d/ai/local-ai-stack/docker-compose.yml up -d --build receipt-watcher
wsl.exe -d Ubuntu-24.04 -- docker logs -f receipt-watcher
```

Start with `DRY_RUN=true` in `receipt-watcher.env`. Watch logs for a few days;
check `/data/receipts.jsonl` in the container for per-email decisions. When
you're satisfied with extraction quality, set `DRY_RUN=false` and restart the
container.

## Files

- `accounts.yaml` (gitignored) — per-mailbox auth + sheet routing.
- `vendors.yaml` (gitignored) — vendor domain whitelist + category.
- `secrets/sheets-key.json` (gitignored) — Google service account JSON.
- `/data/receipt_state.json` (in the container volume) — `last_seen` +
  processed-message-id dedupe set.
- `/data/receipts.jsonl` (in the container volume) — audit log, one line per
  processed email. Inspect with:
  ```
  wsl.exe -d Ubuntu-24.04 -- docker exec receipt-watcher tail -f /data/receipts.jsonl
  ```
