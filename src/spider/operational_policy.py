"""v0.63 operational foundation viability search policy.

Augments READINESS with state-local operational viability.
Does not read the canonical 172 route. No DURABILITY lane.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

from spider.autonomous_cost import (
    COST_HARVEST_CATS,
    COST_LANES,
    CostTracker,
    checkpoints_from_trace,
    load_machine_incumbent,
)
from spider.engine import SpiderState
from spider.operational_viability import (
    compact_operational,
    operational_viability_key,
    rank_ready_suits,
)
from spider.structural_analysis import INF, current_tableau_summary, foundation_readiness
from spider.whole_game_anytime import opening_state
from spider.whole_game_epoch_scheduler import (
    PORTFOLIO_WIDTH,
    SEARCH_RSS_MB,
    SEARCH_TIME_S,
    SEARCH_UNIQUE,
    _n,
    search_epoch_portfolio,
)

INCUMBENT_MOVES = Path(__file__).resolve().parents[2] / "solutions" / "4925153_autonomous_v0_59.moves"

OP_LANES = COST_LANES
OP_HARVEST_CATS = COST_HARVEST_CATS + ("operational_alt", "cheap_viable")


def operational_lane_keys(state: SpiderState, g: int):
    s = current_tableau_summary(state)
    r = foundation_readiness(state)
    fd = int(s["face_down"])
    empty = int(s["empty_n"])
    keys = {
        "cost": (int(g),),
        "reveal": (fd, -empty, int(g)),
        "construction": (
            -int(s["same_suit_bonds"]),
            -int(s["longest_run"]),
            -int(s["merge_edges"]),
            fd,
            int(g),
        ),
        "readiness": None,
        "horizon": None,
        "economy": None,
    }
    ranked = rank_ready_suits(state, readiness=r, summary=s, g=g)
    if ranked["n_ready"] > 0 and ranked["best"] is not None:
        best = ranked["best"]
        keys["readiness"] = operational_viability_key(best, g)
        keys["economy"] = (
            int(g),
            -int(s["foundations"]),
            int(best["global_fd"]),
            _n(best.get("cover")),
            int(best.get("relevant_blockers") or 0),
            -empty,
        )
    else:
        nearest = r["nearest_horizon"]
        if nearest is None:
            nearest = INF
        keys["horizon"] = (
            int(nearest),
            -int(r["horizon_bonds"]),
            -int(r["horizon_longest"]),
            -int(r["horizon_edges"]),
            fd,
            int(g),
        )
        keys["economy"] = (
            int(g),
            fd,
            -int(s["same_suit_bonds"]),
            -empty,
            int(nearest),
        )
    return keys


def operational_pareto_vec(rec: dict) -> tuple:
    if rec.get("n_ready"):
        return (
            int(rec.get("g") or 0),
            int(rec.get("face_down") or 0),
            _n(rec.get("cover")),
            int(rec.get("op_blockers") or 0),
            int(rec.get("k_min_blockers") or INF),
            -int(rec.get("empty_n") or 0),
            -int(rec.get("ready_edges") or 0),
        )
    return (
        int(rec.get("g") or 0),
        -int(rec.get("foundations") or 0),
        int(rec.get("face_down") or 0),
        -int(rec.get("empty_n") or 0),
        -int(rec.get("bonds") or 0),
        -int(rec.get("longest") or 0),
    )


def enrich_operational(state: SpiderState, rec: dict) -> None:
    ranked = rank_ready_suits(state, g=int(rec.get("g") or 0))
    rec["n_ready"] = ranked["n_ready"]
    rec["ready_suits"] = list(ranked["ready_suits"])
    best = ranked["best"]
    second = ranked["second"]
    if best is not None:
        rec.update({f"op_{k}": v for k, v in compact_operational(best).items()})
        rec["cover"] = best.get("cover")
        rec["ready_fd"] = best.get("required_fd")
        rec["ready_edges"] = best.get("edges")
        rec["ready_cond"] = best.get("cond_len")
        rec["ready_gap"] = best.get("gap")
        rec["op_blockers"] = best.get("relevant_blockers")
        rec["k_min_blockers"] = best.get("k_min_blockers")
        rec["a_min_blockers"] = best.get("a_min_blockers")
        rec["anchor_contention"] = best.get("anchor_contention")
        rec["best_ready_suit"] = best["suit"]
        rec["op_key"] = best["key"]
        rec["boundaries_total"] = best.get("boundaries_total")
    else:
        rec["best_ready_suit"] = None
        rec["op_key"] = None
        rec["boundaries_total"] = ranked["scan"].get("boundaries_total")
    if second is not None:
        rec["second_ready_suit"] = second["suit"]
        rec["op_alt_key"] = second["key"]
    else:
        rec["second_ready_suit"] = None
        rec["op_alt_key"] = None


class OperationalTracker:
    def __init__(self) -> None:
        self.cost = CostTracker()
        self.displaced = 0
        self.best_operational = None

    def __call__(self, tops, rec, min_root_g, class_best) -> None:
        self.cost(tops, rec, min_root_g, class_best)
        self.displaced = int(self.cost.displaced)
        if rec.get("n_ready") and rec.get("op_key") is not None:
            if "cheap_viable" in tops:
                tops["cheap_viable"].add(
                    (rec["g"], rec.get("face_down"), _n(rec.get("cover")), rec.get("ordered_digest") or ""),
                    rec,
                )
            if rec.get("op_alt_key") is not None and "operational_alt" in tops:
                tops["operational_alt"].add(
                    (rec.get("face_down"), _n(rec.get("cover")), rec.get("second_ready_suit") or ""),
                    rec,
                )
            ok = tuple(rec["op_key"])
            if self.best_operational is None or ok < tuple(self.best_operational.get("op_key") or ()):
                self.best_operational = dict(rec)


def search_operational_optimisation(
    *,
    opening: Optional[SpiderState] = None,
    incumbent_trace: Optional[dict] = None,
    max_unique: int = SEARCH_UNIQUE,
    time_limit_s: float = SEARCH_TIME_S,
    rss_abort_mb: float = SEARCH_RSS_MB,
    portfolio_width: int = PORTFOLIO_WIDTH,
    initial_roots=None,
    abort_when=None,
    incumbent_by_rows=None,
    cost_ceiling=None,
    harvest_cats=None,
    extra_track=None,
    enrich_fn=None,
    on_harvest=None,
):
    opening = opening or opening_state()
    trace = incumbent_trace or load_machine_incumbent(opening)
    incumbent_g = int(trace["g"])
    ceiling = int(cost_ceiling) if cost_ceiling is not None else incumbent_g - 1
    tracker = OperationalTracker()

    def track(tops, rec, min_root_g, class_best) -> None:
        tracker(tops, rec, min_root_g, class_best)
        if extra_track is not None:
            extra_track(tops, rec, min_root_g, class_best)

    result = search_epoch_portfolio(
        opening=opening,
        max_unique=max_unique,
        time_limit_s=time_limit_s,
        rss_abort_mb=rss_abort_mb,
        cost_ceiling=ceiling,
        portfolio_width=portfolio_width,
        lane_names=OP_LANES,
        keys_fn=operational_lane_keys,
        harvest_cats=OP_HARVEST_CATS if harvest_cats is None else harvest_cats,
        harvest_slack=-1,
        remaining_deal_bound=True,
        incumbent_by_rows=incumbent_by_rows if incumbent_by_rows is not None else checkpoints_from_trace(trace),
        continue_after_solve=True,
        extra_track=track,
        harvest_vec_fn=operational_pareto_vec,
        split_pareto=True,
        enrich_fn=enrich_operational if enrich_fn is None else enrich_fn,
        initial_roots=initial_roots,
        abort_when=abort_when,
        on_harvest=on_harvest,
    )
    result.incumbent_g = incumbent_g
    result.candidate_ceiling = getattr(result, "candidate_ceiling", None) or ceiling
    result.class_displaced = tracker.displaced
    if getattr(result, "best_readiness", None) is None:
        result.best_readiness = tracker.best_operational
    return result


def choose_operational_verdict(p: dict) -> Tuple[str, str]:
    if p.get("accounting_fail") or (p.get("solved") and not p.get("replay_ok")):
        return "OPERATIONAL_VIABILITY_CONTRACT_FAILURE", "replay, identity or accounting failed"
    inc = int(p.get("incumbent_g") or 198)
    best = p.get("solution_g")
    if p.get("solved") and p.get("replay_ok") and best is not None and int(best) < inc:
        return "OPERATIONAL_VIABILITY_COST_IMPROVED", f"best g={best} beats incumbent {inc}"
    if p.get("metric_signal") == "invalid":
        return "OPERATIONAL_VIABILITY_SIGNAL_INVALID", "metric did not distinguish awkward vs accessible ready suits"
    if p.get("lineage_improved"):
        return "OPERATIONAL_VIABILITY_IMPROVES_LINEAGE", "foundation milestones on healthier boards without a cheaper terminal"
    return "OPERATIONAL_VIABILITY_NO_GAIN", f"no material improvement over incumbent {inc}"
