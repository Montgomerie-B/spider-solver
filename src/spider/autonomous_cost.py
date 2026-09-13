"""v0.60 incumbent-aware autonomous whole-game cost optimisation.

Optimises the v0.59 machine solution. Does not read the human canonical
trace for policy. Terminal remains ``state.is_solved()``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from spider.engine import SpiderState
from spider.metrics import Action, parse_moves_file, replay_actions
from spider.packed_state import pack_state, pack_whole_game_identity
from spider.research_actions import (
    apply_action,
    dump_actions,
    face_down_count,
    is_deal,
    opening_from_deal,
    step_cost,
    stock_rows,
)
from spider.structural_analysis import INF, current_tableau_summary, foundation_readiness
from spider.whole_game_anytime import DEAL_PATH, opening_state
from spider.whole_game_epoch_scheduler import (
    PORTFOLIO_WIDTH,
    SEARCH_RSS_MB,
    SEARCH_TIME_S,
    SEARCH_UNIQUE,
    _n,
    epoch_lane_keys,
    search_epoch_portfolio,
)

INCUMBENT_MOVES = Path(__file__).resolve().parents[2] / "solutions" / "4925153_autonomous_v0_59.moves"
COST_LANES = ("cost", "reveal", "construction", "readiness", "horizon", "economy")
COST_HARVEST_CATS = (
    "cheap",
    "cheap_ready",
    "cheap_cover",
    "cheap_construction",
    "cheap_fd",
    "workspace",
    "readiness",
    "horizon",
    "ready_div",
    "economy",
    "class_cheap",
    "pareto",
    "deal_now",
    "incumbent",
)


def compact_readiness(ready: dict) -> dict:
    best = ready.get("best_ready") or {}
    return {
        "n_ready": ready.get("n_ready"),
        "ready_suits": list(ready.get("ready_suits") or []),
        "nearest_horizon": ready.get("nearest_horizon"),
        "nearest_suits": list(ready.get("nearest_suits") or []),
        "cover": best.get("cover"),
        "edges": best.get("edges"),
        "cond_len": best.get("cond_len"),
        "gap": best.get("gap"),
        "fd": best.get("fd"),
    }


def replay_solution_trace(
    opening: SpiderState,
    actions: Sequence[Action],
) -> dict:
    """Derive epoch prefix economics from any legal complete solution."""

    verify = opening.clone()
    total = replay_actions(verify, list(actions))
    if not verify.is_solved():
        raise ValueError("trace is not a complete solved solution")
    deals = sum(1 for a in actions if is_deal(a))
    state = opening.clone()
    g = 0
    prefix: List[Action] = []
    epochs: List[dict] = []

    def snap_enter() -> dict:
        s = current_tableau_summary(state)
        r = foundation_readiness(state)
        return {
            "stock_rows": stock_rows(state),
            "enter_g": g,
            "enter_fd": s["face_down"],
            "enter_foundations": s["foundations"],
            "enter_empty": s["empty_n"],
            "enter_bonds": s["same_suit_bonds"],
            "enter_digest": pack_state(state).hex(),
            "enter_ident": pack_whole_game_identity(state).hex(),
            "enter_readiness": compact_readiness(r),
            "full_actions_enter": dump_actions(prefix),
            "tableau": [],
            "paid": 0,
            "zero_cost": 0,
            "foundations_before": s["foundations"],
        }

    cur = snap_enter()
    for action in actions:
        if is_deal(action):
            s = current_tableau_summary(state)
            r = foundation_readiness(state)
            cur["exit_g"] = g
            cur["paid_increment"] = g - int(cur["enter_g"])
            cur["exit_fd"] = s["face_down"]
            cur["exit_foundations"] = s["foundations"]
            cur["exit_empty"] = s["empty_n"]
            cur["exit_bonds"] = s["same_suit_bonds"]
            cur["exit_digest"] = pack_state(state).hex()
            cur["exit_ident"] = pack_whole_game_identity(state).hex()
            cur["exit_readiness"] = compact_readiness(r)
            cur["fd_delta"] = int(cur["exit_fd"]) - int(cur["enter_fd"])
            cur["tableau_n"] = len(cur["tableau"])
            epochs.append(cur)
            cost = apply_action(state, action)
            g += cost
            prefix.append(action)
            cur = snap_enter()
            continue
        cost = step_cost(state, action)
        apply_action(state, action)
        g += cost
        prefix.append(action)
        cur["tableau"].append(dump_actions([action])[0])
        if cost == 0:
            cur["zero_cost"] += 1
        else:
            cur["paid"] += cost
    s = current_tableau_summary(state)
    r = foundation_readiness(state)
    cur["exit_g"] = g
    cur["paid_increment"] = g - int(cur["enter_g"])
    cur["exit_fd"] = s["face_down"]
    cur["exit_foundations"] = s["foundations"]
    cur["exit_empty"] = s["empty_n"]
    cur["exit_bonds"] = s["same_suit_bonds"]
    cur["exit_digest"] = pack_state(state).hex()
    cur["exit_ident"] = pack_whole_game_identity(state).hex()
    cur["exit_readiness"] = compact_readiness(r)
    cur["fd_delta"] = int(cur["exit_fd"]) - int(cur["enter_fd"])
    cur["tableau_n"] = len(cur["tableau"])
    cur["solved"] = state.is_solved()
    epochs.append(cur)
    if g != total:
        raise ValueError(f"trace g mismatch {g} vs {total}")
    return {
        "g": total,
        "deals": deals,
        "solved": True,
        "replay_ok": True,
        "n_actions": len(actions),
        "tableau_commands": sum(1 for a in actions if not is_deal(a)),
        "zero_cost_total": sum(int(ep["zero_cost"]) for ep in epochs),
        "epochs": epochs,
        "prefix_g_by_rows": {int(ep["stock_rows"]): int(ep["enter_g"]) for ep in epochs},
        "exit_g_by_rows": {int(ep["stock_rows"]): int(ep["exit_g"]) for ep in epochs},
    }


def load_machine_incumbent(opening: Optional[SpiderState] = None) -> dict:
    opening = opening or opening_state()
    actions = parse_moves_file(INCUMBENT_MOVES)
    return replay_solution_trace(opening, actions)


def checkpoints_from_trace(trace: dict) -> Dict[int, dict]:
    out: Dict[int, dict] = {}
    for ep in trace["epochs"]:
        rows = int(ep["stock_rows"])
        out[rows] = {
            "g": int(ep["enter_g"]),
            "full_actions": list(ep["full_actions_enter"]),
            "ordered_digest": ep["enter_digest"],
            "ident": ep["enter_ident"],
            "whole_game_identity": ep["enter_ident"],
            "stock_rows": rows,
            "face_down": ep["enter_fd"],
            "foundations": ep["enter_foundations"],
            "incumbent_control": True,
            "portfolio_cat": "incumbent",
        }
    return out


def cost_lane_keys(state, g: int):
    keys = epoch_lane_keys(state, g)
    s = current_tableau_summary(state)
    r = foundation_readiness(state)
    if r["n_ready"] > 0:
        best = r["best_ready"] or {}
        keys["economy"] = (
            int(g),
            -int(s["foundations"]),
            _n(best.get("cover")),
            int(s["face_down"]),
            -int(s["same_suit_bonds"]),
            -int(s["empty_n"]),
        )
    else:
        nearest = r["nearest_horizon"]
        keys["economy"] = (
            int(g),
            int(s["face_down"]),
            -int(s["same_suit_bonds"]),
            -int(s["empty_n"]),
            int(INF if nearest is None else nearest),
        )
    # Drop workspace as a dedicated lane; reveal still carries workspace.
    keys.pop("workspace", None)
    return keys


def cost_pareto_vec(rec: dict) -> tuple:
    if rec.get("n_ready"):
        return (
            int(rec.get("g") or 0),
            -int(rec.get("foundations") or 0),
            int(rec.get("face_down") or 0),
            -int(rec.get("empty_n") or 0),
            -int(rec.get("bonds") or 0),
            _n(rec.get("cover")),
            -int(rec.get("ready_edges") or 0),
            -int(rec.get("ready_cond") or 0),
        )
    return (
        int(rec.get("g") or 0),
        -int(rec.get("foundations") or 0),
        int(rec.get("face_down") or 0),
        -int(rec.get("empty_n") or 0),
        -int(rec.get("bonds") or 0),
        -int(rec.get("longest") or 0),
    )


def structural_class_key(rec: dict) -> tuple:
    if rec.get("n_ready"):
        return (
            "ready",
            int(rec.get("foundations") or 0),
            rec.get("cover"),
            int(rec.get("face_down") or 0) // 2,
        )
    return (
        "prep",
        int(rec.get("foundations") or 0),
        int(rec.get("face_down") or 0) // 2,
        int(rec.get("bonds") or 0) // 4,
    )


class CostTracker:
    displaced = 0

    def __call__(self, tops, rec, min_root_g, class_best) -> None:
        if rec.get("n_ready"):
            if "cheap_ready" in tops:
                tops["cheap_ready"].add((rec["g"], _n(rec.get("cover")), rec["ordered_digest"]), rec)
            if "cheap_cover" in tops:
                tops["cheap_cover"].add((_n(rec.get("cover")), rec["g"], rec["ordered_digest"]), rec)
            if "economy" in tops:
                tops["economy"].add(
                    (rec["g"], -rec["foundations"], _n(rec.get("cover")), rec["face_down"]),
                    rec,
                )
        if "cheap_construction" in tops:
            tops["cheap_construction"].add((rec["g"], -rec["bonds"], rec["ordered_digest"]), rec)
        if "cheap_fd" in tops:
            tops["cheap_fd"].add((rec["g"], rec["face_down"], rec["ordered_digest"]), rec)
        key = structural_class_key(rec)
        prev = class_best.get(key)
        if prev is None or rec["g"] < prev["g"]:
            if prev is not None:
                self.displaced += 1
            class_best[key] = rec
            if "class_cheap" in tops:
                tops["class_cheap"].add((rec["g"], rec["ordered_digest"]), rec)


def search_cost_optimisation(
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
    tracker = CostTracker()
    result = search_epoch_portfolio(
        opening=opening,
        max_unique=max_unique,
        time_limit_s=time_limit_s,
        rss_abort_mb=rss_abort_mb,
        cost_ceiling=ceiling,
        portfolio_width=portfolio_width,
        lane_names=COST_LANES,
        keys_fn=cost_lane_keys,
        harvest_cats=COST_HARVEST_CATS,
        harvest_slack=-1,
        remaining_deal_bound=True,
        incumbent_by_rows=checkpoints_from_trace(trace),
        continue_after_solve=True,
        extra_track=tracker,
        harvest_vec_fn=cost_pareto_vec,
        split_pareto=True,
    )
    result.incumbent_g = incumbent_g
    result.candidate_ceiling = getattr(result, "candidate_ceiling", None) or ceiling
    result.class_displaced = tracker.displaced
    return result


def choose_cost_verdict(p: dict) -> Tuple[str, str]:
    if p.get("accounting_fail") or (p.get("solved") and not p.get("replay_ok")):
        return "AUTONOMOUS_OPTIMISATION_CONTRACT_FAILURE", "replay, identity or incumbent provenance failed"
    inc = int(p.get("incumbent_g") or 198)
    best = p.get("solution_g")
    if p.get("solved") and p.get("replay_ok") and best is not None and int(best) < inc:
        if int(inc) - int(best) >= 10:
            return "AUTONOMOUS_COST_IMPROVED", f"best g={best} beats incumbent {inc} by {inc - int(best)}"
        return "AUTONOMOUS_COST_IMPROVED", f"best g={best} beats incumbent {inc}"
    return "AUTONOMOUS_INCUMBENT_HELD", f"no solution below {inc}; machine incumbent retained"


def epoch_savings_table(incumbent_trace: dict, candidate_trace: Optional[dict]) -> List[dict]:
    rows = []
    inc_map = incumbent_trace.get("exit_g_by_rows") or {}
    cand_map = (candidate_trace or {}).get("exit_g_by_rows") or {}
    labels = {5: "pre-SD1", 4: "post-SD1", 3: "post-SD2", 2: "post-SD3", 1: "post-SD4", 0: "post-SD5"}
    for r in (5, 4, 3, 2, 1, 0):
        ig = inc_map.get(r)
        cg = cand_map.get(r)
        rows.append(
            {
                "epoch": labels[r],
                "stock_rows": r,
                "incumbent_g": ig,
                "candidate_g": cg,
                "saving": None if ig is None or cg is None else int(ig) - int(cg),
            }
        )
    ig = incumbent_trace.get("g")
    cg = (candidate_trace or {}).get("g")
    rows.append(
        {
            "epoch": "solved",
            "stock_rows": 0,
            "incumbent_g": ig,
            "candidate_g": cg,
            "saving": None if ig is None or cg is None else int(ig) - int(cg),
        }
    )
    return rows
