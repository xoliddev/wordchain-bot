"""Pure game rules: no Telegram, no database, no timers."""
import re
from dataclasses import dataclass, field
from enum import Enum

from .dictionary import Dictionary
from .levels import Level

_WORD_RE = re.compile(r"[a-z]+")
_EDGE_CHARS = " \t\r\n.,!?;:\"'`«»“”‘’()[]{}"


class Reject(Enum):
    FORMAT = "format"           # not a single latin word; does not count as a mistake
    TOO_SHORT = "too_short"
    WRONG_LETTER = "wrong_letter"
    USED = "used"
    UNKNOWN = "unknown"


class Outcome(Enum):
    TIMEOUT = "timeout"
    STRIKES = "strikes"
    RESIGN = "resign"
    STUCK = "stuck"             # the bot could not find a word


@dataclass
class Player:
    id: int | None              # Telegram user id; None for the bot
    name: str
    level: Level
    is_bot: bool = False
    rating: int = 1000
    strikes: int = 0
    words: list[str] = field(default_factory=list)


def normalize(text: str) -> str | None:
    word = text.strip(_EDGE_CHARS).lower()
    return word if _WORD_RE.fullmatch(word) else None


class GameState:
    def __init__(
        self,
        players: list[Player],
        dictionary: Dictionary,
        *,
        min_length: int = 3,
        max_strikes: int = 3,
        first: int = 0,
    ) -> None:
        if len(players) != 2:
            raise ValueError("word chain is a two-player game")
        self.players = players
        self.dictionary = dictionary
        self.min_length = min_length
        self.max_strikes = max_strikes
        self.turn = first
        self.history: list[tuple[int, str]] = []
        self.used: set[str] = set()

    @property
    def current(self) -> Player:
        return self.players[self.turn]

    @property
    def waiting(self) -> Player:
        return self.players[1 - self.turn]

    @property
    def last_word(self) -> str | None:
        return self.history[-1][1] if self.history else None

    @property
    def required_letter(self) -> str | None:
        last = self.last_word
        return last[-1] if last else None

    def index_of(self, user_id: int) -> int | None:
        for i, p in enumerate(self.players):
            if p.id == user_id and not p.is_bot:
                return i
        return None

    def check(self, word: str | None) -> Reject | None:
        if not word:
            return Reject.FORMAT
        if len(word) < self.min_length:
            return Reject.TOO_SHORT
        letter = self.required_letter
        if letter and word[0] != letter:
            return Reject.WRONG_LETTER
        if word in self.used:
            return Reject.USED
        if word not in self.dictionary:
            return Reject.UNKNOWN
        return None

    def play(self, word: str | None) -> Reject | None:
        """Validates and, if accepted, commits the move and passes the turn."""
        reject = self.check(word)
        if reject is not None:
            return reject
        self.used.add(word)
        self.history.append((self.turn, word))
        self.current.words.append(word)
        self.turn = 1 - self.turn
        return None

    def add_strike(self) -> bool:
        """Registers a mistake for the current player; True if they are out."""
        self.current.strikes += 1
        return self.current.strikes >= self.max_strikes

    def longest_word(self) -> str | None:
        return max((w for _, w in self.history), key=len, default=None)
