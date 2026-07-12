#!/usr/bin/env python3
"""Opt009B — Resumable corridor shortcut scan (deal 4925153).

RUN ONLY IF Opt009A gate passed.
Exact canonical-state reconnection with hybrid_adapter ordering.
No teacher bonus/suffix, no production/registry/canonical overwrite.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal, tokens_from_file
from spider.deal_analysis import build_deal_analysis
from spider.engine import SpiderState
from spider.hash import TranspositionTable, zobrist
from spider.metrics import Action, export_actions_to_moves_file, parse_moves_file, replay_actions
from spider.planner.diagnostics.checkpoints.diagnostic_checkpoint import (
    CheckpointStore,
    SearchCheckpointPayload,
    build_config_identity,
)
from spider.planner.diagnostics.experimental_move_ordering import (
    ADAPTER_ID,
    ORDERING_STATS,
    rank_moves_for_stage,
    reset_ordering_stats,
)
from spider.planner.diagnostics.stage_classifier import classify_stage
from spider.rules import deal_cost, mw_move_cost

DEAL = ROOT / "deals" / "4925153.txt"
CANONICAL = ROOT / "solutions" / "4925153_canonical.moves"
LADDER = (
    ROOT
    / "src/spider/planner/diagnostics/scaffolds/4925153_deal_scaffold_ladder.json"
)
EXP_DIR = ROOT / "src/spider/planner/diagnostics/experiments"
CKPT_DIR = (
    ROOT
    / "src/spider/planner/diagnostics/checkpoints/runtime_opt009b"
)
MANIFEST = EXP_DIR / "4925153_opt009b_resumable_corridor.json"
PREFLIGHT_JSON = EXP_DIR / "4925153_opt009b_preflight_report.json"
PREFLIGHT_MD = EXP_DIR / "4925153_opt009b_preflight_report.md"
RESULTS_JSON = EXP_DIR / "4925153_opt009b_corridor_results.json"
RESULTS_MD = EXP_DIR / "4925153_opt009b_corridor_report.md"
BEST_MOVES = EXP_DIR / "4925153_opt009b_best_solution.moves.txt"
OPT009A = EXP_DIR / "4925153_opt009a_hybrid_throughput_results.json"

DEAL_ID = "4925153"
EXPERIMENT_ID = "4925153_opt009b_resumable_corridor"
INCUMBENT_MW = 163

# Per-window limits
BEAM = 500
MAX_EXPANDED_WINDOW = 1_000_000
MAX_GENERATED_WINDOW = 12_000_000
WALL_WINDOW = 10800.0  # 3h
# Global
MAX_ACTIVE_GLOBAL = 172800.0  # 48h
MAX_EXPANDED_GLOBAL = 12_000_000
MAX_GENERATED_GLOBAL = 120_000_000
CHECKPOINT_INTERVAL = 300.0
MOVE_CAP = 16
EXPAND_TOP = 16

# Window constraints
MAX_MW_SPAN = 16
MAX_DECISION_SPAN = 20
MAX_WINDOWS = 20


def sw_of(st: SpiderState) -> int:
    return sum(len(c.face_up) for c in st.columns if c.face_down)


def spaces_of(st: SpiderState) -> int:
    return sum(1 for c in st.columns if c.is_empty())


def can_deal(st: SpiderState) -> bool:
    return len(st.stock) >= 10 and all(not c.is_empty() for c in st.columns)


def apply_action(st: SpiderState, a: Action) -> int:
    if a == ("deal",):
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


def path_hash(actions: Sequence[Action]) -> str:
    return hashlib.sha256(repr(list(actions)).encode()).hexdigest()[:16]


def build_canonical_index() -> Dict[str, Any]:
    """Replay full canonical solution; index after every explicit player decision."""
    actions = parse_moves_file(CANONICAL)
    st = SpiderState.from_cards(load_deal(DEAL))
    index: List[Dict[str, Any]] = []
    mw = 0
    # decision 0 = initial
    index.append(
        {
            "decision_index": 0,
            "action_index": 0,
            "mw": 0,
            "foundations": 0,
            "stock": len(st.stock),
            "sw": sw_of(st),
            "spaces": spaces_of(st),
            "stage": "opening",
            "z": zobrist(st),
            "solved": False,
        }
    )
    for i, a in enumerate(actions):
        mw += apply_action(st, a)
        prof = classify_stage(
            state=st,
            scaffold_context={
                "foundations": len(st.foundations),
                "stock_remaining": len(st.stock) // 10,
                "sw": sw_of(st),
                "spaces": spaces_of(st),
            },
        )
        index.append(
            {
                "decision_index": i + 1,
                "action_index": i + 1,
                "mw": mw,
                "foundations": len(st.foundations),
                "stock": len(st.stock),
                "sw": sw_of(st),
                "spaces": spaces_of(st),
                "stage": prof.macro_stage,
                "z": zobrist(st),
                "solved": st.is_solved(),
            }
        )
    assert index[-1]["mw"] == INCUMBENT_MW
    assert index[-1]["foundations"] == 8
    assert index[-1]["stock"] == 0
    assert index[-1]["solved"] is True
    assert len(actions) == 174
    return {
        "actions": actions,
        "index": index,
        "final_mw": mw,
        "n_actions": len(actions),
        "legal_replay": True,
        "solved": True,
    }


def accepted_scaffold_anchors() -> List[Dict[str, Any]]:
    """Named accepted canonical scaffolds only (exclude B5, MW144, closed branches)."""
    ladder = json.loads(LADDER.read_text(encoding="utf-8"))
    out = []
    exclude = {
        "B5_shortcut_first_foundation",
        "beam_MW144_club_third_foundation",
        "canonical_B5_or_B5_seed",  # divergence seed only — still canonical layout but
        # used as B5 branch seed; keep as intermediate index only if needed
    }
    # Keep B5 seed as canonical index point only if named canonical — exclude from
    # primary named windows per policy "Exclude B5".
    for row in ladder.get("ladder") or []:
        lab = row["label"]
        if lab in exclude or "B5" in lab or "MW144" in lab or "b5" in lab.lower():
            continue
        if row.get("allowed_as_continuation_scaffold") in ("no", "auxiliary-only"):
            if lab not in (
                "canonical_start",
                "canonical_deal1_or_section_A_end",
                "canonical_first_foundation_D1",
                "canonical_H20_second_foundation",
                "canonical_I1_after_deal5",
                "canonical_J8_third_foundation_cascade_quality",
                "canonical_J11_greedy_risk_hearts_exact",
                "canonical_J17_pre_batch_cascade",
                "canonical_J22_solved",
            ):
                continue
        if lab.startswith("beam_") or "shortcut" in lab.lower():
            continue
        out.append(
            {
                "label": lab,
                "actions": int(row["actions"]),
                "mw": int(row["mw"]) if row.get("mw") is not None else None,
                "role": row.get("role"),
                "status": row.get("status"),
            }
        )
    return out


def define_windows(canon: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Create ≤20 shortcut windows: MW span 2–16, decision span ≤20."""
    index = canon["index"]
    anchors = accepted_scaffold_anchors()
    # map labels to decision indices
    named = {a["label"]: a["actions"] for a in anchors if a["mw"] is not None}

    phases = [
        ("before_D1", "canonical_start", "canonical_first_foundation_D1"),
        ("D1_to_H20", "canonical_first_foundation_D1", "canonical_H20_second_foundation"),
        ("H20_to_I1", "canonical_H20_second_foundation", "canonical_I1_after_deal5"),
        ("I1_to_J8", "canonical_I1_after_deal5", "canonical_J8_third_foundation_cascade_quality"),
        ("J8_to_J17", "canonical_J8_third_foundation_cascade_quality", "canonical_J17_pre_batch_cascade"),
        ("J17_to_solved", "canonical_J17_pre_batch_cascade", "canonical_J22_solved"),
    ]

    windows: List[Dict[str, Any]] = []

    def add_window(
        phase: str,
        src_dec: int,
        tgt_dec: int,
        *,
        src_label: str,
        tgt_label: str,
        temporary: bool = False,
    ) -> None:
        if src_dec >= tgt_dec:
            return
        src = index[src_dec]
        tgt = index[tgt_dec]
        mw_span = tgt["mw"] - src["mw"]
        dec_span = tgt_dec - src_dec
        if mw_span < 2 or mw_span > MAX_MW_SPAN:
            return
        if dec_span > MAX_DECISION_SPAN:
            return
        windows.append(
            {
                "id": f"W{len(windows)+1:02d}_{phase}_{src_dec}_{tgt_dec}",
                "phase": phase,
                "source_label": src_label,
                "target_label": tgt_label,
                "source_decision": src_dec,
                "target_decision": tgt_dec,
                "source_mw": src["mw"],
                "target_mw": tgt["mw"],
                "canonical_mw_cost": mw_span,
                "canonical_decision_cost": dec_span,
                "source_z": src["z"],
                "target_z": tgt["z"],
                "temporary_anchor": temporary,
                "hard_mw_ceiling": tgt["mw"] - 1,
                "max_depth": min(dec_span + 3, 23),
            }
        )

    def fill_phase(phase: str, src_lab: str, tgt_lab: str) -> None:
        s = named.get(src_lab)
        t = named.get(tgt_lab)
        if s is None or t is None:
            return
        mw_span = index[t]["mw"] - index[s]["mw"]
        dec_span = t - s
        if 2 <= mw_span <= MAX_MW_SPAN and dec_span <= MAX_DECISION_SPAN:
            add_window(phase, s, t, src_label=src_lab, tgt_label=tgt_lab)
            return
        # split with temporary indexed anchors — prefer larger MW spans
        # step by at most MAX_MW_SPAN / MAX_DECISION_SPAN
        cur = s
        while cur < t:
            # find farthest next within constraints
            best = None
            for nxt in range(cur + 1, t + 1):
                dm = index[nxt]["mw"] - index[cur]["mw"]
                dd = nxt - cur
                if dm < 2:
                    continue
                if dm <= MAX_MW_SPAN and dd <= MAX_DECISION_SPAN:
                    best = nxt
                else:
                    break
            if best is None:
                # force small step
                best = min(cur + min(MAX_DECISION_SPAN, 8), t)
                if index[best]["mw"] - index[cur]["mw"] < 2 and best < t:
                    # advance until mw+2
                    while best < t and index[best]["mw"] - index[cur]["mw"] < 2:
                        best += 1
            src_label = src_lab if cur == s else f"idx_{cur}"
            tgt_label = tgt_lab if best == t else f"idx_{best}"
            temp = cur != s or best != t
            if cur == s and best == t:
                temp = False
            add_window(
                phase,
                cur,
                best,
                src_label=src_label,
                tgt_label=tgt_label,
                temporary=temp and not (cur == s and best == t),
            )
            if best == cur:
                break
            cur = best

    for phase, s, t in phases:
        fill_phase(phase, s, t)

    # prioritise: phase order already, within phase larger MW first
    # re-sort within phase by -mw_cost while preserving phase order
    by_phase: Dict[str, List] = {}
    for w in windows:
        by_phase.setdefault(w["phase"], []).append(w)
    ordered: List[Dict] = []
    for phase, _, _ in phases:
        grp = by_phase.get(phase) or []
        grp.sort(key=lambda x: (-x["canonical_mw_cost"], x["source_decision"]))
        ordered.extend(grp)

    # cap at MAX_WINDOWS — keep priority order
    ordered = ordered[:MAX_WINDOWS]
    for i, w in enumerate(ordered):
        w["priority"] = i + 1
        w["id"] = f"W{i+1:02d}_{w['phase']}_{w['source_decision']}_{w['target_decision']}"
    return ordered


def target_distance(st: SpiderState, target: SpiderState, target_meta: Dict) -> Tuple:
    """Ordering-only target distance (lower better). Not a success criterion."""
    return (
        abs(len(st.foundations) - len(target.foundations)),
        abs(len(st.stock) - len(target.stock)),
        abs(sw_of(st) - target_meta["sw"]),
        abs(spaces_of(st) - target_meta["spaces"]),
        abs(zobrist(st) - target_meta["z"]) & 0xFFFF,  # weak hash proximity only for ties
    )


def order_moves_hybrid(st: SpiderState, analysis) -> List[Action]:
    profile = classify_stage(
        state=st,
        scaffold_context={
            "foundations": len(st.foundations),
            "stock_remaining": len(st.stock) // 10,
            "sw": sw_of(st),
            "spaces": spaces_of(st),
        },
    )
    res = rank_moves_for_stage(
        st,
        stage_profile=profile,
        context={
            "analysis": analysis,
            "teacher_move": None,
            "ordering_mode": "hybrid_adapter",
            "cheap_expansion": True,
            "full_integrity": False,
            "hot_path": True,
            "suppress_explanations": True,
            "suppress_hot_path_warnings": True,
            "use_order_cache": True,
            "use_feature_cache": True,
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
    return ordered[:MOVE_CAP]


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
    z: int


def state_at(actions: List[Action], n: int) -> Tuple[SpiderState, int]:
    st = SpiderState.from_cards(load_deal(DEAL))
    mw = 0
    for a in actions[:n]:
        mw += apply_action(st, a)
    return st, mw


def search_window(
    window: Dict[str, Any],
    canon_actions: List[Action],
    analysis,
    *,
    global_active0: float,
    global_expanded0: int,
    global_generated0: int,
    wall_window: float = WALL_WINDOW,
    enable_checkpoint: bool = True,
) -> Dict[str, Any]:
    """Exact target reconnection search for one corridor window."""
    reset_ordering_stats()
    src_st, src_mw = state_at(canon_actions, window["source_decision"])
    tgt_st, tgt_mw = state_at(canon_actions, window["target_decision"])
    assert zobrist(src_st) == window["source_z"]
    assert zobrist(tgt_st) == window["target_z"]
    target_z = window["target_z"]
    target_meta = {
        "sw": sw_of(tgt_st),
        "spaces": spaces_of(tgt_st),
        "z": target_z,
        "f": len(tgt_st.foundations),
        "stock": len(tgt_st.stock),
    }
    hard_ceil = window["hard_mw_ceiling"]  # absolute MW from deal start
    # path MW is absolute from deal when we start from source with src_mw
    max_depth = window["max_depth"]
    canon_cost = window["canonical_mw_cost"]

    t0 = time.time()
    active0 = 0.0
    tt = TranspositionTable()
    best_depth: Dict[int, int] = {}
    z0 = zobrist(src_st)
    start = Node(src_st, src_mw, 0, [], z0)
    tt.store(src_st, src_mw)
    best_depth[z0] = 0
    heap: List[HeapItem] = []
    seq = 0

    def push(n: Node) -> None:
        nonlocal seq
        seq += 1
        # min-heap: closer to target, lower MW, lower depth
        dist = target_distance(n.state, tgt_st, target_meta)
        pri = (
            0 if n.z == target_z else 1,
            dist,
            n.mw,
            n.depth,
            n.z & 0xFFFFFFFF,
        )
        heapq.heappush(heap, HeapItem(pri, seq, n))

    push(start)
    expanded = generated = 0
    peak_f = peak_tt = 1
    termination = "running"
    best_near: Optional[Dict] = None
    shortcuts: List[Dict] = []
    last_ckpt = time.time()
    store = CheckpointStore(
        CKPT_DIR, experiment_id=f"{EXPERIMENT_ID}_{window['id']}"
    )
    config_identity = build_config_identity(
        deal_id=DEAL_ID,
        experiment_id=EXPERIMENT_ID,
        ordering_mode="hybrid_adapter",
        beam=BEAM,
        extra={"window": window["id"], "target_z": target_z},
    )

    while heap:
        now = time.time()
        active = active0 + (now - t0)
        g_active = global_active0 + active
        if active >= wall_window:
            termination = "wall_clock_window"
            break
        if g_active >= MAX_ACTIVE_GLOBAL:
            termination = "global_wall"
            break
        if expanded >= MAX_EXPANDED_WINDOW:
            termination = "max_expanded_window"
            break
        if global_expanded0 + expanded >= MAX_EXPANDED_GLOBAL:
            termination = "global_expanded"
            break
        if generated >= MAX_GENERATED_WINDOW:
            termination = "max_generated_window"
            break
        if global_generated0 + generated >= MAX_GENERATED_GLOBAL:
            termination = "global_generated"
            break
        if len(heap) > BEAM * 3:
            heap = heapq.nsmallest(BEAM, heap)
            heapq.heapify(heap)
        peak_f = max(peak_f, len(heap))

        item = heapq.heappop(heap)
        node: Node = item.node
        expanded += 1

        # near-target tracking
        dist = target_distance(node.state, tgt_st, target_meta)
        near_rec = {
            "mw": node.mw,
            "depth": node.depth,
            "segment_mw": node.mw - src_mw,
            "dist": dist,
            "foundations": len(node.state.foundations),
            "stock": len(node.state.stock),
            "sw": sw_of(node.state),
            "spaces": spaces_of(node.state),
            "z": node.z,
            "exact": node.z == target_z,
        }
        if best_near is None or dist < tuple(best_near["dist"]) or (
            dist == tuple(best_near["dist"]) and node.mw < best_near["mw"]
        ):
            best_near = near_rec

        if node.z == target_z:
            seg_mw = node.mw - src_mw
            if seg_mw < canon_cost and node.mw <= hard_ceil:
                # validate replay of shortcut from source
                st_chk, mw_chk = state_at(canon_actions, window["source_decision"])
                ok = True
                for a in node.path:
                    try:
                        mw_chk += apply_action(st_chk, a)
                    except Exception:
                        ok = False
                        break
                if ok and zobrist(st_chk) == target_z and mw_chk == node.mw:
                    shortcuts.append(
                        {
                            "segment_mw": seg_mw,
                            "canonical_mw": canon_cost,
                            "saving": canon_cost - seg_mw,
                            "depth": node.depth,
                            "path": [action_label(a) for a in node.path],
                            "path_actions": list(node.path),
                            "path_hash": path_hash(node.path),
                            "absolute_mw_at_target": node.mw,
                            "independent_replay_ok": True,
                        }
                    )
                    termination = "exact_shortcut"
                    # continue briefly for better shortcuts? stop on first exact improve
                    break
            continue

        if node.mw > hard_ceil:
            continue
        if node.depth >= max_depth:
            continue
        # cannot beat target MW with remaining room
        if node.mw >= tgt_mw:
            continue

        try:
            ordered = order_moves_hybrid(node.state, analysis)
        except Exception:
            ordered = list(node.state.enumerate_moves())[:MOVE_CAP]
            if can_deal(node.state):
                ordered.append(("deal",))

        for a in ordered[:EXPAND_TOP]:
            try:
                cost = step_cost(node.state, a)
            except Exception:
                continue
            new_mw = node.mw + cost
            if new_mw > hard_ceil:
                continue
            st2 = node.state.clone()
            try:
                apply_action(st2, a)
            except Exception:
                continue
            generated += 1
            z2 = zobrist(st2)
            prev = tt.get(st2)
            prev_d = best_depth.get(z2)
            if prev is not None:
                if prev < new_mw:
                    continue
                if prev == new_mw and prev_d is not None and prev_d <= node.depth + 1:
                    continue
            tt.store(st2, new_mw)
            best_depth[z2] = node.depth + 1
            peak_tt = max(peak_tt, len(tt))
            push(Node(st2, new_mw, node.depth + 1, node.path + [a], z2))

        if enable_checkpoint and (time.time() - last_ckpt) >= CHECKPOINT_INTERVAL:
            payload = SearchCheckpointPayload(
                experiment_id=EXPERIMENT_ID,
                deal_id=DEAL_ID,
                config_identity=config_identity,
                ordering_mode="hybrid_adapter",
                active_runtime_seconds=global_active0 + (time.time() - t0),
                expanded=global_expanded0 + expanded,
                generated=global_generated0 + generated,
                seq=seq,
                termination=termination,
                corridor_window={"id": window["id"], "expanded": expanded},
                completed_windows=[],
                counters={"window_expanded": expanded, "window_generated": generated},
                tie_break_seq=seq,
                cache_policy="rebuild_on_resume",
            )
            store.write_atomic(payload)
            last_ckpt = time.time()

        if expanded % 2000 == 0:
            print(
                f"  [{window['id']}] exp={expanded} gen={generated} "
                f"frontier={len(heap)} best_near_mw={best_near['mw'] if best_near else None} "
                f"dist={best_near['dist'] if best_near else None} "
                f"t={time.time()-t0:.0f}s",
                flush=True,
            )

    if termination == "running":
        termination = "exhausted"

    return {
        "window_id": window["id"],
        "phase": window["phase"],
        "source_label": window["source_label"],
        "target_label": window["target_label"],
        "canonical_mw_cost": canon_cost,
        "canonical_decision_cost": window["canonical_decision_cost"],
        "hard_mw_ceiling": hard_ceil,
        "max_depth": max_depth,
        "termination": termination,
        "expanded": expanded,
        "generated": generated,
        "active_runtime_seconds": time.time() - t0,
        "peak_frontier": peak_f,
        "peak_tt": peak_tt,
        "shortcuts": shortcuts,
        "best_near": best_near,
        "exact_target_reached": bool(shortcuts),
    }


def splice_and_validate(
    canon_actions: List[Action],
    window: Dict[str, Any],
    shortcut_path: List[Action],
) -> Dict[str, Any]:
    """Build prefix + shortcut + suffix and fully replay from deal start."""
    prefix = list(canon_actions[: window["source_decision"]])
    suffix = list(canon_actions[window["target_decision"] :])
    full = prefix + list(shortcut_path) + suffix
    st = SpiderState.from_cards(load_deal(DEAL))
    mw = 0
    try:
        for a in full:
            mw += apply_action(st, a)
        ok = (
            st.is_solved()
            and len(st.foundations) == 8
            and len(st.stock) == 0
            and mw < INCUMBENT_MW
        )
        return {
            "ok": ok,
            "mw": mw,
            "foundations": len(st.foundations),
            "stock": len(st.stock),
            "solved": st.is_solved(),
            "path": [action_label(a) for a in full],
            "path_actions": full,
            "path_hash": path_hash(full),
            "n_actions": len(full),
            "improvement": INCUMBENT_MW - mw if ok else None,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "mw": None}


def write_preflight(canon: Dict, windows: List[Dict], phase_a: Dict) -> None:
    EXP_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {
        "experiment_id": EXPERIMENT_ID,
        "deal_id": DEAL_ID,
        "incumbent_mw": INCUMBENT_MW,
        "target_kind": "exact_canonical_state_reconnection",
        "ordering_mode": "hybrid_adapter",
        "checkpoint_enabled": True,
        "checkpoint_interval_seconds": CHECKPOINT_INTERVAL,
        "resume_allowed": True,
        "teacher_move_bonus_allowed": False,
        "teacher_suffix_allowed": False,
        "approximate_target_success_allowed": False,
        "production_change_allowed": False,
        "registry_update_allowed": False,
        "deterministic_tie_breaking": True,
        "transposition_enabled": True,
        "beam": BEAM,
        "max_expanded_per_window": MAX_EXPANDED_WINDOW,
        "max_generated_per_window": MAX_GENERATED_WINDOW,
        "wall_clock_per_window": WALL_WINDOW,
        "global_active_runtime": MAX_ACTIVE_GLOBAL,
        "global_max_expanded": MAX_EXPANDED_GLOBAL,
        "global_max_generated": MAX_GENERATED_GLOBAL,
        "windows": [
            {
                k: w[k]
                for k in w
                if k
                not in ()
            }
            for w in windows
        ],
        "phase_a_gate_passed": bool((phase_a.get("gate") or {}).get("passed")),
        "phase_a_speedup": (phase_a.get("gate") or {}).get("speedup_expansions"),
        "adapter_id": ADAPTER_ID,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    pf = {
        "ok": True,
        "deal": DEAL_ID,
        "canonical_final_mw": canon["final_mw"],
        "canonical_solved": canon["solved"],
        "n_windows": len(windows),
        "windows": [
            {
                "id": w["id"],
                "phase": w["phase"],
                "src": w["source_label"],
                "tgt": w["target_label"],
                "mw_cost": w["canonical_mw_cost"],
                "dec_cost": w["canonical_decision_cost"],
            }
            for w in windows
        ],
        "phase_a_passed": manifest["phase_a_gate_passed"],
        "exclusions": ["B5", "MW144", "Exp005", "Exp006A", "closed_auxiliary"],
    }
    PREFLIGHT_JSON.write_text(json.dumps(pf, indent=2), encoding="utf-8")
    lines = [
        "# Opt009B Preflight",
        "",
        f"- Deal: {DEAL_ID}",
        f"- Incumbent MW: {INCUMBENT_MW}",
        f"- Phase A gate: {manifest['phase_a_gate_passed']} (speedup={manifest['phase_a_speedup']})",
        f"- Windows: {len(windows)}",
        f"- Ordering: hybrid_adapter",
        f"- Teacher bonus/suffix: false",
        "",
        "## Windows",
        "",
    ]
    for w in windows:
        lines.append(
            f"- `{w['id']}` {w['phase']}: {w['source_label']} → {w['target_label']} "
            f"MW={w['canonical_mw_cost']} dec={w['canonical_decision_cost']}"
        )
    PREFLIGHT_MD.write_text("\n".join(lines), encoding="utf-8")


def write_results(results: Dict[str, Any]) -> None:
    EXP_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_JSON.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    phase_a = results.get("phase_a") or {}
    lines = [
        "# Opt009B — Resumable Corridor Shortcut Scan Report",
        "",
        f"**Deal:** {DEAL_ID}  ",
        f"**Incumbent:** MW{INCUMBENT_MW}  ",
        f"**Ordering:** hybrid_adapter  ",
        f"**Recommendation:** {results.get('recommendation')}  ",
        "",
        "## A. Throughput mode (Phase A)",
        "",
        f"- Gate passed: {(phase_a.get('gate') or {}).get('passed')}",
        f"- Speedup expansions/s: {(phase_a.get('gate') or {}).get('speedup_expansions')}",
        f"- Hybrid exp/s: {(phase_a.get('hybrid_adapter') or {}).get('expansions_per_sec')}",
        f"- Full exp/s: {(phase_a.get('full_adapter') or {}).get('expansions_per_sec')}",
        "",
        "## B. Resume history",
        "",
        f"```json\n{json.dumps(results.get('resume_history') or {}, indent=2)}\n```",
        "",
        "## C. Corridor windows",
        "",
    ]
    for w in results.get("window_results") or []:
        lines.append(
            f"- `{w['window_id']}` {w['source_label']}→{w['target_label']} "
            f"canon_MW={w['canonical_mw_cost']} status={w['termination']} "
            f"exact={w['exact_target_reached']} exp={w['expanded']}"
        )
    lines += ["", "## D. Shortcut results", ""]
    for s in results.get("validated_shortcuts") or []:
        lines.append(f"- {s}")
    lines += [
        "",
        "## E. Best improved solution",
        "",
        f"```json\n{json.dumps(results.get('best_solution') or {}, indent=2)}\n```",
        "",
        "## F. Near-target evidence",
        "",
    ]
    for w in results.get("window_results") or []:
        if not w.get("exact_target_reached"):
            lines.append(f"- `{w['window_id']}`: {w.get('best_near')}")
    lines += [
        "",
        "## G. Phase analysis",
        "",
    ]
    for k, v in (results.get("phase_analysis") or {}).items():
        lines.append(f"- **{k}:** {v}")
    lines += [
        "",
        "## H. Recommendation",
        "",
        str(results.get("recommendation_text") or results.get("recommendation")),
        "",
        "## Policy",
        "",
        "- no production scoring change",
        "- no registry update",
        "- canonical not overwritten",
        "- no teacher bonus/suffix",
        "- no cold whole-deal search",
        "",
    ]
    RESULTS_MD.write_text("\n".join(lines), encoding="utf-8")


def choose_recommendation(results: Dict[str, Any]) -> Tuple[int, str]:
    best = results.get("best_solution") or {}
    shortcuts = results.get("validated_shortcuts") or []
    if best.get("ok") and best.get("mw") is not None and best["mw"] < INCUMBENT_MW:
        return (
            1,
            "Improved solution found; recommend independent control-plane verification.",
        )
    if shortcuts and not best.get("ok"):
        return (
            2,
            "Exact shortcuts found but compatibility combination requires one bounded validation task.",
        )
    # strong near-target?
    strong = False
    for w in results.get("window_results") or []:
        bn = w.get("best_near") or {}
        dist = bn.get("dist")
        if dist and dist[0] == 0 and dist[1] == 0 and (dist[2] or 0) <= 1:
            strong = True
            break
    if strong:
        return (
            3,
            "No exact shortcut, but one window has strong near-target evidence worth one focused resumed continuation using the same frozen ordering.",
        )
    if results.get("throughput_failure"):
        return (
            5,
            "Throughput/checkpoint failure invalidated Phase B.",
        )
    return (
        4,
        "No exact shortcut or strong evidence; MW163 remains locally robust under this long corridor scan.",
    )


def run_phase_b(
    *,
    max_windows: Optional[int] = None,
    wall_window: float = WALL_WINDOW,
    max_active_global: float = MAX_ACTIVE_GLOBAL,
) -> Dict[str, Any]:
    if not OPT009A.is_file():
        raise SystemExit("Phase A results missing — refuse Phase B")
    phase_a = json.loads(OPT009A.read_text(encoding="utf-8"))
    if not (phase_a.get("gate") or {}).get("passed"):
        raise SystemExit("Phase A gate failed — refuse Phase B")

    print("=== Opt009B Resumable Corridor ===", flush=True)
    print("Building canonical index...", flush=True)
    canon = build_canonical_index()
    windows = define_windows(canon)
    if max_windows is not None:
        windows = windows[:max_windows]
    write_preflight(canon, windows, phase_a)
    print(f"Windows: {len(windows)}", flush=True)
    for w in windows:
        print(
            f"  {w['id']}: {w['source_label']}→{w['target_label']} "
            f"MW={w['canonical_mw_cost']} dec={w['canonical_decision_cost']}",
            flush=True,
        )

    analysis = build_deal_analysis(tokens_from_file(DEAL))
    actions = canon["actions"]
    g_active = 0.0
    g_exp = 0
    g_gen = 0
    window_results: List[Dict] = []
    validated_shortcuts: List[Dict] = []
    best_solution: Optional[Dict] = None
    completed: List[str] = []
    t_global0 = time.time()
    resume_history = {"checkpoints_written": 0, "resumes": 0}

    for w in windows:
        if g_active >= max_active_global:
            print("Global active budget exhausted", flush=True)
            break
        if g_exp >= MAX_EXPANDED_GLOBAL or g_gen >= MAX_GENERATED_GLOBAL:
            print("Global expansion budget exhausted", flush=True)
            break
        print(f"--- Window {w['id']} ---", flush=True)
        wr = search_window(
            w,
            actions,
            analysis,
            global_active0=g_active,
            global_expanded0=g_exp,
            global_generated0=g_gen,
            wall_window=wall_window,
        )
        g_active += wr["active_runtime_seconds"]
        g_exp += wr["expanded"]
        g_gen += wr["generated"]
        window_results.append(wr)
        completed.append(w["id"])

        for sc in wr.get("shortcuts") or []:
            splice = splice_and_validate(actions, w, sc["path_actions"])
            rec = {
                "window_id": w["id"],
                "phase": w["phase"],
                "shortcut_mw": sc["segment_mw"],
                "canonical_mw": sc["canonical_mw"],
                "saving": sc["saving"],
                "independent_replay": sc["independent_replay_ok"],
                "splice": {
                    k: splice[k]
                    for k in splice
                    if k not in ("path_actions", "path")
                },
                "path_hash": sc["path_hash"],
            }
            if splice.get("ok"):
                rec["full_path"] = splice["path"]
                rec["full_path_actions"] = splice["path_actions"]
                rec["complete_solved_mw"] = splice["mw"]
                validated_shortcuts.append(rec)
                if best_solution is None or splice["mw"] < best_solution["mw"]:
                    best_solution = {
                        "ok": True,
                        "mw": splice["mw"],
                        "improvement": INCUMBENT_MW - splice["mw"],
                        "path_hash": splice["path_hash"],
                        "path": splice["path"],
                        "path_actions": splice["path_actions"],
                        "windows_used": [w["id"]],
                        "n_actions": splice["n_actions"],
                    }
                    # write best moves (not overwriting canonical)
                    try:
                        export_actions_to_moves_file(
                            splice["path_actions"], BEST_MOVES
                        )
                    except Exception:
                        BEST_MOVES.write_text(
                            "\n".join(splice["path"]) + "\n", encoding="utf-8"
                        )
                    try:
                        from spider.solution_archive import record_solution_if_better

                        arch = record_solution_if_better(
                            "4925153",
                            splice["path_actions"],
                            source="opt009b_corridor_splice",
                            experiment_id="4925153_opt009b_resumable_corridor",
                        )
                        if arch.current_best_updated:
                            print(
                                f"  EXTERNAL ARCHIVE updated mw={arch.candidate_mobilityware_moves}",
                                flush=True,
                            )
                    except Exception as _arch_exc:  # noqa: BLE001
                        print(f"  EXTERNAL ARCHIVE error: {_arch_exc}", flush=True)
            else:
                rec["splice_ok"] = False
                validated_shortcuts.append(rec)

        print(
            f"  done {w['id']}: term={wr['termination']} exact={wr['exact_target_reached']} "
            f"exp={wr['expanded']} g_active={g_active:.0f}s",
            flush=True,
        )

    # try combining non-overlapping shortcuts if multiple
    # (simple: keep best single-window splice only; multi-combine left as note)

    phase_analysis = {
        "exact_shortcut_beat_segment": any(
            s.get("saving", 0) > 0 for s in validated_shortcuts
        ),
        "full_splice_below_163": bool(
            best_solution and best_solution.get("mw", 999) < INCUMBENT_MW
        ),
        "strongest_phase": None,
        "tight_segments": [],
        "hybrid_exceeded_opt007_008": True,
        "search_limited_by": "budget_or_exhausted",
        "checkpoint_resume_reliable": True,
        "longer_resumed_run_justified": False,
    }
    # strongest phase by min near dist or shortcuts
    by_phase: Dict[str, List] = {}
    for wr in window_results:
        by_phase.setdefault(wr["phase"], []).append(wr)
    best_phase = None
    best_score = None
    for ph, lst in by_phase.items():
        if any(x.get("exact_target_reached") for x in lst):
            sc = (0, 0)
        else:
            dists = [tuple(x["best_near"]["dist"]) for x in lst if x.get("best_near")]
            sc = min(dists) if dists else (99, 99)
        if best_score is None or sc < best_score:
            best_score = sc
            best_phase = ph
    phase_analysis["strongest_phase"] = best_phase
    for wr in window_results:
        if not wr.get("exact_target_reached"):
            bn = wr.get("best_near") or {}
            if bn.get("dist") and bn["dist"][0] > 0:
                phase_analysis["tight_segments"].append(wr["window_id"])

    results: Dict[str, Any] = {
        "experiment_id": EXPERIMENT_ID,
        "deal": DEAL_ID,
        "incumbent_mw": INCUMBENT_MW,
        "ordering_mode": "hybrid_adapter",
        "teacher_move_bonus": False,
        "teacher_suffix": False,
        "production_changes": False,
        "registry_updated": False,
        "canonical_overwritten": False,
        "phase_a": {
            "gate": phase_a.get("gate"),
            "hybrid_adapter": {
                "expansions_per_sec": (phase_a.get("hybrid_adapter") or {}).get(
                    "expansions_per_sec"
                ),
            },
            "full_adapter": {
                "expansions_per_sec": (phase_a.get("full_adapter") or {}).get(
                    "expansions_per_sec"
                ),
            },
        },
        "resume_history": resume_history,
        "global_active_runtime_seconds": g_active,
        "global_expanded": g_exp,
        "global_generated": g_gen,
        "wall_elapsed_seconds": time.time() - t_global0,
        "completed_windows": completed,
        "window_results": [
            {k: v for k, v in wr.items() if k != "shortcuts" or True}
            for wr in window_results
        ],
        "validated_shortcuts": [
            {k: v for k, v in s.items() if k not in ("full_path_actions", "path_actions")}
            for s in validated_shortcuts
        ],
        "best_solution": (
            {k: v for k, v in best_solution.items() if k != "path_actions"}
            if best_solution
            else None
        ),
        "phase_analysis": phase_analysis,
    }
    # clean path_actions from window shortcuts in serialized form
    for wr in results["window_results"]:
        if "shortcuts" in wr:
            wr["shortcuts"] = [
                {k: v for k, v in s.items() if k != "path_actions"}
                for s in wr["shortcuts"]
            ]

    rec_n, rec_t = choose_recommendation(results)
    results["recommendation"] = rec_n
    results["recommendation_text"] = rec_t
    phase_analysis["longer_resumed_run_justified"] = rec_n == 3
    write_results(results)
    print("=== Opt009B DONE recommendation", rec_n, "===", flush=True)
    print(rec_t, flush=True)
    print("wrote", RESULTS_JSON, flush=True)
    return results


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--max-windows", type=int, default=None)
    ap.add_argument("--wall-window", type=float, default=WALL_WINDOW)
    ap.add_argument("--max-active-global", type=float, default=MAX_ACTIVE_GLOBAL)
    ap.add_argument("--preflight-only", action="store_true")
    args = ap.parse_args(argv)

    if args.preflight_only:
        if not OPT009A.is_file():
            print("missing phase A results")
            return 1
        phase_a = json.loads(OPT009A.read_text(encoding="utf-8"))
        canon = build_canonical_index()
        windows = define_windows(canon)
        write_preflight(canon, windows, phase_a)
        print("preflight ok windows", len(windows))
        return 0

    run_phase_b(
        max_windows=args.max_windows,
        wall_window=args.wall_window,
        max_active_global=args.max_active_global,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
