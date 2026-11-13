"""Starting games, matchmaking, invites and in-game input."""
from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from .. import keyboards as kb
from .. import texts
from ..db import Database, UserProfile
from ..dictionary import Dictionary
from ..game_manager import GameManager
from .common import show

router = Router(name="game")
router.message.filter(F.chat.type == ChatType.PRIVATE)


async def _drop_buttons(cb: CallbackQuery) -> None:
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass


# --------------------------------------------------------------- vs bot

@router.message(Command("play"))
async def cmd_play(message: Message, profile: UserProfile) -> None:
    await message.answer(texts.bot_difficulty(profile.lvl), reply_markup=kb.bot_difficulty(profile.lvl))


@router.callback_query(F.data == "bot")
async def cb_bot(cb: CallbackQuery, profile: UserProfile) -> None:
    await show(cb, texts.bot_difficulty(profile.lvl), kb.bot_difficulty(profile.lvl))


@router.callback_query(F.data.startswith("bot:"))
async def cb_bot_start(cb: CallbackQuery, profile: UserProfile, manager: GameManager) -> None:
    delta = max(-1, min(1, int(cb.data.split(":")[1])))
    if not await manager.start_bot_game(profile, delta):
        await cb.answer(texts.BUSY, show_alert=True)
        return
    await cb.answer()
    await _drop_buttons(cb)


# ---------------------------------------------------------- matchmaking

async def _join_queue(profile: UserProfile, manager: GameManager) -> tuple[str, str | None]:
    result = await manager.join_queue(profile)
    return result, {"queued": texts.QUEUE_WAITING, "already": texts.QUEUE_ALREADY, "busy": texts.BUSY}.get(result)


@router.message(Command("pvp"))
async def cmd_pvp(message: Message, profile: UserProfile, manager: GameManager) -> None:
    result, text = await _join_queue(profile, manager)
    if text:
        await message.answer(text, reply_markup=kb.queue_waiting() if result == "queued" else None)


@router.callback_query(F.data == "pvp")
async def cb_pvp(cb: CallbackQuery, profile: UserProfile, manager: GameManager) -> None:
    result, text = await _join_queue(profile, manager)
    if result == "queued":
        await show(cb, text, kb.queue_waiting())
    elif text:
        await cb.answer(text, show_alert=True)
    else:
        await cb.answer()
        await _drop_buttons(cb)


@router.callback_query(F.data == "q:cancel")
async def cb_queue_cancel(cb: CallbackQuery, profile: UserProfile, manager: GameManager) -> None:
    await manager.leave_queue(profile.id)
    await show(cb, texts.QUEUE_LEFT + "\n\n" + texts.welcome(profile), kb.main_menu())


@router.callback_query(F.data == "q:bot")
async def cb_queue_bot(cb: CallbackQuery, profile: UserProfile, manager: GameManager) -> None:
    await manager.leave_queue(profile.id)
    if not await manager.start_bot_game(profile):
        await cb.answer(texts.BUSY, show_alert=True)
        return
    await cb.answer()
    await _drop_buttons(cb)


# --------------------------------------------------------------- invite

@router.message(Command("friend"))
async def cmd_friend(message: Message, profile: UserProfile, manager: GameManager) -> None:
    link = await manager.create_invite(profile)
    if link is None:
        await message.answer(texts.BUSY)
        return
    await message.answer(texts.invite(link), reply_markup=kb.invite(link))


@router.callback_query(F.data == "friend")
async def cb_friend(cb: CallbackQuery, profile: UserProfile, manager: GameManager) -> None:
    link = await manager.create_invite(profile)
    if link is None:
        await cb.answer(texts.BUSY, show_alert=True)
        return
    await show(cb, texts.invite(link), kb.invite(link))


@router.callback_query(F.data == "inv:cancel")
async def cb_invite_cancel(cb: CallbackQuery, profile: UserProfile, manager: GameManager) -> None:
    await manager.cancel_invite(profile.id)
    await show(cb, texts.INVITE_CANCELLED + "\n\n" + texts.welcome(profile), kb.main_menu())


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, manager: GameManager) -> None:
    uid = message.from_user.id
    if await manager.leave_queue(uid):
        await message.answer(texts.QUEUE_LEFT, reply_markup=kb.main_menu())
    elif await manager.cancel_invite(uid):
        await message.answer(texts.INVITE_CANCELLED, reply_markup=kb.main_menu())
    elif manager.session_of(uid):
        await message.answer(texts.RESIGN_CONFIRM, reply_markup=kb.resign_confirm())
    else:
        await message.answer(texts.NOTHING_TO_CANCEL)


# -------------------------------------------------------------- in game

@router.message(Command("hint"))
@router.message(F.text == texts.HINT_BTN)
async def on_hint(message: Message, manager: GameManager) -> None:
    await manager.hint(message.from_user.id)


@router.message(Command("giveup"))
@router.message(F.text == texts.RESIGN_BTN)
async def on_resign(message: Message, manager: GameManager) -> None:
    if manager.session_of(message.from_user.id) is None:
        await message.answer(texts.NOT_IN_GAME, reply_markup=kb.remove())
        return
    await message.answer(texts.RESIGN_CONFIRM, reply_markup=kb.resign_confirm())


@router.callback_query(F.data == "resign:yes")
async def cb_resign(cb: CallbackQuery, manager: GameManager) -> None:
    await cb.answer()
    try:
        await cb.message.delete()
    except TelegramBadRequest:
        pass
    await manager.resign(cb.from_user.id)


@router.callback_query(F.data == "resign:no")
async def cb_resign_no(cb: CallbackQuery) -> None:
    await cb.answer("▶️ Davom etamiz!")
    try:
        await cb.message.delete()
    except TelegramBadRequest:
        pass


@router.callback_query(F.data.startswith("rep:"))
async def cb_report(cb: CallbackQuery, db: Database, dictionary: Dictionary) -> None:
    _, kind, word = cb.data.split(":", 2)
    if kind == "missing" and word in dictionary:
        await cb.answer(texts.REPORT_ALREADY_IN)
        return
    added = await db.add_report(cb.from_user.id, word, kind)
    await cb.answer(texts.REPORT_THANKS if added else texts.REPORT_DUP)
    await _drop_buttons(cb)


@router.message(F.text & ~F.text.startswith("/"))
async def on_text(message: Message, manager: GameManager) -> None:
    uid = message.from_user.id
    if await manager.handle_word(uid, message.text, message.message_id):
        return
    if manager.in_queue(uid):
        await message.answer(texts.WAITING_IN_QUEUE, reply_markup=kb.queue_waiting())
    else:
        await message.answer(texts.NOT_IN_GAME, reply_markup=kb.main_menu())


@router.message()
async def on_other(message: Message, manager: GameManager) -> None:
    if manager.session_of(message.from_user.id):
        await message.answer(texts.FORMAT_HINT)
    else:
        await message.answer(texts.NOT_IN_GAME, reply_markup=kb.main_menu())
