import os
from pathlib import Path

from dotenv import load_dotenv
from pyrogram import Client


load_dotenv()

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
SESSION_NAME = os.getenv("SESSION_NAME", "music_user")
SESSION_DIR = os.getenv("SESSION_DIR", "data/sessions")

if not API_ID or not API_HASH:
    raise RuntimeError("Set API_ID and API_HASH in environment variables.")

Path(SESSION_DIR).mkdir(parents=True, exist_ok=True)
session_path = str(Path(SESSION_DIR) / SESSION_NAME)

print(f"Creating Telegram user session: {session_path}")
print("Enter phone and login code when prompted.")

app = Client(
    name=session_path,
    api_id=API_ID,
    api_hash=API_HASH,
)

with app:
    me = app.get_me()
    print(f"Session is ready for: {me.first_name} (@{me.username or 'no_username'})")
