"""Research-only Gate 2: first flip of AH above unique 9H.

Terminal at blockers_above 2 -> 1.  Does not search JH/9H/Heart foundation.
Full accumulated MW cost is the search g.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from spider.engine import SpiderState
from spider.metrics import Action
from spider.packed_state import pack_state
from spider.simple_deal1_preview import stock_rows
from spider.simple_foundation_horizon import pretty_card
from spider.simple_gate1 import (
    Gate1Result,
    gate1_progress,
    is_gate2,
    search_gate1,
)
from spider.simple_heart_funnel import legal_episode_actions
from spider.simple_h9_cut import pre_sd4_hearts
from spider.simple_progressive_solver import _capture, _restore, apply_action, step_cost

GLOBAL_LB_GATE2 = 71
GATE1_PROVED_MIN = 70


def verify_gate2_chain(state: SpiderState) -> dict:
    """A valid Gate-1 state: 9H down, 2 blockers, top face-down AH, 8D already up."""

    nines = pre_sd4_hearts(state, 9)
    if len(nines) != 1 or nines[0].get("zone") != "down":
        return {"valid": False, "reason": "unique 9H not face-down"}
    h9 = nines[0]
    above = h9.get("face_down_above") or []
    if h9.get("face_down_blockers_above") != 2:
        return {"valid": False, "reason": f"blockers_above={h9.get('face_down_blockers_above')}, expected 2"}
    if above != ["JH", "AH"]:
        return {"valid": False, "reason": f"remaining down above 9H is {above}, expected JH, AH"}
    col = state.columns[h9["column_0"]]
    top_fd = col.face_down[-1] if col.face_down else None
    if top_fd is None or pretty_card(top_fd) != "AH":
        return {"valid": False, "reason": f"top face-down is {pretty_card(top_fd) if top_fd else None}, expected AH"}
    if not col.face_up or pretty_card(col.face_up[-1]) != "8D":
        # 8D should be among face-up; it may not be top if more cards landed
        if "8D" not in [pretty_card(c) for c in col.face_up]:
            return {"valid": False, "reason": "8D not face-up in the 9H column"}
    return {
        "valid": True,
        "column_0": h9["column_0"],
        "column_1": h9.get("column_1"),
        "remaining_down_above_9h": above,
        "top_face_down": "AH",
        "gate2_proof": (
            "After Gate 1, AH is the top face-down blocker above unique 9H. "
            "Every later 9H exposure must first flip AH (blockers 2->1)."
        ),
    }


def global_lb_gate2_audit() -> dict:
    return {
        "valid": True,
        "global_lb": GLOBAL_LB_GATE2,
        "gate1_min": GATE1_PROVED_MIN,
        "plus_one_flip": 1,
        "rationale": (
            "Any Gate-2 path must cross Gate 1 (proved min full MW 70) then perform at "
            "least one non-zero-MW uncover of the still-buried 9H column, so full MW >= 71."
        ),
    }


def one_move_gate2(state: SpiderState) -> List[dict]:
    parent = gate1_progress(state)
    if parent.get("fd_blockers") != 2:
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
            if is_gate2(parent, child, state):
                hits.append(
                    {
                        "action": ["deal"] if action == ("deal",) else [int(action[0]), int(action[1]), int(action[2])],
                        "step_cost": cost,
                        "sd3": action == ("deal",),
                        "ordered_digest": pack_state(state).hex(),
                        "fd_blockers": child["fd_blockers"],
                        "top_face_up": pretty_card(state.columns[child["column_0"]].face_up[-1]),
                        "stock_rows": stock_rows(state),
                    }
                )
        finally:
            _restore(state, cap)
    return hits


def search_gate2(
    sources: Sequence[SpiderState],
    origin_paths: Sequence[Sequence[Action]],
    source_g: Sequence[int],
    **kwargs,
) -> Gate1Result:
    """Full-g Gate-2 search. kwargs forwarded to search_gate1."""

    return search_gate1(
        sources,
        origin_paths,
        source_g=source_g,
        mode="gate2",
        **kwargs,
    )
