"""v0.65 healthy F2 cost-to-go isolation.

Reconstructs the autonomous v0.64 F2 (g=130, rows=1, fd=2) and continues
under frozen v0.63 policy. No canonical reads for search. No new heuristic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Sequence, Tuple

from spider.engine import SpiderState
from spider.metrics import Action, parse_moves_file, replay_actions
from spider.operational_policy import search_operational_optimisation
from spider.operational_viability import (
    compact_operational,
    foundation_operational_viability,
    rank_ready_suits,
)
from spider.packed_state import pack_state, pack_whole_game_identity
from spider.research_actions import (
    dump_actions,
    face_down_count,
    is_deal,
    stock_rows,
    tableau_actions,
)
from spider.structural_analysis import (
    SUITS,
    compact_interference,
    current_tableau_summary,
    foundation_readiness,
    interference_debt,
)
from spider.whole_game_anytime import opening_state

LINEAGE_TAG = "v064_f2_g130"
F2_G = 130
F2_ROWS = 1
F2_FD = 2
F2_N = 2
F2_SUITS = frozenset({"s", "d"})
INCUMBENT_G = 198
CANDIDATE_CEILING = 197
REMAINING_BUDGET = CANDIDATE_CEILING - F2_G
V064_JSON = Path(__file__).resolve().parents[2] / "docs" / "research" / "healthy_f1_lineage_v0_64.json"
CANON_MOVES = Path(__file__).resolve().parents[2] / "solutions" / "4925153_canonical.moves"


def parse_stored_actions(raw: Sequence) -> list:
    actions: list = []
    for item in raw:
        if item == ["deal"] or item == "deal" or item == ("deal",):
            actions.append(("deal",))
        else:
            actions.append((int(item[0]), int(item[1]), int(item[2])))
    return actions


def snapshot_state(state: SpiderState, g: int) -> dict:
    s = current_tableau_summary(state)
    r = foundation_readiness(state)
    ranked = rank_ready_suits(state, readiness=r, summary=s, g=g)
    debt = compact_interference(interference_debt(state))
    by_suit = {
        suit: compact_operational(
            foundation_operational_viability(state, suit, readiness=r, summary=s)
        )
        for suit in SUITS
    }
    return {
        "g": g,
        "stock_rows": stock_rows(state),
        "face_down": s["face_down"],
        "foundations": s["foundations"],
        "foundation_suits": list(s["foundation_suits"]),
        "empty_n": s["empty_n"],
        "legal_tableau": len(tableau_actions(state)),
        "same_suit_bonds": s["same_suit_bonds"],
        "visible_components": s["visible_runs"],
        "run_compression": s["run_compression"],
        "longest_run": s["longest_run"],
        "merge_edges": s["merge_edges"],
        "ordered_digest": pack_state(state).hex(),
        "whole_game_identity": pack_whole_game_identity(state).hex(),
        "n_ready": ranked["n_ready"],
        "ready_suits": ranked["ready_suits"],
        "best_suit": ranked["best_suit"],
        "second_suit": ranked["second_suit"],
        "best": compact_operational(ranked["best"]) if ranked["best"] else None,
        "all_ready": [compact_operational(v) for v in ranked["ranked"]],
        "by_suit": by_suit,
        "interference": debt,
        "solved": state.is_solved(),
    }


def observe_deal(state: SpiderState, g: int) -> dict:
    incoming = list(state.stock[-10:]) if len(state.stock) >= 10 else []
    hooks = [col.top() for col in state.columns]
    land = []
    for col_i, card in enumerate(incoming):
        top = hooks[col_i]
        land.append(
            {
                "column_1": col_i + 1,
                "rank": card.rank,
                "suit": card.suit,
                "rank_ok": bool(top is not None and top.rank == card.rank + 1),
                "same_suit": bool(
                    top is not None and top.suit == card.suit and top.rank == card.rank + 1
                ),
                "mixed_block": bool(top is not None and top.rank != card.rank + 1),
                "empty_land": top is None,
            }
        )
    before = snapshot_state(state, g)
    from spider.research_actions import apply_action

    apply_action(state, ("deal",))
    after = snapshot_state(state, g + 1)
    return {
        "rank_ok": sum(1 for x in land if x["rank_ok"]),
        "same_suit_land": sum(1 for x in land if x["same_suit"]),
        "mixed_block": sum(1 for x in land if x["mixed_block"]),
        "empty_land": sum(1 for x in land if x["empty_land"]),
        "legal_before": before["legal_tableau"],
        "legal_after": after["legal_tableau"],
        "fd_before": before["face_down"],
        "fd_after": after["face_down"],
        "F_before": before["foundations"],
        "F_after": after["foundations"],
        "best_suit_before": before["best_suit"],
        "best_suit_after": after["best_suit"],
        "bonds_before": before["same_suit_bonds"],
        "bonds_after": after["same_suit_bonds"],
        "after": after,
    }


def load_v064_f1_prefix() -> list:
    if not V064_JSON.exists():
        return []
    data = json.loads(V064_JSON.read_text(encoding="utf-8"))
    return parse_stored_actions(data.get("f1_prefix_actions") or [])


def verify_f2_prefix(opening: SpiderState, actions: Sequence[Action]) -> dict:
    end = opening.clone()
    g = replay_actions(end, list(actions))
    suits = frozenset(run[0].suit for run in end.foundations if run)
    ok = (
        g == F2_G
        and stock_rows(end) == F2_ROWS
        and face_down_count(end) == F2_FD
        and len(end.foundations) == F2_N
        and suits == F2_SUITS
        and not end.is_solved()
    )
    snap = snapshot_state(end, g)
    snap["replay_ok"] = ok
    snap["n_actions"] = len(actions)
    snap["n_deals"] = sum(1 for a in actions if is_deal(a))
    snap["suits"] = sorted(suits)
    return snap


def f2_abort(out, rec) -> bool:
    suits = rec.get("foundation_suits") or []
    return (
        int(rec.get("foundations") or 0) >= F2_N
        and int(rec.get("g") or -1) == F2_G
        and int(rec.get("face_down") or -1) == F2_FD
        and int(rec.get("stock_rows") or -1) == F2_ROWS
        and frozenset(suits) == F2_SUITS
    )


def reconstruct_v064_f2(
    opening: Optional[SpiderState] = None,
    *,
    time_limit_s: float = 900.0,
    max_unique: int = 800_000,
) -> dict:
    opening = opening or opening_state()
    f1_actions = load_v064_f1_prefix()
    if not f1_actions:
        return {"ok": False, "reason": "HEALTHY_F2_PROVENANCE_FAILURE", "debug": {"f1": "missing"}}
    from spider.healthy_f1 import verify_f1_prefix

    f1_snap = verify_f1_prefix(opening, f1_actions)
    if not f1_snap.get("replay_ok"):
        return {"ok": False, "reason": "HEALTHY_F2_PROVENANCE_FAILURE", "debug": {"f1": f1_snap}}
    f1_root = {
        "g": 71,
        "ordered_digest": f1_snap["ordered_digest"],
        "whole_game_identity": f1_snap["whole_game_identity"],
        "ident": f1_snap["whole_game_identity"],
        "full_actions": dump_actions(f1_actions),
        "stock_rows": 3,
        "foundations": 1,
        "face_down": 10,
        "lineage": ["v063_f1_g71"],
        "portfolio_cat": "f1_root",
    }
    res = search_operational_optimisation(
        opening=opening,
        initial_roots=[f1_root],
        cost_ceiling=CANDIDATE_CEILING,
        incumbent_by_rows={},
        time_limit_s=time_limit_s,
        max_unique=max_unique,
        abort_when=f2_abort,
    )
    first = (res.foundations_first or {}).get(2)
    cheap = (res.foundations_cheap or {}).get(2)
    rec = None
    for cand in (cheap, first):
        if not cand:
            continue
        if int(cand.get("g") or -1) == F2_G and int(cand.get("face_down") or -1) == F2_FD:
            rec = cand
            break
    rec = rec or cheap or first
    debug = {
        "stop_reason": res.stop_reason,
        "max_foundations": res.max_foundations,
        "unique": res.unique,
        "elapsed_s": res.elapsed_s,
        "first_g": None if not first else first.get("g"),
        "first_fd": None if not first else first.get("face_down"),
        "first_rows": None if not first else first.get("stock_rows"),
        "first_n_actions": None if not first else len(first.get("full_actions") or []),
        "cheap_g": None if not cheap else cheap.get("g"),
        "cheap_fd": None if not cheap else cheap.get("face_down"),
        "cheap_n_actions": None if not cheap else len(cheap.get("full_actions") or []),
    }
    print("F2_DEBUG", debug, flush=True)
    if not rec or not rec.get("full_actions"):
        return {"ok": False, "reason": "HEALTHY_F2_PROVENANCE_FAILURE", "debug": debug}
    actions = parse_stored_actions(rec["full_actions"])
    snap = verify_f2_prefix(opening, actions)
    print(
        "F2_VERIFY",
        {
            "g": snap.get("g"),
            "fd": snap.get("face_down"),
            "rows": snap.get("stock_rows"),
            "F": snap.get("foundations"),
            "suits": snap.get("suits"),
            "ok": snap.get("replay_ok"),
        },
        flush=True,
    )
    if not snap.get("replay_ok"):
        return {"ok": False, "reason": "HEALTHY_F2_PROVENANCE_FAILURE", "snap": snap, "debug": debug}
    if rec.get("ordered_digest") and rec["ordered_digest"] != snap["ordered_digest"]:
        return {"ok": False, "reason": "HEALTHY_F2_PROVENANCE_FAILURE", "snap": snap, "debug": debug}
    root = {
        "g": F2_G,
        "ordered_digest": snap["ordered_digest"],
        "whole_game_identity": snap["whole_game_identity"],
        "ident": snap["whole_game_identity"],
        "full_actions": dump_actions(actions),
        "stock_rows": F2_ROWS,
        "foundations": F2_N,
        "face_down": F2_FD,
        "lineage": [LINEAGE_TAG],
        "portfolio_cat": "f2_root",
    }
    return {
        "ok": True,
        "actions": actions,
        "root": root,
        "snap": snap,
        "elapsed_s": res.elapsed_s,
        "unique": res.unique,
        "stop_reason": res.stop_reason,
        "debug": debug,
    }


def search_f2_continuation(
    *,
    opening: SpiderState,
    recon: dict,
    max_unique: int = 800_000,
    time_limit_s: float = 900.0,
    rss_abort_mb: float = 2.5 * 1024.0,
    portfolio_width: int = 256,
):
    return search_operational_optimisation(
        opening=opening,
        initial_roots=[dict(recon["root"])],
        cost_ceiling=CANDIDATE_CEILING,
        incumbent_by_rows={},
        max_unique=max_unique,
        time_limit_s=time_limit_s,
        rss_abort_mb=rss_abort_mb,
        portfolio_width=portfolio_width,
    )


def canonical_f2_snapshot(opening: SpiderState) -> dict:
    actions = parse_moves_file(CANON_MOVES)
    from spider.research_actions import apply_action, step_cost

    state = opening.clone()
    g = 0
    last_f = 0
    for action in actions:
        cost = 1 if is_deal(action) else step_cost(state, action)
        apply_action(state, action)
        g += cost
        f = len(state.foundations)
        if f >= 2 and last_f < 2:
            return snapshot_state(state, g)
        last_f = f
    return snapshot_state(state, g)


def choose_f2_verdict(p: dict) -> Tuple[str, str]:
    if p.get("provenance_fail"):
        return "HEALTHY_F2_PROVENANCE_FAILURE", "exact F2 path/state could not be verified"
    if p.get("accounting_fail") or (p.get("solved") and not p.get("replay_ok")):
        return "HEALTHY_F2_CONTRACT_FAILURE", "replay, identity or accounting failed"
    inc = int(p.get("incumbent_g") or INCUMBENT_G)
    best = p.get("solution_g")
    if p.get("solved") and p.get("replay_ok") and best is not None:
        if int(best) < inc:
            return "HEALTHY_F2_COST_IMPROVED", f"F2 continuation solved at g={best}"
        return "HEALTHY_F2_CONVERTS_BUT_NOT_CHEAPER", f"solved at g={best} not below {inc}"
    mode = p.get("limit_mode")
    if mode == "coverage":
        return "HEALTHY_F2_COVERAGE_LIMITED", "promising cheap states remain when time expires"
    if mode == "heuristic":
        return "HEALTHY_F2_HEURISTIC_LIMITED", "ordering failed to develop available cheap F3/F4"
    return "HEALTHY_F2_STRUCTURE_LIMITED", "focused search still finds F3/F4 intrinsically expensive"
