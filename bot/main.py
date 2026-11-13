import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from .config import WORDS_FILE, load_settings
from .db import Database
from .dictionary import Dictionary
from .game_manager import GameManager
from .handlers import setup_routers
from .middlewares import SubscriptionMiddleware, UserMiddleware
from .notifier import TelegramNotifier
from .translator import Translator

log = logging.getLogger("wordchain")

COMMANDS = [
    BotCommand(command="start", description="🏠 Bosh menyu"),
    BotCommand(command="play", description="🤖 Bot bilan o'ynash"),
    BotCommand(command="pvp", description="👥 Tasodifiy raqib"),
    BotCommand(command="friend", description="🔗 Do'st bilan o'ynash"),
    BotCommand(command="hint", description="💡 Maslahat (bot bilan o'yinda)"),
    BotCommand(command="giveup", description="🏳️ Taslim bo'lish"),
    BotCommand(command="cancel", description="❌ Qidiruvni bekor qilish"),
    BotCommand(command="stats", description="📊 Statistikam"),
    BotCommand(command="top", description="🏆 Reyting jadvali"),
    BotCommand(command="level", description="📶 Darajani tanlash"),
    BotCommand(command="rules", description="📖 Qoidalar"),
]


async def load_dictionary(db: Database) -> Dictionary:
    if await db.words_count() == 0:
        words = [w for w in WORDS_FILE.read_text(encoding="utf-8").split() if w]
        log.info("seeding %d words from %s", len(words), WORDS_FILE.name)
        await db.seed_words(words)
    dictionary = Dictionary(await db.load_words())
    log.info("dictionary loaded: %d words", len(dictionary))
    return dictionary


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    settings = load_settings()
    db = Database(settings.db_path)
    await db.connect()
    dictionary = await load_dictionary(db)

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    me = await bot.get_me()
    translator = Translator(db) if settings.translate else None
    manager = GameManager(TelegramNotifier(bot), db, dictionary, settings, me.username, translator=translator)

    dp = Dispatcher(db=db, dictionary=dictionary, manager=manager, settings=settings)
    for observer in (dp.message, dp.callback_query):
        observer.outer_middleware(UserMiddleware())
        if settings.required_channel:
            observer.middleware(SubscriptionMiddleware(settings))
    dp.include_routers(*setup_routers())

    await bot.set_my_commands(COMMANDS)
    log.info("@%s started", me.username)
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await manager.shutdown()
        if translator is not None:
            await translator.close()
        await db.close()
        await bot.session.close()


def run() -> None:
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit) as e:
        if isinstance(e, SystemExit) and e.code not in (None, 0):
            raise


if __name__ == "__main__":
    run()
