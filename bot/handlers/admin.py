"""Admin panel: stats, dictionary moderation, word reports, broadcast."""
import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter, TelegramAPIError
from aiogram.filters import Command, CommandObject, Filter
from aiogram.types import CallbackQuery, Message

from .. import keyboards as kb
from ..config import Settings
from ..db import Database
from ..dictionary import Dictionary
from ..engine import normalize
from ..game_manager import GameManager
from ..levels import Level, rank_for_level
from ..texts import esc

log = logging.getLogger(__name__)


class IsAdmin(Filter):
    async def __call__(self, event: Message | CallbackQuery, settings: Settings) -> bool:
        return event.from_user is not None and event.from_user.id in settings.admin_ids


router = Router(name="admin")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

HELP = (
    "\n\n<b>Buyruqlar:</b>\n"
    "/addword <code>word [A1..C2]</code> — so'z qo'shish\n"
    "/delword <code>word</code> — so'zni o'chirish\n"
    "/word <code>word</code> — so'z haqida ma'lumot\n"
    "/tr <code>word = tarjima</code> — tarjimani tuzatish\n"
    "/reports — o'yinchilar xabarlari\n"
    "/broadcast — xabarga reply qilib yuboring"
)


@router.message(Command("admin"))
async def cmd_admin(message: Message, db: Database, manager: GameManager) -> None:
    s = await db.global_stats()
    await message.answer(
        "🛠 <b>Admin panel</b>\n\n"
        f"👤 Foydalanuvchilar: <b>{s['users']}</b> (24 soatda faol: {s['active_day']}, yangi: {s['new_day']},"
        f" bloklagan: {s['blocked']})\n"
        f"🎮 O'yinlar: <b>{s['games']}</b> (24 soatda: {s['games_day']}, PvP: {s['pvp_games']})\n"
        f"📝 Yozilgan so'zlar: <b>{s['moves']}</b>\n"
        f"📚 Lug'at: <b>{s['words']}</b> so'z\n"
        f"🚩 Ochiq xabarlar: <b>{s['reports']}</b>\n\n"
        f"🟢 Hozir: {manager.live_games} ta o'yin, navbatda {manager.queue_size} kishi"
        + HELP
    )


@router.message(Command("addword"))
async def cmd_addword(message: Message, command: CommandObject, db: Database, dictionary: Dictionary) -> None:
    parts = (command.args or "").split()
    word = normalize(parts[0]) if parts else None
    level = Level.parse(parts[1]) if len(parts) > 1 else Level.C1
    if not word or level is None:
        await message.answer("Foydalanish: /addword <code>word [A1..C2]</code>")
        return
    rank = rank_for_level(level)
    await db.upsert_word(word, rank, message.from_user.id)
    dictionary.remove(word)
    dictionary.add(word, rank)
    await db.resolve_reports(word, "missing", "accepted")
    await message.answer(f"✅ <b>{esc(word)}</b> lug'atga qo'shildi ({level.name}).")


@router.message(Command("delword"))
async def cmd_delword(message: Message, command: CommandObject, db: Database, dictionary: Dictionary) -> None:
    word = normalize(command.args or "")
    if not word:
        await message.answer("Foydalanish: /delword <code>word</code>")
        return
    removed = await db.disable_word(word, message.from_user.id)
    dictionary.remove(word)
    await db.resolve_reports(word, "invalid", "accepted")
    await message.answer(f"🗑 <b>{esc(word)}</b> o'chirildi." if removed else "Bu so'z lug'atda yo'q.")


@router.message(Command("word"))
async def cmd_word(message: Message, command: CommandObject, db: Database) -> None:
    word = normalize(command.args or "")
    info = await db.word_info(word) if word else None
    if info is None:
        await message.answer("Bu so'z bazada yo'q.")
        return
    uz = (await db.get_translations([word])).get(word)
    await message.answer(
        f"🔤 <b>{esc(info['word'])}</b>\nDaraja: {Level(info['level']).name} · rank: {info['rank']}\n"
        f"Holat: {'✅ faol' if info['enabled'] else '🚫 o‘chirilgan'} · manba: {info['source']}\n"
        f"🇺🇿 Tarjima: {esc(uz) if uz else '— (birinchi o‘yinda avtomatik olinadi)'}"
    )


@router.message(Command("tr"))
async def cmd_translation(message: Message, command: CommandObject, db: Database) -> None:
    word, sep, uz = (command.args or "").partition("=")
    word = normalize(word)
    uz = " ".join(uz.split())
    if not word or not sep or not uz:
        await message.answer("Foydalanish: /tr <code>word = tarjima</code>\nMasalan: /tr <code>safe = xavfsiz, seyf</code>")
        return
    await db.save_translation(word, uz[:120], "admin")
    await message.answer(f"✅ <b>{esc(word)}</b> — {esc(uz[:120])}")


@router.message(Command("reports"))
async def cmd_reports(message: Message, db: Database) -> None:
    reports = await db.open_reports(10)
    if not reports:
        await message.answer("🎉 Ochiq xabarlar yo'q.")
        return
    for r in reports:
        what = "lug'atda yo'q, lekin to'g'ri" if r["kind"] == "missing" else "noto'g'ri so'z"
        await message.answer(
            f"🚩 <b>{esc(r['word'])}</b> — {what}\n👥 {r['votes']} kishi xabar bergan",
            reply_markup=kb.report_review(r["word"], r["kind"]),
        )


@router.callback_query(F.data.startswith("adm:"))
async def cb_review(cb: CallbackQuery, db: Database, dictionary: Dictionary) -> None:
    _, decision, kind, word = cb.data.split(":", 3)
    if decision == "ok":
        if kind == "missing":
            rank = rank_for_level(Level.C1)
            await db.upsert_word(word, rank, cb.from_user.id)
            dictionary.remove(word)
            dictionary.add(word, rank)
            result = f"➕ <b>{esc(word)}</b> qo'shildi (C1). Darajani /addword bilan o'zgartirish mumkin."
        else:
            await db.disable_word(word, cb.from_user.id)
            dictionary.remove(word)
            result = f"🗑 <b>{esc(word)}</b> o'chirildi."
        await db.resolve_reports(word, kind, "accepted")
    else:
        await db.resolve_reports(word, kind, "rejected")
        result = f"❌ <b>{esc(word)}</b> bo'yicha xabar rad etildi."
    await cb.message.edit_text(result)
    await cb.answer()


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, bot: Bot, db: Database) -> None:
    source = message.reply_to_message
    if source is None:
        await message.answer("Yuboriladigan xabarga <b>reply</b> qilib /broadcast yozing.")
        return
    users = await db.active_user_ids()
    status = await message.answer(f"📤 Yuborilmoqda: {len(users)} kishiga...")
    asyncio.create_task(_broadcast(bot, db, source, users, status))


async def _broadcast(bot: Bot, db: Database, source: Message, users: list[int], status: Message) -> None:
    sent = failed = 0
    for uid in users:
        for _ in range(2):
            try:
                await bot.copy_message(uid, source.chat.id, source.message_id)
                sent += 1
                break
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after)
            except TelegramForbiddenError:
                await db.set_blocked(uid)
                failed += 1
                break
            except TelegramAPIError:
                failed += 1
                break
        await asyncio.sleep(0.05)  # stay well below Telegram's ~30 msg/s limit
    try:
        await status.edit_text(f"✅ Tugadi. Yuborildi: <b>{sent}</b> · Xato/bloklagan: <b>{failed}</b>")
    except TelegramAPIError:
        log.info("broadcast finished: sent=%s failed=%s", sent, failed)
