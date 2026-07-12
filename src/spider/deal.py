"""Load MobilityWare deal files (tableau layout + stock)."""

from __future__ import annotations

from pathlib import Path

from .cards import Card


def tokens_from_text(text: str) -> list[str]:
    return [t for t in text.replace(",", " ").split() if t.strip()]


def tokens_from_file(path: Path) -> list[str]:
    return tokens_from_text(path.read_text(encoding="utf-8"))


def cards_from_tokens(tokens: list[str]) -> list[Card]:
    return [Card.parse(t) for t in tokens if t.strip().lower() != "spider"]


def load_deal(path: Path) -> list[Card]:
    cards = cards_from_tokens(tokens_from_file(path))
    if len(cards) != 104:
        raise ValueError(f"deal must contain 104 cards, got {len(cards)}")
    return cards


def stock_deal_rounds(stock: list[Card]) -> list[list[Card]]:
    """Split stock into deal rounds (round 1 = first deal from stock).

    In ``deals/*.txt`` the stock is one comma-separated run (line 8 after the
    54-card tableau). Read left-to-right as **bottom → top** of the stock pile:

    - First token (e.g. ``3h``) = bottom of pile = last deal in the game (deal 5)
    - Last token (e.g. ``5c``) = top of pile = **first** deal (deal 1)

    Reference deal 4925153 — **deal 1** (cols 1→10):
    ``Js 9d 4d Kh 4d 6d 9s 7d 8s 5c`` (last 10 tokens in the file)

    **Deal 2** (cols 1→10):
    ``Ks As 6h 7s Ad Ad Ah 10d Qh Jd`` (previous 10 tokens)

    Each ``SpiderState.deal()`` removes ``stock[-10:]`` and places
    ``chunk[i]`` on column ``i + 1``.
    """
    if len(stock) % 10:
        raise ValueError(f"stock length must be a multiple of 10, got {len(stock)}")
    rounds: list[list[Card]] = []
    for end in range(len(stock), 0, -10):
        rounds.append(stock[end - 10 : end])
    return rounds