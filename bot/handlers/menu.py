"""Menus, profile, stats and leaderboard."""
from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message

from .. import keyboards as kb
from .. import texts
from ..config import Settings
from ..db import Database, UserProfile
from ..game_manager import GameManager
from ..levels import Level
from .common import show

router = Router(name="menu")
router.message.filter(F.chat.type == ChatType.PRIVATE)


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, profile: UserProfile, manager: GameManager) -> None:
    if command.args and command.args.startswith("inv_"):
        result = await manager.accept_invite(command.args[4:], profile)
        if result == "ok":
            return
        reply = {
            "expired": texts.INVITE_EXPIRED,
            "self": texts.INVITE_SELF,
            "busy": texts.BUSY,
            "host_busy": texts.INVITE_HOST_BUSY,
        }[result]
        await message.answer(reply)
        if result == "busy":
            return
    await message.answer(texts.welcome(profile), reply_markup=kb.main_menu())


@router.message(Command("menu"))
async def cmd_menu(message: Message, profile: UserProfile) -> None:
    await message.answer(texts.welcome(profile), reply_markup=kb.main_menu())


@router.callback_query(F.data == "menu")
async def cb_menu(cb: CallbackQuery, profile: UserProfile) -> None:
    await show(cb, texts.welcome(profile), kb.main_menu())


def _rules(settings: Settings) -> str:
    return texts.rules(settings.pvp_turn_seconds, settings.max_strikes, settings.max_hints, settings.min_word_length)


@router.message(Command("rules", "help"))
async def cmd_rules(message: Message, settings: Settings) -> None:
    await message.answer(_rules(settings), reply_markup=kb.back())


@router.callback_query(F.data == "rules")
async def cb_rules(cb: CallbackQuery, settings: Settings) -> None:
    await show(cb, _rules(settings), kb.back())


# ------------------------------------------------------------------ level

@router.message(Command("level"))
async def cmd_level(message: Message, profile: UserProfile) -> None:
    await message.answer(texts.level_picker(profile.lvl), reply_markup=kb.levels(profile.lvl))


@router.callback_query(F.data == "level")
async def cb_level(cb: CallbackQuery, profile: UserProfile) -> None:
    await show(cb, texts.level_picker(profile.lvl), kb.levels(profile.lvl))


@router.callback_query(F.data.startswith("lvl:"))
async def cb_set_level(cb: CallbackQuery, db: Database) -> None:
    level = Level(int(cb.data.split(":")[1]))
    await db.set_level(cb.from_user.id, level)
    await show(cb, texts.level_picker(level) + "\n\n" + texts.level_set(level), kb.levels(level))


# ------------------------------------------------------------------ stats

async def _stats_text(db: Database, profile: UserProfile) -> str:
    return texts.stats(profile, await db.rating_position(profile.id), await db.vocabulary(profile.id))


@router.message(Command("stats"))
async def cmd_stats(message: Message, profile: UserProfile, db: Database) -> None:
    await message.answer(await _stats_text(db, profile), reply_markup=kb.back())


@router.callback_query(F.data == "stats")
async def cb_stats(cb: CallbackQuery, profile: UserProfile, db: Database) -> None:
    await show(cb, await _stats_text(db, profile), kb.back())


async def _top_text(db: Database, profile: UserProfile) -> str:
    return texts.leaderboard(await db.top_players(10), await db.top_wordsmiths(5), profile,
                             await db.rating_position(profile.id))


@router.message(Command("top"))
async def cmd_top(message: Message, profile: UserProfile, db: Database) -> None:
    await message.answer(await _top_text(db, profile), reply_markup=kb.back())


@router.callback_query(F.data == "top")
async def cb_top(cb: CallbackQuery, profile: UserProfile, db: Database) -> None:
    await show(cb, await _top_text(db, profile), kb.back())


@router.callback_query(F.data == "sub:check")
async def cb_sub_check(cb: CallbackQuery, profile: UserProfile) -> None:
    # only reached once the subscription middleware has confirmed the membership
    await show(cb, texts.welcome(profile), kb.main_menu())
