"""v0.67 stock-empty assembly cost-to-go on the frozen v0.66 harvest.

COMPLETION lane and proof pruning are stock-empty only. Rows=1
transition-aware harvest is unchanged. No DURABILITY. No canonical reads
for search.
"""

from __future__ import annotations

from typing import Optional, Tuple

from spider.assembly_lower_bound import (
    assembly_bound_detail,
    completion_key,
    stock_empty_assembly_h,
)
from spider.engine import SpiderState
from spider.final_deal_transition import (
    CANDIDATE_CEILING,
    TRANSITION_HARVEST_CATS,
    TransitionTracker,
    enrich_transition,
)
from spider.healthy_f2 import INCUMBENT_G
from spider.operational_policy import OP_LANES, operational_lane_keys, search_operational_optimisation
from spider.operational_viability import operational_viability_key, rank_ready_suits
from spider.research_actions import stock_rows
from spider.whole_game_epoch_scheduler import (
    PORTFOLIO_WIDTH,
    SEARCH_RSS_MB,
    SEARCH_TIME_S,
    SEARCH_UNIQUE,
)

COMPLETION_LANES = OP_LANES + ("completion",)
MULTI_SUIT_LANES = COMPLETION_LANES + ("readiness_r2", "readiness_r3")
V066_F3 = 173
V066_F4 = 181
V066_F5 = 186
V066_F6 = 194
V066_F7 = 196


def assembly_lane_keys(state: SpiderState, g: int):
    keys = operational_lane_keys(state, g)
    keys["readiness_r2"] = None
    keys["readiness_r3"] = None
    rows = stock_rows(state)
    if rows == 1:
        ranked = rank_ready_suits(state, g=g).get("ranked") or []
        if len(ranked) >= 2:
            keys["readiness_r2"] = operational_viability_key(ranked[1], g)
        if len(ranked) >= 3:
            keys["readiness_r3"] = operational_viability_key(ranked[2], g)
    if rows != 0:
        keys["completion"] = None
        return keys
    keys["completion"] = completion_key(state, g)
    return keys


def enrich_assembly(state: SpiderState, rec: dict) -> None:
    enrich_transition(state, rec)
    info = assembly_bound_detail(state)
    g = int(rec.get("g") or 0)
    h = int(info["h"])
    rec["assembly_h"] = h
    rec["assembly_f"] = g + h
    rec["assembly_slack"] = CANDIDATE_CEILING - (g + h)
    rec["assembly_u"] = info.get("u_total")
    rec["assembly_active"] = info.get("active")
    rec["assembly_defined"] = info.get("defined")
    rec["copies_remaining"] = info.get("copies_remaining")
    rec["assembly_by_suit"] = {
        suit: {
            "m": row.get("m"),
            "u": row.get("u"),
            "suit_lb": row.get("suit_lb"),
            "feasible": row.get("feasible"),
        }
        for suit, row in (info.get("by_suit") or {}).items()
    }


def search_assembly_continuation(
    *,
    opening: SpiderState,
    recon: dict,
    max_unique: int = SEARCH_UNIQUE,
    time_limit_s: float = SEARCH_TIME_S,
    rss_abort_mb: float = SEARCH_RSS_MB,
    portfolio_width: int = PORTFOLIO_WIDTH,
):
    tracker = TransitionTracker()
    result = search_operational_optimisation(
        opening=opening,
        initial_roots=[dict(recon["root"])],
        cost_ceiling=CANDIDATE_CEILING,
        incumbent_by_rows={},
        max_unique=max_unique,
        time_limit_s=time_limit_s,
        rss_abort_mb=rss_abort_mb,
        portfolio_width=portfolio_width,
        harvest_cats=TRANSITION_HARVEST_CATS,
        extra_track=tracker,
        enrich_fn=enrich_assembly,
        on_harvest=tracker.on_harvest,
        lane_names=COMPLETION_LANES,
        keys_fn=assembly_lane_keys,
        lower_bound_fn=stock_empty_assembly_h,
    )
    result.transition_tracker = tracker
    result.n_previewed = tracker.n_previewed
    result.transition_selected = tracker.selected
    result.transition_cats = tracker.selected_cats
    return result


def choose_assembly_verdict(p: dict) -> Tuple[str, str]:
    if p.get("provenance_fail"):
        return (
            "ASSEMBLY_BOUND_CONTRACT_FAILURE",
            "exact F2 path/state could not be verified",
        )
    if p.get("bound_invalid"):
        return "ASSEMBLY_BOUND_INVALID", "admissibility tests or reasoning failed"
    if p.get("accounting_fail") or (p.get("solved") and not p.get("replay_ok")):
        return "ASSEMBLY_BOUND_CONTRACT_FAILURE", "replay, identity or accounting failed"
    inc = int(p.get("incumbent_g") or INCUMBENT_G)
    best = p.get("solution_g")
    if p.get("solved") and p.get("replay_ok") and best is not None and int(best) < inc:
        return "ASSEMBLY_BOUND_COST_IMPROVED", f"solved at g={best}"
    if p.get("solved") and p.get("replay_ok") and best is not None and int(best) <= CANDIDATE_CEILING:
        return (
            "ASSEMBLY_BOUND_FINDS_F8_AT_CEILING",
            f"F8/terminal at g={best} inside 197 but not below incumbent {inc}",
        )
    f8 = ((p.get("foundations") or {}).get("cheap") or {}).get("8") or {}
    if f8.get("g") is not None and int(f8["g"]) <= CANDIDATE_CEILING:
        return (
            "ASSEMBLY_BOUND_FINDS_F8_AT_CEILING",
            "F8 reached within the ceiling without a promoted incumbent",
        )
    prunes = int(p.get("lower_bound_prunes") or 0)
    generated = int(p.get("generated") or 0)
    frac = 0.0 if generated <= 0 else prunes / float(generated)
    f_improved = bool(p.get("completion_frontier_improved"))
    if f_improved:
        return (
            "ASSEMBLY_BOUND_IMPROVES_COMPLETION_FRONTIER",
            "f-aware search improved the viable late-game frontier",
        )
    if prunes >= 100 and frac >= 0.05:
        return (
            "ASSEMBLY_BOUND_PRUNES_DEAD_ENDS_NO_SOLUTION",
            "bound removed substantial proof-infeasible work without a cheaper terminal",
        )
    if prunes < 20 or frac < 0.01:
        return (
            "ASSEMBLY_BOUND_TOO_WEAK",
            "bound is valid but rarely distinguished or pruned states",
        )
    return (
        "ASSEMBLY_BOUND_PRUNES_DEAD_ENDS_NO_SOLUTION",
        "bound is valid and pruned dead ends without a cheaper terminal",
    )
