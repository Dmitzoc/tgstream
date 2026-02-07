# Telegram Music Stream Bot (voice chat, VPS-ready)

The bot searches for music by title and streams it into a Telegram group call.

## How it works

1. A regular bot (Bot API) handles commands via `BOT_TOKEN`.
2. A userbot session (a normal Telegram account) joins the voice chat and streams audio.
3. When you run `/play <title>`, the bot searches via `yt-dlp`, puts the track into the queue, and if nothing is playing, starts streaming.
4. The queue is per chat, so different groups do not interfere with each other.
5. `/pause` and `/resume` control the current stream, `/skip` moves to the next track, `/stop` clears the queue and leaves the call.

## Important

Full voice chat streaming cannot be done with the Bot API alone.  
Working setup for calls: a bot for commands + a userbot session to connect to the call.

In this project it is already implemented:
- `BOT_TOKEN` accepts commands
- the userbot (normal Telegram account) joins the voice chat and streams audio

## Where to get API_ID, API_HASH, and BOT_TOKEN

### API_ID and API_HASH (Telegram API)

1. Open the Telegram developer site.

```
https://my.telegram.org
```

2. Log in with your Telegram account.
3. Open the `API development tools` section.
4. Create an app: fill `App title` and `Short name` with any clear values.
5. Save `API_ID` and `API_HASH` and put them into `.env`.

### BOT_TOKEN (command bot)

1. Open @BotFather in Telegram.
2. Send `/newbot`.
3. Choose the bot name and username.
4. Copy the generated `BOT_TOKEN` and put it into `.env`.

### Userbot (normal Telegram account)

1. Use a regular Telegram account that will join the voice chat.
2. Add this account to the group.
3. Give it permission to join the voice chat (and ideally `Manage video chats`).
4. Create a session for this account on the first run.

## How to create a userbot session

Option 1. Using Docker (recommended for VPS):

```bash
sudo docker-compose run --rm auth
```

Enter the phone number, Telegram code, and 2FA password (if enabled).  
The session will be saved to `data/sessions`.

Option 2. Local Python:

```bash
python create_session.py
```

Requires Python installed and `.env` filled in.

## Commands

- `/play <title>` - search and add to queue
- `/pause` - pause
- `/resume` or `/unpause` - resume
- `/skip` - skip current track
- `/reconnect` - manually start reconnect
- `/queue` - show queue
- `/now` - current track
- `/stop` - stop and clear queue
- `/ping` - healthcheck
- `/POMOGITE` - help and command list

Pause/resume works only in a group when playback is active.

## Environment variables

Create `.env`:

```env
API_ID=123456
API_HASH=your_api_hash
BOT_TOKEN=123456:ABCDEF
SESSION_NAME=music_user
SESSION_DIR=data/sessions
LOG_LEVEL=INFO
PRIVILEGED_USER_IDS=123456789,987654321
RECONNECT_DELAY_SECONDS=8
RECONNECT_MAX_ATTEMPTS=0
```

`PRIVILEGED_USER_IDS` - comma-separated user IDs allowed to use `/skip` and `/reconnect`.  
Group admins can also use `/skip` and `/reconnect`.  
`RECONNECT_MAX_ATTEMPTS=0` means infinite reconnect attempts.

## VPS deploy with Docker

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-plugin
sudo systemctl enable --now docker

mkdir -p /opt/tgstream
cd /opt/tgstream
# copy the project files here

cp .env.example .env
# fill in .env
```

### 1. Create user session (one time)

```bash
sudo docker-compose run --rm auth
```

Enter the phone number, Telegram code, and 2FA password (if enabled).  
The session will be saved to `data/sessions`.

### 2. Start the bot

```bash
sudo docker-compose up -d --build bot
sudo docker-compose logs -f bot
```

## Update

```bash
cd /opt/tgstream
# update project files
sudo docker-compose up -d --build bot
```

## Group setup

1. Add the bot to the group
2. Add the userbot account (used to create the session) to the same group
3. Give the userbot permission to join the voice chat
4. Start a voice chat
5. Run `/play <title>`
