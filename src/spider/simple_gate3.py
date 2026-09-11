"""Research-only Gate 3: first flip of JH above unique 9H.

Terminal at blockers_above 1 -> 0.  Does not search 9H / Heart foundation.
Full accumulated MW cost is the search g.  SD4 is never expanded.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from spider.engine import SpiderState
from spider.metrics import Action
from spider.packed_state import pack_state
from spider.simple_deal1_preview import stock_rows
from spider.simple_foundation_horizon import pretty_card
from spider.simple_gate1 import (
    Gate1Result,
    gate1_progress,
    is_gate3,
    search_gate1,
)
from spider.simple_h9_cut import pre_sd4_hearts
from spider.simple_heart_funnel import legal_episode_actions
from spider.simple_progressive_solver import _capture, _restore, apply_action, step_cost

GLOBAL_LB_GATE3 = 72
GATE1_PROVED_MIN = 70
GATE2_BEST_KNOWN = 73
EXPECTED_GATE2_BANDS = {"73": 16, "74": 48, "75": 80}
EXPECTED_GATE2_N = 144


def audit_v034_persistence_gap(payload: dict) -> dict:
    """v0.34 harvested 144 Gate-2 states but JSON persisted only the 16 at MW 73."""

    bands = payload.get("bands") or {}
    search = payload.get("search") or {}
    search_bands = search.get("band_counts") or {}
    persisted = int(payload.get("portfolio") or 0)
    if not persisted:
        persisted = sum(int(v) for v in bands.values())
    harvested = int(search.get("witnesses") or 0)
    harvested_bands = {str(k): int(v) for k, v in search_bands.items()}
    persisted_bands = {str(k): int(v) for k, v in bands.items()}
    gap = (
        persisted_bands == {"73": 16}
        and harvested == EXPECTED_GATE2_N
        and harvested_bands == EXPECTED_GATE2_BANDS
        and persisted == 16
    )
    return {
        "confirmed": gap,
        "persisted": persisted,
        "persisted_bands": persisted_bands,
        "harvested": harvested,
        "harvested_bands": harvested_bands,
        "expected_harvest": EXPECTED_GATE2_N,
        "expected_harvest_bands": dict(EXPECTED_GATE2_BANDS),
        "reason": (
            "v0.34 directed search harvested 144 exact Gate-2 states (16/48/80 at 73/74/75) "
            "but the committed JSON kept only the 16 one-move cost-73 states because the "
            "directed incumbent did not beat the fast-path B=73."
            if gap
            else "v0.34 persistence did not match the expected 16-vs-144 gap."
        ),
    }


def verify_gate3_chain(state: SpiderState) -> dict:
    """A valid Gate-2 state: 9H down, 1 blocker, that blocker is JH, AH already up."""

    nines = pre_sd4_hearts(state, 9)
    if len(nines) != 1 or nines[0].get("zone") != "down":
        return {"valid": False, "reason": "unique 9H not face-down"}
    h9 = nines[0]
    above = h9.get("face_down_above") or []
    blockers = h9.get("face_down_blockers_above")
    if blockers != 1:
        return {"valid": False, "reason": f"blockers_above={blockers}, expected 1"}
    if above != ["JH"]:
        return {"valid": False, "reason": f"remaining down above 9H is {above}, expected JH"}
    col = state.columns[h9["column_0"]]
    top_fd = col.face_down[-1] if col.face_down else None
    if top_fd is None or pretty_card(top_fd) != "JH":
        return {"valid": False, "reason": f"top face-down is {pretty_card(top_fd) if top_fd else None}, expected JH"}
    up_names = [pretty_card(c) for c in col.face_up]
    if "AH" not in up_names:
        return {"valid": False, "reason": "AH not face-up in the 9H column"}
    if "JH" in up_names:
        return {"valid": False, "reason": "JH already face-up"}
    return {
        "valid": True,
        "column_0": h9["column_0"],
        "column_1": h9.get("column_1"),
        "remaining_down_above_9h": above,
        "top_face_down": "JH",
        "ah_face_up": True,
        "gate3_proof": (
            "After Gate 2, JH is the last face-down blocker above unique 9H. "
            "Every later 9H exposure must first flip JH (blockers 1->0). "
            "Gate 3 is that transition; 9H remains face-down."
        ),
    }


def global_lb_gate3_audit() -> dict:
    return {
        "valid": True,
        "global_lb": GLOBAL_LB_GATE3,
        "gate1_min": GATE1_PROVED_MIN,
        "plus_ah": 1,
        "plus_jh": 1,
        "gate2_best_known": GATE2_BEST_KNOWN,
        "gate2_proved": False,
        "rationale": (
            "Any pre-SD4 Heart-1 route needs the unique 9H. Exposing that 9H requires "
            "exposing JH last. Gate 1 is proved at full MW 70. Each subsequent uncover "
            "of the still-buried 9H column costs at least 1 corrected MW, so AH then JH "
            "compose to GLOBAL_LB_GATE3 = 72. Gate 2 at 73 is best-known, not a proved "
            "minimum, and is not substituted into this bound."
        ),
    }


def per_source_lb(gate2_g: int) -> int:
    """JH is still face-down, so Gate 3 from this source is at least g+1."""

    return int(gate2_g) + 1


def per_source_lb_audit(gate2_g: int) -> dict:
    return {
        "valid": True,
        "source_g": int(gate2_g),
        "lb": per_source_lb(gate2_g),
        "rationale": (
            "JH remains face-down above unique 9H. Uncovering a still-buried column "
            "cannot be a corrected-MW zero-cost relocate, and one action flips at most "
            "one face-down card, so Gate 3 costs at least source_g + 1."
        ),
    }


def one_move_gate3(state: SpiderState) -> List[dict]:
    parent = gate1_progress(state)
    if parent.get("fd_blockers") != 1:
        return []
    hits = []
    for action in legal_episode_actions(state):
        if action == ("deal",) and stock_rows(state) != 3:
            continue
        cost = step_cost(state, action)
        cap = _capture(state, action)
        try:
            apply_action(state, action)
            child = gate1_progress(state)
            if is_gate3(parent, child, state):
                col = child["column_0"]
                hits.append(
                    {
                        "action": ["deal"] if action == ("deal",) else [int(action[0]), int(action[1]), int(action[2])],
                        "step_cost": cost,
                        "sd3": action == ("deal",),
                        "ordered_digest": pack_state(state).hex(),
                        "fd_blockers": child["fd_blockers"],
                        "face_up_h9": bool(child.get("face_up")),
                        "top_face_up": pretty_card(state.columns[col].face_up[-1]),
                        "stock_rows": stock_rows(state),
                    }
                )
        finally:
            _restore(state, cap)
    return hits


def search_gate3(
    sources: Sequence[SpiderState],
    origin_paths: Sequence[Sequence[Action]],
    source_g: Sequence[int],
    **kwargs,
) -> Gate1Result:
    """Full-g Gate-3 search. kwargs forwarded to search_gate1."""

    return search_gate1(
        sources,
        origin_paths,
        source_g=source_g,
        mode="gate3",
        **kwargs,
    )


def load_v034_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sd3_status(state: SpiderState) -> dict:
    rows = stock_rows(state)
    return {
        "stock_rows": rows,
        "sd3_available": rows == 3,
        "sd3_done": rows < 3,
        "sd4_used": rows < 2,
    }
