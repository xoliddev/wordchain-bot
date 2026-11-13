from urllib.parse import quote

from aiogram.types import (
    InlineKeyboardButton as Btn,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from .levels import Level
from .texts import HINT_BTN, RESIGN_BTN, invite_share_text


def _kb(*rows: list[Btn]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=list(rows))


BACK = Btn(text="⬅️ Orqaga", callback_data="menu")


def main_menu() -> InlineKeyboardMarkup:
    return _kb(
        [Btn(text="🤖 Bot bilan o'ynash", callback_data="bot")],
        [Btn(text="👥 Tasodifiy raqib", callback_data="pvp"), Btn(text="🔗 Do'st bilan", callback_data="friend")],
        [Btn(text="📊 Statistika", callback_data="stats"), Btn(text="🏆 Reyting", callback_data="top")],
        [Btn(text="📶 Daraja", callback_data="level"), Btn(text="📖 Qoidalar", callback_data="rules")],
    )


def back() -> InlineKeyboardMarkup:
    return _kb([BACK])


def levels(current: Level) -> InlineKeyboardMarkup:
    buttons = [
        Btn(text=f"{'✅ ' if lv == current else ''}{lv.name}", callback_data=f"lvl:{int(lv)}") for lv in Level
    ]
    return _kb(buttons[:3], buttons[3:], [BACK])


def bot_difficulty(level: Level) -> InlineKeyboardMarkup:
    rows = [[Btn(text=f"🎯 Darajamda ({level.name})", callback_data="bot:0")]]
    options = []
    if level > Level.A1:
        options.append(Btn(text=f"⬇️ Osonroq ({level.shifted(-1).name})", callback_data="bot:-1"))
    if level < Level.C2:
        options.append(Btn(text=f"⬆️ Qiyinroq ({level.shifted(1).name})", callback_data="bot:1"))
    if options:
        rows.append(options)
    rows.append([BACK])
    return _kb(*rows)


def queue_waiting() -> InlineKeyboardMarkup:
    return _kb([Btn(text="❌ Bekor qilish", callback_data="q:cancel")])


def queue_offer() -> InlineKeyboardMarkup:
    return _kb(
        [Btn(text="🤖 Bot bilan o'ynash", callback_data="q:bot")],
        [Btn(text="❌ Bekor qilish", callback_data="q:cancel")],
    )


def invite(link: str) -> InlineKeyboardMarkup:
    share = f"https://t.me/share/url?url={quote(link, safe='')}&text={quote(invite_share_text())}"
    return _kb(
        [Btn(text="📤 Do'stga yuborish", url=share)],
        [Btn(text="❌ Bekor qilish", callback_data="inv:cancel")],
    )


def game_controls(with_hint: bool) -> ReplyKeyboardMarkup:
    row = [KeyboardButton(text=HINT_BTN)] if with_hint else []
    row.append(KeyboardButton(text=RESIGN_BTN))
    return ReplyKeyboardMarkup(
        keyboard=[row], resize_keyboard=True, input_field_placeholder="Inglizcha so'z yozing..."
    )


def remove() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


def resign_confirm() -> InlineKeyboardMarkup:
    return _kb([Btn(text="🏳️ Ha, taslim", callback_data="resign:yes"),
                Btn(text="▶️ Davom etish", callback_data="resign:no")])


def report_missing(word: str) -> InlineKeyboardMarkup:
    return _kb([Btn(text="📩 Bu so'z to'g'ri — xabar berish", callback_data=f"rep:missing:{word}")])


def report_invalid(word: str) -> InlineKeyboardMarkup:
    return _kb([Btn(text="🚩 Bu so'z noto'g'ri", callback_data=f"rep:invalid:{word}")])


def after_game(mode: str, delta: int) -> InlineKeyboardMarkup:
    again = (Btn(text="🔄 Revansh", callback_data=f"bot:{delta}") if mode == "bot"
             else Btn(text="👥 Yangi raqib", callback_data="pvp"))
    return _kb([again], [Btn(text="🏠 Menyu", callback_data="menu")])


def subscribe(link: str | None) -> InlineKeyboardMarkup:
    rows = [[Btn(text="📢 Kanalga o'tish", url=link)]] if link else []
    rows.append([Btn(text="✅ Tekshirish", callback_data="sub:check")])
    return _kb(*rows)


def report_review(word: str, kind: str) -> InlineKeyboardMarkup:
    ok = "➕ Qo'shish" if kind == "missing" else "🗑 O'chirish"
    return _kb([Btn(text=ok, callback_data=f"adm:ok:{kind}:{word}"),
                Btn(text="❌ Rad etish", callback_data=f"adm:no:{kind}:{word}")])
