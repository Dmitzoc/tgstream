import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv
from pyrogram import Client, filters
from pyrogram.types import Message
from pytgcalls import PyTgCalls
from pytgcalls.types import AudioQuality, MediaStream, StreamAudioEnded
from pytgcalls.types.input_stream import AudioPiped
from yt_dlp import YoutubeDL


load_dotenv()

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("tgstream")


API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
SESSION_NAME = os.getenv("SESSION_NAME", "music_user")
SESSION_DIR = os.getenv("SESSION_DIR", "data/sessions")

if not API_ID or not API_HASH or not BOT_TOKEN:
    raise RuntimeError("Set API_ID, API_HASH and BOT_TOKEN in environment variables.")

Path(SESSION_DIR).mkdir(parents=True, exist_ok=True)


@dataclass
class Track:
    title: str
    webpage_url: str
    direct_url: str
    duration: Optional[int]
    requested_by: str


class MusicQueue:
    def __init__(self) -> None:
        self._queues: Dict[int, List[Track]] = {}
        self._locks: Dict[int, asyncio.Lock] = {}

    def _get_lock(self, chat_id: int) -> asyncio.Lock:
        if chat_id not in self._locks:
            self._locks[chat_id] = asyncio.Lock()
        return self._locks[chat_id]

    async def push(self, chat_id: int, track: Track) -> int:
        async with self._get_lock(chat_id):
            self._queues.setdefault(chat_id, []).append(track)
            return len(self._queues[chat_id])

    async def pop(self, chat_id: int) -> Optional[Track]:
        async with self._get_lock(chat_id):
            queue = self._queues.get(chat_id, [])
            if not queue:
                return None
            return queue.pop(0)

    async def clear(self, chat_id: int) -> None:
        async with self._get_lock(chat_id):
            self._queues[chat_id] = []

    async def list(self, chat_id: int) -> List[Track]:
        async with self._get_lock(chat_id):
            return list(self._queues.get(chat_id, []))

    async def peek(self, chat_id: int) -> Optional[Track]:
        async with self._get_lock(chat_id):
            queue = self._queues.get(chat_id, [])
            return queue[0] if queue else None


queue = MusicQueue()
current_track: Dict[int, Track] = {}
active_calls: Dict[int, bool] = {}


def format_duration(seconds: Optional[int]) -> str:
    if not seconds:
        return "?"
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def search_track(query: str, requested_by: str) -> Track:
    ydl_opts = {
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "default_search": "ytsearch1",
        "quiet": True,
        "noplaylist": True,
        "extract_flat": False,
    }
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(query, download=False)

    entry = info["entries"][0] if "entries" in info else info
    if not entry:
        raise ValueError("Nothing found by your query.")

    direct_url = entry.get("url")
    if not direct_url:
        raise ValueError("yt-dlp did not return a streamable URL.")

    return Track(
        title=entry.get("title", "Unknown title"),
        webpage_url=entry.get("webpage_url", ""),
        direct_url=direct_url,
        duration=entry.get("duration"),
        requested_by=requested_by,
    )


async def start_or_enqueue(chat_id: int, track: Track, calls: PyTgCalls) -> str:
    position = await queue.push(chat_id, track)
    if active_calls.get(chat_id):
        return f"Added to queue #{position}: {track.title}"

    next_track = await queue.peek(chat_id)
    if not next_track:
        return "Queue is empty."

    try:
        await calls.play(
            chat_id,
            MediaStream(
                AudioPiped(next_track.direct_url),
                audio_parameters=AudioQuality.HIGH,
            ),
        )
    except Exception as exc:
        logger.exception("Failed to start call in chat %s", chat_id)
        return (
            "Failed to start playback. Ensure group voice chat is already active and userbot can join it.\n"
            f"Error: {exc}"
        )

    active_calls[chat_id] = True
    current_track[chat_id] = next_track
    return (
        f"Now playing: {next_track.title} ({format_duration(next_track.duration)})\n"
        f"Source: {next_track.webpage_url or 'n/a'}"
    )


async def play_next(chat_id: int, calls: PyTgCalls, bot: Client) -> None:
    await queue.pop(chat_id)
    nxt = await queue.peek(chat_id)
    if not nxt:
        active_calls[chat_id] = False
        current_track.pop(chat_id, None)
        try:
            await calls.leave_group_call(chat_id)
        except Exception:
            logger.warning("Failed to leave call in %s", chat_id)
        try:
            await bot.send_message(chat_id, "Queue ended. Left voice chat.")
        except Exception:
            logger.warning("Failed to notify chat %s", chat_id)
        return

    try:
        await calls.play(
            chat_id,
            MediaStream(
                AudioPiped(nxt.direct_url),
                audio_parameters=AudioQuality.HIGH,
            ),
        )
        current_track[chat_id] = nxt
        await bot.send_message(
            chat_id,
            f"Next track: {nxt.title} ({format_duration(nxt.duration)})",
        )
    except Exception:
        logger.exception("Failed to play next track in chat %s", chat_id)


def build_clients() -> tuple[Client, Client, PyTgCalls]:
    bot_client = Client(
        name="music_bot",
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=BOT_TOKEN,
    )
    user_session_path = str(Path(SESSION_DIR) / SESSION_NAME)
    user_client = Client(
        name=user_session_path,
        api_id=API_ID,
        api_hash=API_HASH,
    )
    call_client = PyTgCalls(user_client)
    return bot_client, user_client, call_client


def main() -> None:
    bot, user, calls = build_clients()

    @calls.on_update()
    async def stream_end_handler(_, update):
        if isinstance(update, StreamAudioEnded):
            await play_next(update.chat_id, calls, bot)

    @bot.on_message(filters.command("start"))
    async def start_cmd(_, m: Message):
        await m.reply_text(
            "Music bot is ready.\n"
            "Commands:\n"
            "/play <query>\n"
            "/skip\n"
            "/queue\n"
            "/stop\n"
            "/now\n"
            "/ping"
        )

    @bot.on_message(filters.command("ping"))
    async def ping_cmd(_, m: Message):
        await m.reply_text("pong")

    @bot.on_message(filters.command("play") & filters.group)
    async def play_cmd(_, m: Message):
        if len(m.command) < 2:
            await m.reply_text("Usage: /play <track name>")
            return
        query = " ".join(m.command[1:]).strip()
        await m.reply_text(f"Searching: {query}")
        try:
            requested_by = m.from_user.mention if m.from_user else "unknown"
            track = await asyncio.to_thread(search_track, query, requested_by)
            status = await start_or_enqueue(m.chat.id, track, calls)
            await m.reply_text(status)
        except Exception as exc:
            await m.reply_text(f"Search/add failed: {exc}")

    @bot.on_message(filters.command("skip") & filters.group)
    async def skip_cmd(_, m: Message):
        if not active_calls.get(m.chat.id):
            await m.reply_text("Nothing is currently playing.")
            return
        await play_next(m.chat.id, calls, bot)
        await m.reply_text("Skipped.")

    @bot.on_message(filters.command("queue") & filters.group)
    async def queue_cmd(_, m: Message):
        items = await queue.list(m.chat.id)
        if not items:
            await m.reply_text("Queue is empty.")
            return
        lines = ["Queue:"]
        for i, tr in enumerate(items[:20], start=1):
            lines.append(f"{i}. {tr.title} [{format_duration(tr.duration)}]")
        if len(items) > 20:
            lines.append(f"... and {len(items) - 20} more")
        await m.reply_text("\n".join(lines))

    @bot.on_message(filters.command("now") & filters.group)
    async def now_cmd(_, m: Message):
        tr = current_track.get(m.chat.id)
        if not tr:
            await m.reply_text("Nothing is currently playing.")
            return
        await m.reply_text(
            f"Now playing: {tr.title}\n"
            f"Duration: {format_duration(tr.duration)}\n"
            f"Source: {tr.webpage_url or 'n/a'}\n"
            f"Requested by: {tr.requested_by}"
        )

    @bot.on_message(filters.command("stop") & filters.group)
    async def stop_cmd(_, m: Message):
        await queue.clear(m.chat.id)
        active_calls[m.chat.id] = False
        current_track.pop(m.chat.id, None)
        try:
            await calls.leave_group_call(m.chat.id)
        except Exception:
            logger.warning("Failed to leave call in %s", m.chat.id)
        await m.reply_text("Stopped playback and cleared queue.")

    user.start()
    calls.start()
    bot.run()


if __name__ == "__main__":
    main()
