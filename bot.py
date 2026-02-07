import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set

from dotenv import load_dotenv
from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.types import Message

# Compatibility shim for Pyrogram error name changes.
try:
    import pyrogram.errors as pyrogram_errors

    if not hasattr(pyrogram_errors, "GroupcallForbidden"):
        if hasattr(pyrogram_errors, "GroupCallForbidden"):
            pyrogram_errors.GroupcallForbidden = pyrogram_errors.GroupCallForbidden
        else:
            class GroupcallForbidden(Exception):
                pass

            pyrogram_errors.GroupcallForbidden = GroupcallForbidden
except Exception:
    pass

from pytgcalls import PyTgCalls

try:
    from pytgcalls.types.input_stream import AudioPiped
except Exception:
    AudioPiped = None
from yt_dlp import YoutubeDL

try:
    from pytgcalls.types import StreamAudioEnded
except Exception:
    StreamAudioEnded = None


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
PRIVILEGED_USER_IDS_RAW = os.getenv("PRIVILEGED_USER_IDS", "")
RECONNECT_DELAY_SECONDS = int(os.getenv("RECONNECT_DELAY_SECONDS", "8"))
RECONNECT_MAX_ATTEMPTS = int(os.getenv("RECONNECT_MAX_ATTEMPTS", "0"))

if not API_ID or not API_HASH or not BOT_TOKEN:
    raise RuntimeError("Set API_ID, API_HASH and BOT_TOKEN in environment variables.")

Path(SESSION_DIR).mkdir(parents=True, exist_ok=True)


def parse_privileged_users(raw: str) -> Set[int]:
    result: Set[int] = set()
    if not raw.strip():
        return result
    for chunk in raw.split(","):
        item = chunk.strip()
        if not item:
            continue
        try:
            result.add(int(item))
        except ValueError:
            logger.warning("Ignored invalid user id in PRIVILEGED_USER_IDS: %s", item)
    return result


PRIVILEGED_USER_IDS = parse_privileged_users(PRIVILEGED_USER_IDS_RAW)


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
reconnect_tasks: Dict[int, asyncio.Task] = {}


def format_duration(seconds: Optional[int]) -> str:
    if not seconds:
        return "?"
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def is_peer_invalid_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return (
        "peer id invalid" in msg
        or "channel private" in msg
        or "channel_private" in msg
        or "chat id invalid" in msg
        or "chat_id_invalid" in msg
    )


def is_groupcall_forbidden(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "groupcallforbidden" in msg or "group call forbidden" in msg or "groupcall_forbidden" in msg


def is_voice_chat_missing(exc: Exception) -> bool:
    msg = str(exc).lower()
    return (
        "groupcall not found" in msg
        or "groupcallnotfound" in msg
        or "group call not found" in msg
        or "voice chat not found" in msg
        or "voice chat not started" in msg
        or "groupcall_not_found" in msg
    )


def explain_play_error(exc: Exception) -> str:
    if is_peer_invalid_error(exc):
        return (
            "Userbot cannot access this group. Add the user account to the group and open the chat at least once, "
            "then retry /play."
        )
    if is_groupcall_forbidden(exc):
        return (
            "Userbot is not allowed to start/join the voice chat. Start the voice chat manually or grant the "
            "'Manage video chats' permission to the user account."
        )
    if is_voice_chat_missing(exc):
        return "Voice chat is not started. Start the voice chat and retry /play."
    return "Failed to start playback. Please ensure the voice chat is started and try again."


def preload_user_dialogs(user: Client) -> None:
    try:
        for _ in user.get_dialogs():
            pass
        logger.info("User dialogs preloaded.")
    except Exception as exc:
        logger.warning("Failed to preload user dialogs: %s", exc)


async def ensure_user_peer(user: Client, chat_id: int) -> None:
    try:
        await user.get_chat(chat_id)
    except Exception as exc:
        logger.warning("Userbot cannot access chat %s: %s", chat_id, exc)
        raise


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


async def start_or_enqueue(chat_id: int, track: Track, calls: PyTgCalls, bot: Client, user: Client) -> str:
    position = await queue.push(chat_id, track)
    if active_calls.get(chat_id):
        return f"Добавлено в очередь #{position}: {track.title}"

    next_track = await queue.peek(chat_id)
    if not next_track:
        return "Очередь пуста."

    try:
        await play_track(calls, user, chat_id, next_track)
    except Exception as exc:
        logger.exception("Failed to start call in chat %s", chat_id)
        active_calls[chat_id] = True
        current_track[chat_id] = next_track
        ensure_reconnect(chat_id, calls, bot, user)
        return (
            f"{explain_play_error(exc)}\nError: {exc}"
        )

    active_calls[chat_id] = True
    current_track[chat_id] = next_track
    return (
        f"Сейчас играет: {next_track.title} ({format_duration(next_track.duration)})\n"
        f"Источник: {next_track.webpage_url or 'n/a'}"
    )


async def play_track(calls: PyTgCalls, user: Client, chat_id: int, track: Track) -> None:
    await ensure_user_peer(user, chat_id)
    stream = AudioPiped(track.direct_url) if AudioPiped else track.direct_url
    await calls.play(chat_id, stream)


async def reconnect_worker(chat_id: int, calls: PyTgCalls, bot: Client, user: Client) -> None:
    attempt = 0
    try:
        while active_calls.get(chat_id):
            track = current_track.get(chat_id)
            if not track:
                return

            attempt += 1
            if RECONNECT_MAX_ATTEMPTS > 0 and attempt > RECONNECT_MAX_ATTEMPTS:
                await bot.send_message(
                    chat_id,
                    "Реконнект не удался: превышено число попыток. Используйте /play снова.",
                )
                active_calls[chat_id] = False
                return

            try:
                await play_track(calls, user, chat_id, track)
                await bot.send_message(chat_id, "Реконнект выполнен, воспроизведение восстановлено.")
                return
            except Exception as exc:
                logger.warning("Reconnect attempt %s failed for chat %s: %s", attempt, chat_id, exc)
                if is_peer_invalid_error(exc):
                    active_calls[chat_id] = False
                    try:
                        await bot.send_message(chat_id, explain_play_error(exc))
                    except Exception:
                        logger.warning("Failed to send peer error message to %s", chat_id)
                    return
                if "valid stream object" in str(exc) or "stream classes found" in str(exc):
                    active_calls[chat_id] = False
                    return
                await asyncio.sleep(RECONNECT_DELAY_SECONDS)
    finally:
        reconnect_tasks.pop(chat_id, None)


def ensure_reconnect(chat_id: int, calls: PyTgCalls, bot: Client, user: Client) -> None:
    task = reconnect_tasks.get(chat_id)
    if task and not task.done():
        return
    reconnect_tasks[chat_id] = asyncio.create_task(reconnect_worker(chat_id, calls, bot, user))


async def play_next(chat_id: int, calls: PyTgCalls, bot: Client, user: Client) -> None:
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
            await bot.send_message(chat_id, "Очередь закончилась, вышел из звонка.")
        except Exception:
            logger.warning("Failed to send end message to %s", chat_id)
        return

    try:
        await play_track(calls, user, chat_id, nxt)
        current_track[chat_id] = nxt
        await bot.send_message(
            chat_id,
            f"Следующий трек: {nxt.title} ({format_duration(nxt.duration)})",
        )
    except Exception as exc:
        logger.exception("Failed to play next track in chat %s", chat_id)
        await bot.send_message(
            chat_id,
            f"{explain_play_error(exc)}\nError: {exc}",
        )
        ensure_reconnect(chat_id, calls, bot, user)


async def is_privileged_user(bot: Client, m: Message) -> bool:
    if not m.from_user:
        return False
    user_id = m.from_user.id
    if user_id in PRIVILEGED_USER_IDS:
        return True
    try:
        member = await bot.get_chat_member(m.chat.id, user_id)
    except Exception:
        return False
    return member.status in {
        ChatMemberStatus.OWNER,
        ChatMemberStatus.ADMINISTRATOR,
    }


async def ensure_group_context(m: Message) -> bool:
    if m.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        return True
    await m.reply_text("Эта команда работает только в группе с активным голосовым чатом.")
    return False


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
        no_updates=True,
    )
    call_client = PyTgCalls(user_client)
    return bot_client, user_client, call_client


def main() -> None:
    bot, user, calls = build_clients()
    logger.info(
        "Stream backend: url_play=True StreamAudioEnded=%s",
        bool(StreamAudioEnded),
    )

    @calls.on_update()
    async def stream_end_handler(_, update):
        if StreamAudioEnded is not None and isinstance(update, StreamAudioEnded):
            await play_next(update.chat_id, calls, bot, user)
            return
        if update.__class__.__name__ == "StreamAudioEnded" and hasattr(update, "chat_id"):
            await play_next(update.chat_id, calls, bot, user)

    @bot.on_message(filters.command("start"))
    async def start_cmd(_, m: Message):
        await m.reply_text(
            "Музыкальный бот готов.\n"
            "Команды:\n"
            "/play <название>\n"
            "/skip\n"
            "/queue\n"
            "/stop\n"
            "/reconnect\n"
            "/now\n"
            "/ping\n\n"
            "Пропуск (/skip) доступен только админам или ID из PRIVILEGED_USER_IDS."
        )

    @bot.on_message(filters.command("ping"))
    async def ping_cmd(_, m: Message):
        await m.reply_text("pong")

    @bot.on_message(filters.command("play"))
    async def play_cmd(_, m: Message):
        if not await ensure_group_context(m):
            return
        if len(m.command) < 2:
            await m.reply_text("Использование: /play <название трека>")
            return
        try:
            await ensure_user_peer(user, m.chat.id)
        except Exception as exc:
            logger.warning("Userbot peer check failed for chat %s: %s", m.chat.id, exc)
            await m.reply_text(
                "Userbot cannot access this group. Add the user account to the group and open the chat at least once, "
                "then retry /play."
            )
            return
        query = " ".join(m.command[1:]).strip()
        await m.reply_text(f"Ищу: {query}")
        try:
            requested_by = m.from_user.mention if m.from_user else "unknown"
            track = await asyncio.to_thread(search_track, query, requested_by)
            status = await start_or_enqueue(m.chat.id, track, calls, bot, user)
            await m.reply_text(status)
        except Exception as exc:
            await m.reply_text(f"Ошибка поиска/добавления: {exc}")

    @bot.on_message(filters.command("skip"))
    async def skip_cmd(_, m: Message):
        if not await ensure_group_context(m):
            return
        if not await is_privileged_user(bot, m):
            await m.reply_text("Недостаточно прав для /skip.")
            return
        if not active_calls.get(m.chat.id):
            await m.reply_text("Сейчас ничего не играет.")
            return
        await play_next(m.chat.id, calls, bot, user)
        await m.reply_text("Трек пропущен.")

    @bot.on_message(filters.command("reconnect"))
    async def reconnect_cmd(_, m: Message):
        if not await ensure_group_context(m):
            return
        if not await is_privileged_user(bot, m):
            await m.reply_text("Недостаточно прав для /reconnect.")
            return
        if not active_calls.get(m.chat.id) or not current_track.get(m.chat.id):
            await m.reply_text("Нет активного трека для реконнекта.")
            return
        ensure_reconnect(m.chat.id, calls, bot, user)
        await m.reply_text("Запущен реконнект.")

    @bot.on_message(filters.command("queue"))
    async def queue_cmd(_, m: Message):
        if not await ensure_group_context(m):
            return
        items = await queue.list(m.chat.id)
        if not items:
            await m.reply_text("Очередь пуста.")
            return
        lines = ["Очередь:"]
        for i, tr in enumerate(items[:20], start=1):
            lines.append(f"{i}. {tr.title} [{format_duration(tr.duration)}]")
        if len(items) > 20:
            lines.append(f"... и еще {len(items) - 20}")
        await m.reply_text("\n".join(lines))

    @bot.on_message(filters.command("now"))
    async def now_cmd(_, m: Message):
        if not await ensure_group_context(m):
            return
        tr = current_track.get(m.chat.id)
        if not tr:
            await m.reply_text("Сейчас ничего не играет.")
            return
        await m.reply_text(
            f"Сейчас играет: {tr.title}\n"
            f"Длительность: {format_duration(tr.duration)}\n"
            f"Источник: {tr.webpage_url or 'n/a'}\n"
            f"Запросил: {tr.requested_by}"
        )

    @bot.on_message(filters.command("stop"))
    async def stop_cmd(_, m: Message):
        if not await ensure_group_context(m):
            return
        await queue.clear(m.chat.id)
        active_calls[m.chat.id] = False
        current_track.pop(m.chat.id, None)
        task = reconnect_tasks.get(m.chat.id)
        if task and not task.done():
            task.cancel()
        try:
            await calls.leave_group_call(m.chat.id)
        except Exception:
            logger.warning("Failed to leave call in %s", m.chat.id)
        await m.reply_text("Остановлено, очередь очищена, вышел из звонка.")

    user.start()
    preload_user_dialogs(user)
    calls.start()
    bot.run()


if __name__ == "__main__":
    main()
