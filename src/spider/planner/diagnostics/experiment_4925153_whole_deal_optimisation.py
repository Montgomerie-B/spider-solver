#!/usr/bin/env python3
"""Opt007 — Whole-deal incumbent challenge for deal 4925153.

Single bounded best-first/beam search from the true initial deal.
Primary ordering: experimental_move_ordering.rank_moves_for_stage (cheap expansion).
Canonical MW=163 is incumbent/fallback only — not a teacher-guided path.
Does not update production scoring or scaffold registry.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal, tokens_from_file
from spider.deal_analysis import build_deal_analysis
from spider.engine import SpiderState
from spider.hash import TranspositionTable, zobrist
from spider.metrics import Action, export_actions_to_moves_file, parse_moves_file, replay_actions
from spider.planner.diagnostics.cleanup_cascade import (
    cleanup_cascade_potential,
    foundation_counts,
)
from spider.planner.diagnostics.experimental_move_ordering import (
    ADAPTER_ID,
    rank_moves_for_stage,
)
from spider.planner.diagnostics.stage_classifier import classify_stage
from spider.rules import deal_cost, mw_move_cost

DEAL = ROOT / "deals" / "4925153.txt"
CANONICAL = ROOT / "solutions" / "4925153_canonical.moves"
EXP_DIR = ROOT / "src" / "spider" / "planner" / "diagnostics" / "experiments"
META = EXP_DIR / "4925153_opt007_whole_deal_incumbent.json"
PREFLIGHT_JSON = EXP_DIR / "4925153_opt007_preflight_report.json"
PREFLIGHT_MD = EXP_DIR / "4925153_opt007_preflight_report.md"
RESULTS_JSON = EXP_DIR / "4925153_opt007_whole_deal_results.json"
RESULTS_MD = EXP_DIR / "4925153_opt007_whole_deal_report.md"
BEST_MOVES = EXP_DIR / "4925153_opt007_best_solution.moves.txt"

# Hard limits (single config)
BEAM = 500
MAX_EXPANDED = 2_000_000
MAX_GENERATED = 12_000_000
WALL_CLOCK = 1800.0  # 30 minutes
MAX_DEPTH = 180
UNSOLVED_MW_CEILING = 162  # do not expand unsolved with mw >= 163
INCUMBENT_MW = 163
MOVE_CAP = 14
EXPAND_TOP = 10  # apply top-N ordered moves per expansion

CANONICAL_MILESTONES = {
    "D1_first_foundation": 84,
    "H20_second_foundation": 131,
    "I1_stock_empty": 141,
    "J8_third_foundation": 149,
    "J17_pre_batch": 158,
    "solved": 163,
}

STAGE_RANK = {
    "cascade_firing": 6,
    "cascade_staging": 5,
    "cleanup_active": 4,
    "pre_cleanup_with_stock": 3,
    "second_foundation_planning": 2,
    "first_foundation_planning": 1,
    "opening": 0,
    "solved": 7,
}


def sw_of(st: SpiderState) -> int:
    return sum(len(c.face_up) for c in st.columns if c.face_down)


def spaces_of(st: SpiderState) -> int:
    return sum(1 for c in st.columns if c.is_empty())


def suit_copies_str(st: SpiderState) -> str:
    c = foundation_counts(st)
    return ",".join(f"{s}:{c[s]}" for s in "schd" if c[s]) or "-"


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
    """Engine legality: stock has a full row. (MW allows empty columns.)"""
    return len(st.stock) >= 10


def apply_action(st: SpiderState, a: Action) -> int:
    if a == ("deal",):
        if not can_deal(st):
            raise ValueError("cannot deal")
        return st.deal()
    s, d, k = a  # type: ignore
    return st.move(s, d, k)


def step_cost_for(st: SpiderState, a: Action) -> int:
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


def validate_incumbent() -> Dict[str, Any]:
    actions = parse_moves_file(CANONICAL)
    st = SpiderState.from_cards(load_deal(DEAL))
    mw = 0
    for a in actions:
        mw += apply_action(st, a)
    tableau = sum(1 for a in actions if a != ("deal",))
    deals = sum(1 for a in actions if a == ("deal",))
    ok = (
        st.is_solved()
        and mw == INCUMBENT_MW
        and len(st.foundations) == 8
        and len(st.stock) == 0
    )
    return {
        "legal": True,
        "ok": ok,
        "mw": mw,
        "solved": st.is_solved(),
        "foundations": len(st.foundations),
        "stock": len(st.stock),
        "actions": len(actions),
        "tableau_moves": tableau,
        "stock_deals": deals,
        "explicit_player_decisions": len(actions),
        "path_hash": path_hash(actions),
        "moves_file": str(CANONICAL.relative_to(ROOT)),
        "actions_raw": actions,
    }


def stage_for(st: SpiderState, analysis) -> Tuple[str, Optional[int], List, List]:
    if st.is_solved() or len(st.foundations) >= 8:
        return "solved", 0, [], []
    cleanup = None
    exact: List = []
    near: List = []
    stage_diag = None
    # Expensive cleanup only after stock empty or multi-foundation
    if len(st.stock) == 0 or len(st.foundations) >= 2:
        try:
            cc = cleanup_cascade_potential(
                st, analysis, deep_one_move=False, precise_merge=False
            )
            cleanup = cc["score"]
            exact = list(cc.get("exact_now_suits") or [])
            near = list(cc.get("near_complete_suits") or [])
            stage_diag = cc.get("stage")
        except Exception:
            pass
    prof = classify_stage(
        state=st,
        scaffold_context={
            "foundations": len(st.foundations),
            "stock_remaining": len(st.stock) // 10,
            "sw": sw_of(st),
            "spaces": spaces_of(st),
        },
        diagnostics={
            "stage": stage_diag,
            "exact_suits": exact,
            "greedy_risk": False,
        },
    )
    return prof.macro_stage, cleanup, exact, near


def heap_priority(
    solved: bool,
    mw: int,
    f: int,
    stock: int,
    sw: int,
    stage: str,
    spaces: int,
    mobility: int,
    cleanup: Optional[int],
    depth: int,
    z: int,
) -> Tuple:
    """Min-heap priority: smaller is better (extract best next).

    Critical: do not prefer stock=0 when foundations=0 (premature full-deal).
    """
    # When f==0, prefer retaining stock (delay deals); when f>=1, prefer less stock.
    stock_key = stock if f >= 1 else (100 - min(stock, 50))
    # Penalise stock-empty zero-foundation positions hard
    premature_deal_all = 1 if (f == 0 and stock == 0) else 0
    return (
        0 if solved else 1,
        mw if solved else 0,
        premature_deal_all,
        -f,
        stock_key,
        sw,
        -STAGE_RANK.get(stage, 0),
        -spaces,
        -mobility,
        -(cleanup if cleanup is not None else -10**9),
        mw,
        depth,
        z & 0xFFFFFFFFFFFFFFFF,
    )


def progress_key_max(
    solved: bool,
    mw: int,
    f: int,
    stock: int,
    sw: int,
    stage: str,
    spaces: int,
    mobility: int,
    cleanup: Optional[int],
    depth: int,
    z: int,
) -> Tuple:
    """Higher is better (for ranking finalists / progress log)."""
    return tuple(
        -x if isinstance(x, int) else x
        for x in heap_priority(
            solved, mw, f, stock, sw, stage, spaces, mobility, cleanup, depth, z
        )
    )


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
    stage: str
    cleanup: Optional[int]
    mobility: int
    z: int


def order_moves_adapter(st: SpiderState, analysis, stage: str) -> List[Action]:
    """Primary ordering path — experimental adapter, no teacher path."""
    profile = classify_stage(
        state=st,
        scaffold_context={
            "foundations": len(st.foundations),
            "stock_remaining": len(st.stock) // 10,
            "sw": sw_of(st),
            "spaces": spaces_of(st),
        },
        diagnostics={"stage": stage},
    )
    result = rank_moves_for_stage(
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
    for lab in result.ordered_moves:
        try:
            ordered.append(parse_label(lab))
        except Exception:
            continue
    if can_deal(st) and ("deal",) not in ordered:
        ordered.append(("deal",))
    return ordered[:MOVE_CAP]


def independent_replay(actions: List[Action]) -> Tuple[bool, int, SpiderState, Optional[str]]:
    st = SpiderState.from_cards(load_deal(DEAL))
    try:
        mw = 0
        for a in actions:
            mw += apply_action(st, a)
        return True, mw, st, None
    except Exception as exc:
        return False, 9999, st, str(exc)


def write_preflight(inc: Dict[str, Any], meta: Dict[str, Any]) -> None:
    pf = {
        "ok": bool(inc.get("ok")),
        "experiment_id": "4925153_opt007_whole_deal_incumbent",
        "deal": "4925153",
        "seed_kind": "initial_deal",
        "incumbent_mw": INCUMBENT_MW,
        "incumbent_ok": inc.get("ok"),
        "incumbent_path_hash": inc.get("path_hash"),
        "production_change_allowed": False,
        "registry_update_allowed": False,
        "teacher_move_bonus_allowed": False,
        "teacher_suffix_allowed": False,
        "adapter": ADAPTER_ID,
        "limits": meta.get("search_limits"),
        "errors": [] if inc.get("ok") else ["incumbent replay failed"],
        "warnings": [],
    }
    PREFLIGHT_JSON.write_text(json.dumps(pf, indent=2), encoding="utf-8")
    lines = [
        "# Opt007 preflight — whole-deal incumbent challenge",
        "",
        f"**ok:** `{pf['ok']}`",
        f"**deal:** 4925153 (initial only)",
        f"**incumbent MW:** {INCUMBENT_MW} (canonical fallback)",
        f"**incumbent ok:** {pf['incumbent_ok']}",
        f"**path hash:** {pf['incumbent_path_hash']}",
        f"**adapter:** {ADAPTER_ID} (experimental_stage_aware)",
        f"**teacher bonus:** false",
        f"**teacher suffix:** false",
        f"**production_change_allowed:** false",
        f"**registry_update_allowed:** false",
        "",
        "## Limits",
        "",
        f"- beam: {BEAM}",
        f"- max expanded: {MAX_EXPANDED}",
        f"- max generated: {MAX_GENERATED}",
        f"- wall clock: {WALL_CLOCK}s",
        f"- max depth: {MAX_DEPTH}",
        f"- unsolved MW ceiling: {UNSOLVED_MW_CEILING} (no expand if mw>=163 unsolved)",
        "",
        "## Incumbent",
        "",
        f"- MW={inc['mw']} solved={inc['solved']} f={inc['foundations']} stock={inc['stock']}",
        f"- actions={inc['actions']} tableau={inc['tableau_moves']} deals={inc['stock_deals']}",
        "",
    ]
    PREFLIGHT_MD.write_text("\n".join(lines), encoding="utf-8")


def run_search(analysis) -> Dict[str, Any]:
    t0 = time.time()
    root = SpiderState.from_cards(load_deal(DEAL))
    stage0, cleanup0, exact0, near0 = stage_for(root, analysis)
    mob0 = len(root.enumerate_moves()) + (1 if can_deal(root) else 0)
    z0 = zobrist(root)
    start = Node(
        state=root,
        mw=0,
        depth=0,
        path=[],
        f=0,
        stock=len(root.stock),
        sw=sw_of(root),
        spaces=spaces_of(root),
        stage=stage0,
        cleanup=cleanup0,
        mobility=mob0,
        z=z0,
    )

    # Incumbent (fallback) — not injected into frontier
    incumbent_mw = INCUMBENT_MW
    incumbent_path: Optional[List[Action]] = None
    incumbent_updates: List[Dict] = []

    tt = TranspositionTable()
    tt.store(root, 0)
    # Also track best depth for equal MW
    best_depth: Dict[int, int] = {z0: 0}

    heap: List[HeapItem] = []
    seq = 0

    def push(node: Node) -> None:
        nonlocal seq
        solved = node.state.is_solved()
        pri = heap_priority(
            solved,
            node.mw,
            node.f,
            node.stock,
            node.sw,
            node.stage,
            node.spaces,
            node.mobility,
            node.cleanup,
            node.depth,
            node.z,
        )
        seq += 1
        heapq.heappush(heap, HeapItem(pri, seq, node))

    push(start)

    expanded = 0
    generated = 0
    tt_probes = 0
    tt_hits = 0
    replaced = 0
    duplicates = 0
    peak_frontier = 1
    peak_tt = 1
    deepest = 0
    termination = "running"

    first_arrival: Dict[str, Dict] = {}
    best_progress: Optional[Node] = start
    best_progress_key = progress_key_max(
        False, 0, 0, start.stock, start.sw, stage0, start.spaces, mob0, cleanup0, 0, z0
    )
    progress_log: List[Dict] = []
    finalists: List[Node] = []

    def note_first(tag: str, node: Node) -> None:
        if tag not in first_arrival:
            first_arrival[tag] = {
                "mw": node.mw,
                "depth": node.depth,
                "f": node.f,
                "stock": node.stock,
                "sw": node.sw,
                "spaces": node.spaces,
                "stage": node.stage,
                "elapsed": round(time.time() - t0, 3),
            }

    def consider_progress(node: Node) -> None:
        nonlocal best_progress, best_progress_key
        solved = node.state.is_solved()
        key = progress_key_max(
            solved,
            node.mw,
            node.f,
            node.stock,
            node.sw,
            node.stage,
            node.spaces,
            node.mobility,
            node.cleanup,
            node.depth,
            node.z,
        )
        if key > best_progress_key:
            best_progress_key = key
            best_progress = node
            progress_log.append(
                {
                    "elapsed": round(time.time() - t0, 3),
                    "expanded": expanded,
                    "generated": generated,
                    "depth": node.depth,
                    "mw": node.mw,
                    "foundations": node.f,
                    "stock": node.stock,
                    "sw": node.sw,
                    "spaces": node.spaces,
                    "stage": node.stage,
                    "cleanup": node.cleanup,
                    "path_len": len(node.path),
                    "path_hash": path_hash(node.path),
                }
            )

    while heap:
        if time.time() - t0 >= WALL_CLOCK:
            termination = "wall_clock"
            break
        if expanded >= MAX_EXPANDED:
            termination = "max_expanded"
            break
        if generated >= MAX_GENERATED:
            termination = "max_generated"
            break

        # Beam prune: keep only BEAM best items
        if len(heap) > BEAM * 3:
            best_items = heapq.nsmallest(BEAM, heap)
            heap = best_items
            heapq.heapify(heap)
        peak_frontier = max(peak_frontier, len(heap))

        item = heapq.heappop(heap)
        node: Node = item.node
        expanded += 1
        deepest = max(deepest, node.depth)

        if node.state.is_solved():
            # Validate and maybe update incumbent
            ok, mw, st, err = independent_replay(node.path)
            if ok and st.is_solved() and mw <= UNSOLVED_MW_CEILING:
                if mw < incumbent_mw:
                    incumbent_mw = mw
                    incumbent_path = list(node.path)
                    incumbent_updates.append(
                        {
                            "mw": mw,
                            "depth": node.depth,
                            "expanded": expanded,
                            "elapsed": round(time.time() - t0, 3),
                            "path_hash": path_hash(node.path),
                        }
                    )
                    print(f"*** IMPROVED INCUMBENT MW={mw} at expanded={expanded} ***", flush=True)
                    # Continue with remaining budget
            consider_progress(node)
            note_first("solved", node)
            finalists.append(node)
            continue

        # Hard prune: unsolved cannot improve if mw >= 163
        if node.mw > UNSOLVED_MW_CEILING:
            continue
        if node.mw >= INCUMBENT_MW:
            # mw==163 unsolved cannot beat incumbent
            continue
        if node.depth >= MAX_DEPTH:
            finalists.append(node)
            continue

        # Milestones
        if node.f >= 1:
            note_first("first_foundation", node)
        if node.f >= 2:
            note_first("second_foundation", node)
        if node.stock == 0:
            note_first("stock0", node)
        if node.f >= 3:
            note_first("third_foundation", node)
        if node.stock == 0 and node.sw == 0:
            note_first("sw0_post_stock", node)
        if node.stage == "cascade_staging":
            note_first("cascade_staging", node)
        if node.stage == "cascade_firing":
            note_first("cascade_firing", node)
        if node.f >= 4:
            note_first("foundation_4", node)

        consider_progress(node)

        # Order moves via adapter
        try:
            ordered = order_moves_adapter(node.state, analysis, node.stage)
        except Exception:
            ordered = list(node.state.enumerate_moves())[:MOVE_CAP]
            if can_deal(node.state):
                ordered.append(("deal",))

        for a in ordered[:EXPAND_TOP]:
            if generated >= MAX_GENERATED:
                break
            # Pre-check MW
            try:
                cost = step_cost_for(node.state, a)
            except Exception:
                continue
            new_mw = node.mw + cost
            # Unsolved child with mw > ceiling: skip (solved check after apply)
            if new_mw > UNSOLVED_MW_CEILING:
                # Might still solve on this move if foundations complete — apply carefully
                pass

            st2 = node.state.clone()
            try:
                apply_action(st2, a)
            except Exception:
                continue
            generated += 1
            depth2 = node.depth + 1
            z2 = zobrist(st2)
            solved2 = st2.is_solved()

            if not solved2 and new_mw > UNSOLVED_MW_CEILING:
                continue
            if not solved2 and new_mw >= INCUMBENT_MW:
                continue

            tt_probes += 1
            prev_g = tt.get(st2)
            prev_d = best_depth.get(z2)
            if prev_g is not None:
                tt_hits += 1
                if prev_g < new_mw:
                    duplicates += 1
                    continue
                if prev_g == new_mw and prev_d is not None and prev_d <= depth2:
                    duplicates += 1
                    continue
                if prev_g > new_mw:
                    replaced += 1

            tt.store(st2, new_mw)
            if prev_d is None or depth2 < prev_d or (prev_g is not None and new_mw < prev_g):
                best_depth[z2] = depth2
            peak_tt = max(peak_tt, len(tt))

            stage2, cleanup2, _, _ = stage_for(st2, analysis)
            mob2 = len(st2.enumerate_moves()) + (1 if can_deal(st2) else 0)
            child = Node(
                state=st2,
                mw=new_mw,
                depth=depth2,
                path=node.path + [a],
                f=len(st2.foundations),
                stock=len(st2.stock),
                sw=sw_of(st2),
                spaces=spaces_of(st2),
                stage=stage2,
                cleanup=cleanup2,
                mobility=mob2,
                z=z2,
            )
            push(child)

        if expanded % 500 == 0:
            bp = best_progress
            print(
                f"  exp={expanded} gen={generated} frontier={len(heap)} tt={len(tt)} "
                f"best f={bp.f if bp else 0} stock={bp.stock if bp else '-'} "
                f"sw={bp.sw if bp else '-'} mw={bp.mw if bp else '-'} "
                f"stage={bp.stage if bp else '-'} inc={incumbent_mw}",
                flush=True,
            )

    if termination == "running":
        termination = "frontier_empty" if not heap else "completed"

    # Collect finalists from remaining frontier + progress log nodes
    while heap and len(finalists) < 50:
        finalists.append(heapq.heappop(heap).node)

    # Unique finalists by z, best progress
    seen_z = set()
    uniq_final: List[Node] = []
    for n in sorted(
        finalists + ([best_progress] if best_progress else []),
        key=lambda n: progress_key_max(
            n.state.is_solved(),
            n.mw,
            n.f,
            n.stock,
            n.sw,
            n.stage,
            n.spaces,
            n.mobility,
            n.cleanup,
            n.depth,
            n.z,
        ),
        reverse=True,
    ):
        if n.z in seen_z:
            continue
        seen_z.add(n.z)
        uniq_final.append(n)
        if len(uniq_final) >= 10:
            break

    elapsed = time.time() - t0
    improved = incumbent_path is not None and incumbent_mw < INCUMBENT_MW

    # Export improved solution
    improved_file = None
    if improved and incumbent_path is not None:
        ok, mw, st, err = independent_replay(incumbent_path)
        if ok and st.is_solved() and mw == incumbent_mw:
            export_actions_to_moves_file(
                incumbent_path,
                BEST_MOVES,
                header=f"Opt007 improved solution mobilityware_moves={mw}",
            )
            improved_file = str(BEST_MOVES.relative_to(ROOT))
            try:
                from spider.solution_archive import record_solution_if_better

                record_solution_if_better(
                    "4925153",
                    incumbent_path,
                    source="opt007_whole_deal",
                    experiment_id="4925153_opt007_whole_deal",
                )
            except Exception:
                pass
        else:
            improved = False
            incumbent_mw = INCUMBENT_MW
            incumbent_path = None

    return {
        "termination": termination,
        "elapsed_secs": round(elapsed, 2),
        "expanded": expanded,
        "generated": generated,
        "tt_probes": tt_probes,
        "tt_hits": tt_hits,
        "duplicates_discarded": duplicates,
        "lower_mw_replacements": replaced,
        "peak_frontier": peak_frontier,
        "peak_tt": peak_tt,
        "deepest_depth": deepest,
        "incumbent_mw_final": incumbent_mw,
        "improved": improved,
        "incumbent_updates": incumbent_updates,
        "improved_path": [action_label(a) for a in incumbent_path]
        if incumbent_path
        else None,
        "improved_file": improved_file,
        "first_arrival": first_arrival,
        "progress_log": progress_log[:50],
        "best_progress": {
            "mw": best_progress.mw if best_progress else None,
            "depth": best_progress.depth if best_progress else None,
            "foundations": best_progress.f if best_progress else None,
            "stock": best_progress.stock if best_progress else None,
            "sw": best_progress.sw if best_progress else None,
            "spaces": best_progress.spaces if best_progress else None,
            "stage": best_progress.stage if best_progress else None,
            "cleanup": best_progress.cleanup if best_progress else None,
            "path_len": len(best_progress.path) if best_progress else 0,
            "path_preview": [action_label(a) for a in (best_progress.path[:30] if best_progress else [])],
            "solved": best_progress.state.is_solved() if best_progress else False,
        },
        "finalists": [
            {
                "id": f"F{i+1}",
                "mw": n.mw,
                "depth": n.depth,
                "foundations": n.f,
                "stock": n.stock,
                "sw": n.sw,
                "spaces": n.spaces,
                "stage": n.stage,
                "cleanup": n.cleanup,
                "mobility": n.mobility,
                "path_len": len(n.path),
                "path_preview": [action_label(a) for a in n.path[:25]],
                "solved": n.state.is_solved(),
                "copies": suit_copies_str(n.state),
            }
            for i, n in enumerate(uniq_final)
        ],
    }


def milestone_table(first_arrival: Dict) -> List[Dict]:
    rows = []
    mapping = [
        ("first_foundation", "D1_first_foundation", CANONICAL_MILESTONES["D1_first_foundation"]),
        ("second_foundation", "H20_second_foundation", CANONICAL_MILESTONES["H20_second_foundation"]),
        ("stock0", "I1_stock_empty", CANONICAL_MILESTONES["I1_stock_empty"]),
        ("third_foundation", "J8_third_foundation", CANONICAL_MILESTONES["J8_third_foundation"]),
        ("cascade_staging", "J8/cascade_staging", CANONICAL_MILESTONES["J8_third_foundation"]),
        ("cascade_firing", "J17_pre_batch", CANONICAL_MILESTONES["J17_pre_batch"]),
        ("solved", "solved", CANONICAL_MILESTONES["solved"]),
    ]
    for tag, label, canon_mw in mapping:
        arr = first_arrival.get(tag)
        if arr:
            rows.append(
                {
                    "milestone": label,
                    "canonical_mw": canon_mw,
                    "search_mw": arr["mw"],
                    "delta": arr["mw"] - canon_mw,
                    "summary": f"f={arr['f']} stock={arr['stock']} sw={arr['sw']} stage={arr['stage']}",
                    "same_as_canonical_state": False,
                }
            )
        else:
            rows.append(
                {
                    "milestone": label,
                    "canonical_mw": canon_mw,
                    "search_mw": None,
                    "delta": None,
                    "summary": "not reached",
                    "same_as_canonical_state": False,
                }
            )
    return rows


def decide(search: Dict, inc: Dict) -> Dict[str, str]:
    if search.get("improved"):
        return {
            "choice": (
                "1. Improved solved route found; recommend it for independent control-plane "
                "verification, without updating the registry yet."
            ),
            "rationale": (
                f"Found solved MW={search['incumbent_mw_final']} < 163 with independent replay. "
                f"Exported to {search.get('improved_file')}. Registry not updated."
            ),
        }
    bp = search.get("best_progress") or {}
    f = bp.get("foundations") or 0
    if f >= 3 and (bp.get("sw") or 99) == 0:
        return {
            "choice": (
                "2. No improved solve, but a clearly superior intermediate route was found; "
                "recommend one specifically bounded continuation test."
            ),
            "rationale": (
                f"Reached f={f} sw=0 stock={bp.get('stock')} at MW={bp.get('mw')} without solving. "
                "A single bounded continuation could be considered later — not run now."
            ),
        }
    if f >= 1:
        return {
            "choice": (
                "3. No improved solve; current search lost improvements before they became "
                "continuation-capable. Report the exact bottleneck."
            ),
            "rationale": (
                f"Best progress f={f} stock={bp.get('stock')} sw={bp.get('sw')} "
                f"stage={bp.get('stage')} MW={bp.get('mw')}. "
                "Did not convert early progress into a solved MW<=162 path under the single bound."
            ),
        }
    if (search.get("expanded") or 0) < 1000:
        return {
            "choice": (
                "4. Search made insufficient progress under the resource bound; identify whether "
                "beam width, transposition behaviour or ordering was limiting."
            ),
            "rationale": (
                f"Only {search.get('expanded')} expansions / {search.get('elapsed_secs')}s; "
                f"termination={search.get('termination')}."
            ),
        }
    return {
        "choice": (
            "3. No improved solve; current search lost improvements before they became "
            "continuation-capable. Report the exact bottleneck."
        ),
        "rationale": (
            f"Best progress remained pre-foundation or weak (f={f}, stock={bp.get('stock')}, "
            f"sw={bp.get('sw')}, MW={bp.get('mw')}). "
            "Main bottleneck: early-game / first-foundation competence under adapter-ordered "
            f"beam={BEAM} (expanded={search.get('expanded')}, term={search.get('termination')}). "
            "Canonical MW=163 remains incumbent. No registry update."
        ),
    }


def write_results(inc: Dict, search: Dict, decision: Dict) -> None:
    milestones = milestone_table(search.get("first_arrival") or {})
    # Branch analysis answers
    fa = search.get("first_arrival") or {}
    branch = {
        "first_foundation_before_mw84": bool(
            fa.get("first_foundation") and fa["first_foundation"]["mw"] < 84
        ),
        "early_first_foundation_continuation_capable": bool(
            fa.get("first_foundation") and fa.get("second_foundation")
        ),
        "two_foundations_before_mw131": bool(
            fa.get("second_foundation") and fa["second_foundation"]["mw"] < 131
        ),
        "strong_stock_empty_before_mw141": bool(
            fa.get("stock0")
            and fa["stock0"]["mw"] < 141
            and fa["stock0"].get("sw", 99) <= 3
        ),
        "third_foundation_before_mw149": bool(
            fa.get("third_foundation") and fa["third_foundation"]["mw"] < 149
        ),
        "cascade_firing_before_mw158": bool(
            fa.get("cascade_firing") and fa["cascade_firing"]["mw"] < 158
        ),
        "solved_below_163": bool(search.get("improved")),
        "largest_canonical_improvement": None,
        "where_improvement_lost": None,
        "known_failure_mode_repeat": "none observed at scale"
        if (search.get("best_progress") or {}).get("foundations", 0) == 0
        else "check early-deal/weak-third if f>=3 with high sw",
        "main_bottleneck_stage": (
            "opening/first_foundation_planning"
            if (search.get("best_progress") or {}).get("foundations", 0) < 1
            else (search.get("best_progress") or {}).get("stage")
        ),
    }
    # improvement vs milestones
    for row in milestones:
        if row["search_mw"] is not None and row["delta"] is not None and row["delta"] < 0:
            branch["largest_canonical_improvement"] = (
                f"{row['milestone']} search_mw={row['search_mw']} vs canon {row['canonical_mw']}"
            )
            break
    if not search.get("improved") and branch["largest_canonical_improvement"]:
        branch["where_improvement_lost"] = (
            "Early tempo not converted to later foundations/solve under MW ceiling"
        )

    payload = {
        "experiment_id": "4925153_opt007_whole_deal_incumbent",
        "deal": "4925153",
        "seed_kind": "initial_deal",
        "adapter": ADAPTER_ID,
        "adapter_primary_ordering": True,
        "teacher_move_bonus": False,
        "teacher_suffix": False,
        "canonical_role": "incumbent_and_fallback_only",
        "limits": {
            "beam": BEAM,
            "max_expanded": MAX_EXPANDED,
            "max_generated": MAX_GENERATED,
            "wall_clock_secs": WALL_CLOCK,
            "max_depth": MAX_DEPTH,
            "unsolved_mw_ceiling": UNSOLVED_MW_CEILING,
        },
        "incumbent": {k: v for k, v in inc.items() if k != "actions_raw"},
        "search": search,
        "milestones": milestones,
        "branch_analysis": branch,
        "decision": decision,
        "production_changes": False,
        "registry_updated": False,
        "canonical_file_overwritten": False,
    }
    RESULTS_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# Opt007 — Whole-deal incumbent challenge (4925153)",
        "",
        "## A. Optimisation summary",
        "",
        f"- deal: **4925153** (initial only)",
        f"- incumbent: **MW={INCUMBENT_MW}** (canonical fallback)",
        f"- objective: solved with **MW≤162**",
        f"- algorithm: best-first beam (width **{BEAM}**), TT dominance by lower MW then depth",
        f"- adapter: **`{ADAPTER_ID}`** via `rank_moves_for_stage` (cheap expansion; no teacher)",
        f"- transposition: enabled; duplicate dominance: lower MW, then lower depth",
        f"- deterministic tie-break: zobrist order",
        f"- effective limits: expanded≤{MAX_EXPANDED}, generated≤{MAX_GENERATED}, "
        f"wall≤{WALL_CLOCK}s, depth≤{MAX_DEPTH}, unsolved MW ceiling **{UNSOLVED_MW_CEILING}**",
        f"- termination: **{search.get('termination')}**",
        f"- production changes: **no** | registry: **no** | canonical overwrite: **no**",
        "",
        "## B. Incumbent replay",
        "",
        f"- legal: **yes**",
        f"- final MW: **{inc['mw']}**",
        f"- actions: {inc['actions']} (tableau {inc['tableau_moves']}, deals {inc['stock_deals']})",
        f"- decisions: {inc['explicit_player_decisions']}",
        f"- foundations: {inc['foundations']} stock: {inc['stock']} solved: **{inc['solved']}**",
        f"- path hash: `{inc['path_hash']}`",
        "",
        "## C. Search statistics",
        "",
        f"- elapsed: **{search.get('elapsed_secs')}s**",
        f"- expanded: **{search.get('expanded')}**",
        f"- generated: **{search.get('generated')}**",
        f"- TT probes/hits: {search.get('tt_probes')} / {search.get('tt_hits')}",
        f"- duplicates discarded: {search.get('duplicates_discarded')}",
        f"- lower-MW replacements: {search.get('lower_mw_replacements')}",
        f"- peak frontier: {search.get('peak_frontier')}",
        f"- peak TT size: {search.get('peak_tt')}",
        f"- deepest depth: {search.get('deepest_depth')}",
        "",
        "## D. Best solved result",
        "",
        f"- improved solution found: **{'yes' if search.get('improved') else 'no'}**",
        f"- final incumbent MW (in-run): **{search.get('incumbent_mw_final')}**",
        f"- improvement vs 163: "
        f"**{INCUMBENT_MW - search['incumbent_mw_final'] if search.get('improved') else 0}**",
        f"- export: {search.get('improved_file') or '(none)'}",
        f"- update history: {search.get('incumbent_updates')}",
        "",
        "## E. Milestone comparison",
        "",
        "| milestone | canonical MW | search MW | delta | summary | same state? |",
        "|---|---:|---:|---:|---|---|",
    ]
    for row in milestones:
        lines.append(
            f"| {row['milestone']} | {row['canonical_mw']} | {row['search_mw']} | "
            f"{row['delta']} | {row['summary']} | no |"
        )

    lines += ["", "## F. Best unsolved / competitive finalists", ""]
    for f in search.get("finalists") or []:
        lines.append(
            f"- **{f['id']}** MW={f['mw']} depth={f['depth']} f={f['foundations']} "
            f"stock={f['stock']} sw={f['sw']} sp={f['spaces']} stage={f['stage']} "
            f"cleanup={f['cleanup']} mobility={f['mobility']} solved={f['solved']}"
        )
        lines.append(f"  - path preview: {', '.join(f.get('path_preview') or [])}")
        lines.append(
            f"  - competitive because: progress key (f/stock/sw/stage); "
            f"not continued due to budget/ceiling/TT"
        )

    ba = branch
    lines += [
        "",
        "## G. Branch analysis",
        "",
        f"- First foundation before MW84? **{ba['first_foundation_before_mw84']}**",
        f"- Early first-foundation continuation-capable? **{ba['early_first_foundation_continuation_capable']}**",
        f"- Two foundations before MW131? **{ba['two_foundations_before_mw131']}**",
        f"- Strong stock-empty before MW141? **{ba['strong_stock_empty_before_mw141']}**",
        f"- Third foundation before MW149? **{ba['third_foundation_before_mw149']}**",
        f"- Cascade firing before MW158? **{ba['cascade_firing_before_mw158']}**",
        f"- Solved below MW163? **{ba['solved_below_163']}**",
        f"- Largest canonical improvement: {ba['largest_canonical_improvement']}",
        f"- Where lost: {ba['where_improvement_lost']}",
        f"- Known failure mode repeat: {ba['known_failure_mode_repeat']}",
        f"- Main bottleneck stage: **{ba['main_bottleneck_stage']}**",
        "",
        "## H. Decision",
        "",
        f"**{decision['choice']}**",
        "",
        decision["rationale"],
        "",
        "## Explicit confirmations",
        "",
        "- only deal 4925153",
        "- start = true initial deal",
        "- canonical = incumbent/fallback only (no move-ordering bonus)",
        "- experimental_move_ordering primary",
        "- no teacher suffix",
        "- unsolved MW ceiling 162 enforced",
        "- no production scoring change",
        "- no scaffold registry update",
        "- canonical moves file not overwritten",
        "",
    ]
    RESULTS_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    EXP_DIR.mkdir(parents=True, exist_ok=True)
    print("OPT007 whole-deal optimisation — deal 4925153", flush=True)
    print(
        f"limits: beam={BEAM} exp={MAX_EXPANDED} gen={MAX_GENERATED} "
        f"wall={WALL_CLOCK}s depth={MAX_DEPTH} unsolved_ceiling={UNSOLVED_MW_CEILING}",
        flush=True,
    )
    print(f"adapter={ADAPTER_ID}; teacher_bonus=False; suffix=False", flush=True)

    meta = json.loads(META.read_text(encoding="utf-8")) if META.is_file() else {}
    inc = validate_incumbent()
    print(
        f"Incumbent: ok={inc['ok']} MW={inc['mw']} solved={inc['solved']} "
        f"actions={inc['actions']} hash={inc['path_hash']}",
        flush=True,
    )
    write_preflight(inc, meta)
    if not inc["ok"]:
        print("STOP: incumbent failed validation", flush=True)
        return 1

    # Store canonical path only as fallback reference (not for search injection)
    _ = inc["actions_raw"]

    tokens = tokens_from_file(DEAL)
    analysis = build_deal_analysis(tokens)

    print("Starting single bounded whole-deal search...", flush=True)
    search = run_search(analysis)
    decision = decide(search, inc)
    write_results(inc, search, decision)

    print(f"Wrote {RESULTS_JSON.relative_to(ROOT)}", flush=True)
    print(f"Wrote {RESULTS_MD.relative_to(ROOT)}", flush=True)
    print(f"Decision: {decision['choice']}", flush=True)
    print(
        f"stats: exp={search['expanded']} gen={search['generated']} "
        f"time={search['elapsed_secs']}s term={search['termination']} "
        f"improved={search['improved']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
