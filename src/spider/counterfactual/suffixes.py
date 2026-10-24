"""Exact-state suffix reuse.

A later state on a verified route may contribute its suffix only when the
packed state matches. Column permutation is not treated as the same state:
deal rows land on physical columns, and a suffix is a list of physical moves.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import Action, replay_actions_detailed
from spider.packed_state import pack_state
from spider.research_actions import apply_action

from .experiment import BASELINE_MW


def retain_cheapest(records: Sequence[dict]) -> dict:
    """Keep the lowest cumulative g for each exact packed state."""

    best = {}
    for record in records:
        key = record["store"]
        current = best.get(key)
        if current is None or int(record["g"]) < int(current["g"]):
            best[key] = record
    return best


def index_route(deal_path: Path, actions: Sequence[Action]) -> dict:
    """Map packed states of one verified line to the cheapest suffix.

    The key is ``pack_state`` bytes. Symmetry keys are not inserted.
    """

    state = SpiderState.from_cards(list(load_deal(deal_path)))
    g = 0
    found: dict = {}
    for index, action in enumerate(actions):
        store = pack_state(state)
        if store not in found or g < int(found[store]["g"]):
            found[store] = {
                "g": g,
                "suffix": list(actions[index:]),
                "steps_remaining": len(actions) - index,
            }
        g += apply_action(state, action)
    store = pack_state(state)
    if store not in found or g < int(found[store]["g"]):
        found[store] = {"g": g, "suffix": [], "steps_remaining": 0}
    return found


def validate_splice(
    deal_path: Path,
    opening_actions: Sequence[Action],
    suffix: Sequence[Action],
    expected_store: bytes,
    search_g: int,
) -> dict:
    """Replay opening actions to the catalog state, then the catalog suffix."""

    try:
        arrived = SpiderState.from_cards(list(load_deal(deal_path)))
        prefix_counters = replay_actions_detailed(arrived, list(opening_actions))
    except Exception as exc:
        return {"ok": False, "error": f"prefix replay failed: {exc}"}
    if pack_state(arrived) != expected_store:
        return {"ok": False, "error": "path did not reach the catalog state"}
    if int(prefix_counters["mobilityware_moves"]) != int(search_g):
        return {
            "ok": False,
            "error": (
                f"path cost {prefix_counters['mobilityware_moves']} "
                f"does not equal recorded g {search_g}"
            ),
        }
    try:
        fresh = SpiderState.from_cards(list(load_deal(deal_path)))
        full = replay_actions_detailed(fresh, list(opening_actions) + list(suffix))
        continued = arrived.clone()
        suffix_counters = replay_actions_detailed(continued, list(suffix))
    except Exception as exc:
        return {"ok": False, "error": f"suffix replay failed: {exc}"}
    total = int(full["mobilityware_moves"])
    packed_total = int(search_g) + int(suffix_counters["mobilityware_moves"])
    solved = bool(fresh.is_solved()) and len(fresh.foundations) == 8 and len(fresh.stock) == 0
    ok = solved and bool(continued.is_solved()) and total == packed_total
    return {
        "ok": ok,
        "total_mw": total,
        "packed_total_mw": packed_total,
        "solved": solved,
        "foundations": len(fresh.foundations),
        "stock_remaining": len(fresh.stock),
        "explicit_actions": len(opening_actions) + len(suffix),
        "improves_on_baseline": bool(ok and total <= BASELINE_MW - 1),
        "error": None if ok else "spliced line did not solve under corrected MW replay",
    }


def cheapest_hit(index: dict, store: bytes, g: int) -> Optional[dict]:
    record = index.get(store)
    if record is None or int(g) >= int(record["g"]):
        return None
    return record
