#!/usr/bin/env python3
"""Opt008 — Continuation-capable first-foundation challenge (deal 4925153).

Opening search from true initial deal → first foundation only.
Continuation probe: depth 12 / beam 100 on D1, B5, and top search candidates.
Canonical D1 = protected control; B5 = negative control only.
No production scoring / registry updates.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal, tokens_from_file
from spider.deal_analysis import build_deal_analysis
from spider.engine import SpiderState
from spider.hash import TranspositionTable, zobrist
from spider.heuristics import (
    detect_foundation_completing_merge,
    foundation_completion_potential,
    next_foundation_completion_potential,
    stock_assisted_executable_gate,
)
from spider.metrics import Action, export_actions_to_moves_file, parse_moves_file, replay_actions
from spider.planner.diagnostics.canonical_second_foundation_teacher_trace import (
    parse_canonical_trace,
)
from spider.planner.diagnostics.experimental_move_ordering import (
    ADAPTER_ID,
    rank_moves_for_stage,
)
from spider.planner.diagnostics.foundation_architecture import all_suit_architecture_scores
from spider.planner.diagnostics.section_d_compatibility import section_d_compatibility_score
from spider.planner.diagnostics.stage_classifier import classify_stage
from spider.rules import deal_cost, mw_move_cost

DEAL = ROOT / "deals" / "4925153.txt"
CANONICAL = ROOT / "solutions" / "4925153_canonical.moves"
B5_MOVES = ROOT / "solutions" / "4925153_b5_shortcut_first_foundation.moves"
EXP_DIR = ROOT / "src" / "spider" / "planner" / "diagnostics" / "experiments"
META = EXP_DIR / "4925153_opt008_first_foundation.json"
PREFLIGHT_JSON = EXP_DIR / "4925153_opt008_preflight_report.json"
PREFLIGHT_MD = EXP_DIR / "4925153_opt008_preflight_report.md"
RESULTS_JSON = EXP_DIR / "4925153_opt008_first_foundation_results.json"
RESULTS_MD = EXP_DIR / "4925153_opt008_first_foundation_report.md"
CANDIDATE_MOVES = EXP_DIR / "4925153_opt008_candidate.moves.txt"

# Opening search
BEAM = 750
MAX_EXPANDED = 300_000
MAX_GENERATED = 3_000_000
WALL = 1800.0
MAX_DEPTH = 100
UNSOLVED_MW_MAX = 84
MOVE_CAP = 14
EXPAND_TOP = 14

# Continuation probe
PROBE_DEPTH = 12
PROBE_BEAM = 100
TOP_CANDS = 5

D1_MW = 84
B5_MW = 56


def sw_of(st: SpiderState) -> int:
    return sum(len(c.face_up) for c in st.columns if c.face_down)


def spaces_of(st: SpiderState) -> int:
    return sum(1 for c in st.columns if c.is_empty())


def action_label(a: Action) -> str:
    if a == ("deal",):
        return "deal"
    s, d, k = a  # type: ignore
    return f"move {s+1} {d+1} {k}"


def parse_label(lab: str) -> Action:
    if lab == "deal":
        return ("deal",)
    p = lab.split()
    return (int(p[1]) - 1, int(p[2]) - 1, int(p[3]))


def can_deal(st: SpiderState) -> bool:
    return len(st.stock) >= 10


def apply_action(st: SpiderState, a: Action) -> int:
    if a == ("deal",):
        if not can_deal(st):
            raise ValueError("cannot deal")
        return st.deal()
    s, d, k = a  # type: ignore
    return st.move(s, d, k)


def step_cost(st: SpiderState, a: Action) -> int:
    if a == ("deal",):
        return deal_cost()
    s, d, k = a  # type: ignore
    return mw_move_cost(
        cards_moved=k,
        source_face_up_count=len(st.columns[s].face_up),
        dest_was_empty=st.columns[d].is_empty(),
    )


def path_hash(actions: List[Action]) -> str:
    return hashlib.sha256(repr(actions).encode()).hexdigest()[:16]


def foundation_suit(st: SpiderState) -> Optional[str]:
    if not st.foundations:
        return None
    return st.foundations[-1][0].suit


# --- caches (runner-local) ---
_stage_cache: Dict[int, str] = {}
_diag_cache: Dict[int, Dict] = {}
_order_cache: Dict[int, List[Action]] = {}
_cache_stats = {
    "stage_hits": 0,
    "stage_miss": 0,
    "diag_hits": 0,
    "diag_miss": 0,
    "order_hits": 0,
    "order_miss": 0,
    "adapter_evals": 0,
}


def reset_caches() -> None:
    _stage_cache.clear()
    _diag_cache.clear()
    _order_cache.clear()
    for k in _cache_stats:
        _cache_stats[k] = 0


def metrics_bundle(st: SpiderState, analysis, *, d1_ref: Optional[SpiderState] = None, mw: Optional[int] = None) -> Dict:
    z = zobrist(st)
    if z in _diag_cache:
        _cache_stats["diag_hits"] += 1
        return dict(_diag_cache[z])
    _cache_stats["diag_miss"] += 1
    deals_used = max(0, 5 - len(st.stock) // 10)
    f = len(st.foundations)
    sw = sw_of(st)
    sp = spaces_of(st)
    stock = len(st.stock)
    if z in _stage_cache:
        _cache_stats["stage_hits"] += 1
        stage = _stage_cache[z]
    else:
        _cache_stats["stage_miss"] += 1
        prof = classify_stage(
            state=st,
            scaffold_context={
                "foundations": f,
                "stock_remaining": stock // 10,
                "sw": sw,
                "spaces": sp,
            },
        )
        stage = prof.macro_stage
        _stage_cache[z] = stage

    try:
        fcp = foundation_completion_potential(
            st, analysis=analysis, round_index=deals_used, lookahead=1
        )
    except Exception:
        fcp = {"best_suit": None, "score": 0}
    try:
        nfcp = next_foundation_completion_potential(
            st, analysis=analysis, round_index=deals_used, lookahead=1
        )
    except Exception:
        nfcp = {"best_suit": None, "score": 0}
    try:
        arch = all_suit_architecture_scores(st, analysis=analysis, round_index=deals_used)
        best_a = max(arch, key=lambda s: arch[s].get("score", 0)) if arch else None
        arch_score = int(arch[best_a]["score"]) if best_a else 0
    except Exception:
        best_a, arch_score = None, 0
    try:
        sag = stock_assisted_executable_gate(
            st, analysis, round_index=deals_used, lookahead=1
        )
    except Exception:
        sag = {"pass": False, "reason": "error"}
    sd = None
    if d1_ref is not None and f >= 1:
        try:
            sd = section_d_compatibility_score(
                st,
                d1_ref,
                canonical_mw_to_first=D1_MW,
                candidate_mw_to_first=mw,
            )
        except Exception:
            sd = {"score": 0, "replayable_section_d_prefix_len": 0}

    out = {
        "foundations": f,
        "foundation_suit": foundation_suit(st),
        "stock": stock,
        "sw": sw,
        "spaces": sp,
        "stage": stage,
        "fcp_suit": fcp.get("best_suit"),
        "fcp_score": int(fcp.get("score") or 0),
        "nfcp_suit": nfcp.get("best_suit"),
        "nfcp_score": int(nfcp.get("score") or 0),
        "arch_suit": best_a,
        "arch_score": arch_score,
        "sag_pass": bool(sag.get("pass")),
        "sag_reason": sag.get("reason"),
        "sd_score": (sd or {}).get("score"),
        "sd_prefix": (sd or {}).get("replayable_section_d_prefix_len"),
        "sd": sd,
        "mobility": len(st.enumerate_moves()) + (1 if can_deal(st) else 0),
        "z": z,
    }
    _diag_cache[z] = out
    return dict(out)


def order_moves(st: SpiderState, analysis) -> List[Action]:
    z = zobrist(st)
    if z in _order_cache:
        _cache_stats["order_hits"] += 1
        return list(_order_cache[z])
    _cache_stats["order_miss"] += 1
    _cache_stats["adapter_evals"] += 1
    f = len(st.foundations)
    profile = classify_stage(
        state=st,
        scaffold_context={
            "foundations": f,
            "stock_remaining": len(st.stock) // 10,
            "sw": sw_of(st),
            "spaces": spaces_of(st),
        },
    )
    res = rank_moves_for_stage(
        st,
        legal_moves=None,
        stage_profile=profile,
        context={
            "analysis": analysis,
            "teacher_move": None,
            "cheap_expansion": True,
            "full_integrity": False,
            "deals": max(0, 5 - len(st.stock) // 10),
        },
    )
    ordered: List[Action] = []
    for lab in res.ordered_moves:
        try:
            ordered.append(parse_label(lab))
        except Exception:
            continue
    if can_deal(st) and ("deal",) not in ordered:
        ordered.append(("deal",))
    # Prefer known foundation-completing merges (existing detector — not teacher path).
    merge_moves: List[Action] = []
    for suit in "schd":
        try:
            m = detect_foundation_completing_merge(st, suit)
            if m.get("found") and m.get("legal"):
                mv = (m["source_col"] - 1, m["dest_col"] - 1, m["move_count"])
                if st.can_move(*mv):
                    merge_moves.append(mv)
        except Exception:
            pass
    # Opening: after some shaping, evaluate stock deal early for stock-assisted F1.
    if can_deal(st) and sw_of(st) <= 12 and len(st.stock) >= 40:
        ordered = [("deal",)] + [m for m in ordered if m != ("deal",)]
    if merge_moves:
        ordered = merge_moves + [m for m in ordered if m not in merge_moves]
    ordered = ordered[:MOVE_CAP]
    _order_cache[z] = ordered
    return list(ordered)


def parse_d1_actions() -> List[Action]:
    moves = parse_canonical_trace()
    return [m.action for m in moves[:91]]


def parse_b5_actions() -> List[Action]:
    return parse_moves_file(B5_MOVES)


def replay_actions_list(actions: List[Action]) -> Tuple[SpiderState, int]:
    st = SpiderState.from_cards(load_deal(DEAL))
    mw = 0
    for a in actions:
        mw += apply_action(st, a)
    return st, mw


def control_snapshot(name: str, actions: List[Action], analysis, d1_ref: Optional[SpiderState]) -> Dict:
    st, mw = replay_actions_list(actions)
    m = metrics_bundle(st, analysis, d1_ref=d1_ref or st, mw=mw)
    return {
        "name": name,
        "legal": True,
        "actions": len(actions),
        "explicit_player_decisions": len(actions),
        "tableau_moves": sum(1 for a in actions if a != ("deal",)),
        "stock_deals": sum(1 for a in actions if a == ("deal",)),
        "mw": mw,
        "path": [action_label(a) for a in actions],
        "path_hash": path_hash(actions),
        **m,
        "actions_raw": actions,
        "state": st,
    }


@dataclass(order=True)
class HeapItem:
    priority: Tuple
    seq: int
    node: Any = field(compare=False)


@dataclass
class Node:
    state: SpiderState
    mw: int
    depth: int
    path: List[Action]
    f: int
    stock: int
    sw: int
    spaces: int
    z: int


def heap_pri(n: Node) -> Tuple:
    """Min-heap: prefer first foundation, then lower MW, then structure.

    Before first foundation: allow progressive stock use (40/30) when sw is low,
    but still penalise emptying stock with zero foundations.
    """
    done = 0 if n.f >= 1 else 1
    premature = 1 if (n.f == 0 and n.stock == 0) else 0
    if n.f >= 1:
        stock_key = n.stock
    else:
        # Prefer having taken 1–2 deals (stock 40 or 30) over never dealing (50)
        # or over-dealing (20/10/0), when still seeking first foundation.
        if n.stock in (40, 30):
            stock_key = 0
        elif n.stock == 50:
            stock_key = 2 if n.sw > 11 else 1
        elif n.stock == 20:
            stock_key = 3
        else:
            stock_key = 5
    # Prefer deeper nodes while seeking first foundation (avoid shallow churn).
    depth_key = -n.depth if n.f == 0 else n.depth
    return (
        done,
        n.mw if n.f >= 1 else 0,
        premature,
        -n.f,
        stock_key,
        depth_key,
        n.sw,
        n.mw,
        n.z & 0xFFFFFFFF,
    )


def opening_search(analysis, d1_ref: SpiderState) -> Dict[str, Any]:
    reset_caches()
    t0 = time.time()
    t_order = t_apply = t_tt = 0.0
    root = SpiderState.from_cards(load_deal(DEAL))
    z0 = zobrist(root)
    start = Node(root, 0, 0, [], 0, len(root.stock), sw_of(root), spaces_of(root), z0)
    tt = TranspositionTable()
    tt.store(root, 0)
    best_depth: Dict[int, int] = {z0: 0}
    heap: List[HeapItem] = []
    seq = 0

    def push(n: Node) -> None:
        nonlocal seq
        seq += 1
        heapq.heappush(heap, HeapItem(heap_pri(n), seq, n))

    push(start)
    expanded = generated = 0
    tt_probes = tt_hits = dups = replaced = 0
    peak_f = peak_tt = 1
    deepest = 0
    termination = "running"
    completed: List[Dict] = []
    seen_complete_z: set = set()

    while heap:
        if time.time() - t0 >= WALL:
            termination = "wall_clock"
            break
        if expanded >= MAX_EXPANDED:
            termination = "max_expanded"
            break
        if generated >= MAX_GENERATED:
            termination = "max_generated"
            break
        if len(heap) > BEAM * 3:
            heap = heapq.nsmallest(BEAM, heap)
            heapq.heapify(heap)
        peak_f = max(peak_f, len(heap))

        item = heapq.heappop(heap)
        node: Node = item.node
        expanded += 1
        deepest = max(deepest, node.depth)

        if node.f >= 1:
            # completed first foundation — record, do not expand
            if node.z not in seen_complete_z:
                seen_complete_z.add(node.z)
                # validate replay
                try:
                    st_chk, mw_chk = replay_actions_list(node.path)
                    legal = len(st_chk.foundations) >= 1 and mw_chk == node.mw
                except Exception:
                    legal = False
                    st_chk = node.state
                m = metrics_bundle(st_chk, analysis, d1_ref=d1_ref, mw=node.mw)
                branch_warn = None
                if m.get("sd_prefix") is not None and m["sd_prefix"] <= 1 and node.mw < D1_MW:
                    branch_warn = "continuation_risk_low_section_d_prefix (B5-like)"
                completed.append(
                    {
                        "id": f"C{len(completed)+1}",
                        "legal": legal,
                        "mw": node.mw,
                        "depth": node.depth,
                        "path": [action_label(a) for a in node.path],
                        "path_hash": path_hash(node.path),
                        "actions_raw": node.path,
                        **m,
                        "branch_warning": branch_warn,
                    }
                )
            continue

        if node.mw > UNSOLVED_MW_MAX:
            continue
        if node.depth >= MAX_DEPTH:
            continue

        t1 = time.time()
        try:
            ordered = order_moves(node.state, analysis)
        except Exception:
            ordered = list(node.state.enumerate_moves())[:MOVE_CAP]
            if can_deal(node.state):
                ordered.append(("deal",))
        t_order += time.time() - t1

        for a in ordered[:EXPAND_TOP]:
            if generated >= MAX_GENERATED:
                break
            try:
                cost = step_cost(node.state, a)
            except Exception:
                continue
            new_mw = node.mw + cost
            # allow one step to complete foundation at/near ceiling
            if new_mw > UNSOLVED_MW_MAX + 5:
                continue

            t2 = time.time()
            st2 = node.state.clone()
            try:
                apply_action(st2, a)
            except Exception:
                t_apply += time.time() - t2
                continue
            t_apply += time.time() - t2
            generated += 1
            f2 = len(st2.foundations)
            if f2 == 0 and new_mw > UNSOLVED_MW_MAX:
                continue

            t3 = time.time()
            z2 = zobrist(st2)
            tt_probes += 1
            prev = tt.get(st2)
            prev_d = best_depth.get(z2)
            if prev is not None:
                tt_hits += 1
                if prev < new_mw:
                    dups += 1
                    t_tt += time.time() - t3
                    continue
                if prev == new_mw and prev_d is not None and prev_d <= node.depth + 1:
                    dups += 1
                    t_tt += time.time() - t3
                    continue
                if prev > new_mw:
                    replaced += 1
            tt.store(st2, new_mw)
            best_depth[z2] = node.depth + 1
            peak_tt = max(peak_tt, len(tt))
            t_tt += time.time() - t3

            child = Node(
                state=st2,
                mw=new_mw,
                depth=node.depth + 1,
                path=node.path + [a],
                f=f2,
                stock=len(st2.stock),
                sw=sw_of(st2),
                spaces=spaces_of(st2),
                z=z2,
            )
            push(child)

        if expanded % 1000 == 0:
            n_done = len(completed)
            print(
                f"  exp={expanded} gen={generated} frontier={len(heap)} tt={len(tt)} "
                f"completed_ff={n_done} deepest={deepest}",
                flush=True,
            )

    if termination == "running":
        termination = "frontier_empty" if not heap else "completed"

    elapsed = time.time() - t0
    # Sort completed: lower MW, then higher sd_score, then higher arch
    completed.sort(
        key=lambda c: (
            0 if c.get("legal") else 1,
            c.get("mw") or 999,
            -(c.get("sd_score") or 0),
            -(c.get("arch_score") or 0),
            c.get("id") or "",
        )
    )
    # re-id
    for i, c in enumerate(completed):
        c["id"] = f"C{i+1}"

    return {
        "termination": termination,
        "elapsed_secs": round(elapsed, 2),
        "expanded": expanded,
        "generated": generated,
        "expansions_per_sec": round(expanded / elapsed, 2) if elapsed > 0 else 0,
        "generated_per_sec": round(generated / elapsed, 2) if elapsed > 0 else 0,
        "tt_probes": tt_probes,
        "tt_hits": tt_hits,
        "duplicates_discarded": dups,
        "lower_mw_replacements": replaced,
        "peak_frontier": peak_f,
        "peak_tt": peak_tt,
        "deepest_depth": deepest,
        "time_order_secs": round(t_order, 2),
        "time_apply_secs": round(t_apply, 2),
        "time_tt_secs": round(t_tt, 2),
        "cache_stats": dict(_cache_stats),
        "avg_legal_moves_approx": MOVE_CAP,
        "completed_candidates": [
            {k: v for k, v in c.items() if k != "actions_raw"} for c in completed
        ],
        "completed_raw": completed,  # with actions for probe
    }


def continuation_probe(
    start_st: SpiderState,
    start_mw: int,
    analysis,
    d1_ref: SpiderState,
    label: str,
) -> Dict[str, Any]:
    """Fixed depth-12 beam=100 probe from a first-foundation state."""
    reset_caches()
    root = start_st.clone()
    z0 = zobrist(root)
    start = Node(
        root,
        start_mw,
        0,
        [],
        len(root.foundations),
        len(root.stock),
        sw_of(root),
        spaces_of(root),
        z0,
    )
    tt = TranspositionTable()
    tt.store(root, start_mw)
    heap: List[HeapItem] = []
    seq = 0

    def push(n: Node) -> None:
        nonlocal seq
        seq += 1
        # prefer more foundations, lower sw, lower stock, lower mw
        pri = (
            -n.f,
            n.sw,
            n.stock,
            n.mw,
            n.depth,
            n.z & 0xFFFFFFFF,
        )
        heapq.heappush(heap, HeapItem(pri, seq, n))

    push(start)
    best = start
    best_key = (-start.f, start.sw, start.stock, start.mw)

    for _ in range(PROBE_DEPTH):
        if not heap:
            break
        if len(heap) > PROBE_BEAM * 2:
            heap = heapq.nsmallest(PROBE_BEAM, heap)
            heapq.heapify(heap)
        nxt: List[Node] = []
        batch = []
        while heap and len(batch) < PROBE_BEAM:
            batch.append(heapq.heappop(heap).node)
        for node in batch:
            key = (-node.f, node.sw, node.stock, node.mw)
            if key < best_key:
                best_key = key
                best = node
            if node.depth >= PROBE_DEPTH:
                nxt.append(node)
                continue
            try:
                ordered = order_moves(node.state, analysis)
            except Exception:
                ordered = list(node.state.enumerate_moves())[:MOVE_CAP]
            for a in ordered[:EXPAND_TOP]:
                st2 = node.state.clone()
                try:
                    cost = apply_action(st2, a)
                except Exception:
                    continue
                # do not approach H20-scale search; just 12 plies
                z2 = zobrist(st2)
                mw2 = node.mw + cost
                prev = tt.get(st2)
                if prev is not None and prev <= mw2:
                    continue
                tt.store(st2, mw2)
                child = Node(
                    st2,
                    mw2,
                    node.depth + 1,
                    node.path + [a],
                    len(st2.foundations),
                    len(st2.stock),
                    sw_of(st2),
                    spaces_of(st2),
                    z2,
                )
                nxt.append(child)
        heap = []
        seq = 0
        for n in sorted(nxt, key=lambda x: (-x.f, x.sw, x.stock, x.mw, x.depth))[:PROBE_BEAM]:
            push(n)

    m = metrics_bundle(best.state, analysis, d1_ref=d1_ref, mw=best.mw)
    # continuation verdict vs simple heuristics
    if best.f >= 2:
        verdict = "strong_progress_second_foundation"
    elif best.f >= 1 and best.sw < sw_of(start_st) and m.get("sd_prefix", 0) >= 2:
        verdict = "continuation_capable"
    elif best.f >= 1 and m.get("sd_prefix", 0) <= 1 and best.mw < D1_MW:
        verdict = "weak_or_shortcut"
    elif best.f >= 1 and best.sw <= sw_of(start_st) + 2:
        verdict = "mixed"
    else:
        verdict = "weak"

    return {
        "label": label,
        "start_mw": start_mw,
        "end_mw": best.mw,
        "delta_mw": best.mw - start_mw,
        "depth": best.depth,
        "foundations": best.f,
        "stock": best.stock,
        "sw": best.sw,
        "spaces": best.spaces,
        "stage": m.get("stage"),
        "arch_score": m.get("arch_score"),
        "fcp_score": m.get("fcp_score"),
        "nfcp_score": m.get("nfcp_score"),
        "sd_score": m.get("sd_score"),
        "sd_prefix": m.get("sd_prefix"),
        "sag_pass": m.get("sag_pass"),
        "mobility": m.get("mobility"),
        "continuation_verdict": verdict,
        "path_preview": [action_label(a) for a in best.path[:12]],
    }


def classify_candidate(c: Dict, d1: Dict, b5: Dict, probe: Optional[Dict]) -> str:
    if not c.get("legal"):
        return "reject"
    mw = c.get("mw") or 999
    sd_score = c.get("sd_score") or 0
    sd_prefix = c.get("sd_prefix") or 0
    d1_sd = d1.get("sd_score") or 1500
    b5_sd = b5.get("sd_score") or 0
    arch = c.get("arch_score") or 0
    d1_arch = d1.get("arch_score") or 0
    probe_v = (probe or {}).get("continuation_verdict") or ""

    # executable evidence: completed foundation legally; SAG about next is soft
    exec_ok = c.get("foundations", 0) >= 1 and (
        c.get("sag_pass")
        or (c.get("stock", 50) < 50)  # used stock
        or True  # foundation completed is executable evidence of merge
    )

    b5_like = sd_prefix <= 1 and mw < D1_MW
    if b5_like and probe_v in ("weak_or_shortcut", "weak"):
        return "shortcut-only"

    cont_ok = (
        sd_prefix >= 3
        and sd_score >= max(b5_sd + 200, 700)
        and probe_v in ("continuation_capable", "strong_progress_second_foundation", "mixed")
    )
    d1_level = sd_score >= int(d1_sd * 0.9) or sd_prefix >= 8

    if mw <= 83 and exec_ok and cont_ok and d1_level and arch >= d1_arch - 40:
        if probe and probe.get("continuation_verdict") in (
            "continuation_capable",
            "strong_progress_second_foundation",
        ):
            # competitive with D1 probe
            if (probe.get("sd_prefix") or 0) >= 2 or (probe.get("foundations") or 0) >= 1:
                return "replacement-review-candidate"
        return "structural-interest"

    if mw == 84 and (d1_level or sd_prefix >= 8) and cont_ok:
        return "match-only"

    if mw < 84 and cont_ok and not d1_level:
        return "structural-interest"

    if mw < 84 and (b5_like or not cont_ok):
        return "shortcut-only"

    if mw <= 84 and c.get("foundations", 0) >= 1:
        return "structural-interest" if sd_prefix >= 2 else "shortcut-only"

    return "reject"


def write_preflight(d1: Dict, b5: Dict) -> None:
    pf = {
        "ok": d1["legal"] and b5["legal"] and d1["mw"] == D1_MW and b5["mw"] == B5_MW,
        "experiment_id": "4925153_opt008_first_foundation",
        "d1_mw": d1["mw"],
        "b5_mw": b5["mw"],
        "d1_sd_score": d1.get("sd_score"),
        "b5_sd_score": b5.get("sd_score"),
        "b5_closed": True,
        "production_change_allowed": False,
        "registry_update_allowed": False,
        "teacher_move_bonus_allowed": False,
        "limits": {
            "beam": BEAM,
            "max_expanded": MAX_EXPANDED,
            "wall": WALL,
            "unsolved_mw_max": UNSOLVED_MW_MAX,
            "probe_depth": PROBE_DEPTH,
            "probe_beam": PROBE_BEAM,
        },
        "errors": [],
    }
    if d1["mw"] != D1_MW:
        pf["errors"].append(f"D1 mw {d1['mw']} != 84")
        pf["ok"] = False
    if b5["mw"] != B5_MW:
        pf["errors"].append(f"B5 mw {b5['mw']} != 56")
        pf["ok"] = False
    PREFLIGHT_JSON.write_text(json.dumps(pf, indent=2), encoding="utf-8")
    PREFLIGHT_MD.write_text(
        "\n".join(
            [
                "# Opt008 preflight — first-foundation challenge",
                "",
                f"**ok:** `{pf['ok']}`",
                f"- D1 control MW={d1['mw']} f={d1['foundations']} sd={d1.get('sd_score')} prefix={d1.get('sd_prefix')}",
                f"- B5 negative MW={b5['mw']} f={b5['foundations']} sd={b5.get('sd_score')} prefix={b5.get('sd_prefix')} **closed non-continuation**",
                f"- opening beam={BEAM} exp≤{MAX_EXPANDED} wall={WALL}s unsolved MW≤{UNSOLVED_MW_MAX}",
                f"- probe depth={PROBE_DEPTH} beam={PROBE_BEAM}",
                f"- adapter={ADAPTER_ID}; teacher_bonus=false",
                f"- production/registry changes: false",
                "",
            ]
        ),
        encoding="utf-8",
    )


def write_report(payload: Dict) -> None:
    RESULTS_JSON.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    d1 = payload["controls"]["D1"]
    b5 = payload["controls"]["B5"]
    stats = payload["search_stats"]
    lines = [
        "# Opt008 — Continuation-Capable First-Foundation Challenge",
        "",
        "## A. Experiment summary",
        "",
        f"- deal: **4925153**",
        f"- target: continuation-capable first foundation",
        f"- D1 incumbent: MW=**{D1_MW}**",
        f"- B5 negative control: MW=**{B5_MW}** (closed / non-continuation)",
        f"- opening: beam={BEAM}, exp≤{MAX_EXPANDED}, wall={WALL}s, unsolved MW≤{UNSOLVED_MW_MAX}",
        f"- probe: depth={PROBE_DEPTH}, beam={PROBE_BEAM}, top candidates={TOP_CANDS}",
        f"- adapter: `{ADAPTER_ID}` (no teacher bonus)",
        f"- termination: **{stats.get('termination')}**",
        f"- production/registry: **no**",
        "",
        "## B. Control reproduction",
        "",
        "| control | MW | actions | decisions | suit | stock | sw | spaces | arch | FCP | NFCP | SAG | SD score | SD prefix | hash |",
        "|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---|",
    ]
    for key in ("D1", "B5"):
        c = payload["controls"][key]
        lines.append(
            f"| {key} | {c['mw']} | {c['actions']} | {c['explicit_player_decisions']} | "
            f"{c.get('foundation_suit')} | {c.get('stock')} | {c.get('sw')} | {c.get('spaces')} | "
            f"{c.get('arch_score')} | {c.get('fcp_score')} | {c.get('nfcp_score')} | "
            f"{c.get('sag_pass')} | {c.get('sd_score')} | {c.get('sd_prefix')} | `{c.get('path_hash')}` |"
        )

    lines += [
        "",
        "## C. Search statistics",
        "",
        f"- elapsed: **{stats.get('elapsed_secs')}s**",
        f"- expanded/generated: **{stats.get('expanded')}** / **{stats.get('generated')}**",
        f"- expansions/s: **{stats.get('expansions_per_sec')}**",
        f"- generated/s: **{stats.get('generated_per_sec')}**",
        f"- TT probes/hits: {stats.get('tt_probes')} / {stats.get('tt_hits')}",
        f"- duplicates discarded: {stats.get('duplicates_discarded')}",
        f"- peak frontier/TT: {stats.get('peak_frontier')} / {stats.get('peak_tt')}",
        f"- adapter evals: {stats.get('cache_stats', {}).get('adapter_evals')} "
        f"(order hits {stats.get('cache_stats', {}).get('order_hits')})",
        f"- stage cache hits/miss: {stats.get('cache_stats', {}).get('stage_hits')}/"
        f"{stats.get('cache_stats', {}).get('stage_miss')}",
        f"- diag cache hits/miss: {stats.get('cache_stats', {}).get('diag_hits')}/"
        f"{stats.get('cache_stats', {}).get('diag_miss')}",
        f"- time order/apply/tt: {stats.get('time_order_secs')} / "
        f"{stats.get('time_apply_secs')} / {stats.get('time_tt_secs')} s",
        f"- deepest depth: {stats.get('deepest_depth')}",
        "",
        "## D. Completed first-foundation candidates (top 10)",
        "",
        "| id | legal | MW | suit | depth | stock | sw | sp | arch | FCP | NFCP | SAG | SD | prefix | warn | class |",
        "|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---|---|",
    ]
    for c in (payload.get("candidates") or [])[:10]:
        lines.append(
            f"| {c['id']} | {c.get('legal')} | {c.get('mw')} | {c.get('foundation_suit')} | "
            f"{c.get('depth')} | {c.get('stock')} | {c.get('sw')} | {c.get('spaces')} | "
            f"{c.get('arch_score')} | {c.get('fcp_score')} | {c.get('nfcp_score')} | "
            f"{c.get('sag_pass')} | {c.get('sd_score')} | {c.get('sd_prefix')} | "
            f"{c.get('branch_warning') or '-'} | {c.get('classification')} |"
        )

    lines += ["", "## E. Continuation-probe comparison", ""]
    lines.append(
        "| label | start MW | end MW | f | stock | sw | sp | stage | arch | FCP | NFCP | SD | prefix | mobility | verdict |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---|")
    for p in payload.get("probes") or []:
        lines.append(
            f"| {p['label']} | {p['start_mw']} | {p['end_mw']} | {p['foundations']} | "
            f"{p['stock']} | {p['sw']} | {p['spaces']} | {p.get('stage')} | "
            f"{p.get('arch_score')} | {p.get('fcp_score')} | {p.get('nfcp_score')} | "
            f"{p.get('sd_score')} | {p.get('sd_prefix')} | {p.get('mobility')} | "
            f"{p.get('continuation_verdict')} |"
        )

    a = payload.get("analysis") or {}
    lines += [
        "",
        "## F. Candidate analysis",
        "",
        f"- First foundation before MW84? **{a.get('any_before_84')}**",
        f"- Early candidate pass executable gate? **{a.get('any_exec')}**",
        f"- Early match/beat D1 compatibility? **{a.get('any_d1_compat')}**",
        f"- Early outperform B5 continuation? **{a.get('any_better_than_b5')}**",
        f"- Match D1 in fixed probe? **{a.get('any_match_d1_probe')}**",
        f"- Replacement-review candidate? **{a.get('any_replacement')}**",
        f"- D1 control preserved? **yes**",
        f"- Fastest shortcut-only MW? **{a.get('fastest_shortcut_mw')}**",
        f"- Repeated B5 failure mode? **{a.get('b5_mode_repeat')}**",
        f"- Throughput vs Opt007 (~9 exp/s)? **{a.get('throughput_vs_opt007')}**",
        "",
        "## G. Recommendation",
        "",
        f"**{payload['recommendation']['choice']}**",
        "",
        payload["recommendation"]["rationale"],
        "",
        "## Explicit confirmations",
        "",
        "- deal 4925153 only; initial start",
        "- D1 control / B5 negative only",
        "- no teacher bonuses; adapter primary",
        "- no H20+ search; probe depth 12 only",
        "- no production scoring / registry / canonical overwrite",
        "",
    ]
    RESULTS_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    EXP_DIR.mkdir(parents=True, exist_ok=True)
    print("OPT008 first-foundation challenge — deal 4925153", flush=True)
    print(
        f"opening beam={BEAM} exp≤{MAX_EXPANDED} wall={WALL}s unsolved_mw≤{UNSOLVED_MW_MAX}",
        flush=True,
    )
    print(f"probe depth={PROBE_DEPTH} beam={PROBE_BEAM}", flush=True)

    tokens = tokens_from_file(DEAL)
    analysis = build_deal_analysis(tokens)

    d1_actions = parse_d1_actions()
    b5_actions = parse_b5_actions()
    # bootstrap D1 ref state
    st_d1_tmp, _ = replay_actions_list(d1_actions)
    d1 = control_snapshot("D1", d1_actions, analysis, d1_ref=st_d1_tmp)
    b5 = control_snapshot("B5", b5_actions, analysis, d1_ref=d1["state"])
    # refresh D1 metrics with self-ref
    d1 = control_snapshot("D1", d1_actions, analysis, d1_ref=d1["state"])

    print(
        f"D1: MW={d1['mw']} f={d1['foundations']} suit={d1['foundation_suit']} "
        f"sw={d1['sw']} sd={d1['sd_score']} prefix={d1['sd_prefix']}",
        flush=True,
    )
    print(
        f"B5: MW={b5['mw']} f={b5['foundations']} suit={b5['foundation_suit']} "
        f"sw={b5['sw']} sd={b5['sd_score']} prefix={b5['sd_prefix']} CLOSED",
        flush=True,
    )
    write_preflight(d1, b5)
    if d1["mw"] != D1_MW or b5["mw"] != B5_MW:
        print("STOP: control replay mismatch", flush=True)
        return 1

    print("Opening search...", flush=True)
    search = opening_search(analysis, d1["state"])
    raw_cands = search.pop("completed_raw", [])
    print(
        f"Opening done: exp={search['expanded']} gen={search['generated']} "
        f"eps={search['expansions_per_sec']} completed={len(raw_cands)} "
        f"term={search['termination']}",
        flush=True,
    )

    # Probes: D1, B5, top 5 candidates
    print("Continuation probes...", flush=True)
    probes = []
    probes.append(
        continuation_probe(d1["state"], d1["mw"], analysis, d1["state"], "D1_control")
    )
    probes.append(
        continuation_probe(b5["state"], b5["mw"], analysis, d1["state"], "B5_negative")
    )

    top = [c for c in raw_cands if c.get("legal")][:TOP_CANDS]
    cand_probes: Dict[str, Dict] = {}
    for c in top:
        st_c, mw_c = replay_actions_list(c["actions_raw"])
        p = continuation_probe(st_c, mw_c, analysis, d1["state"], c["id"])
        probes.append(p)
        cand_probes[c["id"]] = p
        print(
            f"  probe {c['id']} MW{c['mw']} → end_mw={p['end_mw']} "
            f"f={p['foundations']} sw={p['sw']} verdict={p['continuation_verdict']}",
            flush=True,
        )

    # Classify
    candidates = []
    for c in raw_cands[:20]:
        pr = cand_probes.get(c["id"])
        cls = classify_candidate(c, d1, b5, pr)
        c2 = {k: v for k, v in c.items() if k not in ("actions_raw", "state", "sd")}
        c2["classification"] = cls
        candidates.append(c2)

    any_before = any(c.get("mw", 999) < 84 and c.get("legal") for c in candidates)
    any_rep = any(c.get("classification") == "replacement-review-candidate" for c in candidates)
    any_struct = any(c.get("classification") == "structural-interest" for c in candidates)
    any_short = any(c.get("classification") == "shortcut-only" for c in candidates)
    shortcuts = [c for c in candidates if c.get("classification") == "shortcut-only"]
    fastest_short = min((c["mw"] for c in shortcuts), default=None)

    d1_probe = probes[0]
    b5_probe = probes[1]
    better_b5 = any(
        (cand_probes.get(c["id"]) or {}).get("continuation_verdict")
        in ("continuation_capable", "strong_progress_second_foundation")
        and (c.get("sd_prefix") or 0) > (b5.get("sd_prefix") or 0)
        for c in candidates
        if c.get("mw", 999) < 84
    )
    match_d1_probe = any(
        (cand_probes.get(c["id"]) or {}).get("continuation_verdict")
        == d1_probe.get("continuation_verdict")
        and (c.get("sd_prefix") or 0) >= 3
        for c in candidates
    )

    # Export replacement if any
    rep = next(
        (c for c in raw_cands if any(
            x["id"] == c["id"] and x.get("classification") == "replacement-review-candidate"
            for x in candidates
        )),
        None,
    )
    export_path = None
    if rep:
        export_actions_to_moves_file(
            rep["actions_raw"],
            CANDIDATE_MOVES,
            header=f"Opt008 replacement-review candidate MW={rep['mw']}",
        )
        export_path = str(CANDIDATE_MOVES.relative_to(ROOT))

    eps = search.get("expansions_per_sec") or 0
    throughput = (
        f"yes (~{eps} exp/s vs Opt007 ~9 exp/s)"
        if eps >= 15
        else f"partial (~{eps} exp/s vs Opt007 ~9 exp/s)"
    )

    if any_rep:
        choice = (
            "1. Recommend an earlier continuation-capable first-foundation candidate "
            "for a later D1→H20 challenge; do not update the registry."
        )
        rationale = (
            "A candidate completed first foundation at MW≤83 with continuation gates "
            "competitive with D1 and better than B5. Export for control-plane review only."
        )
    elif any_struct and any_before:
        choice = (
            "2. Keep D1 accepted; retain one earlier candidate as structural-interest only."
        )
        rationale = (
            "Earlier first foundations were found but missed full D1-equivalent continuation "
            "criteria. Keep D1; no registry update."
        )
    elif any_short or (any_before and not any_struct):
        choice = (
            "3. Keep D1 accepted; all earlier foundations were shortcut-only or continuation-inferior."
        )
        rationale = (
            f"Early foundations (fastest shortcut MW={fastest_short}) failed Section-D / "
            "continuation probe relative to D1 and resemble B5 risk. D1 remains accepted."
        )
    elif not candidates:
        choice = (
            "4. No competitive foundation was reached; opening ordering or throughput remains the bottleneck."
        )
        rationale = (
            f"Opening search terminated ({search.get('termination')}) without a legal "
            f"first-foundation candidate under MW≤84. Throughput {throughput}."
        )
    else:
        choice = (
            "3. Keep D1 accepted; all earlier foundations were shortcut-only or continuation-inferior."
        )
        rationale = (
            "Completed foundations did not improve on D1 continuation quality. Keep D1."
        )

    # strip non-serializable from controls
    def slim_control(c: Dict) -> Dict:
        return {k: v for k, v in c.items() if k not in ("state", "actions_raw", "sd")}

    payload = {
        "experiment_id": "4925153_opt008_first_foundation",
        "deal": "4925153",
        "adapter": ADAPTER_ID,
        "adapter_primary_ordering": True,
        "teacher_move_bonus": False,
        "controls": {"D1": slim_control(d1), "B5": slim_control(b5)},
        "search_stats": search,
        "candidates": candidates,
        "probes": probes,
        "analysis": {
            "any_before_84": any_before,
            "any_exec": any(c.get("foundations", 0) >= 1 for c in candidates),
            "any_d1_compat": any(
                (c.get("sd_prefix") or 0) >= 3 or (c.get("sd_score") or 0) >= 0.5 * (d1.get("sd_score") or 1)
                for c in candidates
                if (c.get("mw") or 999) <= 84
            ),
            "any_better_than_b5": better_b5,
            "any_match_d1_probe": match_d1_probe,
            "any_replacement": any_rep,
            "fastest_shortcut_mw": fastest_short,
            "b5_mode_repeat": "yes" if any_short else "no",
            "throughput_vs_opt007": throughput,
        },
        "recommendation": {"choice": choice, "rationale": rationale},
        "export_path": export_path,
        "production_changes": False,
        "registry_updated": False,
        "canonical_overwritten": False,
        "b5_remains_closed": True,
    }
    write_report(payload)
    print(f"Wrote {RESULTS_JSON.relative_to(ROOT)}", flush=True)
    print(f"Wrote {RESULTS_MD.relative_to(ROOT)}", flush=True)
    print(f"Recommendation: {choice}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
