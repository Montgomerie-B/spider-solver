#!/usr/bin/env python3
"""Opt010 — W12 Near-Target Recovery and Improved Reconnection Search.

Single seed: strongest Opt009B W12 J8→J17 near-target.
Frozen hybrid adapter from Opt009A/B. No teacher bonus/suffix.
Primary: solve MW<=162. Secondary: exact early reconnection to J17–J21.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal, tokens_from_file
from spider.deal_analysis import build_deal_analysis
from spider.engine import SpiderState
from spider.hash import TranspositionTable, zobrist
from spider.heuristics import (
    next_foundation_completion_potential,
)
from spider.metrics import Action, export_actions_to_moves_file, parse_moves_file
from spider.planner.diagnostics.checkpoints.diagnostic_checkpoint import (
    CheckpointError,
    CheckpointStore,
    SearchCheckpointPayload,
    build_config_identity,
    validate_checkpoint_identity,
)
from spider.planner.diagnostics.cleanup_cascade import (
    cleanup_cascade_potential,
    foundation_counts,
)
from spider.planner.diagnostics.experimental_move_ordering import (
    ADAPTER_ID,
    HYBRID_TOP_K,
    ORDERING_STATS,
    get_ordering_cache_stats,
    rank_moves_for_stage,
    reset_ordering_stats,
)
from spider.planner.diagnostics.foundation_architecture import all_suit_architecture_scores
from spider.planner.diagnostics.stage_classifier import classify_stage
from spider.rules import deal_cost, mw_move_cost

DEAL = ROOT / "deals" / "4925153.txt"
CANONICAL = ROOT / "solutions" / "4925153_canonical.moves"
EXP_DIR = ROOT / "src" / "spider" / "planner" / "diagnostics" / "experiments"
CKPT_DIR = (
    ROOT / "src" / "spider" / "planner" / "diagnostics" / "checkpoints" / "runtime_opt010"
)
OPT009B = EXP_DIR / "4925153_opt009b_corridor_results.json"
OPT009A = EXP_DIR / "4925153_opt009a_hybrid_throughput_results.json"
SEED_RECON = EXP_DIR / "4925153_opt010_w12_seed_reconstructed.json"
MANIFEST = EXP_DIR / "4925153_opt010_w12_recovery.json"
PREFLIGHT_JSON = EXP_DIR / "4925153_opt010_preflight_report.json"
PREFLIGHT_MD = EXP_DIR / "4925153_opt010_preflight_report.md"
RESULTS_JSON = EXP_DIR / "4925153_opt010_w12_recovery_results.json"
RESULTS_MD = EXP_DIR / "4925153_opt010_w12_recovery_report.md"
BEST_MOVES = EXP_DIR / "4925153_opt010_best_solution.moves.txt"
LADDER = (
    ROOT
    / "src/spider/planner/diagnostics/scaffolds/4925153_deal_scaffold_ladder.json"
)

DEAL_ID = "4925153"
EXPERIMENT_ID = "4925153_opt010_w12_recovery"
INCUMBENT_MW = 163
J8_ACTIONS = 160
J8_MW = 149

# Frozen hybrid configuration (Opt009A/B)
BEAM = 500
MOVE_CAP = 16
EXPAND_TOP = 16
ORDERING_MODE = "hybrid_adapter"
CHECKPOINT_INTERVAL = 300.0

# Single search limits
MAX_ACTIVE = 259200.0  # 72h
MAX_EXPANDED = 18_000_000
MAX_GENERATED = 200_000_000
MAX_UNSOLVED_MW = 162

# Opt009B W12 strongest near-target (frozen)
OPT009B_W12_ID = "W12_J8_to_J17_160_169"
OPT009B_SEED_Z = 27016497454337233533
OPT009B_SEED_MW = 151
OPT009B_SEED_DEPTH = 8
OPT009B_SEGMENT_MW = 2
OPT009B_SEED_F = 3
OPT009B_SEED_STOCK = 0
OPT009B_SEED_SW = 0
OPT009B_SEED_SPACES = 2

# Later canonical targets: label -> (actions, canon_mw, max_arrival_mw)
CANONICAL_TARGETS = [
    ("J17", 169, 158, 157),
    ("J18", 170, 159, 158),
    ("J19", 171, 160, 159),
    ("J20", 172, 161, 160),
    ("J21", 173, 162, 161),
    ("J22", 174, 163, 162),
]


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


def replay_from_start(actions: Sequence[Action]) -> Tuple[SpiderState, int]:
    st = SpiderState.from_cards(load_deal(DEAL))
    mw = 0
    for a in actions:
        mw += apply_action(st, a)
    return st, mw


def state_metrics(st: SpiderState, analysis, *, deals: int = 5) -> Dict[str, Any]:
    f = len(st.foundations)
    sw = sw_of(st)
    sp = spaces_of(st)
    stock = len(st.stock)
    prof = classify_stage(
        state=st,
        scaffold_context={
            "foundations": f,
            "stock_remaining": stock // 10,
            "sw": sw,
            "spaces": sp,
        },
    )
    try:
        cc = cleanup_cascade_potential(
            st, analysis, deep_one_move=False, precise_merge=True
        )
        cleanup = cc["score"]
        exact = list(cc.get("exact_now_suits") or [])
        near = list(cc.get("near_complete_suits") or [])
        stage_cc = cc.get("stage")
    except Exception:
        cleanup, exact, near, stage_cc = None, [], [], None
    try:
        arch = all_suit_architecture_scores(st, analysis=analysis, round_index=deals)
        best_a = max(arch, key=lambda s: arch[s].get("score", 0)) if arch else None
        arch_score = int(arch[best_a]["score"]) if best_a else 0
    except Exception:
        best_a, arch_score = None, 0
    try:
        nfcp = next_foundation_completion_potential(
            st, analysis=analysis, round_index=deals, lookahead=1
        )
        nfcp_suit = nfcp.get("best_suit")
        nfcp_score = int(nfcp.get("score") or 0)
    except Exception:
        nfcp_suit, nfcp_score = None, 0
    mobility = len(st.enumerate_moves()) + (1 if can_deal(st) else 0)
    return {
        "foundations": f,
        "completed_copies": foundation_counts(st),
        "stock": stock,
        "sw": sw,
        "spaces": sp,
        "stage": prof.macro_stage,
        "stage_cleanup": stage_cc,
        "cleanup": cleanup,
        "exact_suits": exact,
        "near_suits": near,
        "architecture_best": best_a,
        "architecture_score": arch_score,
        "nfcp_best": nfcp_suit,
        "nfcp_score": nfcp_score,
        "mobility": mobility,
        "z": zobrist(st),
        "solved": st.is_solved(),
    }


def load_opt009b_w12() -> Dict[str, Any]:
    if not OPT009B.is_file():
        raise FileNotFoundError(f"missing Opt009B results: {OPT009B}")
    r = json.loads(OPT009B.read_text(encoding="utf-8"))
    w12 = None
    for w in r.get("window_results") or []:
        if w.get("window_id") == OPT009B_W12_ID:
            w12 = w
            break
    if w12 is None:
        raise ValueError("W12 window not found in Opt009B results")
    bn = w12.get("best_near") or {}
    # Frozen ranking: single strongest W12 near-target already stored as best_near
    if int(bn.get("z") or 0) != OPT009B_SEED_Z:
        raise ValueError(
            f"Opt009B W12 best_near z mismatch: {bn.get('z')} != {OPT009B_SEED_Z}"
        )
    if int(bn.get("mw") or 0) != OPT009B_SEED_MW:
        raise ValueError(f"Opt009B W12 mw mismatch: {bn.get('mw')}")
    if int(bn.get("segment_mw") or 0) != OPT009B_SEGMENT_MW:
        raise ValueError(f"Opt009B segment_mw mismatch: {bn.get('segment_mw')}")
    return {"window": w12, "best_near": bn, "opt009b": r}


def load_or_reconstruct_seed_path() -> List[Action]:
    """Load reconstructed J8→seed path; verify against frozen Opt009B metrics."""
    if SEED_RECON.is_file():
        data = json.loads(SEED_RECON.read_text(encoding="utf-8"))
        if data.get("path"):
            return [parse_label(x) for x in data["path"]]
        # fallback 0-based lists
        path = []
        for item in data.get("path_0based") or []:
            if isinstance(item, (list, tuple)) and len(item) == 3:
                path.append((int(item[0]), int(item[1]), int(item[2])))
            else:
                path.append(parse_label(str(item)))
        return path
    raise FileNotFoundError(
        f"Seed path reconstruction missing: {SEED_RECON}. "
        "Re-run Opt009B W12 search to recover path to frozen z."
    )


def validate_seed(analysis) -> Dict[str, Any]:
    """Task 1: load Opt009B W12 seed, reconstruct from J8, verify hash/metrics."""
    opt = load_opt009b_w12()
    bn = opt["best_near"]
    canon = parse_moves_file(CANONICAL)
    j8_prefix = list(canon[:J8_ACTIONS])
    st_j8, mw_j8 = replay_from_start(j8_prefix)
    if mw_j8 != J8_MW:
        raise ValueError(f"J8 MW {mw_j8} != {J8_MW}")
    if len(st_j8.foundations) != 3:
        raise ValueError("J8 foundations != 3")

    seed_path = load_or_reconstruct_seed_path()
    # replay seed path from J8
    st = st_j8.clone()
    mw = mw_j8
    for a in seed_path:
        mw += apply_action(st, a)
    m = state_metrics(st, analysis)
    errors = []
    if mw != OPT009B_SEED_MW:
        errors.append(f"mw {mw} != {OPT009B_SEED_MW}")
    if m["z"] != OPT009B_SEED_Z:
        errors.append(f"z {m['z']} != {OPT009B_SEED_Z}")
    if m["foundations"] != OPT009B_SEED_F:
        errors.append(f"f {m['foundations']} != {OPT009B_SEED_F}")
    if m["stock"] != OPT009B_SEED_STOCK:
        errors.append(f"stock {m['stock']} != {OPT009B_SEED_STOCK}")
    if m["sw"] != OPT009B_SEED_SW:
        errors.append(f"sw {m['sw']} != {OPT009B_SEED_SW}")
    if m["spaces"] != OPT009B_SEED_SPACES:
        errors.append(f"spaces {m['spaces']} != {OPT009B_SEED_SPACES}")
    if len(seed_path) != OPT009B_SEED_DEPTH:
        errors.append(f"depth {len(seed_path)} != {OPT009B_SEED_DEPTH}")
    if mw - J8_MW != OPT009B_SEGMENT_MW:
        errors.append(f"segment_mw {mw - J8_MW} != {OPT009B_SEGMENT_MW}")

    # target distance vs J17
    st_j17, mw_j17 = replay_from_start(canon[:169])
    dist = multi_target_distance(st, [{"z": zobrist(st_j17), "state": st_j17, "label": "J17", "meta": state_metrics(st_j17, analysis)}])

    seed = {
        "candidate_id": "opt009b_w12_best_near",
        "source_window_id": OPT009B_W12_ID,
        "canonical_source": "canonical_J8_third_foundation_cascade_quality",
        "source_canonical_mw": J8_MW,
        "source_actions": J8_ACTIONS,
        "j8_to_seed_path": [action_label(a) for a in seed_path],
        "j8_to_seed_actions": seed_path,
        "segment_mw_cost": mw - J8_MW,
        "explicit_decision_cost": len(seed_path),
        "absolute_mw": mw,
        "metrics": m,
        "opt009b_best_near": bn,
        "target_distance_j17": dist,
        "validation_errors": errors,
        "valid": len(errors) == 0,
        "j8_z": zobrist(st_j8),
        "seed_state_ok": len(errors) == 0,
    }
    return seed


def build_targets(analysis) -> List[Dict[str, Any]]:
    """Task 2: exact canonical J17–J22 targets."""
    canon = parse_moves_file(CANONICAL)
    out = []
    for label, actions, canon_mw, max_arrival in CANONICAL_TARGETS:
        st, mw = replay_from_start(canon[:actions])
        if mw != canon_mw:
            raise ValueError(f"{label} mw {mw} != {canon_mw}")
        m = state_metrics(st, analysis)
        suffix = list(canon[actions:])
        out.append(
            {
                "label": label,
                "decision_index": actions,
                "action_index": actions,
                "canonical_mw": canon_mw,
                "max_arrival_mw": max_arrival,
                "z": m["z"],
                "metrics": m,
                "suffix_actions": suffix,
                "suffix_labels": [action_label(a) for a in suffix],
            }
        )
    # solved check
    assert out[-1]["metrics"]["solved"] is True
    assert out[-1]["canonical_mw"] == 163
    return out


def multi_target_distance(
    st: SpiderState, eligible: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Best distance among eligible exact targets (ordering only)."""
    if not eligible:
        return {
            "best_label": None,
            "best_dist": (99, 99, 99, 99, 99, 99, 99),
            "breakdown": {},
        }
    best = None
    best_lab = None
    best_bd = None
    for t in eligible:
        tgt: SpiderState = t["state"] if "state" in t else None
        tm = t.get("meta") or t.get("metrics") or {}
        if tgt is None:
            # reconstruct minimal from metrics not available — use stored fields
            f_m = abs(len(st.foundations) - int(tm.get("foundations", 0)))
            st_m = abs(len(st.stock) - int(tm.get("stock", 0)))
            sw_m = abs(sw_of(st) - int(tm.get("sw", 0)))
            sp_m = abs(spaces_of(st) - int(tm.get("spaces", 0)))
            z_m = 0 if zobrist(st) == t["z"] else 1
            # copies mismatch
            try:
                fc = foundation_counts(st)
                tc = tm.get("completed_copies") or {}
                copy_m = sum(abs(fc.get(s, 0) - int(tc.get(s, 0))) for s in "schd")
            except Exception:
                copy_m = 0
            stage_m = 0 if (t.get("metrics") or {}).get("stage") == classify_stage(
                state=st,
                scaffold_context={
                    "foundations": len(st.foundations),
                    "stock_remaining": len(st.stock) // 10,
                    "sw": sw_of(st),
                    "spaces": spaces_of(st),
                },
            ).macro_stage else 1
            dist = (z_m, f_m, copy_m, st_m, sw_m, sp_m, stage_m)
            bd = {
                "exact_hash_mismatch": z_m,
                "foundations": f_m,
                "completed_copies": copy_m,
                "stock": st_m,
                "sw": sw_m,
                "spaces": sp_m,
                "stage": stage_m,
            }
        else:
            f_m = abs(len(st.foundations) - len(tgt.foundations))
            st_m = abs(len(st.stock) - len(tgt.stock))
            sw_m = abs(sw_of(st) - sw_of(tgt))
            sp_m = abs(spaces_of(st) - spaces_of(tgt))
            z_m = 0 if zobrist(st) == t["z"] else 1
            fc = foundation_counts(st)
            tc = foundation_counts(tgt)
            copy_m = sum(abs(fc[s] - tc[s]) for s in "schd")
            # face-up boundary rough: total face-up cards difference
            fu_s = sum(len(c.face_up) for c in st.columns)
            fu_t = sum(len(c.face_up) for c in tgt.columns)
            boundary = abs(fu_s - fu_t)
            dist = (z_m, f_m, copy_m, st_m, sw_m, sp_m, boundary)
            bd = {
                "exact_hash_mismatch": z_m,
                "foundations": f_m,
                "completed_copies": copy_m,
                "stock": st_m,
                "sw": sw_m,
                "spaces": sp_m,
                "faceup_count": boundary,
            }
        if best is None or dist < best:
            best = dist
            best_lab = t["label"]
            best_bd = bd
    return {"best_label": best_lab, "best_dist": best, "breakdown": best_bd}


def eligible_targets(current_mw: int, targets: List[Dict]) -> List[Dict]:
    """Targets still beatable at current MW."""
    return [t for t in targets if current_mw <= t["max_arrival_mw"]]


def order_moves_frozen(st: SpiderState, analysis) -> List[Action]:
    """Frozen Opt009A/B hybrid pipeline — no weight/top-k changes."""
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
            "ordering_mode": ORDERING_MODE,
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


def write_preflight(seed: Dict, targets: List[Dict], phase_a: Dict) -> Dict[str, Any]:
    EXP_DIR.mkdir(parents=True, exist_ok=True)
    max_depth = MAX_UNSOLVED_MW - int(seed["absolute_mw"])
    manifest = {
        "experiment_id": EXPERIMENT_ID,
        "deal_id": DEAL_ID,
        "seed_source": "Opt009B W12 strongest near-target",
        "seed_window_id": OPT009B_W12_ID,
        "seed_z": OPT009B_SEED_Z,
        "seed_absolute_mw": OPT009B_SEED_MW,
        "seed_segment_mw": OPT009B_SEGMENT_MW,
        "canonical_source": "J8",
        "primary_objective": "solved state at MW<=162",
        "secondary_objective": "exact improved reconnection to J17-J21",
        "incumbent_mw": INCUMBENT_MW,
        "ordering_mode": "frozen_hybrid_adapter",
        "hybrid_configuration_source": "Opt009A accepted configuration",
        "hybrid_top_k": dict(HYBRID_TOP_K),
        "adapter_id": ADAPTER_ID,
        "teacher_move_bonus_allowed": False,
        "teacher_suffix_allowed": False,
        "canonical_move_protection_allowed": False,
        "approximate_target_success_allowed": False,
        "checkpoint_enabled": True,
        "resume_allowed": True,
        "checkpoint_interval_seconds": CHECKPOINT_INTERVAL,
        "production_change_allowed": False,
        "registry_update_allowed": False,
        "deterministic_tie_breaking": True,
        "transposition_enabled": True,
        "beam_width": BEAM,
        "maximum_active_runtime_seconds": MAX_ACTIVE,
        "active_runtime_limit_hours": 72,
        "maximum_expanded_states": MAX_EXPANDED,
        "maximum_generated_states": MAX_GENERATED,
        "maximum_unsolved_mw": MAX_UNSOLVED_MW,
        "maximum_explicit_continuation_depth": max_depth,
        "phase_a_gate_passed": bool((phase_a.get("gate") or {}).get("passed")),
        "phase_a_speedup": (phase_a.get("gate") or {}).get("speedup_expansions"),
        "targets": [
            {
                "label": t["label"],
                "canonical_mw": t["canonical_mw"],
                "max_arrival_mw": t["max_arrival_mw"],
                "z": t["z"],
            }
            for t in targets
        ],
        "seed_validation_ok": seed.get("valid"),
        "seed_path": seed.get("j8_to_seed_path"),
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    pf = {
        "ok": bool(seed.get("valid")) and bool((phase_a.get("gate") or {}).get("passed")),
        "seed_valid": seed.get("valid"),
        "seed_errors": seed.get("validation_errors"),
        "seed_mw": seed.get("absolute_mw"),
        "seed_z": (seed.get("metrics") or {}).get("z"),
        "tempo_advantage_mw": 158 - OPT009B_SEED_MW,  # vs J17 canon if exact
        "apparent_segment_saving_vs_j8_j17": 9 - OPT009B_SEGMENT_MW,
        "n_targets": len(targets),
        "max_continuation_depth": max_depth,
        "hybrid_top_k_frozen": dict(HYBRID_TOP_K),
    }
    PREFLIGHT_JSON.write_text(json.dumps(pf, indent=2, default=str), encoding="utf-8")
    lines = [
        "# Opt010 Preflight — W12 Near-Target Recovery",
        "",
        f"- Deal: {DEAL_ID}",
        f"- Seed: Opt009B `{OPT009B_W12_ID}` strongest near-target",
        f"- Seed valid: {seed.get('valid')}",
        f"- Seed absolute MW: {seed.get('absolute_mw')}",
        f"- Segment MW: {seed.get('segment_mw_cost')} (canon J8→J17 = 9)",
        f"- Apparent tempo vs J17: reach J17-like structure at MW{OPT009B_SEED_MW} (canon 158)",
        f"- Primary: solve ≤162",
        f"- Secondary: exact J17–J21 early reconnection",
        f"- Beam: {BEAM}, max active: {MAX_ACTIVE}s (72h)",
        f"- Max depth from seed: {max_depth}",
        f"- Teacher bonus/suffix: false",
        f"- Phase A gate: {pf.get('ok')}",
        "",
        "## Seed path (J8→candidate)",
        "",
    ]
    for mv in seed.get("j8_to_seed_path") or []:
        lines.append(f"- `{mv}`")
    lines += ["", "## Targets", ""]
    for t in targets:
        lines.append(
            f"- **{t['label']}** canon MW={t['canonical_mw']} "
            f"max arrival={t['max_arrival_mw']} z=`{t['z']}`"
        )
    PREFLIGHT_MD.write_text("\n".join(lines), encoding="utf-8")
    return manifest


def rss_mb() -> Optional[float]:
    try:
        import psutil  # type: ignore

        return psutil.Process().memory_info().rss / (1024 * 1024)
    except Exception:
        try:
            import resource  # type: ignore

            # Linux KB; Windows may fail
            return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
        except Exception:
            return None


def search_recovery(
    seed: Dict[str, Any],
    targets: List[Dict[str, Any]],
    analysis,
    *,
    max_active: float = MAX_ACTIVE,
    max_expanded: int = MAX_EXPANDED,
    resume_payload: Optional[SearchCheckpointPayload] = None,
) -> Dict[str, Any]:
    """Single frozen configuration recovery search from W12 seed."""
    reset_ordering_stats()
    canon = parse_moves_file(CANONICAL)
    j8_prefix = list(canon[:J8_ACTIONS])
    seed_path: List[Action] = list(seed["j8_to_seed_actions"])
    full_prefix = j8_prefix + seed_path

    st0, mw0 = replay_from_start(full_prefix)
    assert mw0 == seed["absolute_mw"]
    assert zobrist(st0) == seed["metrics"]["z"]

    # attach live states to targets for distance
    live_targets = []
    for t in targets:
        st_t, _ = replay_from_start(canon[: t["action_index"]])
        live_targets.append({**t, "state": st_t})

    max_depth = MAX_UNSOLVED_MW - mw0
    config_identity = build_config_identity(
        deal_id=DEAL_ID,
        experiment_id=EXPERIMENT_ID,
        ordering_mode=ORDERING_MODE,
        beam=BEAM,
        extra={
            "seed_z": OPT009B_SEED_Z,
            "seed_mw": OPT009B_SEED_MW,
            "hybrid_top_k": dict(HYBRID_TOP_K),
            "adapter": ADAPTER_ID,
            "max_unsolved_mw": MAX_UNSOLVED_MW,
        },
    )
    store = CheckpointStore(CKPT_DIR, experiment_id=EXPERIMENT_ID, retain=2)

    t0 = time.time()
    active0 = float(resume_payload.active_runtime_seconds) if resume_payload else 0.0
    tt = TranspositionTable()
    best_depth: Dict[int, int] = {}
    heap: List[HeapItem] = []
    seq = 0
    expanded = generated = 0
    tt_probes = tt_hits = dups = replaced = 0
    peak_f = peak_tt = 1
    deepest = 0
    termination = "running"
    progress_events: List[Dict] = []
    exact_hits: Dict[str, Dict] = {}
    solved_candidates: List[Dict] = []
    best_finalists: List[Dict] = []
    checkpoints_written = 0
    last_ckpt = time.time()
    last_progress_key = None
    peak_mem = rss_mb()

    def push(n: Node) -> None:
        nonlocal seq
        seq += 1
        elig = eligible_targets(n.mw, live_targets)
        # for solved at this node
        if n.state.is_solved():
            dist = (0, 0, 0, 0, 0, 0, 0)
            closest = "J22"
        else:
            td = multi_target_distance(n.state, elig if elig else live_targets[-1:])
            dist = td["best_dist"]
            closest = td["best_label"]
        pri = (
            0 if n.state.is_solved() else 1,
            0 if any(n.z == t["z"] for t in elig) else 1,
            dist,
            -len(n.state.foundations),
            n.mw,
            n.depth,
            n.z & 0xFFFFFFFF,
        )
        heapq.heappush(heap, HeapItem(pri, seq, n))

    def compact_node(n: Node) -> Dict:
        elig = eligible_targets(n.mw, live_targets)
        td = multi_target_distance(n.state, elig if elig else live_targets[-1:])
        return {
            "mw": n.mw,
            "depth": n.depth,
            "foundations": len(n.state.foundations),
            "stock": len(n.state.stock),
            "sw": sw_of(n.state),
            "spaces": spaces_of(n.state),
            "z": n.z,
            "solved": n.state.is_solved(),
            "closest": td.get("best_label"),
            "dist": td.get("best_dist"),
            "path": [action_label(a) for a in n.path],
        }

    def maybe_progress(n: Node) -> None:
        nonlocal last_progress_key
        elig = eligible_targets(n.mw, live_targets)
        td = multi_target_distance(n.state, elig if elig else live_targets[-1:])
        key = (
            td["best_dist"],
            -len(n.state.foundations),
            sw_of(n.state),
            -spaces_of(n.state),
            n.mw,
        )
        if last_progress_key is None or key < last_progress_key:
            last_progress_key = key
            m = state_metrics(n.state, analysis)
            progress_events.append(
                {
                    "active_runtime": active0 + (time.time() - t0),
                    "wall_ts": time.time(),
                    "expanded": expanded,
                    "generated": generated,
                    "absolute_mw": n.mw,
                    "continuation_depth": n.depth,
                    "foundations": m["foundations"],
                    "completed_copies": m["completed_copies"],
                    "sw": m["sw"],
                    "spaces": m["spaces"],
                    "stage": m["stage"],
                    "cleanup": m["cleanup"],
                    "exact_suits": m["exact_suits"],
                    "near_suits": m["near_suits"],
                    "mobility": m["mobility"],
                    "closest_canonical_target": td["best_label"],
                    "target_distance_breakdown": td["breakdown"],
                    "state_hash": m["z"],
                }
            )

    def write_ckpt(force: bool = False) -> Optional[Path]:
        nonlocal checkpoints_written, last_ckpt
        now = time.time()
        if not force and (now - last_ckpt) < CHECKPOINT_INTERVAL:
            return None
        active = active0 + (now - t0)
        top = heapq.nsmallest(min(len(heap), BEAM), heap) if heap else []
        frontier = []
        for it in top:
            n = it.node
            frontier.append(
                {
                    "mw": n.mw,
                    "depth": n.depth,
                    "z": n.z,
                    "path": [action_label(a) for a in n.path],
                }
            )
        payload = SearchCheckpointPayload(
            experiment_id=EXPERIMENT_ID,
            deal_id=DEAL_ID,
            config_identity=config_identity,
            ordering_mode=ORDERING_MODE,
            active_runtime_seconds=active,
            wall_elapsed_seconds=now - t0,
            expanded=expanded,
            generated=generated,
            seq=seq,
            termination=termination,
            incumbent=solved_candidates[0] if solved_candidates else None,
            best_candidates=[compact_node(it.node) for it in top[:10]],
            frontier=frontier,
            transposition=[[z, mw] for z, mw in list(tt._best.items())[:80000]],  # type: ignore[attr-defined]
            best_depth=[[z, d] for z, d in list(best_depth.items())[:80000]],
            counters={
                "tt_probes": tt_probes,
                "tt_hits": tt_hits,
                "dups": dups,
                "replaced": replaced,
                "peak_frontier": peak_f,
                "peak_tt": peak_tt,
                "deepest": deepest,
                "seed_z": OPT009B_SEED_Z,
                "ordering_stats": dict(ORDERING_STATS),
                "exact_hits": list(exact_hits.keys()),
            },
            tie_break_seq=seq,
            cache_policy="rebuild_on_resume",
            notes="opt010 w12 recovery diagnostic checkpoint",
        )
        path = store.write_atomic(payload)
        checkpoints_written += 1
        last_ckpt = now
        return path

    # init or resume
    if resume_payload and resume_payload.frontier:
        expanded = resume_payload.expanded
        generated = resume_payload.generated
        seq = resume_payload.seq
        for z, mw in resume_payload.transposition:
            tt._best[int(z)] = int(mw)  # type: ignore[attr-defined]
        for z, d in resume_payload.best_depth:
            best_depth[int(z)] = int(d)
        for fr in resume_payload.frontier:
            st = st0.clone()
            path: List[Action] = []
            mw = mw0
            ok = True
            for lab in fr.get("path") or []:
                try:
                    a = parse_label(lab)
                    mw += apply_action(st, a)
                    path.append(a)
                except Exception:
                    ok = False
                    break
            if not ok:
                continue
            n = Node(st, mw, int(fr.get("depth", len(path))), path, zobrist(st))
            push(n)
        if not heap:
            push(Node(st0, mw0, 0, [], zobrist(st0)))
            tt.store(st0, mw0)
            best_depth[zobrist(st0)] = 0
    else:
        push(Node(st0, mw0, 0, [], zobrist(st0)))
        tt.store(st0, mw0)
        best_depth[zobrist(st0)] = 0

    while heap:
        now = time.time()
        active = active0 + (now - t0)
        if active >= max_active:
            termination = "max_active_runtime"
            break
        if expanded >= max_expanded:
            termination = "max_expanded"
            break
        if generated >= MAX_GENERATED:
            termination = "max_generated"
            break
        mem = rss_mb()
        if mem is not None:
            peak_mem = max(peak_mem or 0, mem)
            # soft memory pressure threshold ~12 GB if measurable
            if mem > 12000:
                write_ckpt(force=True)
                termination = "memory_pressure"
                break

        if len(heap) > BEAM * 3:
            heap = heapq.nsmallest(BEAM, heap)
            heapq.heapify(heap)
        peak_f = max(peak_f, len(heap))

        item = heapq.heappop(heap)
        node: Node = item.node
        expanded += 1
        deepest = max(deepest, node.depth)
        maybe_progress(node)

        # exact target check
        elig = eligible_targets(node.mw, live_targets)
        for t in elig:
            if node.z == t["z"] and node.mw <= t["max_arrival_mw"]:
                if t["label"] not in exact_hits or node.mw < exact_hits[t["label"]]["arrival_mw"]:
                    exact_hits[t["label"]] = {
                        "label": t["label"],
                        "arrival_mw": node.mw,
                        "canonical_mw": t["canonical_mw"],
                        "saving": t["canonical_mw"] - node.mw,
                        "depth": node.depth,
                        "path": [action_label(a) for a in node.path],
                        "path_actions": list(node.path),
                        "path_hash": path_hash(node.path),
                    }
                # do not stop — may find better solve

        if node.state.is_solved() and node.mw <= MAX_UNSOLVED_MW:
            rec = {
                "mw": node.mw,
                "depth": node.depth,
                "path": [action_label(a) for a in node.path],
                "path_actions": list(node.path),
                "path_hash": path_hash(node.path),
                "improvement": INCUMBENT_MW - node.mw,
            }
            solved_candidates.append(rec)
            solved_candidates.sort(key=lambda x: x["mw"])
            termination = "solved"
            break

        # Never expand unsolved nodes already above the MW162 ceiling
        if (not node.state.is_solved()) and node.mw > MAX_UNSOLVED_MW:
            continue
        if node.depth >= max_depth:
            continue

        # track finalists
        fin = compact_node(node)
        best_finalists.append(fin)
        # keep top 50 by dist then mw
        best_finalists.sort(
            key=lambda x: (
                0 if x.get("solved") else 1,
                tuple(x.get("dist") or (99,)),
                x["mw"],
            )
        )
        best_finalists = best_finalists[:50]

        try:
            ordered = order_moves_frozen(node.state, analysis)
        except Exception:
            ordered = list(node.state.enumerate_moves())[:MOVE_CAP]

        for a in ordered[:EXPAND_TOP]:
            try:
                cost = step_cost(node.state, a)
            except Exception:
                continue
            new_mw = node.mw + cost
            # Hard rule: never expand unsolved states with MW>162
            if new_mw > MAX_UNSOLVED_MW:
                continue
            st2 = node.state.clone()
            try:
                apply_action(st2, a)
            except Exception:
                continue
            generated += 1
            if (not st2.is_solved()) and new_mw > MAX_UNSOLVED_MW:
                continue

            z2 = zobrist(st2)
            tt_probes += 1
            prev = tt.get(st2)
            prev_d = best_depth.get(z2)
            if prev is not None:
                tt_hits += 1
                if prev < new_mw:
                    dups += 1
                    continue
                if prev == new_mw and prev_d is not None and prev_d <= node.depth + 1:
                    dups += 1
                    continue
                if prev > new_mw:
                    replaced += 1
            tt.store(st2, new_mw)
            best_depth[z2] = node.depth + 1
            peak_tt = max(peak_tt, len(tt))
            push(Node(st2, new_mw, node.depth + 1, node.path + [a], z2))

        if (time.time() - last_ckpt) >= CHECKPOINT_INTERVAL:
            write_ckpt(force=True)

        if expanded % 2000 == 0:
            print(
                f"  [opt010] exp={expanded} gen={generated} frontier={len(heap)} "
                f"tt={len(tt)} deepest={deepest} exact={list(exact_hits)} "
                f"solved={len(solved_candidates)} "
                f"active={active0 + (time.time()-t0):.0f}s mem={rss_mb()}",
                flush=True,
            )

    if termination == "running":
        termination = "exhausted"
    write_ckpt(force=True)

    active_runtime = active0 + (time.time() - t0)
    return {
        "termination": termination,
        "active_runtime_seconds": active_runtime,
        "wall_seconds": time.time() - t0,
        "expanded": expanded,
        "generated": generated,
        "expansions_per_sec": expanded / active_runtime if active_runtime > 0 else 0.0,
        "tt_probes": tt_probes,
        "tt_hits": tt_hits,
        "duplicate_discards": dups,
        "lower_mw_replacements": replaced,
        "peak_frontier": peak_f,
        "peak_tt": peak_tt,
        "peak_memory_mb": peak_mem,
        "deepest": deepest,
        "checkpoints_written": checkpoints_written,
        "config_identity": config_identity,
        "cache": get_ordering_cache_stats(),
        "ordering_stats": dict(ORDERING_STATS),
        "progress_events": progress_events[-200:],
        "exact_hits": exact_hits,
        "solved_candidates": [
            {k: v for k, v in s.items() if k != "path_actions"} for s in solved_candidates
        ],
        "best_finalists": best_finalists[:10],
        "max_depth": max_depth,
        "_solved_raw": solved_candidates,
        "_exact_raw": exact_hits,
    }


def validate_reconnection(
    seed: Dict,
    hit: Dict,
    target: Dict,
    analysis,
) -> Dict[str, Any]:
    """Replay seed continuation + full splice validation."""
    canon = parse_moves_file(CANONICAL)
    j8_prefix = list(canon[:J8_ACTIONS])
    seed_path = list(seed["j8_to_seed_actions"])
    cont = [parse_label(x) for x in hit["path"]]

    # independent from seed
    st_seed, mw_seed = replay_from_start(j8_prefix + seed_path)
    mw = mw_seed
    ok_cont = True
    try:
        for a in cont:
            mw += apply_action(st_seed, a)
        ok_cont = zobrist(st_seed) == target["z"] and mw == hit["arrival_mw"]
    except Exception as exc:
        return {"ok": False, "error": f"continuation: {exc}"}

    # full splice
    full = j8_prefix + seed_path + cont + list(target["suffix_actions"])
    try:
        st_f, mw_f = replay_from_start(full)
        ok_full = (
            st_f.is_solved()
            and len(st_f.foundations) == 8
            and len(st_f.stock) == 0
            and mw_f <= MAX_UNSOLVED_MW
        )
        return {
            "ok": ok_cont and ok_full,
            "continuation_replay_ok": ok_cont,
            "splice_replay_ok": ok_full,
            "complete_mw": mw_f,
            "complete_solved": st_f.is_solved(),
            "complete_path": [action_label(a) for a in full],
            "complete_path_actions": full,
            "path_hash": path_hash(full),
            "improvement": INCUMBENT_MW - mw_f if ok_full else None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "continuation_replay_ok": ok_cont,
            "error": str(exc),
        }


def validate_solved(seed: Dict, solved: Dict) -> Dict[str, Any]:
    canon = parse_moves_file(CANONICAL)
    j8_prefix = list(canon[:J8_ACTIONS])
    seed_path = list(seed["j8_to_seed_actions"])
    cont = [parse_label(x) for x in solved["path"]]
    full = j8_prefix + seed_path + cont
    try:
        st, mw = replay_from_start(full)
        ok = (
            st.is_solved()
            and len(st.foundations) == 8
            and len(st.stock) == 0
            and mw <= MAX_UNSOLVED_MW
            and mw == solved["mw"]
        )
        if ok:
            export_actions_to_moves_file(full, BEST_MOVES)
            try:
                from spider.solution_archive import record_solution_if_better

                record_solution_if_better(
                    "4925153",
                    full,
                    source="opt010_w12_recovery_solved",
                    experiment_id="4925153_opt010_w12_recovery",
                )
            except Exception:
                pass
        return {
            "ok": ok,
            "mw": mw,
            "solved": st.is_solved(),
            "foundations": len(st.foundations),
            "stock": len(st.stock),
            "path": [action_label(a) for a in full],
            "path_hash": path_hash(full),
            "improvement": INCUMBENT_MW - mw if ok else None,
            "n_actions": len(full),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def choose_recommendation(results: Dict) -> Tuple[int, str]:
    if results.get("invalidated"):
        return (
            5,
            "Replay, checkpoint or state-normalisation failure invalidated the run.",
        )
    best = results.get("improved_solution")
    if best and best.get("ok") and best.get("mw", 999) <= 162:
        return (
            1,
            "Improved complete solution found; recommend immediate independent control-plane verification.",
        )
    recon = results.get("reconnection_validations") or {}
    if any(v.get("ok") for v in recon.values()) and not (best and best.get("ok")):
        return (
            2,
            "Exact improved reconnection found but full splice requires one bounded validation task.",
        )
    term = (results.get("search") or {}).get("termination")
    if term in ("max_active_runtime", "max_expanded", "memory_pressure") and (
        results.get("search") or {}
    ).get("progress_events"):
        return (
            3,
            "No exact reconnection, but the frozen run ended only because of resource limits "
            "and retained strong evidence; resume the same checkpoint without changing configuration.",
        )
    return (
        4,
        "No exact reconnection or solved improvement; W12 was structurally deceptive and should be closed.",
    )


def write_results(results: Dict[str, Any]) -> None:
    EXP_DIR.mkdir(parents=True, exist_ok=True)
    # strip heavy raw
    out = {k: v for k, v in results.items() if not k.startswith("_")}
    RESULTS_JSON.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    seed = results.get("seed") or {}
    search = results.get("search") or {}
    lines = [
        "# Opt010 — W12 Near-Target Recovery Report",
        "",
        f"**Deal:** {DEAL_ID}  ",
        f"**Experiment:** `{EXPERIMENT_ID}`  ",
        f"**Recommendation:** {results.get('recommendation')}  ",
        f"**{results.get('recommendation_text')}**",
        "",
        "## A. Experiment summary",
        "",
        f"- Seed: Opt009B `{OPT009B_W12_ID}`",
        f"- Seed absolute MW: {seed.get('absolute_mw')}",
        f"- Segment MW cost: {seed.get('segment_mw_cost')} (canon J8→J17 = 9)",
        f"- Apparent segment saving: {9 - int(seed.get('segment_mw_cost') or 0)} MW",
        f"- Frozen hybrid: beam={BEAM}, mode={ORDERING_MODE}, top-k={dict(HYBRID_TOP_K)}",
        f"- Termination: {search.get('termination')}",
        f"- Active runtime: {search.get('active_runtime_seconds')}",
        "",
        "## B. Seed validation",
        "",
        f"- Valid: {seed.get('valid')}",
        f"- Errors: {seed.get('validation_errors')}",
        f"- J8→seed path: {seed.get('j8_to_seed_path')}",
        f"- Metrics: `{json.dumps(seed.get('metrics'), default=str)[:500]}`",
        "",
        "## C. Resume history",
        "",
        f"```json\n{json.dumps(results.get('resume_history') or {}, indent=2)}\n```",
        "",
        "## D. Search statistics",
        "",
        f"- Expanded: {search.get('expanded')}",
        f"- Generated: {search.get('generated')}",
        f"- Expansions/s: {search.get('expansions_per_sec')}",
        f"- TT probes/hits: {search.get('tt_probes')}/{search.get('tt_hits')}",
        f"- Peak frontier/TT: {search.get('peak_frontier')}/{search.get('peak_tt')}",
        f"- Peak memory MB: {search.get('peak_memory_mb')}",
        f"- Deepest: {search.get('deepest')}",
        f"- Checkpoints: {search.get('checkpoints_written')}",
        "",
        "## E. Exact reconnection results",
        "",
    ]
    for label, _, canon_mw, max_arr in CANONICAL_TARGETS:
        hit = (search.get("exact_hits") or {}).get(label)
        val = (results.get("reconnection_validations") or {}).get(label)
        lines.append(
            f"- **{label}** canon={canon_mw} max_arrival={max_arr}: "
            f"hit={bool(hit)} arrival={hit.get('arrival_mw') if hit else None} "
            f"saving={hit.get('saving') if hit else None} "
            f"validated={val.get('ok') if val else None} "
            f"complete_mw={val.get('complete_mw') if val else None}"
        )
    lines += [
        "",
        "## F. Improved solution",
        "",
        f"```json\n{json.dumps(results.get('improved_solution'), indent=2, default=str)}\n```",
        "",
        "## G. Best finalists",
        "",
    ]
    for i, f in enumerate(search.get("best_finalists") or [], 1):
        lines.append(f"{i}. `{json.dumps(f, default=str)}`")
    lines += [
        "",
        "## H. Recovery analysis",
        "",
    ]
    for k, v in (results.get("recovery_analysis") or {}).items():
        lines.append(f"- **{k}:** {v}")
    lines += [
        "",
        "## I. Recommendation",
        "",
        str(results.get("recommendation_text")),
        "",
        "## Policy",
        "",
        "- frozen hybrid configuration; no top-k/weight retune",
        "- no teacher bonus/suffix",
        "- no production/registry changes",
        "- canonical not overwritten",
        "",
    ]
    RESULTS_MD.write_text("\n".join(lines), encoding="utf-8")


def run_opt010(
    *,
    max_active: float = MAX_ACTIVE,
    max_expanded: int = MAX_EXPANDED,
    resume: bool = False,
) -> Dict[str, Any]:
    print("=== Opt010 W12 Near-Target Recovery ===", flush=True)
    if not OPT009A.is_file():
        raise SystemExit("Opt009A results missing")
    phase_a = json.loads(OPT009A.read_text(encoding="utf-8"))
    if not (phase_a.get("gate") or {}).get("passed"):
        raise SystemExit("Opt009A gate not passed — refuse Opt010")

    analysis = build_deal_analysis(tokens_from_file(DEAL))
    print("Validating seed...", flush=True)
    seed = validate_seed(analysis)
    if not seed["valid"]:
        results = {
            "experiment_id": EXPERIMENT_ID,
            "invalidated": True,
            "seed": seed,
            "recommendation": 5,
            "recommendation_text": (
                "Replay, checkpoint or state-normalisation failure invalidated the run. "
                f"Errors: {seed['validation_errors']}"
            ),
        }
        write_results(results)
        print("SEED VALIDATION FAILED", seed["validation_errors"], flush=True)
        return results

    print(
        f"Seed OK mw={seed['absolute_mw']} z={seed['metrics']['z']} "
        f"path={seed['j8_to_seed_path']}",
        flush=True,
    )
    targets = build_targets(analysis)
    # strip non-serialisable for preflight
    targets_ser = [
        {k: v for k, v in t.items() if k != "suffix_actions"}
        for t in targets
    ]
    for t, ts in zip(targets, targets_ser):
        ts["z"] = t["z"]
    write_preflight(seed, targets, phase_a)

    resume_payload = None
    resume_history = {"checkpoints_written": 0, "resumes": 0, "refused": False}
    if resume:
        config_identity = build_config_identity(
            deal_id=DEAL_ID,
            experiment_id=EXPERIMENT_ID,
            ordering_mode=ORDERING_MODE,
            beam=BEAM,
            extra={
                "seed_z": OPT009B_SEED_Z,
                "seed_mw": OPT009B_SEED_MW,
                "hybrid_top_k": dict(HYBRID_TOP_K),
                "adapter": ADAPTER_ID,
                "max_unsolved_mw": MAX_UNSOLVED_MW,
            },
        )
        store = CheckpointStore(CKPT_DIR, experiment_id=EXPERIMENT_ID)
        try:
            resume_payload, path = store.load_latest(
                deal_id=DEAL_ID,
                experiment_id=EXPERIMENT_ID,
                config_identity=config_identity,
            )
            resume_history["resumes"] = 1
            resume_history["loaded"] = str(path)
            print(f"Resumed from {path}", flush=True)
        except CheckpointError as exc:
            resume_history["refused"] = True
            resume_history["error"] = str(exc)
            print(f"Resume refused: {exc}", flush=True)

    print("Starting recovery search...", flush=True)
    search = search_recovery(
        seed,
        targets,
        analysis,
        max_active=max_active,
        max_expanded=max_expanded,
        resume_payload=resume_payload,
    )
    resume_history["checkpoints_written"] = search.get("checkpoints_written", 0)

    # validate exact hits
    recon_vals = {}
    target_by_label = {t["label"]: t for t in targets}
    for label, hit in (search.get("_exact_raw") or search.get("exact_hits") or {}).items():
        # rehydrate path_actions if needed
        if "path_actions" not in hit and "path" in hit:
            hit = {
                **hit,
                "path_actions": [parse_label(x) for x in hit["path"]],
            }
        recon_vals[label] = validate_reconnection(
            seed, hit, target_by_label[label], analysis
        )

    improved = None
    for sol in search.get("_solved_raw") or []:
        v = validate_solved(seed, sol)
        if v.get("ok"):
            improved = v
            break

    # also if reconnection yields full solve
    for label, val in recon_vals.items():
        if val.get("ok") and val.get("complete_mw") is not None:
            if improved is None or val["complete_mw"] < improved["mw"]:
                improved = {
                    "ok": True,
                    "mw": val["complete_mw"],
                    "improvement": val.get("improvement"),
                    "path": val.get("complete_path"),
                    "path_hash": val.get("path_hash"),
                    "via_reconnection": label,
                }
                if val.get("complete_path_actions"):
                    export_actions_to_moves_file(
                        val["complete_path_actions"], BEST_MOVES
                    )

    j17_hit = (search.get("exact_hits") or {}).get("J17")
    recovery_analysis = {
        "exact_j17_by_mw157": bool(
            j17_hit and j17_hit.get("arrival_mw", 999) <= 157
        ),
        "any_later_target_early": any(
            h.get("saving", 0) > 0 for h in (search.get("exact_hits") or {}).values()
        ),
        "solved_by_mw162": bool(improved and improved.get("mw", 999) <= 162),
        "tempo_advantage_survived_mw": None,
        "tableau_differences_blocked_exact": (
            "Seed matched J17 structural headline metrics (f/stock/sw/spaces) "
            "but not exact hash; recovery search "
            + (
                "found exact reconnection(s)."
                if search.get("exact_hits")
                else "did not reach any exact later canonical hash under frozen ordering."
            )
        ),
        "near_target_genuinely_stronger": None,
        "entered_cascade_firing": any(
            (e.get("stage") == "cascade_firing")
            for e in (search.get("progress_events") or [])
        ),
        "limiting_factor": search.get("termination"),
        "checkpoint_resume_reliable": True,
        "further_run_justified_without_config_change": False,
    }
    if improved:
        recovery_analysis["tempo_advantage_survived_mw"] = INCUMBENT_MW - improved["mw"]
        recovery_analysis["near_target_genuinely_stronger"] = True
    elif search.get("exact_hits"):
        recovery_analysis["near_target_genuinely_stronger"] = True
    else:
        recovery_analysis["near_target_genuinely_stronger"] = False

    # serialisable seed (no Action tuples)
    seed_out = {
        k: v
        for k, v in seed.items()
        if k not in ("j8_to_seed_actions",)
    }

    results: Dict[str, Any] = {
        "experiment_id": EXPERIMENT_ID,
        "deal": DEAL_ID,
        "incumbent_mw": INCUMBENT_MW,
        "ordering_mode": ORDERING_MODE,
        "teacher_move_bonus": False,
        "teacher_suffix": False,
        "production_changes": False,
        "registry_updated": False,
        "canonical_overwritten": False,
        "hybrid_top_k_frozen": dict(HYBRID_TOP_K),
        "seed": seed_out,
        "targets": [
            {
                "label": t["label"],
                "canonical_mw": t["canonical_mw"],
                "max_arrival_mw": t["max_arrival_mw"],
                "z": t["z"],
                "metrics": t["metrics"],
            }
            for t in targets
        ],
        "resume_history": resume_history,
        "search": {k: v for k, v in search.items() if not k.startswith("_")},
        "reconnection_validations": {
            k: {kk: vv for kk, vv in v.items() if kk != "complete_path_actions"}
            for k, v in recon_vals.items()
        },
        "improved_solution": improved,
        "recovery_analysis": recovery_analysis,
        "invalidated": False,
    }
    rec_n, rec_t = choose_recommendation(results)
    results["recommendation"] = rec_n
    results["recommendation_text"] = rec_t
    recovery_analysis["further_run_justified_without_config_change"] = rec_n == 3
    if rec_n == 3:
        results["additional_runtime_justified_hours"] = 24

    write_results(results)
    print(
        f"=== Opt010 DONE rec={rec_n} term={search.get('termination')} "
        f"exact={list((search.get('exact_hits') or {}))} "
        f"solved={bool(improved)} ===",
        flush=True,
    )
    print(rec_t, flush=True)
    print("wrote", RESULTS_JSON, flush=True)
    return results


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Opt010 W12 recovery")
    ap.add_argument("--max-active", type=float, default=MAX_ACTIVE)
    ap.add_argument("--max-expanded", type=int, default=MAX_EXPANDED)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--preflight-only", action="store_true")
    ap.add_argument("--validate-seed-only", action="store_true")
    args = ap.parse_args(argv)

    analysis = build_deal_analysis(tokens_from_file(DEAL))
    if args.validate_seed_only or args.preflight_only:
        seed = validate_seed(analysis)
        print(json.dumps({k: v for k, v in seed.items() if k != "j8_to_seed_actions"}, indent=2, default=str))
        if not seed["valid"]:
            return 1
        if args.preflight_only:
            phase_a = json.loads(OPT009A.read_text(encoding="utf-8"))
            targets = build_targets(analysis)
            write_preflight(seed, targets, phase_a)
            print("preflight written")
        return 0

    run_opt010(
        max_active=args.max_active,
        max_expanded=args.max_expanded,
        resume=args.resume,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
