"""Card representation and MobilityWare deal token parsing."""

from __future__ import annotations

from dataclasses import dataclass

RANK_MAP = {"a": 1, "j": 11, "q": 12, "k": 13}
RANK_TO_STR = {1: "A", 11: "J", 12: "Q", 13: "K"}


def rank_str(rank: int) -> str:
    return RANK_TO_STR.get(rank, str(rank))


@dataclass(frozen=True)
class Card:
    suit: str  # s, h, d, c
    rank: int  # 1..13

    def __str__(self) -> str:
        return f"{rank_str(self.rank)}{self.suit}"

    @staticmethod
    def parse(tok: str) -> Card:
        t = tok.strip().lower().rstrip(",")
        if not t:
            raise ValueError("empty token")
        suit = t[-1]
        r = t[:-1]
        if r not in RANK_MAP and not r.isdigit():
            raise ValueError(f"bad rank token {tok}")
        rank = RANK_MAP[r] if r in RANK_MAP else int(r)
        if suit not in "shdc":
            raise ValueError(f"bad suit in {tok}")
        return Card(suit, rank)

    @staticmethod
    def from_notation(notation: str) -> Card:
        """Parse '7S', '10h', 'kc' style tokens from solution text."""
        t = notation.strip().lower()
        if len(t) < 2:
            raise ValueError(notation)
        suit = t[-1]
        r = t[:-1]
        rank = RANK_MAP[r] if r in RANK_MAP else int(r)
        return Card(suit, rank)


def card_id(card: Card) -> int:
    return "shdc".index(card.suit) * 13 + (card.rank - 1)