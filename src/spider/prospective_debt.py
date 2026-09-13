"""v0.62 prospective interference-debt optimisation.

State-local durability on the frozen v0.59/v0.60 architecture.
Does not read the canonical 172 route. Does not alter exact TT or MW g.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

from spider.autonomous_cost import (
    COST_HARVEST_CATS,
    COST_LANES,
    CostTracker,
    checkpoints_from_trace,
    cost_lane_keys,
    cost_pareto_vec,
    load_machine_incumbent,
)
from spider.engine import SpiderState
from spider.structural_analysis import compact_interference, durability_key, interference_debt
from spider.whole_game_anytime import opening_state
from spider.whole_game_epoch_scheduler import (
    PORTFOLIO_WIDTH,
    SEARCH_RSS_MB,
    SEARCH_TIME_S,
    SEARCH_UNIQUE,
    search_epoch_portfolio,
)

INCUMBENT_MOVES = Path(__file__).resolve().parents[2] / "solutions" / "4925153_autonomous_v0_59.moves"

DEBT_LANES = COST_LANES + ("durability",)
DEBT_HARVEST_CATS = COST_HARVEST_CATS + ("durability", "cheap_debt", "cheap_durable")


def enrich_debt(state: SpiderState, rec: dict) -> None:
    d = interference_debt(state)
    rec.update(compact_interference(d))
    rec["durability_key"] = durability_key(state, int(rec.get("g") or 0))


def debt_lane_keys(state: SpiderState, g: int):
    keys = cost_lane_keys(state, g)
    keys["durability"] = durability_key(state, g)
    return keys


class DebtTracker:
    def __init__(self) -> None:
        self.cost = CostTracker()
        self.displaced = 0
        self.n_samples = 0
        self.best_durability = None

    def __call__(self, tops, rec, min_root_g, class_best) -> None:
        self.cost(tops, rec, min_root_g, class_best)
        self.displaced = int(self.cost.displaced)
        b = rec.get("boundaries_total")
        if b is None:
            return
        b = int(b)
        layers = int(rec.get("component_layers") or 0)
        mixed = int(rec.get("mixed_supports") or 0)
        self.n_samples += 1
        dkey = (
            -int(rec.get("foundations") or 0),
            b,
            layers,
            mixed,
            int(rec.get("face_down") or 0),
            int(rec.get("g") or 0),
        )
        if self.best_durability is None or dkey < tuple(self.best_durability.get("durability_key") or ()):
            snap = dict(rec)
            snap["durability_key"] = dkey
            self.best_durability = snap
        if "durability" in tops:
            tops["durability"].add(
                (
                    -int(rec.get("foundations") or 0),
                    b,
                    layers,
                    mixed,
                    int(rec.get("face_down") or 0),
                    int(rec.get("g") or 0),
                    rec.get("ordered_digest") or "",
                ),
                rec,
            )
        if "cheap_debt" in tops:
            tops["cheap_debt"].add((int(rec["g"]), b, layers, rec.get("ordered_digest") or ""), rec)
        tier = (
            "debt_tier",
            int(rec.get("foundations") or 0),
            b // 3,
            1 if rec.get("n_ready") else 0,
        )
        prev = class_best.get(tier)
        if prev is None or rec["g"] < prev["g"]:
            if prev is not None:
                self.displaced += 1
            class_best[tier] = rec
            if "cheap_durable" in tops:
                tops["cheap_durable"].add((rec["g"], rec.get("ordered_digest") or ""), rec)


def search_debt_optimisation(
    *,
    opening: Optional[SpiderState] = None,
    incumbent_trace: Optional[dict] = None,
    max_unique: int = SEARCH_UNIQUE,
    time_limit_s: float = SEARCH_TIME_S,
    rss_abort_mb: float = SEARCH_RSS_MB,
    portfolio_width: int = PORTFOLIO_WIDTH,
):
    opening = opening or opening_state()
    trace = incumbent_trace or load_machine_incumbent(opening)
    incumbent_g = int(trace["g"])
    ceiling = incumbent_g - 1
    tracker = DebtTracker()
    result = search_epoch_portfolio(
        opening=opening,
        max_unique=max_unique,
        time_limit_s=time_limit_s,
        rss_abort_mb=rss_abort_mb,
        cost_ceiling=ceiling,
        portfolio_width=portfolio_width,
        lane_names=DEBT_LANES,
        keys_fn=debt_lane_keys,
        harvest_cats=DEBT_HARVEST_CATS,
        harvest_slack=-1,
        remaining_deal_bound=True,
        incumbent_by_rows=checkpoints_from_trace(trace),
        continue_after_solve=True,
        extra_track=tracker,
        harvest_vec_fn=cost_pareto_vec,
        split_pareto=True,
        enrich_fn=enrich_debt,
    )
    result.incumbent_g = incumbent_g
    result.candidate_ceiling = getattr(result, "candidate_ceiling", None) or ceiling
    result.class_displaced = tracker.displaced
    if result.best_durability is None:
        result.best_durability = tracker.best_durability
    return result


def choose_debt_verdict(p: dict) -> Tuple[str, str]:
    if p.get("accounting_fail") or (p.get("solved") and not p.get("replay_ok")):
        return "INTERFERENCE_DEBT_CONTRACT_FAILURE", "replay, identity or accounting failed"
    inc = int(p.get("incumbent_g") or 198)
    best = p.get("solution_g")
    if p.get("solved") and p.get("replay_ok") and best is not None and int(best) < inc:
        return "INTERFERENCE_DEBT_COST_IMPROVED", f"best g={best} beats incumbent {inc}"
    signal = p.get("metric_signal")
    if signal == "invalid":
        return "INTERFERENCE_DEBT_SIGNAL_INVALID", "state-local metric did not track future rehandling"
    if p.get("rehandling_improved") and not (best is not None and int(best) < inc):
        return "INTERFERENCE_DEBT_REDUCES_REHANDLING_ONLY", "rehandling/interference improved without a cheaper terminal"
    return "INTERFERENCE_DEBT_NO_GAIN", f"no useful improvement over incumbent {inc}"
