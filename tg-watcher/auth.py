"""One-time interactive auth. Run with: docker compose run --rm -it tg-watcher python auth.py"""
import asyncio, getpass, os, sys

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

API_ID   = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
PHONE    = os.environ["TG_PHONE"]
SESSION  = os.environ.get("TG_SESSION_FILE", "/data/tg_session")


async def main():
    client = TelegramClient(SESSION, API_ID, API_HASH)
    await client.connect()

    if await client.is_user_authorized():
        me = await client.get_me()
        print(f"Already logged in as {me.first_name} (@{me.username})", flush=True)
        await client.disconnect()
        return

    await client.send_code_request(PHONE)

    sys.stdout.write("Enter the Telegram code: ")
    sys.stdout.flush()
    code = sys.stdin.readline().strip()

    try:
        await client.sign_in(PHONE, code)
    except SessionPasswordNeededError:
        password = getpass.getpass("2FA password: ")
        await client.sign_in(password=password)

    me = await client.get_me()
    print(f"Success! Logged in as {me.first_name} (@{me.username})", flush=True)
    print(f"Session saved to {SESSION}", flush=True)
    await client.disconnect()


asyncio.run(main())
