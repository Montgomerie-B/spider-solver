"""v0.68 integrated whole-game optimisation from the autonomous 192 incumbent.

Starts from the untouched opening. Retains operational viability, frozen
v0.66 final-Deal preview, and the v0.67 stock-empty assembly bound.
No canonical reads for search. No DURABILITY.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

from spider.assembly_lower_bound import stock_empty_assembly_h
from spider.assembly_policy import COMPLETION_LANES, assembly_lane_keys, enrich_assembly
from spider.autonomous_cost import checkpoints_from_trace, replay_solution_trace
from spider.engine import SpiderState
from spider.final_deal_transition import TRANSITION_HARVEST_CATS, TransitionTracker
from spider.metrics import AUTONOMOUS_INCUMBENT_MW, parse_moves_file, replay_actions
from spider.operational_policy import search_operational_optimisation
from spider.research_actions import is_deal
from spider.whole_game_anytime import opening_state
from spider.whole_game_epoch_scheduler import (
    PORTFOLIO_WIDTH,
    SEARCH_RSS_MB,
    SEARCH_TIME_S,
    SEARCH_UNIQUE,
)

INCUMBENT_MOVES = Path(__file__).resolve().parents[2] / "solutions" / "4925153_autonomous_v0_67.moves"
CANDIDATE_CEILING = AUTONOMOUS_INCUMBENT_MW - 1
PARENT_INCUMBENT = AUTONOMOUS_INCUMBENT_MW


def load_autonomous_192(opening: Optional[SpiderState] = None) -> dict:
    opening = opening or opening_state()
    actions = parse_moves_file(INCUMBENT_MOVES)
    return replay_solution_trace(opening, actions)


def verify_autonomous_192(opening: Optional[SpiderState] = None) -> dict:
    opening = opening or opening_state()
    actions = parse_moves_file(INCUMBENT_MOVES)
    end = opening.clone()
    g = replay_actions(end, list(actions))
    deals = sum(1 for a in actions if is_deal(a))
    ok = (
        g == AUTONOMOUS_INCUMBENT_MW
        and deals == 5
        and end.is_solved()
        and len(end.foundations) == 8
        and not end.stock
        and all(c.is_empty() for c in end.columns)
    )
    return {
        "ok": ok,
        "g": g,
        "deals": deals,
        "n_actions": len(actions),
        "tableau_commands": len(actions) - deals,
        "solved": end.is_solved(),
        "foundations": len(end.foundations),
        "stock_empty": not end.stock,
        "tableau_empty": all(c.is_empty() for c in end.columns),
        "actions": actions,
    }


def enrich_integrated(state, rec: dict) -> None:
    enrich_assembly(state, rec)
    g = int(rec.get("g") or 0)
    h = int(rec.get("assembly_h") or 0)
    rec["assembly_slack"] = CANDIDATE_CEILING - (g + h)


def search_integrated_optimisation(
    *,
    opening: Optional[SpiderState] = None,
    max_unique: int = SEARCH_UNIQUE,
    time_limit_s: float = SEARCH_TIME_S,
    rss_abort_mb: float = SEARCH_RSS_MB,
    portfolio_width: int = PORTFOLIO_WIDTH,
    use_checkpoints: bool = True,
):
    opening = opening or opening_state()
    trace = load_autonomous_192(opening)
    if int(trace["g"]) != AUTONOMOUS_INCUMBENT_MW:
        raise ValueError("autonomous 192 incumbent failed to replay")
    tracker = TransitionTracker()
    ck = checkpoints_from_trace(trace) if use_checkpoints else {}
    result = search_operational_optimisation(
        opening=opening,
        incumbent_trace=trace,
        cost_ceiling=CANDIDATE_CEILING,
        incumbent_by_rows=ck,
        max_unique=max_unique,
        time_limit_s=time_limit_s,
        rss_abort_mb=rss_abort_mb,
        portfolio_width=portfolio_width,
        harvest_cats=TRANSITION_HARVEST_CATS,
        extra_track=tracker,
        enrich_fn=enrich_integrated,
        on_harvest=tracker.on_harvest,
        lane_names=COMPLETION_LANES,
        keys_fn=assembly_lane_keys,
        lower_bound_fn=stock_empty_assembly_h,
    )
    result.transition_tracker = tracker
    result.n_previewed = tracker.n_previewed
    result.transition_selected = tracker.selected
    result.transition_cats = tracker.selected_cats
    result.incumbent_g = AUTONOMOUS_INCUMBENT_MW
    result.candidate_ceiling = getattr(result, "candidate_ceiling", None) or CANDIDATE_CEILING
    return result


def choose_integrated_verdict(p: dict) -> Tuple[str, str]:
    if p.get("incumbent_fail"):
        return (
            "INTEGRATED_WHOLE_GAME_CONTRACT_FAILURE",
            "autonomous 192 incumbent failed replay",
        )
    if p.get("accounting_fail") or (p.get("solved") and not p.get("replay_ok")):
        return "INTEGRATED_WHOLE_GAME_CONTRACT_FAILURE", "replay, identity or accounting failed"
    inc = int(p.get("incumbent_g") or AUTONOMOUS_INCUMBENT_MW)
    best = p.get("solution_g")
    if p.get("solved") and p.get("replay_ok") and best is not None and int(best) < inc:
        return "INTEGRATED_WHOLE_GAME_COST_IMPROVED", f"solved at g={best}"
    if p.get("solved") and p.get("replay_ok") and best is not None and int(best) == inc:
        return (
            "INTEGRATED_WHOLE_GAME_REDISCOVERS_192_CLASS",
            f"whole-game search recovered a {best}-class terminal",
        )
    max_f = int(p.get("max_foundations") or 0)
    f2 = ((p.get("foundations") or {}).get("cheap") or {}).get("2") or {}
    if max_f >= 8 or (p.get("solution_g") is not None and int(p["solution_g"]) <= inc + 6):
        return (
            "INTEGRATED_WHOLE_GAME_REDISCOVERS_192_CLASS",
            "reached a 192-class late-game structure without beating 192",
        )
    if p.get("ceiling_excluded_strong"):
        return (
            "INTEGRATED_WHOLE_GAME_CEILING_TOO_TIGHT_NO_TERMINAL",
            "strong lineages exist but are excluded by ceiling 191",
        )
    if max_f <= 2 and not f2:
        return (
            "INTEGRATED_WHOLE_GAME_LINEAGE_NOT_REDISCOVERED",
            "whole-game scheduler did not preserve a strong F2-class lineage from opening",
        )
    return (
        "INTEGRATED_WHOLE_GAME_LINEAGE_NOT_REDISCOVERED",
        "focused endgame mechanisms did not surface a 192-class complete line from move zero",
    )
