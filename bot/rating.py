K_FACTOR = 32


def expected(rating: int, opponent: int) -> float:
    return 1 / (1 + 10 ** ((opponent - rating) / 400))


def elo(winner: int, loser: int, k: int = K_FACTOR) -> tuple[int, int]:
    """New (winner, loser) ratings after a decisive game."""
    delta = max(1, round(k * (1 - expected(winner, loser))))
    return winner + delta, max(100, loser - delta)
