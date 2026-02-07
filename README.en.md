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
