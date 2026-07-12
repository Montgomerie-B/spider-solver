#!/usr/bin/env python3
"""Diagnostic-only foundation-action delta classifier.

Distinguishes cascade-positive exact foundation moves (e.g. J:7→J:8 clubs)
from cascade-negative early exact takes (e.g. greedy hearts at J:11).

Does not alter production scoring.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple, Union

from spider.deal_analysis import DealAnalysis
from spider.engine import SpiderState
from spider.heuristics import (
    detect_foundation_completing_merge,
    next_foundation_completion_potential,
)
from spider.planner.diagnostics.cleanup_cascade import (
    cleanup_cascade_potential,
    foundation_counts,
    remaining_suits,
)
from spider.planner.diagnostics.foundation_architecture import (
    all_suit_architecture_scores,
    foundation_architecture_score,
)

MoveSpec = Union[Tuple[int, int, int], str]


def parse_move(move: MoveSpec) -> Tuple[int, int, int]:
    """Parse 0-based (src,dst,k) or 1-based 'move S D K' string."""
    if isinstance(move, tuple) and len(move) == 3:
        src, dst, k = move
        # Heuristic: if values look 1-based columns (1..10), convert
        if src >= 1 and dst >= 1 and src <= 10 and dst <= 10 and (
            isinstance(src, int) and src > 0
        ):
            # Ambiguous: beam uses 0-based. Prefer explicit string for 1-based.
            return int(src), int(dst), int(k)
        return int(src), int(dst), int(k)
    s = str(move).strip()
    parts = s.split()
    if parts[0] == "move":
        parts = parts[1:]
    src, dst, k = int(parts[0]), int(parts[1]), int(parts[2])
    # 1-based columns in text form
    return src - 1, dst - 1, k


def _spaces(st: SpiderState) -> int:
    return sum(1 for c in st.columns if c.is_empty())


def _sw(st: SpiderState) -> int:
    return sum(len(c.face_up) for c in st.columns if c.face_down)


def _nfcp_best(st: SpiderState, analysis: Optional[DealAnalysis], deals: int) -> Tuple[Optional[str], int]:
    pot = next_foundation_completion_potential(
        st, analysis=analysis, round_index=deals, lookahead=1
    )
    bs = pot.get("best_suit")
    if not bs:
        return None, int(pot.get("score", 0))
    sc = int(pot.get("per_suit", {}).get(bs, {}).get("score", 0))
    return bs, sc


def _arch_best(st: SpiderState, analysis: Optional[DealAnalysis], deals: int) -> Tuple[Optional[str], int]:
    arch = all_suit_architecture_scores(st, analysis=analysis, round_index=deals)
    if not arch:
        # second-copy: also score remaining via counts
        rem = remaining_suits(st)
        best_s, best_sc = None, 0
        for s in rem:
            ar = foundation_architecture_score(st, s, analysis=analysis, round_index=deals)
            if ar.get("score", 0) >= best_sc:
                best_s, best_sc = s, int(ar.get("score", 0))
        return best_s, best_sc
    best_s = max(arch.keys(), key=lambda s: arch[s].get("score", 0))
    # Prefer clubs if tied-ish and remaining
    if "c" in arch and "c" in remaining_suits(st):
        if arch["c"].get("score", 0) >= arch[best_s].get("score", 0) - 5:
            return "c", int(arch["c"].get("score", 0))
    return best_s, int(arch[best_s].get("score", 0))


def _snapshot(
    st: SpiderState,
    analysis: Optional[DealAnalysis],
    deals: int,
    *,
    deep: bool = False,
) -> Dict:
    cc = cleanup_cascade_potential(
        st, analysis, deep_one_move=deep, precise_merge=True
    )
    nfcp_s, nfcp_sc = _nfcp_best(st, analysis, deals)
    arch_s, arch_sc = _arch_best(st, analysis, deals)
    return {
        "foundations": len(st.foundations),
        "foundation_counts": foundation_counts(st),
        "sw": _sw(st),
        "spaces": _spaces(st),
        "stock": len(st.stock),
        "cleanup_score": cc["score"],
        "active": cc["active"],
        "stage": cc["stage"],
        "exact_suits": list(cc["exact_now_suits"]),
        "near_suits": list(cc["near_complete_suits"]),
        "greedy_risk": cc["greedy_risk"],
        "cascade_est": dict(cc["cascade_count_estimate"]),
        "expected_space_gain": cc["expected_space_gain"],
        "nfcp_best": nfcp_s,
        "nfcp_score": nfcp_sc,
        "arch_best": arch_s,
        "arch_score": arch_sc,
        "cleanup": cc,
    }


def estimate_reachable_foundations(
    state: SpiderState,
    *,
    horizon: int = 5,
    move_cap: int = 12,
    node_cap: int = 80,
) -> Dict[str, int]:
    """Cheap BFS-ish estimate of max foundations within 1/2/5 moves."""
    base_f = len(state.foundations)
    best = {1: base_f, 2: base_f, 5: base_f}
    # Layered expansion
    frontier = [state.clone()]
    seen = set()
    for depth in range(1, horizon + 1):
        nxt = []
        for st in frontier:
            moves = st.enumerate_moves()
            # Prefer longer / empty-dest / foundation-looking
            def prio(m):
                s, d, k = m
                empty = 1 if st.columns[d].is_empty() else 0
                return (-empty, -k)

            moves = sorted(moves, key=prio)[:move_cap]
            for src, dst, k in moves:
                sim = st.clone()
                try:
                    sim.move(src, dst, k)
                except Exception:
                    continue
                key = (len(sim.foundations), tuple(str(c.top()) for c in sim.columns))
                if key in seen:
                    continue
                seen.add(key)
                f = len(sim.foundations)
                if depth <= 1:
                    best[1] = max(best[1], f)
                if depth <= 2:
                    best[2] = max(best[2], f)
                if depth <= 5:
                    best[5] = max(best[5], f)
                nxt.append(sim)
                if len(nxt) >= node_cap:
                    break
            if len(nxt) >= node_cap:
                break
        frontier = nxt[:node_cap]
        if not frontier:
            break
    return {
        "within_1": best[1] - base_f,
        "within_2": best[2] - base_f,
        "within_5": best[5] - base_f,
        "max_foundations_1": best[1],
        "max_foundations_2": best[2],
        "max_foundations_5": best[5],
    }


def classify_foundation_action_delta(
    before: Dict,
    after: Dict,
    *,
    suit_completed: Optional[str] = None,
    reachable_after: Optional[Dict] = None,
) -> Tuple[str, str]:
    """Return (classification, one-sentence explanation)."""
    df = after["foundations"] - before["foundations"]
    d_sp = after["spaces"] - before["spaces"]
    d_sw = after["sw"] - before["sw"]
    d_cl = after["cleanup_score"] - before["cleanup_score"]
    before_exact = set(before["exact_suits"])
    after_exact = set(after["exact_suits"])
    before_near = set(before["near_suits"])
    after_near = set(after["near_suits"])
    # Near suits excluding the one just completed (copy may still remain)
    multi_exact_after = len(after_exact) >= 2
    multi_near_before = len(before_near) >= 3 or (
        len(before_near) >= 2 and len(before_exact) >= 1
    )
    stage_after = after["stage"]
    stage_before = before["stage"]

    # Firing: multi-exact before or after, or stage already cascade_firing
    # (multi-exact means cascade is ready to fire — not greedy risk)
    if (
        multi_exact_after
        or len(before_exact) >= 2
        or stage_before == "cascade_firing"
        or stage_after == "cascade_firing"
        or after["foundations"] >= 6
    ):
        return (
            "cascade-firing",
            f"Foundation +{df} in multi-exact/firing regime "
            f"(exact {sorted(before_exact)}→{sorted(after_exact)}); take foundations now.",
        )

    near_loss = len(before_near - after_near - ({suit_completed} if suit_completed else set()))
    space_gain_good = d_sp >= 2
    space_gain_ok = d_sp >= 1
    cleanup_ok = d_cl >= -300
    cleanup_good = d_cl >= -100 or after["cleanup_score"] >= before["cleanup_score"]
    other_near = before_near - before_exact
    other_near_and_partners = before_near - ({suit_completed} if suit_completed else set())
    # Staging partners: near/exact suits that are NOT the one being completed
    staging_partners = sorted(
        (before_near | before_exact) - ({suit_completed} if suit_completed else set())
        - before_exact  # partners are non-exact near suits
    )
    # Prefer: non-exact near suits as staging partners
    staging_partners = sorted(before_near - before_exact)

    # --- Cascade-negative BEFORE generic space-gain positive ---
    # J:11 hearts: greedy_risk + single exact + multiple other near suits still staging.
    # Even if spaces rise, taking the only exact foundation while 2+ other suits are
    # near-complete consumes the staging window (canonical delays hearts to J:21-22).
    if df >= 1 and before["greedy_risk"] and len(before_exact) == 1:
        if len(staging_partners) >= 2:
            # Exception: completing the *first* third foundation (f 2→3) with +spaces
            # is usually cascade-positive (J:7→J:8 clubs), not greedy-negative.
            third_foundation_setup = before["foundations"] == 2 and after["foundations"] >= 3
            if third_foundation_setup and space_gain_ok:
                pass  # fall through to positive checks
            else:
                return (
                    "cascade-negative",
                    f"Exact {suit_completed or sorted(before_exact)} under greedy_risk while "
                    f"staging partners {staging_partners} remain near-complete; "
                    f"canonical-style multi-suit staging should continue "
                    f"(Δspaces={d_sp}, Δcleanup={d_cl}).",
                )
        if len(staging_partners) >= 1 and d_cl < -150 and after["foundations"] >= 3:
            # Mild negative: one partner + large cleanup drop after third already secured
            if not (before["foundations"] == 2 and space_gain_good):
                return (
                    "cascade-negative",
                    f"Exact completion under greedy_risk with partner {staging_partners} "
                    f"and cleanup drop {d_cl}; likely early relative to cascade staging.",
                )

    # Cascade-positive: third-foundation setup (f2→3) with space gain — J:7→J:8 pattern
    if (
        df >= 1
        and before["foundations"] == 2
        and after["foundations"] >= 3
        and space_gain_ok
    ):
        return (
            "cascade-positive",
            f"Exact {suit_completed or 'suit'} third-foundation completion opens +{d_sp} "
            f"spaces (cleanup {before['cleanup_score']}→{after['cleanup_score']}); "
            f"cascade-positive setup move.",
        )

    # Strong positive: foundation + spaces up without greedy multi-suit conflict
    if df >= 1 and space_gain_good and after["foundations"] >= 3 and not (
        before["greedy_risk"] and len(staging_partners) >= 2
    ):
        return (
            "cascade-positive",
            f"Exact foundation +{df} opens +{d_sp} spaces and advances cascade staging "
            f"(cleanup {before['cleanup_score']}→{after['cleanup_score']}).",
        )

    if df >= 1 and space_gain_ok and cleanup_ok and not (
        before["greedy_risk"] and len(staging_partners) >= 2
    ):
        if after["stage"] in ("cascade_staging", "cascade_active", "cleanup_active", "cascade_firing"):
            return (
                "cascade-positive",
                f"Exact {suit_completed or 'suit'} completion is cascade-positive: "
                f"+{d_sp} spaces, stage {stage_before}→{stage_after}.",
            )

    # Acceptable: foundation progress without strong positive or negative signal
    if df >= 1:
        if cleanup_good or space_gain_ok:
            return (
                "cascade-acceptable",
                f"Exact foundation +{df} is acceptable (Δspaces={d_sp}, Δcleanup={d_cl}, "
                f"stage {stage_after}); not strongly positive or greedy-negative.",
            )
        return (
            "cascade-acceptable",
            f"Exact foundation +{df} with mixed cascade delta (Δspaces={d_sp}, "
            f"Δcleanup={d_cl}); allow but do not dominate search.",
        )

    # Non-foundation move (shouldn't happen for this tool's primary use)
    if d_cl > 50 and d_sp >= 0:
        return (
            "cascade-positive",
            f"Non-foundation move improves cleanup by {d_cl} (spaces {d_sp}).",
        )
    if d_cl < -100:
        return (
            "cascade-negative",
            f"Move worsens cleanup by {-d_cl} without clear cascade gain.",
        )
    return (
        "cascade-acceptable",
        f"Neutral cascade delta (Δcleanup={d_cl}, Δspaces={d_sp}).",
    )


def foundation_action_delta(
    state: SpiderState,
    move: MoveSpec,
    *,
    analysis: Optional[DealAnalysis] = None,
    deals: int = 5,
    estimate_horizon: bool = True,
    one_based_move_tuple: bool = False,
) -> Dict:
    """Compute before/after deltas for a candidate exact-foundation (or any) move.

    ``move``: 0-based (src,dst,k) by default, or ``\"move S D K\"`` 1-based string.
    Set ``one_based_move_tuple=True`` if passing 1-based integer tuples.
    """
    if isinstance(move, str) or (
        isinstance(move, tuple) and one_based_move_tuple
    ):
        if isinstance(move, tuple):
            src, dst, k = int(move[0]) - 1, int(move[1]) - 1, int(move[2])
        else:
            src, dst, k = parse_move(move)
    else:
        src, dst, k = int(move[0]), int(move[1]), int(move[2])

    before = _snapshot(state, analysis, deals)
    after_st = state.clone()
    try:
        cost = after_st.move(src, dst, k)
        legal = True
        error = None
    except Exception as exc:
        return {
            "legal": False,
            "error": str(exc),
            "move": f"move {src+1} {dst+1} {k}",
            "classification": "illegal",
            "explanation": f"Illegal move: {exc}",
        }

    after = _snapshot(after_st, analysis, deals)
    suit_completed = None
    if after["foundations"] > before["foundations"]:
        # newly completed suit is last foundation pile
        suit_completed = after_st.foundations[-1][0].suit

    reachable = None
    if estimate_horizon:
        try:
            reachable = estimate_reachable_foundations(after_st, horizon=5)
        except Exception:
            reachable = None

    classification, explanation = classify_foundation_action_delta(
        before, after, suit_completed=suit_completed, reachable_after=reachable
    )

    # Enrich with reachable comparison if available
    reach_before = None
    if estimate_horizon:
        try:
            reach_before = estimate_reachable_foundations(state, horizon=5)
        except Exception:
            pass

    return {
        "legal": legal,
        "move": f"move {src+1} {dst+1} {k}",
        "move_0based": (src, dst, k),
        "mw_cost": cost,
        "suit_completed": suit_completed,
        "before": before,
        "after": after,
        "delta": {
            "foundations": after["foundations"] - before["foundations"],
            "spaces": after["spaces"] - before["spaces"],
            "sw": after["sw"] - before["sw"],
            "cleanup": after["cleanup_score"] - before["cleanup_score"],
            "exact_suits": sorted(set(after["exact_suits"]) - set(before["exact_suits"])),
            "exact_suits_lost": sorted(set(before["exact_suits"]) - set(after["exact_suits"])),
            "near_suits": sorted(set(after["near_suits"]) - set(before["near_suits"])),
            "near_suits_lost": sorted(set(before["near_suits"]) - set(after["near_suits"])),
            "foundation_counts": {
                s: after["foundation_counts"][s] - before["foundation_counts"][s]
                for s in "schd"
            },
        },
        "reachable_before": reach_before,
        "reachable_after": reachable,
        "classification": classification,
        "explanation": explanation,
        "nfcp_before": (before["nfcp_best"], before["nfcp_score"]),
        "nfcp_after": (after["nfcp_best"], after["nfcp_score"]),
        "arch_before": (before["arch_best"], before["arch_score"]),
        "arch_after": (after["arch_best"], after["arch_score"]),
    }


def list_exact_foundation_moves(state: SpiderState) -> List[Dict]:
    """All legal one-move foundation completions (any remaining suit copy)."""
    out = []
    for s in remaining_suits(state):
        m = detect_foundation_completing_merge(state, s)
        if m.get("found") and m.get("legal"):
            out.append(
                {
                    "suit": s,
                    "move": f"move {m['source_col']} {m['dest_col']} {m['move_count']}",
                    "move_0based": (
                        m["source_col"] - 1,
                        m["dest_col"] - 1,
                        m["move_count"],
                    ),
                    "detail": m,
                }
            )
    return out
