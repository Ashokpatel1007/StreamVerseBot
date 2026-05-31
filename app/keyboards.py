from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def make_single_url(delivery_username: str, file_id: int) -> str:
    return f"https://t.me/{delivery_username}?start=f_{file_id}"


def make_all_url(delivery_username: str, token: str) -> str:
    return f"https://t.me/{delivery_username}?start=a_{token}"


def build_search_keyboard(
    *,
    delivery_username: str,
    total: int,
    page: int,
    page_size: int,
    session_token: str,
    page_items: list[dict],
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    for row in page_items:
        rows.append([InlineKeyboardButton(text=row["title"], url=make_single_url(delivery_username, int(row["id"])))])

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="<-- Prev", callback_data=f"pg|{session_token}|{page-1}"))
    if (page + 1) * page_size < total:
        nav.append(InlineKeyboardButton(text="Next -->", callback_data=f"pg|{session_token}|{page+1}"))
    if nav:
        rows.append(nav)

    if total > 1:
        rows.append([InlineKeyboardButton(text=f"SEND ALL FILES ({total})", url=make_all_url(delivery_username, session_token))])

    return InlineKeyboardMarkup(inline_keyboard=rows)