from enum import IntEnum


class Level(IntEnum):
    A1 = 0
    A2 = 1
    B1 = 2
    B2 = 3
    C1 = 4
    C2 = 5

    def shifted(self, delta: int) -> "Level":
        return Level(min(max(self + delta, Level.A1), Level.C2))

    @classmethod
    def parse(cls, value: str) -> "Level | None":
        try:
            return cls[value.strip().upper()]
        except KeyError:
            return None


# How many of the most frequent words a speaker of each level "knows".
# A word's level is the lowest level whose vocabulary contains it.
VOCAB_SIZE: dict[Level, int] = {
    Level.A1: 1_000,
    Level.A2: 2_500,
    Level.B1: 5_000,
    Level.B2: 10_000,
    Level.C1: 20_000,
    Level.C2: 10**9,
}

LEVEL_TITLES: dict[Level, str] = {
    Level.A1: "Boshlang'ich",
    Level.A2: "Elementar",
    Level.B1: "O'rta",
    Level.B2: "O'rtadan yuqori",
    Level.C1: "Yuqori",
    Level.C2: "Professional",
}

# Seconds per move against the bot: beginners get more time to think.
BOT_TURN_SECONDS: dict[Level, int] = {
    Level.A1: 60,
    Level.A2: 50,
    Level.B1: 45,
    Level.B2: 40,
    Level.C1: 35,
    Level.C2: 30,
}


def level_for_rank(rank: int) -> Level:
    for level in Level:
        if rank < VOCAB_SIZE[level]:
            return level
    return Level.C2


def rank_for_level(level: Level) -> int:
    """Rank given to words added by admins: the rarest word of that level."""
    return VOCAB_SIZE[level] - 1 if level < Level.C2 else 60_000
