"""Feeds real Telegram updates through the aiogram dispatcher with a fake Bot API
session, so handlers, filters, middlewares and keyboards are exercised end to end."""
import asyncio
import random
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.methods import EditMessageText, GetMe, SendMessage, TelegramMethod
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from bot.config import WORDS_FILE, Settings
from bot.db import Database
from bot.dictionary import Dictionary
from bot.game_manager import GameManager
from bot.handlers import setup_routers
from bot.levels import Level
from bot.middlewares import UserMiddleware
from bot.notifier import TelegramNotifier

ADMIN = 99
BOT_USER = User(id=1, is_bot=True, first_name="WordChain", username="wordchain_bot")


class FakeSession(BaseSession):
    """Records every Bot API call and returns plausible results."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod] = []
        self._ids = 1000

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, GetMe):
            return BOT_USER
        if isinstance(method, (SendMessage, EditMessageText)):
            self._ids += 1
            return Message(message_id=self._ids, date=datetime.now(timezone.utc),
                           chat=Chat(id=method.chat_id or 0, type="private"), text=method.text,
                           from_user=BOT_USER)
        return True

    async def close(self):
        pass

    async def stream_content(self, *a, **kw):  # pragma: no cover
        raise NotImplementedError

    def texts(self, chat_id: int) -> list[str]:
        return [c.text for c in self.calls
                if isinstance(c, (SendMessage, EditMessageText)) and c.chat_id == chat_id]

    def markups(self, chat_id: int) -> list:
        return [c.reply_markup for c in self.calls if isinstance(c, SendMessage) and c.chat_id == chat_id]


def _make_dispatcher() -> Dispatcher:
    # routers are module-level singletons and can join only one dispatcher, so the tests
    # share it and pass each test's own db/manager to feed_update instead
    dp = Dispatcher()
    for observer in (dp.message, dp.callback_query):
        observer.outer_middleware(UserMiddleware())
    dp.include_routers(*setup_routers())
    return dp


DP = _make_dispatcher()


class Harness:
    def __init__(self, tmp_path):
        self.tmp_path = tmp_path
        self.update_id = 0
        self.msg_id = 0

    async def __aenter__(self):
        self.db = Database(self.tmp_path / "tg.db")
        await self.db.connect()
        await self.db.seed_words(WORDS_FILE.read_text(encoding="utf-8").split())
        self.dictionary = Dictionary(await self.db.load_words())
        self.session = FakeSession()
        self.bot = Bot("123456:TEST", session=self.session,
                       default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        settings = Settings(bot_token="x", admin_ids=frozenset({ADMIN}))
        self.manager = GameManager(TelegramNotifier(self.bot), self.db, self.dictionary, settings,
                                   "wordchain_bot", bot_speed=0.0, rng=random.Random(3))
        self.deps = dict(db=self.db, dictionary=self.dictionary, manager=self.manager, settings=settings)
        return self

    async def __aexit__(self, *exc):
        await self.manager.shutdown()
        await self.db.close()

    @staticmethod
    def user(uid: int) -> User:
        return User(id=uid, is_bot=False, first_name=f"User{uid}", username=f"user{uid}")

    async def send(self, uid: int, text: str) -> None:
        self.update_id += 1
        self.msg_id += 1
        message = Message(message_id=self.msg_id, date=datetime.now(timezone.utc),
                          chat=Chat(id=uid, type="private"), from_user=self.user(uid), text=text)
        await DP.feed_update(self.bot, Update(update_id=self.update_id, message=message), **self.deps)
        await self.settle()

    async def press(self, uid: int, data: str) -> None:
        self.update_id += 1
        menu = Message(message_id=1, date=datetime.now(timezone.utc), chat=Chat(id=uid, type="private"),
                       from_user=BOT_USER, text="menu")
        cb = CallbackQuery(id=str(self.update_id), from_user=self.user(uid), chat_instance="ci",
                           message=menu, data=data)
        await DP.feed_update(self.bot, Update(update_id=self.update_id, callback_query=cb), **self.deps)
        await self.settle()

    async def settle(self) -> None:
        for _ in range(30):
            await asyncio.sleep(0)
        await asyncio.sleep(0.01)

    def last(self, uid: int) -> str:
        return self.session.texts(uid)[-1]


def run(coro):
    asyncio.run(coro)


def test_menu_level_stats_and_top(tmp_path):
    async def go():
        async with Harness(tmp_path) as h:
            await h.send(5, "/start")
            assert "Salom, <b>User5</b>" in h.last(5)
            await h.press(5, "level")
            assert "darajangizni tanlang" in h.last(5)
            await h.press(5, "lvl:3")
            assert (await h.db.get_user(5)).level == Level.B2 and "B2" in h.last(5)
            await h.press(5, "stats")
            assert "Statistika" in h.last(5)
            await h.press(5, "top")
            assert "Reyting jadvali" in h.last(5)
            await h.press(5, "rules")
            assert "qoidalari" in h.last(5)
            await h.send(5, "hello")                                  # not in a game
            assert "o'yinda emassiz" in h.last(5)
    run(go())


def test_full_bot_game_through_telegram(tmp_path):
    async def go():
        async with Harness(tmp_path) as h:
            await h.send(7, "/start")
            await h.press(7, "bot")
            assert "Bot qanday darajada" in h.last(7)
            await h.press(7, "bot:0")
            assert "O'yin boshlandi" in h.last(7)
            assert h.session.markups(7)[-1].keyboard[0][0].text == "💡 Yordam"
            await h.send(7, "💡 Yordam")
            assert "Maslahat" in h.last(7)
            for _ in range(300):
                s = h.manager.session_of(7)
                if s is None:
                    break
                if s.state.current.id == 7:
                    letter = s.state.required_letter or "s"
                    word = next(w for w in h.dictionary.known(letter, Level.C2) if w not in s.state.used)
                    await h.send(7, word.capitalize())
                else:
                    await h.settle()
            sent = "\n".join(h.session.texts(7))
            assert "🤖" in sent and "G'ALABA" in sent and "Yana o'ynaymizmi" in sent
            assert (await h.db.get_user(7)).bot_wins == 1
    run(go())


def test_wrong_word_report_and_resign(tmp_path):
    async def go():
        async with Harness(tmp_path) as h:
            await h.press(8, "bot:0")
            await h.send(8, "qwxyzz")
            assert "lug'atda bunday so'z topilmadi" in h.last(8)
            await h.press(8, "rep:missing:qwxyzz")
            assert (await h.db.open_reports())[0]["word"] == "qwxyzz"
            await h.send(8, "🏳️ Taslim bo'lish")
            assert "taslim" in h.last(8).lower()
            await h.press(8, "resign:yes")
            assert h.manager.session_of(8) is None
            assert any("Mag'lubiyat" in t for t in h.session.texts(8))
    run(go())


def test_pvp_queue_and_invite(tmp_path):
    async def go():
        async with Harness(tmp_path) as h:
            await h.press(10, "pvp")
            assert "Raqib qidirilmoqda" in h.last(10)
            await h.send(11, "/pvp")
            assert "Raqib topildi" in h.last(10) and "Raqib topildi" in h.last(11)
            s = h.manager.session_of(10)
            first, second = s.state.current.id, s.state.waiting.id
            await h.send(second, "apple")
            assert "navbati" in h.last(second)
            await h.send(first, "apple")
            assert "👤" in h.last(second) and "<b>Apple</b>" in h.last(second)
            await h.send(first, "/giveup")
            await h.press(first, "resign:yes")
            assert h.manager.session_of(10) is None

            await h.press(10, "friend")
            link = next(t for t in reversed(h.session.texts(10)) if "start=inv_" in t)
            code = link.split("start=inv_")[1].split("<")[0]
            await h.send(12, f"/start inv_{code}")
            assert "Raqib topildi" in h.last(12) and "Raqib topildi" in h.last(10)
    run(go())


def test_admin_commands_and_access(tmp_path):
    async def go():
        async with Harness(tmp_path) as h:
            await h.send(5, "/admin")
            assert "Admin panel" not in h.last(5)                    # regular users are ignored
            await h.send(ADMIN, "/admin")
            assert "Admin panel" in h.last(ADMIN)
            await h.send(ADMIN, "/addword selfie B1")
            assert "selfie" in h.dictionary and h.dictionary.level_of("selfie") == Level.B1
            await h.send(ADMIN, "/delword selfie")
            assert "selfie" not in h.dictionary
            await h.db.add_report(5, "qwxyzz", "missing")
            await h.send(ADMIN, "/reports")
            assert "qwxyzz" in h.last(ADMIN)
            await h.press(ADMIN, "adm:no:missing:qwxyzz")
            assert await h.db.open_reports() == []
    run(go())
