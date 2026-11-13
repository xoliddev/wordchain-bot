"""SQLite storage (aiosqlite). One shared connection; writes are serialized with
a lock so concurrent games never interleave inside a transaction."""
import asyncio
import logging
from dataclasses import dataclass, fields
from pathlib import Path

import aiosqlite

from .levels import Level, level_for_rank

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    username      TEXT,
    full_name     TEXT    NOT NULL DEFAULT '',
    level         INTEGER NOT NULL DEFAULT 0,
    rating        INTEGER NOT NULL DEFAULT 1000,
    bot_games     INTEGER NOT NULL DEFAULT 0,
    bot_wins      INTEGER NOT NULL DEFAULT 0,
    pvp_games     INTEGER NOT NULL DEFAULT 0,
    pvp_wins      INTEGER NOT NULL DEFAULT 0,
    streak        INTEGER NOT NULL DEFAULT 0,
    best_streak   INTEGER NOT NULL DEFAULT 0,
    words_played  INTEGER NOT NULL DEFAULT 0,
    longest_word  TEXT    NOT NULL DEFAULT '',
    is_blocked    INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen     TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_users_rating ON users(rating DESC);

CREATE TABLE IF NOT EXISTS words (
    word        TEXT    PRIMARY KEY,
    rank        INTEGER NOT NULL,
    level       INTEGER NOT NULL,
    enabled     INTEGER NOT NULL DEFAULT 1,
    source      TEXT    NOT NULL DEFAULT 'base',
    updated_by  INTEGER,
    updated_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS games (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    mode         TEXT    NOT NULL,              -- 'bot' | 'pvp'
    bot_level    INTEGER,
    player1_id   INTEGER NOT NULL,
    player2_id   INTEGER,                       -- NULL = bot
    winner_id    INTEGER,                       -- NULL = bot won
    reason       TEXT    NOT NULL,
    moves_count  INTEGER NOT NULL,
    rated        INTEGER NOT NULL DEFAULT 0,
    started_at   TEXT    NOT NULL,
    finished_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_games_finished ON games(finished_at);

CREATE TABLE IF NOT EXISTS moves (
    game_id  INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    idx      INTEGER NOT NULL,
    user_id  INTEGER,                           -- NULL = bot
    word     TEXT    NOT NULL,
    PRIMARY KEY (game_id, idx)
);

CREATE TABLE IF NOT EXISTS user_words (
    user_id     INTEGER NOT NULL REFERENCES users(id),
    word        TEXT    NOT NULL,
    times       INTEGER NOT NULL DEFAULT 1,
    first_used  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, word)
);

CREATE TABLE IF NOT EXISTS word_reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    word        TEXT    NOT NULL,
    kind        TEXT    NOT NULL,               -- 'missing' | 'invalid'
    status      TEXT    NOT NULL DEFAULT 'open',
    created_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, word, kind)
);
CREATE INDEX IF NOT EXISTS idx_reports_open ON word_reports(status, word);

CREATE TABLE IF NOT EXISTS translations (
    word        TEXT PRIMARY KEY,
    uz          TEXT NOT NULL,
    source      TEXT NOT NULL,                  -- 'google' | 'admin'
    updated_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


@dataclass(frozen=True)
class UserProfile:
    id: int
    username: str | None
    full_name: str
    level: int
    rating: int
    bot_games: int
    bot_wins: int
    pvp_games: int
    pvp_wins: int
    streak: int
    best_streak: int
    words_played: int
    longest_word: str
    is_blocked: int
    created_at: str
    last_seen: str

    @property
    def display_name(self) -> str:
        name = self.full_name or (f"@{self.username}" if self.username else "Player")
        return name[:32]

    @property
    def lvl(self) -> Level:
        return Level(self.level)


_PROFILE_FIELDS = [f.name for f in fields(UserProfile)]


@dataclass
class PlayerResult:
    user_id: int
    won: bool
    words: list[str]
    rating_delta: int = 0


@dataclass
class GameRecord:
    mode: str
    bot_level: int | None
    player1_id: int
    player2_id: int | None
    winner_id: int | None
    reason: str
    rated: bool
    started_at: str
    finished_at: str
    results: list[PlayerResult]
    moves: list[tuple[int | None, str]]


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._conn: aiosqlite.Connection | None = None
        self._write = asyncio.Lock()

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("database is not connected")
        return self._conn

    async def connect(self) -> None:
        if self.path != Path(":memory:"):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        await self._conn.executescript(SCHEMA)
        await self._conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def _fetchone(self, sql: str, params: tuple = ()) -> aiosqlite.Row | None:
        async with self.conn.execute(sql, params) as cur:
            return await cur.fetchone()

    async def _fetchall(self, sql: str, params: tuple = ()) -> list[aiosqlite.Row]:
        async with self.conn.execute(sql, params) as cur:
            return list(await cur.fetchall())

    async def _scalar(self, sql: str, params: tuple = ()) -> int:
        row = await self._fetchone(sql, params)
        return row[0] if row and row[0] is not None else 0

    # ------------------------------------------------------------------ words

    async def words_count(self) -> int:
        return await self._scalar("SELECT COUNT(*) FROM words WHERE enabled = 1")

    async def seed_words(self, words: list[str]) -> None:
        rows = [(w, rank, int(level_for_rank(rank))) for rank, w in enumerate(words)]
        async with self._write:
            await self.conn.executemany(
                "INSERT OR IGNORE INTO words (word, rank, level) VALUES (?, ?, ?)", rows
            )
            await self.conn.commit()

    async def load_words(self) -> list[tuple[str, int]]:
        rows = await self._fetchall("SELECT word, rank FROM words WHERE enabled = 1")
        return [(r["word"], r["rank"]) for r in rows]

    async def word_info(self, word: str) -> aiosqlite.Row | None:
        return await self._fetchone("SELECT * FROM words WHERE word = ?", (word,))

    async def upsert_word(self, word: str, rank: int, admin_id: int) -> None:
        async with self._write:
            await self.conn.execute(
                """INSERT INTO words (word, rank, level, enabled, source, updated_by)
                   VALUES (?, ?, ?, 1, 'admin', ?)
                   ON CONFLICT(word) DO UPDATE SET rank = excluded.rank, level = excluded.level,
                       enabled = 1, updated_by = excluded.updated_by, updated_at = CURRENT_TIMESTAMP""",
                (word, rank, int(level_for_rank(rank)), admin_id),
            )
            await self.conn.commit()

    async def disable_word(self, word: str, admin_id: int) -> bool:
        async with self._write:
            cur = await self.conn.execute(
                """UPDATE words SET enabled = 0, updated_by = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE word = ? AND enabled = 1""",
                (admin_id, word),
            )
            await self.conn.commit()
            return cur.rowcount > 0

    # ----------------------------------------------------------- translations

    async def get_translations(self, words: list[str]) -> dict[str, str]:
        if not words:
            return {}
        marks = ",".join("?" * len(words))
        rows = await self._fetchall(f"SELECT word, uz FROM translations WHERE word IN ({marks})", tuple(words))
        return {r["word"]: r["uz"] for r in rows}

    async def save_translation(self, word: str, uz: str, source: str) -> None:
        """Admin translations are never overwritten by automatic ones."""
        async with self._write:
            await self.conn.execute(
                """INSERT INTO translations (word, uz, source) VALUES (?, ?, ?)
                   ON CONFLICT(word) DO UPDATE SET uz = excluded.uz, source = excluded.source,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE translations.source != 'admin' OR excluded.source = 'admin'""",
                (word, uz, source),
            )
            await self.conn.commit()

    # ------------------------------------------------------------------ users

    async def upsert_user(self, user_id: int, username: str | None, full_name: str) -> UserProfile:
        async with self._write:
            await self.conn.execute(
                """INSERT INTO users (id, username, full_name) VALUES (?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET username = excluded.username,
                       full_name = excluded.full_name, is_blocked = 0, last_seen = CURRENT_TIMESTAMP""",
                (user_id, username, full_name),
            )
            await self.conn.commit()
        profile = await self.get_user(user_id)
        assert profile is not None
        return profile

    async def get_user(self, user_id: int) -> UserProfile | None:
        row = await self._fetchone("SELECT * FROM users WHERE id = ?", (user_id,))
        return UserProfile(**{k: row[k] for k in _PROFILE_FIELDS}) if row else None

    async def set_level(self, user_id: int, level: Level) -> None:
        async with self._write:
            await self.conn.execute("UPDATE users SET level = ? WHERE id = ?", (int(level), user_id))
            await self.conn.commit()

    async def set_blocked(self, user_id: int) -> None:
        async with self._write:
            await self.conn.execute("UPDATE users SET is_blocked = 1 WHERE id = ?", (user_id,))
            await self.conn.commit()

    async def ratings(self, *user_ids: int) -> dict[int, int]:
        marks = ",".join("?" * len(user_ids))
        rows = await self._fetchall(f"SELECT id, rating FROM users WHERE id IN ({marks})", user_ids)
        return {r["id"]: r["rating"] for r in rows}

    async def active_user_ids(self) -> list[int]:
        rows = await self._fetchall("SELECT id FROM users WHERE is_blocked = 0")
        return [r["id"] for r in rows]

    async def top_players(self, limit: int = 10) -> list[UserProfile]:
        rows = await self._fetchall(
            "SELECT * FROM users WHERE pvp_games > 0 ORDER BY rating DESC, pvp_wins DESC LIMIT ?", (limit,)
        )
        return [UserProfile(**{k: r[k] for k in _PROFILE_FIELDS}) for r in rows]

    async def top_wordsmiths(self, limit: int = 10) -> list[UserProfile]:
        rows = await self._fetchall(
            "SELECT * FROM users WHERE words_played > 0 ORDER BY words_played DESC LIMIT ?", (limit,)
        )
        return [UserProfile(**{k: r[k] for k in _PROFILE_FIELDS}) for r in rows]

    async def rating_position(self, user_id: int) -> int | None:
        row = await self._fetchone(
            """SELECT 1 + (SELECT COUNT(*) FROM users o WHERE o.pvp_games > 0 AND o.rating > u.rating)
               FROM users u WHERE u.id = ? AND u.pvp_games > 0""",
            (user_id,),
        )
        return row[0] if row else None

    async def vocabulary(self, user_id: int) -> dict[Level, int]:
        rows = await self._fetchall(
            """SELECT w.level AS level, COUNT(*) AS n FROM user_words uw
               JOIN words w ON w.word = uw.word WHERE uw.user_id = ? GROUP BY w.level""",
            (user_id,),
        )
        return {Level(r["level"]): r["n"] for r in rows}

    # ------------------------------------------------------------------ games

    async def save_game(self, rec: GameRecord) -> int:
        async with self._write:
            try:
                cur = await self.conn.execute(
                    """INSERT INTO games (mode, bot_level, player1_id, player2_id, winner_id, reason,
                                          moves_count, rated, started_at, finished_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (rec.mode, rec.bot_level, rec.player1_id, rec.player2_id, rec.winner_id, rec.reason,
                     len(rec.moves), int(rec.rated), rec.started_at, rec.finished_at),
                )
                game_id = cur.lastrowid
                await self.conn.executemany(
                    "INSERT INTO moves (game_id, idx, user_id, word) VALUES (?, ?, ?, ?)",
                    [(game_id, i, uid, w) for i, (uid, w) in enumerate(rec.moves)],
                )
                bot = rec.mode == "bot"
                for r in rec.results:
                    longest = max(r.words, key=len, default="")
                    await self.conn.execute(
                        """UPDATE users SET
                               bot_games = bot_games + ?, bot_wins = bot_wins + ?,
                               pvp_games = pvp_games + ?, pvp_wins = pvp_wins + ?,
                               rating = rating + ?,
                               streak = CASE WHEN ? THEN streak + 1 ELSE 0 END,
                               best_streak = MAX(best_streak, CASE WHEN ? THEN streak + 1 ELSE 0 END),
                               words_played = words_played + ?,
                               longest_word = CASE WHEN length(?) > length(longest_word)
                                                   THEN ? ELSE longest_word END
                           WHERE id = ?""",
                        (int(bot), int(bot and r.won), int(not bot), int(not bot and r.won),
                         r.rating_delta, r.won, r.won, len(r.words), longest, longest, r.user_id),
                    )
                    await self.conn.executemany(
                        """INSERT INTO user_words (user_id, word) VALUES (?, ?)
                           ON CONFLICT(user_id, word) DO UPDATE SET times = times + 1""",
                        [(r.user_id, w) for w in r.words],
                    )
                await self.conn.commit()
                return game_id
            except Exception:
                await self.conn.rollback()
                raise

    # ---------------------------------------------------------------- reports

    async def add_report(self, user_id: int, word: str, kind: str) -> bool:
        async with self._write:
            cur = await self.conn.execute(
                "INSERT OR IGNORE INTO word_reports (user_id, word, kind) VALUES (?, ?, ?)",
                (user_id, word, kind),
            )
            await self.conn.commit()
            return cur.rowcount > 0

    async def open_reports(self, limit: int = 10) -> list[aiosqlite.Row]:
        return await self._fetchall(
            """SELECT word, kind, COUNT(*) AS votes FROM word_reports WHERE status = 'open'
               GROUP BY word, kind ORDER BY votes DESC, MIN(id) LIMIT ?""",
            (limit,),
        )

    async def resolve_reports(self, word: str, kind: str, status: str) -> None:
        async with self._write:
            await self.conn.execute(
                "UPDATE word_reports SET status = ? WHERE word = ? AND kind = ? AND status = 'open'",
                (status, word, kind),
            )
            await self.conn.commit()

    # ------------------------------------------------------------------ admin

    async def global_stats(self) -> dict[str, int]:
        q = {
            "users": "SELECT COUNT(*) FROM users",
            "active_day": "SELECT COUNT(*) FROM users WHERE last_seen >= datetime('now', '-1 day')",
            "new_day": "SELECT COUNT(*) FROM users WHERE created_at >= datetime('now', '-1 day')",
            "blocked": "SELECT COUNT(*) FROM users WHERE is_blocked = 1",
            "games": "SELECT COUNT(*) FROM games",
            "games_day": "SELECT COUNT(*) FROM games WHERE finished_at >= datetime('now', '-1 day')",
            "pvp_games": "SELECT COUNT(*) FROM games WHERE mode = 'pvp'",
            "moves": "SELECT COUNT(*) FROM moves",
            "words": "SELECT COUNT(*) FROM words WHERE enabled = 1",
            "reports": "SELECT COUNT(DISTINCT word || kind) FROM word_reports WHERE status = 'open'",
        }
        return {k: await self._scalar(sql) for k, sql in q.items()}
