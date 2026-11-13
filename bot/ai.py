"""The bot opponent.

It only "knows" the vocabulary of its level, prefers common words like a real
learner, sometimes blanks out (more often as the game drags on or when it
knows few words for the letter), and stronger levels play strategically by
handing back letters that are hard to continue.
"""
import random
from dataclasses import dataclass

from .dictionary import Dictionary
from .levels import Level


@dataclass(frozen=True)
class Persona:
    fail_chance: float              # chance to blank out on any move
    fatigue: float                  # extra fail chance per move it has made
    cunning: float                  # chance to pick a word ending in a hard letter
    think: tuple[float, float]      # seconds spent "typing"


PERSONAS: dict[Level, Persona] = {
    Level.A1: Persona(0.050, 0.0040, 0.00, (3.5, 8.0)),
    Level.A2: Persona(0.040, 0.0035, 0.10, (3.0, 7.0)),
    Level.B1: Persona(0.032, 0.0030, 0.20, (2.5, 6.0)),
    Level.B2: Persona(0.025, 0.0025, 0.35, (2.0, 5.0)),
    Level.C1: Persona(0.018, 0.0020, 0.50, (1.8, 4.5)),
    Level.C2: Persona(0.012, 0.0015, 0.65, (1.5, 4.0)),
}

BOT_NAMES = (
    "Alex", "Emma", "Liam", "Olivia", "Noah", "Sophia", "Jack", "Mia",
    "Leo", "Grace", "Ethan", "Lucy", "Ryan", "Chloe", "Adam", "Ella",
)

# said when the letter is genuinely hard for the bot's vocabulary
HARD_LETTER_PHRASES = (
    "That's a tough letter... I give up!",
    "Ugh, I know so few words with that letter 😩 You win!",
    "Okay, you got me with that one. GG!",
)
# said when the bot simply blanks out (late in a long game)
BLANK_PHRASES = (
    "Hmm... I can't think of anything. You win! 👏",
    "Oh no, my mind went blank 😅 You got me!",
    "Pass! Well played 🙌",
    "Wait, wait... no, I've got nothing. GG!",
    "My brain is tired after such a long game 😵 You win!",
)

WIN_PHRASES = (
    "Good game! Want a rematch? 😉",
    "GG! You were close 💪",
    "That was fun! Try again?",
)

COMPLIMENTS = (
    "Ooh, nice word! 👀",
    "Wow, fancy one 😮",
    "Great word!",
    "Didn't expect that one 😄",
)

MAX_FAIL = 0.55
WARM_UP = 6          # the random blank-out chance ramps up over the bot's first moves
HARD_LETTER = 15     # fewer known words than this makes a letter "hard"
OPENING_LETTERS = "abcdefghilmnoprstw"


class BotBrain:
    def __init__(
        self,
        dictionary: Dictionary,
        level: Level,
        *,
        rng: random.Random | None = None,
        speed: float = 1.0,
    ) -> None:
        self.dictionary = dictionary
        self.level = level
        self.persona = PERSONAS[level]
        self.rng = rng or random.Random()
        self.speed = speed
        self.name = self.rng.choice(BOT_NAMES)
        self.last_options = 0   # how many words it knew for the letter it was last given

    def think_time(self) -> float:
        low, high = self.persona.think
        return self.rng.uniform(low, high) * self.speed

    def fail_chance(self, moves_made: int, options: int) -> float:
        """A person does not forget "every" on their first move, but gets tired in a long
        game and struggles with letters they know few words for."""
        warm = min(1.0, moves_made / WARM_UP)
        p = (self.persona.fail_chance + self.persona.fatigue * moves_made) * warm
        if options < 5:
            p += 0.25
        elif options < HARD_LETTER:
            p += 0.08
        return min(p, MAX_FAIL)

    def give_up_phrase(self) -> str:
        return self.phrase(HARD_LETTER_PHRASES if self.last_options < HARD_LETTER else BLANK_PHRASES)

    def choose(self, letter: str | None, used: set[str], moves_made: int = 0) -> str | None:
        """The bot's next word, or None if it gives up."""
        letter = letter or self.rng.choice(OPENING_LETTERS)
        options = [w for w in self.dictionary.known(letter, self.level) if w not in used]
        self.last_options = len(options)
        if not options or self.rng.random() < self.fail_chance(moves_made, len(options)):
            return None
        # common words come to mind first, but not always the same ones
        weights = [1 / (i + 20) ** 0.6 for i in range(len(options))]
        picks = self.rng.choices(options, weights=weights, k=min(10, len(options)))
        if self.rng.random() < self.persona.cunning:
            return min(set(picks), key=lambda w: (self.dictionary.count_known(w[-1], self.level), w))
        return picks[0]

    def phrase(self, phrases: tuple[str, ...]) -> str:
        return self.rng.choice(phrases)
