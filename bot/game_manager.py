"""Runs live games: turns, timers, the bot opponent, matchmaking and invites.

Concurrency model: every game has its own lock; every state change of a game
happens while holding it. Each turn gets a fresh `token`; a timer or bot task
whose token is stale (the turn already moved on) does nothing.
"""
import asyncio
import logging
import random
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import keyboards as kb
from . import texts
from .ai import COMPLIMENTS, WIN_PHRASES, BotBrain
from .config import Settings
from .db import Database, GameRecord, PlayerResult, UserProfile
from .dictionary import Dictionary
from .engine import GameState, Outcome, Player, Reject, normalize
from .levels import BOT_TURN_SECONDS, Level
from .notifier import Notifier
from .rating import elo
from .translator import Translator

log = logging.getLogger(__name__)

WARN_BEFORE = 10            # seconds before the deadline to warn the player
QUEUE_OFFER_AFTER = 45      # seconds in the queue before suggesting a bot game
QUEUE_WIDEN_AFTER = 30      # after this, match with any level
INVITE_TTL = 600
MIN_RATED_MOVES = 2         # shorter PvP games do not change the rating
LEARN_WORDS = 12            # bot words shown after the game to learn from


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


@dataclass(eq=False)
class Session:
    mode: str                               # "bot" | "pvp"
    state: GameState
    turn_seconds: float
    brain: BotBrain | None = None
    bot_delta: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    task: asyncio.Task | None = None
    token: int = 0
    finished: bool = False
    started_at: str = field(default_factory=utcnow)
    hints: dict[int, int] = field(default_factory=dict)

    @property
    def humans(self) -> list[Player]:
        return [p for p in self.state.players if not p.is_bot]


@dataclass(eq=False)
class Waiting:
    profile: UserProfile
    joined: float
    task: asyncio.Task | None = None


@dataclass(eq=False)
class Invite:
    code: str
    profile: UserProfile
    created: float


class GameManager:
    def __init__(
        self,
        notifier: Notifier,
        db: Database,
        dictionary: Dictionary,
        settings: Settings,
        bot_username: str,
        *,
        bot_speed: float = 1.0,
        time_scale: float = 1.0,
        rng: random.Random | None = None,
        translator: Translator | None = None,
    ) -> None:
        self.notifier = notifier
        self.translator = translator
        self.db = db
        self.dictionary = dictionary
        self.settings = settings
        self.bot_username = bot_username
        self.bot_speed = bot_speed
        self.time_scale = time_scale
        self.rng = rng or random.Random()
        self._sessions: dict[int, Session] = {}
        self._queue: dict[int, Waiting] = {}
        self._invites: dict[str, Invite] = {}
        self._registry = asyncio.Lock()      # guards _sessions/_queue/_invites membership

    # ------------------------------------------------------------- queries

    def session_of(self, user_id: int) -> Session | None:
        return self._sessions.get(user_id)

    def in_queue(self, user_id: int) -> bool:
        return user_id in self._queue

    @property
    def live_games(self) -> int:
        return len({id(s) for s in self._sessions.values()})

    @property
    def queue_size(self) -> int:
        return len(self._queue)

    # ------------------------------------------------------- starting games

    async def start_bot_game(self, profile: UserProfile, delta: int = 0) -> bool:
        async with self._registry:
            if profile.id in self._sessions:
                return False
            self._leave_queue_locked(profile.id)
            self._drop_invites_locked(profile.id)
            level = profile.lvl.shifted(delta)
            brain = BotBrain(self.dictionary, level, rng=random.Random(self.rng.random()), speed=self.bot_speed)
            players = [
                Player(profile.id, profile.display_name, profile.lvl, rating=profile.rating),
                Player(None, brain.name, level, is_bot=True),
            ]
            s = Session("bot", self._new_state(players, first=0),
                        BOT_TURN_SECONDS[profile.lvl] * self.time_scale, brain=brain, bot_delta=delta)
            await s.lock.acquire()
            self._sessions[profile.id] = s
        try:
            await self.notifier.send(
                profile.id,
                texts.bot_game_started(brain.name, level, s.turn_seconds,
                                       self.settings.max_strikes, self.settings.max_hints),
                kb.game_controls(with_hint=True),
            )
            self._begin_turn(s)
        finally:
            s.lock.release()
        return True

    async def _start_pvp_locked(self, a: UserProfile, b: UserProfile) -> None:
        """Caller holds the registry lock."""
        players = [
            Player(a.id, a.display_name, a.lvl, rating=a.rating),
            Player(b.id, b.display_name, b.lvl, rating=b.rating),
        ]
        first = self.rng.randrange(2)
        s = Session("pvp", self._new_state(players, first=first),
                    self.settings.pvp_turn_seconds * self.time_scale)
        await s.lock.acquire()
        self._sessions[a.id] = self._sessions[b.id] = s
        try:
            for i, p in enumerate(players):
                o = players[1 - i]
                await self.notifier.send(
                    p.id,
                    texts.pvp_started(o.name, o.level, o.rating, i == first, s.turn_seconds,
                                      self.settings.max_strikes),
                    kb.game_controls(with_hint=False),
                )
            self._begin_turn(s)
        finally:
            s.lock.release()

    def _new_state(self, players: list[Player], first: int) -> GameState:
        return GameState(players, self.dictionary, min_length=self.settings.min_word_length,
                         max_strikes=self.settings.max_strikes, first=first)

    # --------------------------------------------------------- matchmaking

    async def join_queue(self, profile: UserProfile) -> str:
        """Returns 'busy', 'already', 'matched' or 'queued'."""
        async with self._registry:
            if profile.id in self._sessions:
                return "busy"
            if profile.id in self._queue:
                return "already"
            self._drop_invites_locked(profile.id)
            opponent = self._find_opponent(profile)
            if opponent is not None:
                waiting = self._queue.pop(opponent)
                self._cancel(waiting.task)
                await self._start_pvp_locked(waiting.profile, profile)
                return "matched"
            entry = Waiting(profile, time.monotonic())
            entry.task = asyncio.create_task(self._offer_bot_later(profile.id, entry))
            self._queue[profile.id] = entry
            return "queued"

    def _find_opponent(self, profile: UserProfile) -> int | None:
        now = time.monotonic()
        best, best_key = None, None
        for uid, w in self._queue.items():
            diff = abs(w.profile.level - profile.level)
            if diff > 1 and now - w.joined < QUEUE_WIDEN_AFTER * self.time_scale:
                continue
            key = (diff, abs(w.profile.rating - profile.rating), w.joined)
            if best_key is None or key < best_key:
                best, best_key = uid, key
        return best

    async def _offer_bot_later(self, user_id: int, entry: Waiting) -> None:
        await asyncio.sleep(QUEUE_OFFER_AFTER * self.time_scale)
        if self._queue.get(user_id) is entry:
            await self.notifier.send(user_id, texts.QUEUE_OFFER, kb.queue_offer())

    async def leave_queue(self, user_id: int) -> bool:
        async with self._registry:
            return self._leave_queue_locked(user_id)

    def _leave_queue_locked(self, user_id: int) -> bool:
        entry = self._queue.pop(user_id, None)
        if entry is None:
            return False
        self._cancel(entry.task)
        return True

    # ------------------------------------------------------------- invites

    async def create_invite(self, profile: UserProfile) -> str | None:
        async with self._registry:
            if profile.id in self._sessions:
                return None
            self._leave_queue_locked(profile.id)
            self._drop_invites_locked(profile.id)
            code = secrets.token_urlsafe(6)
            self._invites[code] = Invite(code, profile, time.monotonic())
            return f"https://t.me/{self.bot_username}?start=inv_{code}"

    async def accept_invite(self, code: str, profile: UserProfile) -> str:
        """Returns 'ok', 'expired', 'self', 'busy' or 'host_busy'."""
        async with self._registry:
            inv = self._invites.get(code)
            if inv is None or time.monotonic() - inv.created > INVITE_TTL:
                self._invites.pop(code, None)
                return "expired"
            if inv.profile.id == profile.id:
                return "self"
            if profile.id in self._sessions:
                return "busy"
            if inv.profile.id in self._sessions:
                del self._invites[code]
                return "host_busy"
            del self._invites[code]
            for uid in (inv.profile.id, profile.id):
                self._leave_queue_locked(uid)
                self._drop_invites_locked(uid)
            host = await self.db.get_user(inv.profile.id) or inv.profile
            await self._start_pvp_locked(host, profile)
            return "ok"

    async def cancel_invite(self, user_id: int) -> bool:
        async with self._registry:
            return self._drop_invites_locked(user_id)

    def _drop_invites_locked(self, user_id: int) -> bool:
        codes = [c for c, inv in self._invites.items() if inv.profile.id == user_id]
        for c in codes:
            del self._invites[c]
        return bool(codes)

    # ---------------------------------------------------------- turn flow

    def _begin_turn(self, s: Session) -> None:
        """Caller holds s.lock."""
        self._cancel(s.task)
        s.token += 1
        coro = self._bot_turn(s, s.token) if s.state.current.is_bot else self._turn_clock(s, s.token)
        s.task = asyncio.create_task(coro)

    @staticmethod
    def _cancel(task: asyncio.Task | None) -> None:
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()

    @staticmethod
    def _stale(s: Session, token: int) -> bool:
        return s.finished or s.token != token

    async def _turn_clock(self, s: Session, token: int) -> None:
        try:
            total = s.turn_seconds
            warn = WARN_BEFORE * self.time_scale
            if total > 2 * warn:
                await asyncio.sleep(total - warn)
                async with s.lock:
                    if self._stale(s, token):
                        return
                    await self.notifier.send(s.state.current.id, texts.time_warning(WARN_BEFORE))
                await asyncio.sleep(warn)
            else:
                await asyncio.sleep(total)
            async with s.lock:
                if not self._stale(s, token):
                    await self._finish(s, loser=s.state.turn, outcome=Outcome.TIMEOUT)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("turn clock failed")

    async def _bot_turn(self, s: Session, token: int) -> None:
        try:
            human = s.humans[0]
            delay, waited = s.brain.think_time(), 0.0
            while waited < delay:
                await self.notifier.typing(human.id)
                step = min(4.0, delay - waited)
                await asyncio.sleep(step)
                waited += step
            async with s.lock:
                if self._stale(s, token):
                    return
                st, bot = s.state, s.state.current
                word = s.brain.choose(st.required_letter, st.used, len(bot.words))
                if word is None or st.play(word) is not None:
                    await self.notifier.send(human.id, texts.bot_says(bot.name, s.brain.give_up_phrase()))
                    await self._finish(s, loser=st.players.index(bot), outcome=Outcome.STUCK)
                    return
                await self.notifier.send(
                    human.id,
                    texts.bot_move(bot.name, word, self.dictionary.level_of(word), s.turn_seconds),
                    kb.report_invalid(word),
                )
                self._begin_turn(s)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("bot turn failed")

    # ------------------------------------------------------- player input

    async def handle_word(self, user_id: int, text: str, message_id: int | None = None) -> bool:
        """Processes a message from a player. False if the user is not in a game."""
        s = self._sessions.get(user_id)
        if s is None:
            return False
        async with s.lock:
            if s.finished:
                return True
            st = s.state
            idx = st.index_of(user_id)
            me, other = st.players[idx], st.players[1 - idx]
            if st.turn != idx:
                await self.notifier.send(user_id, texts.not_your_turn(other.name))
                return True

            word = normalize(text)
            reject = st.play(word)
            if reject is Reject.FORMAT:
                await self.notifier.send(user_id, texts.FORMAT_HINT)
                return True
            if reject is not None:
                out = st.add_strike()
                await self.notifier.send(
                    user_id,
                    texts.rejected(reject, word, st.required_letter, me.strikes, st.max_strikes),
                    kb.report_missing(word) if reject is Reject.UNKNOWN else None,
                )
                if out:
                    await self._finish(s, loser=idx, outcome=Outcome.STRIKES)
                return True

            level = self.dictionary.level_of(word)
            emoji = "🔥" if len(word) >= 8 else "👍"
            if message_id is None or not await self.notifier.react(user_id, message_id, emoji):
                await self.notifier.send(user_id, texts.accepted(word, level))
            if other.is_bot:
                if len(word) >= 8 and s.brain.rng.random() < 0.35:
                    await self.notifier.send(user_id, texts.bot_says(other.name, s.brain.phrase(COMPLIMENTS)))
            else:
                await self.notifier.send(
                    other.id, texts.opponent_move(me.name, word, level, s.turn_seconds), kb.report_invalid(word)
                )
            self._begin_turn(s)
            return True

    async def hint(self, user_id: int) -> None:
        s = self._sessions.get(user_id)
        if s is None:
            await self.notifier.send(user_id, texts.NOT_IN_GAME)
            return
        async with s.lock:
            if s.finished:
                return
            st = s.state
            if s.mode != "bot":
                await self.notifier.send(user_id, texts.HINTS_PVP)
                return
            if st.current.id != user_id:
                await self.notifier.send(user_id, texts.HINT_WAIT)
                return
            used = s.hints.get(user_id, 0)
            if used >= self.settings.max_hints:
                await self.notifier.send(user_id, texts.HINTS_OVER)
                return
            word = self._suggest(st.required_letter or self.rng.choice("bcdfmpst"), st.current.level, st.used)
            if word is None:
                await self.notifier.send(user_id, texts.HINT_NOT_FOUND)
                return
            s.hints[user_id] = used + 1
            await self.notifier.send(user_id, texts.hint(word, self.settings.max_hints - used - 1))

    def _suggest(self, letter: str, level: Level, used: set[str]) -> str | None:
        for lv in range(level, Level.C2 + 1):
            options = [w for w in self.dictionary.known(letter, Level(lv))[:300] if w not in used]
            if options:
                return self.rng.choice(options[:40])
        return None

    async def resign(self, user_id: int) -> bool:
        s = self._sessions.get(user_id)
        if s is None:
            return False
        async with s.lock:
            if not s.finished:
                await self._finish(s, loser=s.state.index_of(user_id), outcome=Outcome.RESIGN)
        return True

    # ---------------------------------------------------------- game over

    async def _finish(self, s: Session, loser: int, outcome: Outcome) -> None:
        """Caller holds s.lock."""
        if s.finished:
            return
        s.finished = True
        self._cancel(s.task)
        for p in s.humans:
            if self._sessions.get(p.id) is s:
                del self._sessions[p.id]

        st = s.state
        winner = 1 - loser
        ratings = await self._persist(s, winner, outcome)
        longest = st.longest_word()
        for i, p in enumerate(st.players):
            if p.is_bot:
                continue
            o = st.players[1 - i]
            learn = []
            if o.is_bot and o.words:
                rare_first = sorted(set(o.words), key=lambda w: -(self.dictionary.rank(w) or 0))[:LEARN_WORDS]
                uz = await self._translate(rare_first)
                learn = [(w, self.dictionary.level_of(w), uz.get(w)) for w in rare_first]
            await self.notifier.send(
                p.id,
                texts.game_over(won=i == winner, outcome=outcome, opponent=o.name, total=len(st.history),
                                mine=len(p.words), theirs=len(o.words), longest=longest,
                                rating=ratings.get(p.id), learn=learn),
                kb.remove(),
            )
            if o.is_bot and i == loser:
                await self.notifier.send(p.id, texts.bot_says(o.name, s.brain.phrase(WIN_PHRASES)))
            await self.notifier.send(p.id, texts.PLAY_AGAIN, kb.after_game(s.mode, s.bot_delta))

    async def _translate(self, words: list[str]) -> dict[str, str]:
        if self.translator is None:
            return {}
        try:
            return await self.translator.translate_many(words)
        except Exception:
            log.exception("translation failed")
            return {}

    async def _persist(self, s: Session, winner: int, outcome: Outcome) -> dict[int, tuple[int, int]]:
        st = s.state
        a, b = st.players
        rated = s.mode == "pvp" and len(st.history) >= MIN_RATED_MOVES
        ratings: dict[int, tuple[int, int]] = {}
        try:
            if rated:
                current = await self.db.ratings(a.id, b.id)
                w, l = st.players[winner], st.players[1 - winner]
                rw, rl = current.get(w.id, w.rating), current.get(l.id, l.rating)
                nw, nl = elo(rw, rl)
                ratings = {w.id: (rw, nw), l.id: (rl, nl)}
            results = [
                PlayerResult(p.id, i == winner, list(p.words),
                             ratings[p.id][1] - ratings[p.id][0] if p.id in ratings else 0)
                for i, p in enumerate(st.players) if not p.is_bot
            ]
            await self.db.save_game(GameRecord(
                mode=s.mode,
                bot_level=int(s.brain.level) if s.brain else None,
                player1_id=a.id,
                player2_id=b.id,
                winner_id=st.players[winner].id,
                reason=outcome.value,
                rated=rated,
                started_at=s.started_at,
                finished_at=utcnow(),
                results=results,
                moves=[(st.players[i].id, w) for i, w in st.history],
            ))
        except Exception:
            log.exception("failed to save game")
        return ratings

    # ------------------------------------------------------------ shutdown

    async def shutdown(self) -> None:
        async with self._registry:
            for entry in self._queue.values():
                self._cancel(entry.task)
            self._queue.clear()
            self._invites.clear()
            sessions = {id(s): s for s in self._sessions.values()}.values()
            self._sessions.clear()
        for s in sessions:
            s.finished = True
            self._cancel(s.task)
            for p in s.humans:
                await self.notifier.send(p.id, texts.GAME_ABORTED, kb.remove())
