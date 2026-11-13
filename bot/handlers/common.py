from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup


async def show(cb: CallbackQuery, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    """Edits the menu message in place, falling back to a new message."""
    try:
        await cb.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            await cb.message.answer(text, reply_markup=markup)
    await cb.answer()
