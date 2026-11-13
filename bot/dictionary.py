"""In-memory word index. The database is the source of truth; this mirrors it
so that validating a word or finding the bot's next move never hits the disk."""
import bisect
from collections import defaultdict
from collections.abc import Iterable

from .levels import VOCAB_SIZE, Level, level_for_rank


class Dictionary:
    def __init__(self, entries: Iterable[tuple[str, int]] = ()) -> None:
        self._rank: dict[str, int] = {}
        # words grouped by first letter, most frequent first (parallel lists)
        self._words: dict[str, list[str]] = defaultdict(list)
        self._ranks: dict[str, list[int]] = defaultdict(list)
        for word, rank in sorted(entries, key=lambda e: e[1]):
            if word not in self._rank:
                self._rank[word] = rank
                self._words[word[0]].append(word)
                self._ranks[word[0]].append(rank)

    def __contains__(self, word: object) -> bool:
        return word in self._rank

    def __len__(self) -> int:
        return len(self._rank)

    def rank(self, word: str) -> int | None:
        return self._rank.get(word)

    def level_of(self, word: str) -> Level | None:
        rank = self._rank.get(word)
        return None if rank is None else level_for_rank(rank)

    def count_known(self, letter: str, level: Level) -> int:
        """How many words starting with `letter` a `level` speaker knows."""
        ranks = self._ranks.get(letter)
        return bisect.bisect_left(ranks, VOCAB_SIZE[level]) if ranks else 0

    def known(self, letter: str, level: Level) -> list[str]:
        """Words starting with `letter` that a `level` speaker knows, most frequent first."""
        return self._words[letter][: self.count_known(letter, level)] if letter in self._words else []

    def add(self, word: str, rank: int) -> bool:
        if word in self._rank:
            return False
        letter = word[0]
        i = bisect.bisect_right(self._ranks[letter], rank)
        self._ranks[letter].insert(i, rank)
        self._words[letter].insert(i, word)
        self._rank[word] = rank
        return True

    def remove(self, word: str) -> bool:
        if self._rank.pop(word, None) is None:
            return False
        words = self._words[word[0]]
        i = words.index(word)
        del words[i]
        del self._ranks[word[0]][i]
        return True
