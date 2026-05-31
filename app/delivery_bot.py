import asyncio
import time
from aiogram import Bot, Dispatcher, Router
from aiogram.enums import ChatAction
from aiogram.filters import CommandStart
from aiogram.types import Message

from .config import load_config
from .db_sqlite import SQLiteDB

router = Router()

# simple in-memory rate limit + per-user lock (no redis needed)
_last_delivery: dict[int, float] = {}
_user_locks: dict[int, asyncio.Lock] = {}


def get_user_lock(user_id: int) -> asyncio.Lock:
    if user_id not in _user_locks:
        _user_locks[user_id] = asyncio.Lock()
    return _user_locks[user_id]


async def send_single(bot: Bot, db: SQLiteDB, message: Message, file_id: int):
    record = await db.get_file(file_id)
    if not record:
        await message.answer("File not found.")
        return

    await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_DOCUMENT)

    try:
        await bot.copy_message(
            chat_id=message.chat.id,
            from_chat_id=int(record["source_chat_id"]),
            message_id=int(record["source_message_id"]),
        )
        await message.answer(f"Delivered: {record['title']}")
    except Exception:
        await message.answer("Unable to send this file (blocked or missing).")


async def send_all(bot: Bot, db: SQLiteDB, message: Message, token: str, session_ttl: int, progress_every: int):
    session = await db.get_search_session(token, ttl_seconds=session_ttl)
    if not session:
        await message.answer("Session expired. Please search again from the group.")
        return

    ids = session["file_ids"]
    total = len(ids)
    if total == 0:
        await message.answer("No files in this session.")
        return

    status = await message.answer(f"Starting delivery: 0/{total}")
    sent = 0

    for i, file_id in enumerate(ids, start=1):
        record = await db.get_file(file_id)
        if not record:
            continue

        await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_DOCUMENT)

        try:
            await bot.copy_message(
                chat_id=message.chat.id,
                from_chat_id=int(record["source_chat_id"]),
                message_id=int(record["source_message_id"]),
            )
            sent += 1
        except Exception:
            await message.answer(f"Skipped: {record['title']}")

        if i % progress_every == 0 or i == total:
            try:
                await status.edit_text(f"Sending... {i}/{total} (sent {sent})")
            except Exception:
                pass

        await asyncio.sleep(0.15)

    await message.answer(f"Done ✅ Sent {sent}/{total} file(s).")


@router.message(CommandStart())
async def start_handler(message: Message, bot: Bot, db: SQLiteDB, cfg):
    text = (message.text or "").strip()
    parts = text.split(maxsplit=1)

    if len(parts) == 1:
        await message.answer("Open me from the group file buttons to receive files.")
        return

    uid = message.from_user.id if message.from_user else 0

    # rate limit
    now = time.time()
    last = _last_delivery.get(uid, 0.0)
    if now - last < cfg.delivery_rate_limit_seconds:
        await message.answer("Too fast 🙂 Please wait 2 seconds and try again.")
        return
    _last_delivery[uid] = now

    payload = parts[1].strip()

    # per-user lock
    lock = get_user_lock(uid)
    if lock.locked():
        await message.answer("I’m already sending you files. Please wait 🙂")
        return

    async with lock:
        if payload.startswith("f_"):
            try:
                file_id = int(payload[2:])
            except ValueError:
                await message.answer("Invalid file link.")
                return
            await send_single(bot, db, message, file_id)
            return

        if payload.startswith("a_"):
            token = payload[2:]
            await send_all(
                bot,
                db,
                message,
                token,
                session_ttl=cfg.session_ttl_seconds,
                progress_every=cfg.delivery_progress_every,
            )
            return

        await message.answer("Invalid start payload.")


async def main():
    cfg = load_config()

    bot = Bot(token=cfg.delivery_bot_token)
    dp = Dispatcher()
    dp.include_router(router)

    db = SQLiteDB("files.db")
    await db.init()

    # dependency injection
    dp["cfg"] = cfg
    dp["db"] = db
    dp["bot"] = bot

    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())