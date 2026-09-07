#!/usr/bin/env python3
"""Freeze the deterministic ten-deal workspace-service panel v0.1."""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "research"))

import common_priority_schema_ab_v0_1 as common
from spider.cards import Card
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.rules import MW_RULES


PANEL_ID = "workspace-service-panel-v0-1"
GENERATOR_VERSION = "sha256-fisher-yates-v1"
CALIBRATION_PATH = ROOT / "deals" / "4925153.txt"
FIXTURE_DIR = ROOT / "research" / "fixtures" / "workspace_service_panel_v0_1"
PANEL_PATH = (
    ROOT
    / "docs"
    / "research"
    / "workspace_service_generalisation_panel_v0_1_panel.json"
)
SUIT_ORDER = "shdc"


def derive_seed(panel_entry: str) -> int:
    """First eight SHA-256 bytes, interpreted as an unsigned big-endian integer."""

    material = f"{PANEL_ID}:{panel_entry}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big", signed=False)


class StableSha256Random:
    """Version-stable unsigned 64-bit draws derived from SHA-256 counter blocks."""

    _DOMAIN = b"workspace-service-panel-v0-1/shuffle-v1\0"

    def __init__(self, seed: int) -> None:
        if not 0 <= seed < 2**64:
            raise ValueError("seed must fit unsigned 64 bits")
        self.seed = seed
        self.counter = 0

    def uint64(self) -> int:
        block = hashlib.sha256(
            self._DOMAIN
            + self.seed.to_bytes(8, "big", signed=False)
            + self.counter.to_bytes(8, "big", signed=False)
        ).digest()
        self.counter += 1
        return int.from_bytes(block[:8], "big", signed=False)

    def below(self, bound: int) -> int:
        """Unbiased integer in ``range(bound)`` using rejection sampling."""

        if bound <= 0:
            raise ValueError("bound must be positive")
        accepted = (2**64 // bound) * bound
        while True:
            value = self.uint64()
            if value < accepted:
                return value % bound


def standard_two_deck() -> list[Card]:
    """Two explicit 52-card decks in stable copy/suit/rank order."""

    return [
        Card(suit, rank)
        for _copy in range(2)
        for suit in SUIT_ORDER
        for rank in range(1, 14)
    ]


def generate_cards(seed: int) -> tuple[Card, ...]:
    cards = standard_two_deck()
    source = StableSha256Random(seed)
    for index in range(len(cards) - 1, 0, -1):
        swap = source.below(index + 1)
        cards[index], cards[swap] = cards[swap], cards[index]
    return tuple(cards)


def validate_cards(cards: tuple[Card, ...]) -> SpiderState:
    if len(cards) != 104:
        raise AssertionError(f"expected 104 cards, received {len(cards)}")
    expected = Counter(
        {(suit, rank): 2 for suit in SUIT_ORDER for rank in range(1, 14)}
    )
    actual = Counter((card.suit, card.rank) for card in cards)
    if actual != expected:
        raise AssertionError({"actual": actual, "expected": expected})
    state = SpiderState.from_cards(list(cards))
    totals = [len(column.face_down) + len(column.face_up) for column in state.columns]
    face_up = [len(column.face_up) for column in state.columns]
    face_down = [len(column.face_down) for column in state.columns]
    if totals != [6] * 4 + [5] * 6:
        raise AssertionError({"tableau_totals": totals})
    if face_up != [1] * 10 or face_down != [5] * 4 + [4] * 6:
        raise AssertionError({"face_up": face_up, "face_down": face_down})
    if len(state.stock) != 50:
        raise AssertionError({"stock": len(state.stock)})
    if not MW_RULES.can_deal_into_empty:
        raise AssertionError("panel requires the benchmark MobilityWare rule profile")
    return state


def serialize_deal(cards: tuple[Card, ...]) -> str:
    """Repository deal format: 54 tableau cards followed by 50 stock cards."""

    validate_cards(cards)
    lines = ["spider"]
    for start in range(0, 50, 10):
        lines.append(",".join(str(card) for card in cards[start : start + 10]) + ",")
    lines.append(",".join(str(card) for card in cards[50:54]) + ",")
    lines.append(",".join(str(card) for card in cards[54:]))
    return "\n".join(lines) + "\n"


def arm_order(panel_index: int) -> tuple[str, str]:
    if not 0 <= panel_index <= 9:
        raise ValueError("panel index must be P0..P9")
    return (
        ("WORKSPACE_SERVICE_1", "CONTROL")
        if panel_index % 2 == 0
        else ("CONTROL", "WORKSPACE_SERVICE_1")
    )


def _fixture_record(panel_index: int, path: Path, seed: int | None) -> dict:
    cards = tuple(load_deal(path))
    state = validate_cards(cards)
    return {
        "panel_entry": f"P{panel_index}",
        "kind": "CALIBRATION" if panel_index == 0 else "DETERMINISTIC_RESEARCH_DEAL",
        "fixture_path": path.relative_to(ROOT).as_posix(),
        "seed": seed,
        "opening_digest": common.digest(state),
        "fixture_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "run_order": list(arm_order(panel_index)),
    }


def build_panel_definition() -> dict:
    entries = [_fixture_record(0, CALIBRATION_PATH, None)]
    for panel_index in range(1, 10):
        fixture = FIXTURE_DIR / f"P{panel_index}.txt"
        entries.append(_fixture_record(panel_index, fixture, derive_seed(f"P{panel_index}")))
    return {
        "panel_id": PANEL_ID,
        "generator_version": GENERATOR_VERSION,
        "seed_derivation": {
            "input": "workspace-service-panel-v0-1:P{index}",
            "hash": "SHA-256",
            "conversion": "first 8 digest bytes as unsigned 64-bit big-endian",
        },
        "deck_construction": {
            "copies": 2,
            "cards_per_copy": 52,
            "suit_order": SUIT_ORDER,
            "rank_order": list(range(1, 14)),
            "base_order": "copy, then suit, then ascending rank",
        },
        "shuffle": {
            "algorithm": "descending Fisher-Yates",
            "draw_source": "first 8 bytes of SHA-256(domain || seed_u64_be || counter_u64_be)",
            "domain_hex": StableSha256Random._DOMAIN.hex(),
            "bounded_draw": "64-bit rejection sampling, then modulo current bound",
        },
        "layout": {
            "tableau_cards": 54,
            "column_totals": [6, 6, 6, 6, 5, 5, 5, 5, 5, 5],
            "initial_face_up_per_column": 1,
            "stock_cards": 50,
            "stock_rows": 5,
        },
        "rule_profile": {"name": "MW_RULES", **asdict(MW_RULES)},
        "calibration_fixture_path": CALIBRATION_PATH.relative_to(ROOT).as_posix(),
        "entries": entries,
    }


def freeze_panel() -> dict:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    for panel_index in range(1, 10):
        cards = generate_cards(derive_seed(f"P{panel_index}"))
        fixture = FIXTURE_DIR / f"P{panel_index}.txt"
        rendered = serialize_deal(cards)
        if fixture.exists() and fixture.read_text(encoding="utf-8") != rendered:
            raise RuntimeError(f"refusing to replace frozen panel member {fixture}")
        fixture.write_text(rendered, encoding="utf-8", newline="\n")
    definition = build_panel_definition()
    rendered_definition = json.dumps(definition, indent=2, sort_keys=True) + "\n"
    if PANEL_PATH.exists() and PANEL_PATH.read_text(encoding="utf-8") != rendered_definition:
        raise RuntimeError(f"refusing to replace frozen panel definition {PANEL_PATH}")
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    PANEL_PATH.write_text(rendered_definition, encoding="utf-8", newline="\n")
    return definition


def main() -> int:
    definition = freeze_panel()
    print(json.dumps(definition, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
