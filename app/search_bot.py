import asyncio
import time
from aiogram import Bot, Dispatcher, Router, F
from aiogram.enums import ChatAction
from aiogram.types import Message, CallbackQuery

from .config import load_config
from .db_sqlite import SQLiteDB
from .keyboards import build_search_keyboard

router = Router()

# simple in-memory rate limiter (no redis needed)
_last_search: dict[int, float] = {}


def extract_title(message: Message) -> str:
    if message.document and message.document.file_name:
        return message.document.file_name
    if message.video and message.video.file_name:
        return message.video.file_name
    if message.audio and message.audio.file_name:
        return message.audio.file_name
    if message.animation and message.animation.file_name:
        return message.animation.file_name
    if message.caption:
        return message.caption
    return f"file_{message.message_id}"


def detect_file_type(message: Message) -> str:
    if message.document:
        return "document"
    if message.video:
        return "video"
    if message.audio:
        return "audio"
    if message.photo:
        return "photo"
    if message.voice:
        return "voice"
    if message.animation:
        return "animation"
    return "other"


async def show_page(
    *,
    message_obj,
    delivery_username: str,
    db: SQLiteDB,
    session_token: str,
    query: str,
    all_ids: list[int],
    page: int,
    page_size: int,
    edit: bool,
):
    total = len(all_ids)
    max_page = max(0, (total - 1) // page_size)
    page = max(0, min(page, max_page))

    start = page * page_size
    end = min(start + page_size, total)

    page_ids = all_ids[start:end]
    page_items = await db.get_files_by_ids(page_ids)

    text = (
        f"Found {total} result(s) for: {query}\n"
        f"Page {page+1}/{max_page+1} (showing {start+1}-{end})\n"
        f"Tap a file, use Next/Prev, or SEND ALL."
    )

    kb = build_search_keyboard(
        delivery_username=delivery_username,
        total=total,
        page=page,
        page_size=page_size,
        session_token=session_token,
        page_items=page_items,
    )

    if edit:
        await message_obj.edit_text(text, reply_markup=kb)
    else:
        await message_obj.answer(text, reply_markup=kb)


@router.channel_post()
async def index_channel_posts(message: Message, db: SQLiteDB, cfg):
    if message.chat.id != cfg.source_channel_id:
        return

    if not any([message.document, message.video, message.audio, message.photo, message.voice, message.animation]):
        return

    title = extract_title(message)
    file_type = detect_file_type(message)
    keywords = message.caption or title

    file_id = await db.add_file(
        source_chat_id=message.chat.id,
        source_message_id=message.message_id,
        title=title,
        file_type=file_type,
        keywords=keywords,
    )
    print(f"Indexed file #{file_id}: {title}")


@router.message()
async def group_search_handler(message: Message, bot: Bot, db: SQLiteDB, cfg):
    if not message.text:
        return
    if message.chat.type not in ("group", "supergroup"):
        return
    if message.from_user and message.from_user.is_bot:
        return

    text = message.text.strip()

    if text.startswith("/search"):
        query = text[len("/search"):].strip()
        if not query:
            await message.answer("Usage: /search HELLO\nExample: /search HELLO.2")
            return
    elif text.startswith("/"):
        return
    else:
        query = text

    if len(query) < 2:
        return

    uid = message.from_user.id if message.from_user else 0
    now = time.time()
    last = _last_search.get(uid, 0.0)
    if now - last < cfg.search_rate_limit_seconds:
        await message.answer("Too fast 🙂 Please wait 2 seconds and search again.")
        return
    _last_search[uid] = now

    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    all_ids = await db.search_file_ids(query)
    if not all_ids:
        await message.answer(
            f"No exact match for: {query}\n"
            f"Please search using correct file name.\n"
            f"Example: /search HELLO"
        )
        return

    token = await db.create_search_session(query, all_ids, ttl_seconds=cfg.session_ttl_seconds)

    await show_page(
        message_obj=message,
        delivery_username=cfg.delivery_bot_username,
        db=db,
        session_token=token,
        query=query,
        all_ids=all_ids,
        page=0,
        page_size=cfg.page_size,
        edit=False,
    )


@router.callback_query(F.data.startswith("pg|"))
async def paginate_results(callback: CallbackQuery, db: SQLiteDB, cfg):
    data = callback.data
    if not data:
        await callback.answer("Invalid page", show_alert=True)
        return

    await callback.answer()

    try:
        _, token, page_str = data.split("|", 2)
        page = int(page_str)
    except Exception:
        await callback.answer("Invalid page", show_alert=True)
        return

    session = await db.get_search_session(token, ttl_seconds=cfg.session_ttl_seconds)
    if not session:
        await callback.answer("Session expired. Search again.", show_alert=True)
        return

    await show_page(
        message_obj=callback.message,
        delivery_username=cfg.delivery_bot_username,
        db=db,
        session_token=token,
        query=session["query"],
        all_ids=session["file_ids"],
        page=page,
        page_size=cfg.page_size,
        edit=True,
    )


async def main():
    cfg = load_config()

    bot = Bot(token=cfg.search_bot_token)
    dp = Dispatcher()
    dp.include_router(router)

    db = SQLiteDB("files.db")
    await db.init()

    dp["db"] = db
    dp["cfg"] = cfg
    dp["bot"] = bot

    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())