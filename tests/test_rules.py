import random

import pytest

from bot.ai import BotBrain
from bot.config import WORDS_FILE
from bot.dictionary import Dictionary
from bot.engine import GameState, Player, Reject, normalize
from bot.levels import Level, level_for_rank
from bot.rating import elo


@pytest.fixture(scope="module")
def full_dict() -> Dictionary:
    words = WORDS_FILE.read_text(encoding="utf-8").split()
    return Dictionary((w, i) for i, w in enumerate(words))


SMALL = Dictionary((w, i) for i, w in enumerate(["apple", "egg", "elephant", "tree", "time", "ear", "rat"]))


def new_game(d: Dictionary = SMALL) -> GameState:
    return GameState([Player(1, "A", Level.A1), Player(2, "B", Level.A1)], d)


def test_normalize():
    assert normalize("  Apple! ") == "apple"
    assert normalize("«Tree».") == "tree"
    assert normalize("two words") is None
    assert normalize("яблоко") is None
    assert normalize("don't") is None


def test_chain_rules():
    g = new_game()
    assert g.play("apple") is None
    assert g.required_letter == "e" and g.turn == 1
    assert g.play("tree") is Reject.WRONG_LETTER
    assert g.play("ox") is Reject.TOO_SHORT
    assert g.play("eeek") is Reject.UNKNOWN
    assert g.play("egg") is None
    assert g.play("garden") is Reject.UNKNOWN          # not in SMALL
    assert g.turn == 0 and g.players[1].words == ["egg"]


def test_no_repeats():
    g = new_game()
    for w in ["tree", "egg"]:
        assert g.play(w) is None
    g.history.append((0, "great"))                       # force letter 't' again
    g.used.add("great")
    assert g.play("tree") is Reject.USED


def test_strikes():
    g = new_game()
    assert not g.add_strike() and not g.add_strike()
    assert g.add_strike()


def test_dictionary_levels(full_dict: Dictionary):
    assert full_dict.level_of("time") == Level.A1
    assert full_dict.level_of("notawordxyz") is None
    a1, c2 = full_dict.count_known("s", Level.A1), full_dict.count_known("s", Level.C2)
    assert 0 < a1 < c2
    assert all(level_for_rank(full_dict.rank(w)) == Level.A1 for w in full_dict.known("s", Level.A1))


def test_dictionary_add_remove():
    d = Dictionary([("apple", 5), ("axe", 10)])
    assert d.add("ant", 7) and not d.add("ant", 1)
    assert d.known("a", Level.A1) == ["apple", "ant", "axe"]
    assert d.remove("ant") and "ant" not in d and not d.remove("ant")


def test_bot_plays_valid_words_within_its_level(full_dict: Dictionary):
    brain = BotBrain(full_dict, Level.A2, rng=random.Random(1))
    brain.fail_chance = lambda *a: 0.0
    used: set[str] = set()
    letter = "s"
    for _ in range(30):
        word = brain.choose(letter, used)
        assert word and word[0] == letter and word not in used
        assert full_dict.level_of(word) <= Level.A2
        used.add(word)
        letter = word[-1]


def test_bot_never_blanks_on_an_easy_first_move(full_dict: Dictionary):
    """Regression: an A1 bot gave up on 'e' as its very first move."""
    brain = BotBrain(full_dict, Level.A1, rng=random.Random(0))
    for letter in "abcdefghilmnoprstw":
        assert full_dict.count_known(letter, Level.A1) >= 15
        assert all(brain.choose(letter, set(), moves_made=0) for _ in range(200)), letter


def test_give_up_phrase_matches_the_situation(full_dict: Dictionary):
    brain = BotBrain(full_dict, Level.A1, rng=random.Random(0))
    brain.choose("e", set(), 0)
    assert "letter" not in brain.give_up_phrase()
    brain.choose("x", set(), 0)
    assert brain.last_options < 15


def test_bot_can_lose_and_is_level_aware(full_dict: Dictionary):
    """Bot-vs-bot: games end in reasonable time, and a C2 bot beats an A1 bot."""
    rng = random.Random(42)
    wins = {Level.A1: 0, Level.C2: 0}
    lengths = []
    for _ in range(200):
        bots = [BotBrain(full_dict, Level.A1, rng=rng), BotBrain(full_dict, Level.C2, rng=rng)]
        used: set[str] = set()
        letter, turn, moves = None, rng.randrange(2), [0, 0]
        while True:
            word = bots[turn].choose(letter, used, moves[turn])
            if word is None:
                wins[bots[1 - turn].level] += 1
                break
            used.add(word)
            moves[turn] += 1
            letter, turn = word[-1], 1 - turn
        lengths.append(sum(moves))
    assert wins[Level.C2] > wins[Level.A1] > 0
    assert 4 < sum(lengths) / len(lengths) < 80


def test_format_translation():
    from bot.translator import format_translation

    safe = [[["xavfsiz", "safe", None, None]], [["adjective", ["xavfsiz", "ishonchli", "zararsiz"]],
                                                   ["noun", ["po'lat sandiq", "temir sandiq"]]]]
    assert format_translation("safe", safe) == "xavfsiz, po'lat sandiq, ishonchli"
    assert format_translation("yeah", [[["ha", "yeah"]], None]) == "ha"
    assert format_translation("pizza", [[["pizza", "pizza"]]]) == "pizza"
    assert format_translation("bank", [[["bank", "bank"]], [["noun", ["bank", "qirg'oq"]]]]) == "bank, qirg'oq"
    assert format_translation("x", "garbage") is None


def test_elo():
    assert elo(1000, 1000) == (1016, 984)
    w, l = elo(1400, 1000)
    assert w - 1400 < 16 and l == 1000 - (w - 1400)
