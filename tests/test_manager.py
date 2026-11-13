"""End-to-end game flow with a fake Telegram and a real (temporary) database."""
import asyncio
import random

import pytest

from bot.config import WORDS_FILE, Settings
from bot.db import Database
from bot.dictionary import Dictionary
from bot.game_manager import GameManager
from bot.levels import Level


class FakeNotifier:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    async def send(self, chat_id, text, markup=None) -> bool:
        self.messages.append((chat_id, text))
        return True

    async def typing(self, chat_id) -> None:
        pass

    async def react(self, chat_id, message_id, emoji) -> bool:
        return True

    def to(self, uid: int) -> list[str]:
        return [t for c, t in self.messages if c == uid]


WORDS = WORDS_FILE.read_text(encoding="utf-8").split()


async def setup(tmp_path, time_scale=1.0):
    db = Database(tmp_path / "test.db")
    await db.connect()
    await db.seed_words(WORDS)
    dictionary = Dictionary(await db.load_words())
    notifier = FakeNotifier()
    settings = Settings(bot_token="x")
    manager = GameManager(notifier, db, dictionary, settings, "testbot",
                          bot_speed=0.0, time_scale=time_scale, rng=random.Random(7))
    p1 = await db.upsert_user(1, "ali", "Ali")
    p2 = await db.upsert_user(2, "vali", "Vali")
    return db, dictionary, notifier, manager, p1, p2


async def settle(manager: GameManager) -> None:
    for _ in range(20):
        await asyncio.sleep(0)
    await asyncio.sleep(0.01)


def next_word(dictionary: Dictionary, letter: str | None, used: set[str]) -> str:
    return next(w for w in dictionary.known(letter or "s", Level.C2) if w not in used)


def test_bot_game_until_someone_wins(tmp_path):
    async def run():
        db, dictionary, notifier, manager, p1, _ = await setup(tmp_path)
        await db.set_level(1, Level.B1)
        p1 = await db.get_user(1)
        assert await manager.start_bot_game(p1)
        assert not await manager.start_bot_game(p1)           # already playing
        for _ in range(400):
            s = manager.session_of(1)
            if s is None:
                break
            async with s.lock:
                my_turn = s.state.current.id == 1
                letter, used = s.state.required_letter, set(s.state.used)
            if my_turn:
                assert await manager.handle_word(1, next_word(dictionary, letter, used).upper() + "!", 10)
            await settle(manager)
        assert manager.session_of(1) is None
        text = "\n".join(notifier.to(1))
        assert "G'ALABA" in text                               # the bot eventually blanks out
        user = await db.get_user(1)
        assert user.bot_games == 1 and user.bot_wins == 1 and user.words_played > 0
        assert user.rating == 1000                             # bot games are unrated
        vocab = await db.vocabulary(1)
        assert sum(vocab.values()) == user.words_played
        await db.close()

    asyncio.run(run())


def test_strikes_and_wrong_turn(tmp_path):
    async def run():
        db, dictionary, notifier, manager, p1, p2 = await setup(tmp_path)
        assert await manager.join_queue(p1) == "queued"
        assert await manager.join_queue(p1) == "already"
        assert await manager.join_queue(p2) == "matched"
        s = manager.session_of(1)
        assert s is manager.session_of(2) and not manager.in_queue(1)
        cur = s.state.current.id
        other = 2 if cur == 1 else 1
        await manager.handle_word(other, "apple")
        assert "navbati" in notifier.to(other)[-1]
        await manager.handle_word(cur, "привет")              # format errors are free
        assert s.state.current.strikes == 0
        for w in ["qwzx", "zzqq", "xqxq"]:
            await manager.handle_word(cur, w)
        assert manager.session_of(1) is None
        assert "G'ALABA" in "\n".join(notifier.to(other))
        loser = await db.get_user(cur)
        assert loser.pvp_games == 1 and loser.pvp_wins == 0
        assert loser.rating == 1000                            # too short to be rated
        await db.close()

    asyncio.run(run())


def test_rated_pvp_and_timeout(tmp_path):
    async def run():
        db, dictionary, notifier, manager, p1, p2 = await setup(tmp_path, time_scale=0.01)
        link = await manager.create_invite(p1)
        code = link.split("inv_")[1]
        assert await manager.accept_invite(code, p1) == "self"
        assert await manager.accept_invite(code, p2) == "ok"
        assert await manager.accept_invite(code, p2) == "expired"
        s = manager.session_of(1)
        for _ in range(3):
            async with s.lock:
                cur, letter, used = s.state.current.id, s.state.required_letter, set(s.state.used)
            await manager.handle_word(cur, next_word(dictionary, letter, used))
        async with s.lock:
            slow = s.state.current.id
        await asyncio.sleep(0.6)                               # 45s * 0.01 turn timer
        assert manager.session_of(1) is None
        assert any("Vaqtingiz tugadi" in t for t in notifier.to(slow))
        fast = 2 if slow == 1 else 1
        assert (await db.get_user(fast)).rating == 1016
        assert (await db.get_user(slow)).rating == 984
        top = await db.top_players()
        assert [u.id for u in top] == [fast, slow]
        await db.close()

    asyncio.run(run())


def test_hint_and_resign(tmp_path):
    async def run():
        db, dictionary, notifier, manager, p1, _ = await setup(tmp_path)
        await manager.start_bot_game(p1)
        for _ in range(3):
            await manager.hint(1)
        msgs = notifier.to(1)
        assert sum("Maslahat" in m for m in msgs) == 2 and "tugadi" in msgs[-1]
        await manager.resign(1)
        assert manager.session_of(1) is None
        assert (await db.get_user(1)).bot_games == 1
        await db.close()

    asyncio.run(run())


class FakeTranslator:
    def __init__(self, db):
        self.db = db
        self.requested: list[str] = []

    async def translate_many(self, words):
        self.requested += words
        found = await self.db.get_translations(words)
        return {w: found.get(w, f"uz-{w}") for w in words}


def test_summary_shows_translations(tmp_path):
    async def run():
        db, dictionary, notifier, manager, p1, _ = await setup(tmp_path)
        manager.translator = FakeTranslator(db)
        await manager.start_bot_game(p1)
        await manager.handle_word(1, "safe")
        await settle(manager)                                   # the bot answers
        bot_word = manager.session_of(1).state.players[1].words[0]
        await db.save_translation(bot_word, "admin tarjimasi", "admin")
        await db.save_translation(bot_word, "google tarjimasi", "google")   # must not overwrite
        await manager.resign(1)
        summary = next(t for t in notifier.to(1) if "yodlab oling" in t)
        assert f"<b>{bot_word}</b>" in summary and "admin tarjimasi" in summary
        assert manager.translator.requested == [bot_word]      # only the bot's words
        await db.close()

    asyncio.run(run())


def test_reports(tmp_path):
    async def run():
        db, *_ = await setup(tmp_path)
        assert await db.add_report(1, "selfie", "missing")
        assert not await db.add_report(1, "selfie", "missing")
        await db.add_report(2, "selfie", "missing")
        reports = await db.open_reports()
        assert reports[0]["word"] == "selfie" and reports[0]["votes"] == 2
        await db.resolve_reports("selfie", "missing", "accepted")
        assert await db.open_reports() == []
        await db.close()

    asyncio.run(run())
