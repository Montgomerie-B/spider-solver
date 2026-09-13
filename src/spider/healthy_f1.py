"""v0.64 healthy F1 lineage reconstruction and continuation.

Telemetry lineage only. Does not change packed identity or TT.
Does not read the canonical 172 route for search.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence, Tuple

from spider.engine import SpiderState
from spider.metrics import Action, parse_moves_file, replay_actions
from spider.operational_policy import search_operational_optimisation
from spider.operational_viability import compact_operational, rank_ready_suits
from spider.packed_state import pack_state, pack_whole_game_identity
from spider.research_actions import (
    apply_action,
    dump_actions,
    face_down_count,
    is_deal,
    stock_rows,
    tableau_actions,
)
from spider.structural_analysis import (
    compact_interference,
    current_tableau_summary,
    foundation_readiness,
    interference_debt,
)
from spider.whole_game_anytime import opening_state

LINEAGE_TAG = "v063_f1_g71"
F1_G = 71
F1_ROWS = 3
F1_FD = 10
F1_N = 1
INCUMBENT_G = 198
CANDIDATE_CEILING = 197
V063_JSON = Path(__file__).resolve().parents[2] / "docs" / "research" / "operational_foundation_viability_v0_63.json"
AUTO_MOVES = Path(__file__).resolve().parents[2] / "solutions" / "4925153_autonomous_v0_59.moves"


def snapshot_f1(state: SpiderState, g: int) -> dict:
    s = current_tableau_summary(state)
    r = foundation_readiness(state)
    ranked = rank_ready_suits(state, readiness=r, summary=s, g=g)
    debt = compact_interference(interference_debt(state))
    return {
        "g": g,
        "stock_rows": stock_rows(state),
        "face_down": s["face_down"],
        "foundations": s["foundations"],
        "foundation_suits": list(s["foundation_suits"]),
        "empty_n": s["empty_n"],
        "legal_tableau": len(tableau_actions(state)),
        "ordered_digest": pack_state(state).hex(),
        "whole_game_identity": pack_whole_game_identity(state).hex(),
        "n_ready": ranked["n_ready"],
        "ready_suits": ranked["ready_suits"],
        "best_suit": ranked["best_suit"],
        "second_suit": ranked["second_suit"],
        "best": compact_operational(ranked["best"]) if ranked["best"] else None,
        "all_ready": [compact_operational(v) for v in ranked["ranked"]],
        "interference": debt,
        "solved": state.is_solved(),
    }


def verify_f1_prefix(opening: SpiderState, actions: Sequence[Action]) -> dict:
    end = opening.clone()
    g = replay_actions(end, list(actions))
    ok = (
        g == F1_G
        and stock_rows(end) == F1_ROWS
        and face_down_count(end) == F1_FD
        and len(end.foundations) == F1_N
        and not end.is_solved()
    )
    snap = snapshot_f1(end, g)
    snap["replay_ok"] = ok
    snap["n_actions"] = len(actions)
    snap["n_deals"] = sum(1 for a in actions if is_deal(a))
    return snap


def f1_abort(out, rec) -> bool:
    return (
        int(rec.get("foundations") or 0) >= F1_N
        and int(rec.get("g") or -1) == F1_G
        and int(rec.get("face_down") or -1) == F1_FD
        and int(rec.get("stock_rows") or -1) == F1_ROWS
    )


def reconstruct_v063_f1(
    opening: Optional[SpiderState] = None,
    *,
    time_limit_s: float = 900.0,
    max_unique: int = 800_000,
) -> dict:
    """Replay v0.63 policy from the opening until the recorded F1 milestone."""

    opening = opening or opening_state()
    res = search_operational_optimisation(
        opening=opening,
        time_limit_s=time_limit_s,
        max_unique=max_unique,
        abort_when=f1_abort,
    )
    first = (res.foundations_first or {}).get(1)
    cheap = (res.foundations_cheap or {}).get(1)
    rec = None
    for cand in (cheap, first):
        if not cand:
            continue
        if int(cand.get("g") or -1) == F1_G and int(cand.get("face_down") or -1) == F1_FD:
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
        "cheap_rows": None if not cheap else cheap.get("stock_rows"),
        "cheap_n_actions": None if not cheap else len(cheap.get("full_actions") or []),
    }
    print("F1_DEBUG", debug, flush=True)
    if not rec or not rec.get("full_actions"):
        return {"ok": False, "reason": "HEALTHY_F1_PROVENANCE_FAILURE", "debug": debug, "search": res}
    actions = []
    for item in rec["full_actions"]:
        if item == ["deal"] or item == "deal":
            actions.append(("deal",))
        else:
            actions.append((int(item[0]), int(item[1]), int(item[2])))
    snap = verify_f1_prefix(opening, actions)
    debug["verify"] = {
        "g": snap.get("g"),
        "fd": snap.get("face_down"),
        "rows": snap.get("stock_rows"),
        "F": snap.get("foundations"),
        "deals": snap.get("n_deals"),
        "ok": snap.get("replay_ok"),
    }
    print("F1_VERIFY", debug["verify"], flush=True)
    if not (
        snap.get("g") == F1_G
        and snap.get("face_down") == F1_FD
        and snap.get("stock_rows") == F1_ROWS
        and snap.get("foundations") == F1_N
        and not snap.get("solved")
    ):
        return {"ok": False, "reason": "HEALTHY_F1_PROVENANCE_FAILURE", "snap": snap, "debug": debug, "search": res}
    if rec.get("ordered_digest") and rec["ordered_digest"] != snap["ordered_digest"]:
        return {"ok": False, "reason": "HEALTHY_F1_PROVENANCE_FAILURE", "snap": snap, "debug": debug, "search": res}
    root = {
        "g": F1_G,
        "ordered_digest": snap["ordered_digest"],
        "whole_game_identity": snap["whole_game_identity"],
        "ident": snap["whole_game_identity"],
        "full_actions": dump_actions(actions),
        "stock_rows": F1_ROWS,
        "foundations": F1_N,
        "face_down": F1_FD,
        "lineage": [LINEAGE_TAG],
        "incumbent_control": False,
        "portfolio_cat": "f1_root",
    }
    return {
        "ok": True,
        "reason": None,
        "actions": actions,
        "root": root,
        "snap": snap,
        "elapsed_s": res.elapsed_s,
        "unique": res.unique,
        "stop_reason": res.stop_reason,
    }


def audit_v063_ancestry() -> dict:
    if not V063_JSON.exists():
        return {"status": "ANCESTRY_NOT_RECORDED", "reason": "missing v0.63 json"}
    import json

    data = json.loads(V063_JSON.read_text(encoding="utf-8"))
    cheap = ((data.get("foundations") or {}).get("cheap") or {}).get("1") or {}
    has_path = bool(cheap.get("full_actions"))
    has_digest = bool(cheap.get("ordered_digest"))
    if not has_path:
        return {
            "status": "ANCESTRY_NOT_RECORDED",
            "reason": "v0.63 slimed F1 full_actions and later-epoch identities",
            "recorded_f1": {
                "g": cheap.get("g"),
                "stock_rows": cheap.get("stock_rows"),
                "face_down": cheap.get("face_down"),
                "foundations": cheap.get("foundations"),
                "foundation_suits": cheap.get("foundation_suits"),
            },
            "has_path": has_path,
            "has_digest": has_digest,
        }
    return {"status": "RECORDED", "recorded_f1": cheap}


def f1_continuation_root(recon: dict) -> list:
    return [dict(recon["root"])]


def search_f1_continuation(
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
        initial_roots=f1_continuation_root(recon),
        cost_ceiling=CANDIDATE_CEILING,
        incumbent_by_rows={},
        max_unique=max_unique,
        time_limit_s=time_limit_s,
        rss_abort_mb=rss_abort_mb,
        portfolio_width=portfolio_width,
    )


def incumbent_epoch_snapshots(opening: SpiderState) -> list:
    actions = parse_moves_file(AUTO_MOVES)
    state = opening.clone()
    g = 0
    deal_n = 0
    out = [snapshot_f1(state, 0)]
    out[0]["label"] = "opening"
    for action in actions:
        if is_deal(action):
            deal_n += 1
        from spider.research_actions import step_cost

        cost = 1 if is_deal(action) else step_cost(state, action)
        apply_action(state, action)
        g += cost
        if is_deal(action):
            snap = snapshot_f1(state, g)
            snap["label"] = f"post-SD{deal_n}"
            out.append(snap)
    snap = snapshot_f1(state, g)
    snap["label"] = "solved"
    out.append(snap)
    return out


def choose_f1_verdict(p: dict) -> Tuple[str, str]:
    if p.get("provenance_fail"):
        return "HEALTHY_F1_PROVENANCE_FAILURE", "exact F1 path/state could not be verified"
    if p.get("accounting_fail") or (p.get("solved") and not p.get("replay_ok")):
        return "HEALTHY_F1_CONTRACT_FAILURE", "replay, identity or accounting failed"
    inc = int(p.get("incumbent_g") or INCUMBENT_G)
    best = p.get("solution_g")
    if p.get("solved") and p.get("replay_ok") and best is not None and int(best) < inc:
        return "HEALTHY_F1_CONTINUATION_COST_IMPROVED", f"lineage solved at g={best}"
    if p.get("lineage_lost"):
        return "HEALTHY_F1_LINEAGE_LOST_BY_PORTFOLIO", "F1 descendants discarded despite attractive structure"
    max_f = int(p.get("max_foundations") or 1)
    rows_reached = p.get("min_stock_rows_reached")
    if max_f >= 3 or (rows_reached is not None and int(rows_reached) == 0):
        remaining = None if best is None else inc - 1 - int(p.get("best_post_stock_g") or best or inc)
        if p.get("late_cost_failure"):
            return "HEALTHY_F1_LINEAGE_LATE_COST_FAILURE", "lineage survived but later states exceed budget 197"
        return "HEALTHY_F1_LINEAGE_REACHES_DEEP_ENDGAME", f"descendants reached F={max_f} / rows={rows_reached}"
    if p.get("late_cost_failure"):
        return "HEALTHY_F1_LINEAGE_LATE_COST_FAILURE", "continuation remaining cost exceeds 197"
    return "HEALTHY_F1_LINEAGE_LATE_COST_FAILURE", "no sub-198 terminal from the F1 lineage"
