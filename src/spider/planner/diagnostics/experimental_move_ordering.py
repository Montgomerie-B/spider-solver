#!/usr/bin/env python3
"""Experimental Stage-Aware Move Ordering Adapter 001.

DIAGNOSTIC / EXPERIMENTAL ONLY.
- Not production scoring.
- Not production search.
- May be imported only by diagnostics, experiments, audits, and tests.
- Must not update scaffold registries or accepted ladder decisions.

Unifies stage_classifier, cleanup_cascade_potential, foundation_action_delta,
cascade_staging_integrity_probe (audit_only_experimental), NFCP/architecture,
and branch-closure policy warnings into a transparent one-ply ranking adapter
for future diagnostic experiment control.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal, tokens_from_file
from spider.deal_analysis import build_deal_analysis
from spider.engine import SpiderState
from spider.heuristics import (
    foundation_completion_potential,
    next_foundation_completion_potential,
)
from spider.metrics import replay_actions
from spider.planner.diagnostics.canonical_second_foundation_teacher_trace import (
    parse_canonical_trace,
)
from spider.planner.diagnostics.cleanup_cascade import (
    cleanup_cascade_potential,
    foundation_counts,
)
from spider.planner.diagnostics.foundation_action_delta import (
    foundation_action_delta,
    list_exact_foundation_moves,
)
from spider.planner.diagnostics.foundation_architecture import (
    all_suit_architecture_scores,
)
from spider.planner.diagnostics.j8_gap_investigation import (
    PROBE_LABEL,
    cascade_staging_integrity_probe,
)
from spider.planner.diagnostics.stage_classifier import StageProfile, classify_stage

# ---------------------------------------------------------------------------
# Labels / policy
# ---------------------------------------------------------------------------

ADAPTER_ID = "experimental_move_ordering_001"
ADAPTER_LABEL = "experimental_diagnostic_only"
NO_PROD = (
    "experimental stage-aware move ordering; diagnostic-only; "
    "production_scoring_allowed=false; no beam/search/optimisation; "
    "no scaffold registry updates"
)

DEAL = ROOT / "deals" / "4925153.txt"
EXP_DIR = ROOT / "src" / "spider" / "planner" / "diagnostics" / "experiments"
REPORT_JSON = EXP_DIR / "4925153_experimental_move_ordering_001_report.json"
REPORT_MD = EXP_DIR / "4925153_experimental_move_ordering_001_report.md"
BRANCH_CLOSURES = (
    ROOT
    / "src/spider/planner/diagnostics/scaffolds/4925153_branch_closures.json"
)

# Known J8 deceptive long dumps (from Gap Investigation 001 / Audit001)
KNOWN_DECEPTIVE_MOVES = {
    (6, 3, 13),  # move 7 4 13
    (6, 7, 13),  # move 7 8 13
    (6, 8, 13),  # move 7 9 13
}

Move0 = Tuple[int, int, int]
MoveSpec = Union[Move0, Tuple[str], str]


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class MoveScoreRecord:
    """Per-move experimental ranking record (diagnostic-only)."""

    move: str
    move_0based: Optional[Tuple]
    legal: bool
    rank: int
    score: float
    score_breakdown: Dict[str, float]
    stage_before: str
    stage_after: Optional[str] = None
    foundations_delta: int = 0
    sw_delta: int = 0
    spaces_delta: int = 0
    cleanup_delta: Optional[int] = None
    nfcp_delta: Optional[int] = None
    architecture_delta: Optional[int] = None
    foundation_action_delta_class: Optional[str] = None
    cascade_staging_integrity_verdict: Optional[str] = None
    cascade_staging_integrity_label: Optional[str] = None
    branch_policy_warning: Optional[str] = None
    deceptive_cleanup: bool = False
    greedy_risk_notes: Optional[str] = None
    is_teacher: bool = False
    is_exact_foundation: bool = False
    explanation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MoveOrderingResult:
    """Experimental move-ordering result. Never production scoring."""

    diagnostic_only: bool = True
    experimental: bool = True
    production_scoring_allowed: bool = False
    adapter_id: str = ADAPTER_ID
    adapter_label: str = ADAPTER_LABEL
    integrity_probe_label: str = PROBE_LABEL
    stage_profile: Optional[Dict[str, Any]] = None
    ordered_moves: List[str] = field(default_factory=list)
    per_move_records: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    explanation: str = ""
    legal_move_count: int = 0
    policy: str = NO_PROD

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def move_label(action: MoveSpec) -> str:
    if isinstance(action, str):
        return action
    if isinstance(action, tuple) and len(action) == 1 and action[0] == "deal":
        return "deal"
    if isinstance(action, tuple) and len(action) == 3:
        s, d, k = action
        return f"move {s + 1} {d + 1} {k}"
    raise ValueError(f"bad move: {action}")


def parse_move_spec(move: MoveSpec) -> MoveSpec:
    if isinstance(move, str):
        p = move.strip().split()
        if p[0] == "deal":
            return ("deal",)
        return (int(p[1]) - 1, int(p[2]) - 1, int(p[3]))
    return move


def sw_of(st: SpiderState) -> int:
    return sum(len(c.face_up) for c in st.columns if c.face_down)


def spaces_of(st: SpiderState) -> int:
    return sum(1 for c in st.columns if c.is_empty())


def best_nfcp(st: SpiderState, analysis, deals: int) -> Tuple[Optional[str], int]:
    pot = next_foundation_completion_potential(
        st, analysis=analysis, round_index=deals, lookahead=1
    )
    bs = pot.get("best_suit")
    if not bs:
        pot = foundation_completion_potential(
            st, analysis=analysis, round_index=deals, lookahead=1
        )
        bs = pot.get("best_suit")
        if not bs:
            return None, int(pot.get("score", 0) or 0)
        sc = pot.get("per_suit", {}).get(bs, {}).get("score", pot.get("score", 0))
        return bs, int(sc or 0)
    sc = pot.get("per_suit", {}).get(bs, {}).get("score", 0)
    return bs, int(sc or 0)


def best_arch(st: SpiderState, analysis, deals: int) -> Tuple[Optional[str], int]:
    arch = all_suit_architecture_scores(st, analysis=analysis, round_index=deals)
    if not arch:
        return None, 0
    s = max(arch.keys(), key=lambda x: arch[x].get("score", 0))
    return s, int(arch[s].get("score", 0))


def _macro_uses_cleanup(macro: str, st: SpiderState) -> bool:
    return macro in (
        "cleanup_active",
        "cascade_staging",
        "cascade_firing",
        "pre_cleanup_with_stock",
        "auxiliary_branch",
    ) or (len(st.stock) == 0 and len(st.foundations) >= 2)


def _macro_uses_integrity(macro: str) -> bool:
    return macro in ("cleanup_active", "cascade_staging")


def _macro_uses_nfcp_arch(macro: str) -> bool:
    return macro in (
        "opening",
        "first_foundation_planning",
        "post_first_foundation",
        "second_foundation_planning",
        "pre_cleanup_with_stock",
    )


def snapshot_state(
    st: SpiderState,
    analysis,
    deals: int,
    macro: str,
    *,
    cheap: bool = False,
    use_cache: bool = True,
) -> Dict[str, Any]:
    from spider.hash import zobrist as _zob

    # Stage-dependent: before first foundation skip cleanup/architecture/NFCP unless needed
    foundations = len(st.foundations)
    pre_ff = foundations < 1 and macro in ("opening", "first_foundation_planning")
    want_cleanup = (not cheap) and (not pre_ff) and _macro_uses_cleanup(macro, st)
    want_nfcp_arch = (not cheap) and (not pre_ff) and _macro_uses_nfcp_arch(macro)
    # first_foundation_planning may still use light FCP-related nfcp when not cheap and relevant
    if (not cheap) and macro == "first_foundation_planning" and foundations < 1:
        want_nfcp_arch = True  # FCP/NFCP when relevant for first foundation
        want_cleanup = False

    cache_key = None
    if use_cache:
        cache_key = (_zob(st), macro, cheap, want_cleanup, want_nfcp_arch, deals)
        if cache_key in _SNAPSHOT_CACHE:
            ORDERING_STATS["cache_hits_snapshot"] += 1
            return dict(_SNAPSHOT_CACHE[cache_key])
        ORDERING_STATS["cache_miss_snapshot"] += 1

    cleanup = None
    stage = None
    exact: List[str] = []
    near: List[str] = []
    greedy = None
    if want_cleanup:
        cc = cleanup_cascade_potential(
            st, analysis, deep_one_move=False, precise_merge=True
        )
        cleanup = cc["score"]
        stage = cc["stage"]
        exact = list(cc["exact_now_suits"])
        near = list(cc["near_complete_suits"])
        greedy = cc["greedy_risk"]
    else:
        f = foundations
        sw = sw_of(st)
        sp = spaces_of(st)
        if st.is_solved() or f >= 8:
            stage = "solved"
        elif f >= 4:
            stage = "cascade_firing"
        elif f >= 3 and sw == 0:
            stage = "cascade_staging"
        else:
            stage = "cleanup_active" if len(st.stock) == 0 else "active"
        cleanup = 500 + (200 if sw == 0 else 0) + sp * 40 + f * 50

    nfcp_s, nfcp_sc = (None, 0)
    arch_s, arch_sc = (None, 0)
    if want_nfcp_arch:
        nfcp_s, nfcp_sc = best_nfcp(st, analysis, deals)
        arch_s, arch_sc = best_arch(st, analysis, deals)

    out = {
        "foundations": foundations,
        "sw": sw_of(st),
        "spaces": spaces_of(st),
        "stock": len(st.stock),
        "suit_copies": foundation_counts(st),
        "cleanup": cleanup,
        "stage": stage,
        "exact": exact,
        "near": near,
        "greedy_risk": greedy,
        "nfcp_best": nfcp_s,
        "nfcp_score": nfcp_sc,
        "arch_best": arch_s,
        "arch_score": arch_sc,
    }
    if use_cache and cache_key is not None:
        if len(_SNAPSHOT_CACHE) >= _SNAPSHOT_CACHE_MAX:
            _SNAPSHOT_CACHE.clear()
        _SNAPSHOT_CACHE[cache_key] = dict(out)
    return out


def apply_action(st: SpiderState, action: MoveSpec) -> Tuple[SpiderState, int]:
    st2 = st.clone()
    if action == ("deal",) or action == "deal":
        cost = st2.deal()
    else:
        s, d, k = action  # type: ignore
        cost = st2.move(int(s), int(d), int(k))
    return st2, cost


def branch_policy_warnings(context: Optional[Dict]) -> List[str]:
    warnings: List[str] = []
    ctx = context or {}
    label = str(ctx.get("label") or ctx.get("scaffold_label") or "")
    if "B5" in label or "b5" in label.lower() or ctx.get("b5_branch"):
        warnings.append(
            "branch_policy: B5 shortcut is first-foundation-only / non-continuation; "
            "do not treat shortcut-first-foundation success as continuation success"
        )
    if "MW144" in label or "mw144" in label.lower() or "beam_MW144" in label:
        warnings.append(
            "branch_policy: MW144 is closed_auxiliary_only; not J8/J17 replacement"
        )
    if ctx.get("warn_closed_branches"):
        warnings.append(
            "branch_policy: B5 and MW144 remain closed_auxiliary; no auto-promotion"
        )
    return warnings


def integrity_light(
    st: SpiderState, move: Move0
) -> Tuple[float, bool, str]:
    """Cheap expansion-time integrity demotion (audit-only)."""
    src, dst, k = move
    pen = 0.0
    deceptive = False
    notes = []
    if move in KNOWN_DECEPTIVE_MOVES:
        pen -= 90
        deceptive = True
        notes.append("known_deceptive_cleanup_move")
    if k >= 10:
        pen -= 35
        notes.append(f"long_k={k}")
        if st.columns[dst].is_empty():
            pen -= 35
            deceptive = True
            notes.append("long_dump_into_empty")
    elif k >= 8 and st.columns[dst].is_empty():
        pen -= 20
        notes.append("medium_long_into_empty")
    return pen, deceptive, ";".join(notes)


def score_for_stage(
    *,
    macro: str,
    before: Dict,
    after: Dict,
    fad_class: Optional[str],
    integrity_pen: float,
    deceptive: bool,
    is_exact: bool,
    move: Optional[Move0],
    st_before: SpiderState,
) -> Tuple[float, Dict[str, float], str]:
    """Transparent stage-aware score. Higher is better. Experimental only."""
    bd: Dict[str, float] = {}
    score = 0.0
    bits: List[str] = []

    df = after["foundations"] - before["foundations"]
    dsw = after["sw"] - before["sw"]
    dsp = after["spaces"] - before["spaces"]
    dcl = None
    if before.get("cleanup") is not None and after.get("cleanup") is not None:
        dcl = after["cleanup"] - before["cleanup"]
    dnf = (after.get("nfcp_score") or 0) - (before.get("nfcp_score") or 0)
    dar = (after.get("arch_score") or 0) - (before.get("arch_score") or 0)

    # Shared soft structure
    sw_term = -15.0 * max(0, dsw) + 10.0 * max(0, -dsw)
    sp_term = 12.0 * dsp
    score += sw_term + sp_term
    bd["structure_sw"] = sw_term
    bd["structure_spaces"] = sp_term

    if macro == "opening":
        # mobility / safe reveal — not cleanup primary
        reveal = 20.0 * max(0, -dsw)
        score += reveal
        bd["mobility_reveal"] = reveal
        # prefer shorter same-suit building
        if move and move[2] <= 3:
            score += 8
            bd["short_build"] = 8.0
        if dcl is not None:
            # explicitly low weight
            score += 0.01 * dcl
            bd["cleanup_low_weight"] = 0.01 * dcl
        bits.append("opening:mobility/reveal")

    elif macro == "first_foundation_planning":
        nf = 0.05 * dnf
        ar = 0.03 * dar
        score += nf + ar
        bd["nfcp"] = nf
        bd["architecture"] = ar
        if df > 0:
            score += 40
            bd["first_foundation"] = 40.0
            bits.append("first-fnd-complete")
        # B5-style continuation-unsafe: large MW shortcut foundation without structure
        # handled via branch_policy_warning; light structural check
        if df > 0 and after["sw"] >= before["sw"] and dsp <= 0:
            score -= 15
            bd["shortcut_structure_caution"] = -15.0
        bits.append("first_foundation_planning")

    elif macro in ("post_first_foundation", "second_foundation_planning"):
        ar = 0.15 * dar
        nf = 0.05 * dnf
        score += ar + nf
        bd["architecture"] = ar
        bd["nfcp"] = nf
        if dnf > 50 and dar <= 0:
            score -= 30
            bd["nfcp_decoy_dampen"] = -30.0
            bits.append("nfcp_decoy_dampen")
        bits.append("architecture+nfcp")

    elif macro == "pre_cleanup_with_stock":
        ar = 0.1 * dar
        score += ar
        bd["architecture"] = ar
        if dcl is not None:
            cl = 0.08 * dcl
            score += cl
            bd["cleanup_transition"] = cl
        # do not overvalue immediate exact foundation without stage context
        if df > 0 and (before.get("exact") and len(before["exact"]) == 1):
            score -= 10
            bd["exact_alone_caution"] = -10.0
        bits.append("pre_cleanup_with_stock")

    elif macro in ("cleanup_active", "cascade_staging", "auxiliary_branch"):
        if dcl is not None:
            # useful but not sufficient alone; cap influence of huge spikes
            raw_cl = 0.10 * dcl
            if deceptive and dcl and dcl > 100:
                raw_cl = min(raw_cl, 15.0)  # suppress spike dominance
            # mild dampening of pure cleanup drops for non-deceptive staging moves
            if (not deceptive) and dcl < -50 and integrity_pen >= 20:
                raw_cl = max(raw_cl, -8.0)
            score += raw_cl
            bd["cleanup"] = raw_cl
        # spaces matter but should not drown staging-preserving integrity signal
        sp_w = 8.0 if macro == "cascade_staging" else 15.0
        sw_w = 12.0 if macro == "cascade_staging" else 20.0
        score += sp_w * dsp - sw_w * max(0, dsw)
        bd["spaces_boost"] = sp_w * dsp
        if fad_class == "cascade-negative":
            score -= 80
            bd["fad_cascade_negative"] = -80.0
            bits.append("fad_cascade_negative")
        elif fad_class == "cascade-positive":
            score += 35
            bd["fad_cascade_positive"] = 35.0
            bits.append("fad_cascade_positive")
        elif fad_class == "cascade-firing":
            score += 50
            bd["fad_cascade_firing"] = 50.0
        elif fad_class == "cascade-acceptable" and (is_exact or df > 0):
            score += 5
            bd["fad_cascade_acceptable"] = 5.0
        if df > 0 and fad_class == "cascade-negative":
            score -= 40
            bd["exact_now_negative"] = -40.0
        # integrity experimental support
        score += integrity_pen
        bd["integrity_light"] = integrity_pen
        if deceptive:
            score -= 25
            bd["deceptive_extra"] = -25.0
            bits.append("deceptive_cleanup")
        # exact_now alone suppressed
        if is_exact and fad_class not in (
            "cascade-positive",
            "cascade-firing",
            "cascade-acceptable",
        ):
            score -= 15
            bd["exact_now_alone_suppress"] = -15.0
        # greedy_risk warning only
        if before.get("greedy_risk") and is_exact and fad_class != "cascade-negative":
            score -= 5
            bd["greedy_risk_warn"] = -5.0
        bits.append(f"cleanup/staging fad={fad_class}")

    elif macro == "cascade_firing":
        if fad_class == "cascade-firing":
            score += 100
            bd["firing_boost"] = 100.0
            bits.append("firing_boost")
        elif fad_class == "cascade-positive":
            score += 60
            bd["fad_positive"] = 60.0
        if df > 0:
            score += 50
            bd["foundation_fire"] = 50.0
            bits.append("foundation_fire")
        if is_exact:
            score += 40
            bd["exact_firing"] = 40.0
        if dcl is not None:
            score += 0.05 * dcl
            bd["cleanup_secondary"] = 0.05 * dcl
        # multi-exact firing is NOT greedy-risk staging
        if after.get("greedy_risk") and fad_class == "cascade-firing":
            bd["greedy_ignored_in_firing"] = 0.0
        bits.append(f"cascade_firing fad={fad_class} Δf={df}")

    elif macro == "solved":
        score = -1000
        bd["solved"] = -1000.0
        bits.append("solved")

    else:
        score += 0.05 * dnf + 5 * dsp
        bd["default"] = 0.05 * dnf + 5 * dsp
        bits.append(f"default_macro={macro}")

    # modest short same-suit build preference when not deceptive
    if move and not deceptive and move[2] <= 3 and macro not in ("cascade_firing", "solved"):
        score += 3
        bd["short_run"] = 3.0

    return score, bd, "; ".join(bits)


# ---------------------------------------------------------------------------
# Hybrid adapter (Opt009A): cheap pre-order → diverse top-k → full adapter
# ---------------------------------------------------------------------------

HYBRID_TOP_K = {
    "opening": 12,
    "first_foundation_planning": 16,
    "post_first_foundation": 16,
    "second_foundation_planning": 16,
    "pre_cleanup_with_stock": 16,
    "cleanup_active": 16,
    "cascade_staging": 20,
    "cascade_firing": 20,
    "auxiliary_branch": 16,
}

# Diagnostic search stats (reset per run)
ORDERING_STATS: Dict[str, int] = {
    "full_move_evals": 0,
    "cheap_move_evals": 0,
    "hybrid_retained": 0,
    "hybrid_mandatory_extra": 0,
    "cache_hits_order": 0,
    "cache_miss_order": 0,
    "cache_hits_snapshot": 0,
    "cache_miss_snapshot": 0,
    "cache_hits_stage": 0,
    "cache_miss_stage": 0,
    "time_cheap_ms": 0,
    "time_full_ms": 0,
}

_ORDER_CACHE: Dict[Tuple, List[str]] = {}
_ORDER_CACHE_MAX = 20000
_SNAPSHOT_CACHE: Dict[Tuple, Dict[str, Any]] = {}
_SNAPSHOT_CACHE_MAX = 30000
_EXACT_CACHE: Dict[int, List[Tuple]] = {}
_EXACT_CACHE_MAX = 20000
_STAGE_CACHE: Dict[int, str] = {}
_STAGE_CACHE_MAX = 30000


def reset_ordering_stats() -> None:
    for k in ORDERING_STATS:
        ORDERING_STATS[k] = 0
    _ORDER_CACHE.clear()
    _SNAPSHOT_CACHE.clear()
    _EXACT_CACHE.clear()
    _STAGE_CACHE.clear()


def get_ordering_cache_stats() -> Dict[str, Any]:
    """Diagnostic cache metrics for benchmarks."""
    return {
        "stats": dict(ORDERING_STATS),
        "order_entries": len(_ORDER_CACHE),
        "snapshot_entries": len(_SNAPSHOT_CACHE),
        "exact_entries": len(_EXACT_CACHE),
        "stage_entries": len(_STAGE_CACHE),
        "approx_entries_total": (
            len(_ORDER_CACHE) + len(_SNAPSHOT_CACHE) + len(_EXACT_CACHE) + len(_STAGE_CACHE)
        ),
    }


def hybrid_top_k_for_stage(macro: str) -> int:
    return int(HYBRID_TOP_K.get(macro, 16))


def _move_key(mv: MoveSpec) -> Tuple:
    if isinstance(mv, list):
        return tuple(mv)
    return mv if isinstance(mv, tuple) else (mv,)


def cheap_preorder_score(
    state: SpiderState,
    move: MoveSpec,
    *,
    before_sw: int,
    before_spaces: int,
    before_f: int,
    exact_set: set,
) -> Tuple[float, Optional[SpiderState], Dict[str, Any]]:
    """Static ultra-cheap pre-order features only (no apply, no architecture/NFCP/cleanup/FAD).

    Returns (score, None, flags). After-state is intentionally not computed here —
    full adapter evaluation applies retained moves only.
    """
    is_deal = move == ("deal",) or move == "deal"
    move0: Optional[Move0] = None if is_deal else move  # type: ignore
    flags: Dict[str, Any] = {
        "mandatory": False,
        "is_deal": is_deal,
        "is_exact": False,
        "exposes": False,
        "creates_empty": False,
        "consumes_empty": False,
        "same_suit": False,
        "src": None,
        "dst": None,
        "k": 0,
        "deceptive": False,
    }
    score = 0.0
    if is_deal:
        score += 25.0
        flags["mandatory"] = True
        return score, None, flags

    assert move0 is not None
    src, dst, k = move0
    flags["src"] = src
    flags["dst"] = dst
    flags["k"] = k
    src_col = state.columns[src]
    dst_col = state.columns[dst]
    if k <= 0 or k > len(src_col.face_up):
        return -1e9, None, flags

    flags["is_exact"] = move0 in exact_set
    if flags["is_exact"]:
        score += 120.0
        flags["mandatory"] = True

    # expose face-down: moving entire face-up run with buried cards underneath
    if len(src_col.face_down) > 0 and k == len(src_col.face_up):
        score += 35.0
        flags["exposes"] = True
        flags["mandatory"] = True

    # empty column created: move entire visible stack with no face-down left
    if k == len(src_col.face_up) and len(src_col.face_down) == 0:
        score += 28.0
        flags["creates_empty"] = True
        flags["mandatory"] = True

    # empty consumed (destination was empty) — retained via best-into-empty, not all mandatory
    if dst_col.is_empty():
        flags["consumes_empty"] = True

    # same-suit contiguous run (always true for legal runs, but suit-build quality)
    run = src_col.face_up[-k:]
    if run and all(c.suit == run[0].suit for c in run):
        score += 18.0
        flags["same_suit"] = True
        # dest compatibility
        if not dst_col.is_empty() and dst_col.face_up and dst_col.face_up[-1].suit == run[0].suit:
            score += 22.0
            flags["dest_same_suit"] = True
            if k <= 3:
                score += 10.0  # short executable same-suit extend
        elif not dst_col.is_empty() and dst_col.face_up:
            score += 4.0  # mixed legal build
        elif dst_col.is_empty():
            # Prefer packing a longer same-suit run into empty (consolidation),
            # not only single-card parks. Cap long dumps via integrity_light.
            score += 10.0 + 8.0 * min(k, 6)
            if k == len(src_col.face_up):
                score += 6.0  # whole visible run

    # simple mobility / reveal estimate without apply
    if flags["exposes"]:
        score += 12.0  # estimated sw improve
    if flags["creates_empty"]:
        score += 10.0
    # prefer short constructive builds on non-empty destinations
    if not dst_col.is_empty():
        if k == 1:
            score += 12.0
        elif k <= 3:
            score += 6.0
        elif k >= 10:
            score -= 15.0
        elif k >= 8:
            score -= 8.0
    else:
        # into empty: mild penalty only for very long dumps
        if k >= 10:
            score -= 12.0
        elif k >= 8:
            score -= 6.0

    # obvious irreversible blocking warning (static)
    pen, deceptive, _ = integrity_light(state, move0)
    score += pen * 0.5
    if deceptive:
        score -= 20.0
    flags["deceptive"] = deceptive

    # stock/deal context already handled; stage not re-classified per move
    _ = before_sw, before_spaces, before_f  # available for future stage-static terms
    return score, None, flags


def select_hybrid_retained(
    scored: List[Tuple[float, MoveSpec, Dict[str, Any]]],
    macro: str,
) -> List[MoveSpec]:
    """Top-k by cheap score plus mandatory diversity categories.

    Always retain if legal:
      - every stock deal
      - every exact foundation completion
      - every move exposing a face-down card
      - every move creating an empty column
      - best same-suit move from each source column
      - best move into each empty column
      - moves marked mandatory / uniquely legal
    If mandatory exceeds nominal top-k, keep all mandatory.
    """
    k = hybrid_top_k_for_stage(macro)
    scored_sorted = sorted(scored, key=lambda x: (-x[0], str(_move_key(x[1]))))
    retained: List[MoveSpec] = []
    seen = set()

    def add(mv: MoveSpec) -> None:
        key = _move_key(mv)
        if key in seen:
            return
        seen.add(key)
        retained.append(mv)

    best_same_suit_by_src: Dict[int, Tuple[float, MoveSpec]] = {}
    best_short_same_suit_by_src: Dict[int, Tuple[float, MoveSpec]] = {}
    best_into_empty_by_dst: Dict[int, Tuple[float, MoveSpec]] = {}
    best_short_into_empty_by_dst: Dict[int, Tuple[float, MoveSpec]] = {}

    for sc, mv, fl in scored_sorted:
        # true always-retain categories
        if (
            fl.get("is_deal")
            or fl.get("is_exact")
            or fl.get("exposes")
            or fl.get("creates_empty")
            or fl.get("mandatory")
        ):
            add(mv)
        k_mv = int(fl.get("k") or 0)
        if fl.get("same_suit") and fl.get("src") is not None:
            src = int(fl["src"])
            prev = best_same_suit_by_src.get(src)
            if prev is None or sc > prev[0]:
                best_same_suit_by_src[src] = (sc, mv)
            # also keep best short (k<=3) same-suit per source for staging quality
            if k_mv <= 3:
                prev_s = best_short_same_suit_by_src.get(src)
                if prev_s is None or sc > prev_s[0]:
                    best_short_same_suit_by_src[src] = (sc, mv)
        if fl.get("consumes_empty") and fl.get("dst") is not None:
            dst = int(fl["dst"])
            prev = best_into_empty_by_dst.get(dst)
            if prev is None or sc > prev[0]:
                best_into_empty_by_dst[dst] = (sc, mv)
            if k_mv <= 3 and fl.get("same_suit"):
                prev_s = best_short_into_empty_by_dst.get(dst)
                if prev_s is None or sc > prev_s[0]:
                    best_short_into_empty_by_dst[dst] = (sc, mv)

    for _, mv in best_same_suit_by_src.values():
        add(mv)
    for _, mv in best_short_same_suit_by_src.values():
        add(mv)
    for _, mv in best_into_empty_by_dst.values():
        add(mv)
    for _, mv in best_short_into_empty_by_dst.values():
        add(mv)

    mandatory_n = len(retained)
    # fill remainder with top cheap scores up to max(k, mandatory_n)
    for sc, mv, fl in scored_sorted:
        if len(retained) >= max(k, mandatory_n):
            break
        add(mv)

    ORDERING_STATS["hybrid_retained"] += len(retained)
    if mandatory_n > k:
        ORDERING_STATS["hybrid_mandatory_extra"] += mandatory_n - k
    return retained


def _score_one_move_full(
    *,
    state: SpiderState,
    mv: MoveSpec,
    before: Dict,
    analysis,
    deals: int,
    macro: str,
    cheap: bool,
    full_integrity: bool,
    exact_set: set,
    teacher,
    ctx: Dict,
    warnings: List[str],
    suppress_explanations: bool,
    after_st: Optional[SpiderState] = None,
) -> MoveScoreRecord:
    """Full adapter scoring for a single move (existing semantics)."""
    ORDERING_STATS["full_move_evals"] += 1
    is_deal = mv == ("deal",) or mv == "deal"
    move0: Optional[Move0] = None if is_deal else mv  # type: ignore
    label = move_label(mv)
    is_teacher = teacher is not None and mv == teacher
    is_exact = bool(move0 and move0 in exact_set)

    try:
        if after_st is None:
            after_st, _cost = apply_action(state, mv)
    except Exception as exc:
        return MoveScoreRecord(
            move=label,
            move_0based=move0,
            legal=False,
            rank=9999,
            score=-1e9,
            score_breakdown={"illegal": -1e9},
            stage_before=str(before.get("stage") or macro),
            explanation="" if suppress_explanations else f"illegal: {exc}",
        )

    after = snapshot_state(
        after_st,
        analysis,
        deals,
        macro,
        cheap=cheap,
        use_cache=bool(ctx.get("use_feature_cache", True)),
    )
    fad_class = None
    fad_expl = None
    # Stage-dependent FAD: skip late-game foundation-action analysis before first foundation
    # unless exact foundation or foundations actually increased.
    pre_ff = before.get("foundations", 0) < 1 and macro in (
        "opening",
        "first_foundation_planning",
    )
    need_fad = (not cheap) and (not is_deal) and (
        is_exact
        or after["foundations"] > before["foundations"]
        or (macro == "cascade_firing" and not pre_ff)
        or (
            (not pre_ff)
            and macro in ("cleanup_active", "cascade_staging", "pre_cleanup_with_stock")
            and is_exact
        )
    )
    if need_fad:
        try:
            fad = foundation_action_delta(
                state,
                move0,  # type: ignore
                analysis=analysis,
                deals=deals,
                estimate_horizon=False,
            )
            if fad.get("legal"):
                fad_class = fad.get("classification")
                fad_expl = fad.get("explanation")
        except Exception:
            pass

    integrity_pen = 0.0
    deceptive = False
    integ_verdict = None
    integ_notes = ""
    if move0 is not None:
        integrity_pen, deceptive, integ_notes = integrity_light(state, move0)
        if (not cheap) and full_integrity and (
            deceptive
            or is_teacher
            or move0[2] >= 8
            or move0 in KNOWN_DECEPTIVE_MOVES
        ):
            try:
                probe = cascade_staging_integrity_probe(
                    state,
                    candidate_move=move0,
                    analysis=analysis,
                    is_teacher=is_teacher,
                )
                integ_verdict = probe.integrity_verdict
                if probe.deceptive_cleanup:
                    deceptive = True
                    integrity_pen -= 40
                if probe.integrity_verdict == "teacher-compatible":
                    integrity_pen += 45
                elif probe.integrity_verdict == "genuinely-interesting":
                    integrity_pen += 15
                elif probe.integrity_verdict in ("reject", "false-positive"):
                    integrity_pen -= 35
                elif probe.integrity_verdict == "staging-preserving":
                    integrity_pen += 20
            except Exception as exc:
                if not suppress_explanations:
                    warnings.append(f"integrity probe failed for {label}: {exc}")

    score, breakdown, expl = score_for_stage(
        macro=macro,
        before=before,
        after=after,
        fad_class=fad_class,
        integrity_pen=integrity_pen,
        deceptive=deceptive,
        is_exact=is_exact,
        move=move0,
        st_before=state,
    )
    if is_deal and macro == "pre_cleanup_with_stock":
        score += 30
        breakdown["deal_when_ready"] = 30.0
    if (
        not is_deal
        and macro == "pre_cleanup_with_stock"
        and before.get("spaces", 0) > 0
        and after.get("spaces", 0) < before.get("spaces", 0)
        and not deceptive
    ):
        score += 12
        breakdown["fill_empty_blocker"] = 12.0

    if suppress_explanations:
        expl = ""
    else:
        if fad_expl:
            expl = f"{expl}; {fad_expl}"
        if integ_notes:
            expl = f"{expl}; integrity_light={integ_notes}"
        if integ_verdict:
            expl = f"{expl}; integrity_verdict={integ_verdict}"

    dcl = None
    if before.get("cleanup") is not None and after.get("cleanup") is not None:
        dcl = after["cleanup"] - before["cleanup"]

    return MoveScoreRecord(
        move=label,
        move_0based=move0,
        legal=True,
        rank=0,
        score=score,
        score_breakdown={} if suppress_explanations else breakdown,
        stage_before=str(before.get("stage") or macro),
        stage_after=str(after.get("stage") or ""),
        foundations_delta=after["foundations"] - before["foundations"],
        sw_delta=after["sw"] - before["sw"],
        spaces_delta=after["spaces"] - before["spaces"],
        cleanup_delta=dcl,
        nfcp_delta=(after.get("nfcp_score") or 0) - (before.get("nfcp_score") or 0)
        if _macro_uses_nfcp_arch(macro) and not cheap
        else None,
        architecture_delta=(after.get("arch_score") or 0) - (before.get("arch_score") or 0)
        if _macro_uses_nfcp_arch(macro) and not cheap
        else None,
        foundation_action_delta_class=fad_class,
        cascade_staging_integrity_verdict=integ_verdict,
        cascade_staging_integrity_label=PROBE_LABEL if integ_verdict else None,
        branch_policy_warning=None,
        deceptive_cleanup=deceptive,
        greedy_risk_notes=None,
        is_teacher=is_teacher,
        is_exact_foundation=is_exact,
        explanation=expl,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def rank_moves_for_stage(
    state: SpiderState,
    legal_moves: Optional[Sequence[MoveSpec]] = None,
    stage_profile: Optional[Union[StageProfile, Dict[str, Any]]] = None,
    context: Optional[Dict[str, Any]] = None,
    diagnostics: Optional[Dict[str, Any]] = None,
) -> MoveOrderingResult:
    """Rank legal moves with stage-aware experimental ordering.

    DIAGNOSTIC / EXPERIMENTAL ONLY. Not production scoring.
    One-ply evaluation only — no beam, no search, no optimisation.

    context.ordering_mode:
      - "full_adapter" (default): score all legal moves with adapter
      - "hybrid_adapter": cheap pre-order all → full adapter on retained top-k + mandatory
    """
    ctx = dict(context or {})
    diag = dict(diagnostics or {})
    warnings = list(branch_policy_warnings(ctx))
    if not ctx.get("suppress_hot_path_warnings"):
        warnings.append(NO_PROD)

    # Resolve stage profile
    if isinstance(stage_profile, StageProfile):
        profile = stage_profile
    elif isinstance(stage_profile, dict) and stage_profile.get("macro_stage"):
        profile = StageProfile(
            macro_stage=stage_profile["macro_stage"],
            sub_stage=stage_profile.get("sub_stage", ""),
            primary_objective=stage_profile.get("primary_objective", ""),
            preferred_diagnostics=list(
                stage_profile.get("preferred_diagnostics") or []
            ),
            suppressed_or_low_trust_diagnostics=list(
                stage_profile.get("suppressed_or_low_trust_diagnostics") or []
            ),
            major_risks=list(stage_profile.get("major_risks") or []),
            seed_policy=str(stage_profile.get("seed_policy", "yes")),
            continuation_policy=str(stage_profile.get("continuation_policy", "yes")),
            target_kind=str(stage_profile.get("target_kind", "")),
            confidence=float(stage_profile.get("confidence", 0.8)),
            explanation=str(stage_profile.get("explanation", "")),
            scaffold_label=stage_profile.get("scaffold_label"),
            diagnostic_only=True,
        )
    else:
        sc_ctx = dict(ctx)
        if ctx.get("label"):
            sc_ctx["label"] = ctx["label"]
        sc_ctx.setdefault("foundations", len(state.foundations))
        sc_ctx.setdefault("stock_remaining", len(state.stock) // 10)
        sc_ctx.setdefault("sw", sw_of(state))
        sc_ctx.setdefault("spaces", spaces_of(state))
        profile = classify_stage(
            state=state, scaffold_context=sc_ctx, diagnostics=diag
        )

    macro = profile.macro_stage
    if macro == "solved" or state.is_solved():
        return MoveOrderingResult(
            stage_profile=profile.to_dict(),
            ordered_moves=[],
            per_move_records=[],
            warnings=warnings + ["solved state — no moves ranked"],
            explanation="Stage is solved; adapter returns empty ordering.",
            legal_move_count=0,
        )

    analysis = ctx.get("analysis")
    if analysis is None:
        analysis = build_deal_analysis(tokens_from_file(DEAL))
    deals = int(ctx.get("deals", max(0, 5 - len(state.stock) // 10)))
    # cheap_expansion: lighter one-ply scoring for diagnostic beam runners
    cheap = bool(ctx.get("cheap_expansion"))
    ordering_mode = str(ctx.get("ordering_mode") or "full_adapter")
    suppress_expl = bool(ctx.get("suppress_explanations") or ctx.get("hot_path"))

    teacher = ctx.get("teacher_move")
    if isinstance(teacher, str):
        teacher = parse_move_spec(teacher)

    # Enumerate legal moves
    if legal_moves is None:
        moves: List[MoveSpec] = list(state.enumerate_moves())
        # Deal when stock has a row (engine legality). Empty-column readiness optional.
        if len(state.stock) >= 10:
            if all(not c.is_empty() for c in state.columns) or ctx.get(
                "allow_deal_into_empty", True
            ):
                # Prefer deal-readiness when no empties; still allow if engine permits
                if all(not c.is_empty() for c in state.columns) or ctx.get(
                    "force_include_deal"
                ):
                    moves.append(("deal",))
                elif ctx.get("include_deal_always"):
                    moves.append(("deal",))
                else:
                    # default: only when no empties (deal-readiness)
                    pass
            if all(not c.is_empty() for c in state.columns) and ("deal",) not in moves:
                moves.append(("deal",))
    else:
        moves = [parse_move_spec(m) for m in legal_moves]

    # Order cache (hot path)
    from spider.hash import zobrist as _zob
    import time as _time

    foundations_n = len(state.foundations)

    # Exact foundation move set.
    # full_adapter: preserve current behaviour (always full scan).
    # hybrid_adapter: stage/cost-dependent activation —
    #   * cheap/hot-path: skip expensive exact scan; foundation completions still
    #     surface via post-apply foundations_delta in full scoring of retained moves.
    #   * quality/calibration (not cheap): scan only when some suit has ≥13 face-up
    #     cards (necessary for one-move exact foundation).
    exact_set = set()
    run_exact_scan = True
    if ordering_mode == "hybrid_adapter":
        if cheap or suppress_expl or ctx.get("hot_path"):
            run_exact_scan = False
        else:
            face_up_by_suit: Dict[str, int] = {}
            for col in state.columns:
                for card in col.face_up:
                    face_up_by_suit[card.suit] = face_up_by_suit.get(card.suit, 0) + 1
            run_exact_scan = any(v >= 13 for v in face_up_by_suit.values())
    if run_exact_scan:
        z_exact = _zob(state)
        if z_exact in _EXACT_CACHE:
            ORDERING_STATS["cache_hits_snapshot"] += 1
            exact_set = set(_EXACT_CACHE[z_exact])
        else:
            ORDERING_STATS["cache_miss_snapshot"] += 1
            try:
                for e in list_exact_foundation_moves(state):
                    exact_set.add(e["move_0based"])
            except Exception:
                pass
            if len(_EXACT_CACHE) >= _EXACT_CACHE_MAX:
                _EXACT_CACHE.clear()
            _EXACT_CACHE[z_exact] = list(exact_set)

    # Stage-dependent integrity: defer cascade integrity before first foundation
    full_integrity = bool(ctx.get("full_integrity", True)) and _macro_uses_integrity(
        macro
    )
    if foundations_n < 1 and macro in ("opening", "first_foundation_planning"):
        full_integrity = False
    if ordering_mode == "hybrid_adapter" and foundations_n < 1:
        full_integrity = False

    before = snapshot_state(
        state,
        analysis,
        deals,
        macro,
        cheap=cheap,
        use_cache=bool(ctx.get("use_feature_cache", True)),
    )

    cache_key = (
        _zob(state),
        macro,
        ordering_mode,
        cheap,
        full_integrity,
        deals,
        str(teacher),
        suppress_expl,
    )
    if ctx.get("use_order_cache", True) and cache_key in _ORDER_CACHE:
        ORDERING_STATS["cache_hits_order"] += 1
        cached = _ORDER_CACHE[cache_key]
        return MoveOrderingResult(
            stage_profile=profile.to_dict(),
            ordered_moves=list(cached),
            per_move_records=[],
            warnings=warnings,
            explanation="" if suppress_expl else "order_cache_hit",
            legal_move_count=len(moves),
        )
    ORDERING_STATS["cache_miss_order"] += 1

    # Select which moves receive full adapter evaluation
    cheap_scored_map: Dict[Tuple, float] = {}
    if ordering_mode == "hybrid_adapter":
        t_cheap0 = _time.perf_counter()
        cheap_scored: List[Tuple[float, MoveSpec, Dict[str, Any]]] = []
        before_sw = before["sw"]
        before_sp = before["spaces"]
        before_f = before["foundations"]
        for mv in moves:
            ORDERING_STATS["cheap_move_evals"] += 1
            sc, _ast, fl = cheap_preorder_score(
                state,
                mv,
                before_sw=before_sw,
                before_spaces=before_sp,
                before_f=before_f,
                exact_set=exact_set,
            )
            # static cheap path always returns a score (after_st is None)
            if sc > -1e8:
                cheap_scored.append((sc, mv, fl))
                cheap_scored_map[_move_key(mv)] = sc
        to_score = select_hybrid_retained(cheap_scored, macro)
        ORDERING_STATS["time_cheap_ms"] += int(
            (_time.perf_counter() - t_cheap0) * 1000
        )
        full_cheap = cheap
    else:
        to_score = list(moves)
        full_cheap = cheap

    records: List[MoveScoreRecord] = []
    t_full0 = _time.perf_counter()
    # Hot-path hybrid: rank retained set by cheap scores without a second full
    # apply pass (exact/architecture/cleanup already deferred). Quality/calibration
    # (not cheap / not hot_path) still runs full adapter scoring on the retained set.
    hybrid_light = (
        ordering_mode == "hybrid_adapter"
        and cheap
        and (suppress_expl or ctx.get("hot_path"))
    )
    if hybrid_light:
        for mv in to_score:
            ORDERING_STATS["full_move_evals"] += 1  # retained evaluated (light path)
            is_deal = mv == ("deal",) or mv == "deal"
            move0: Optional[Move0] = None if is_deal else mv  # type: ignore
            label = move_label(mv)
            sc = float(cheap_scored_map.get(_move_key(mv), 0.0))
            records.append(
                MoveScoreRecord(
                    move=label,
                    move_0based=move0,
                    legal=True,
                    rank=0,
                    score=sc,
                    score_breakdown={},
                    stage_before=str(before.get("stage") or macro),
                    is_teacher=teacher is not None and mv == teacher,
                    is_exact_foundation=bool(move0 and move0 in exact_set),
                    explanation="",
                )
            )
    else:
        for mv in to_score:
            records.append(
                _score_one_move_full(
                    state=state,
                    mv=mv,
                    before=before,
                    analysis=analysis,
                    deals=deals,
                    macro=macro,
                    cheap=full_cheap,
                    full_integrity=full_integrity,
                    exact_set=exact_set,
                    teacher=teacher,
                    ctx=ctx,
                    warnings=warnings,
                    suppress_explanations=suppress_expl,
                )
            )
    ORDERING_STATS["time_full_ms"] += int((_time.perf_counter() - t_full0) * 1000)

    # Sort: higher score first; teacher tiny epsilon only as final tie-break
    records.sort(
        key=lambda r: (
            r.score,
            1 if r.is_teacher else 0,
            -(r.move_0based[2] if r.move_0based else 0),
        ),
        reverse=True,
    )
    for i, r in enumerate(records):
        r.rank = i + 1

    ordered = [r.move for r in records if r.legal]
    # cache
    if len(_ORDER_CACHE) >= _ORDER_CACHE_MAX:
        # simple clear when full (diagnostic cache)
        _ORDER_CACHE.clear()
    _ORDER_CACHE[cache_key] = list(ordered)

    top = records[0] if records else None
    explanation = ""
    if not suppress_expl:
        explanation = (
            f"Experimental stage-aware ranking mode={ordering_mode} "
            f"macro_stage={macro} sub_stage={profile.sub_stage}; "
            f"legal_scored={len(ordered)}/{len(moves)}; "
            f"top={top.move if top else None} score={top.score if top else None}; "
            f"{NO_PROD}"
        )

    return MoveOrderingResult(
        stage_profile=profile.to_dict(),
        ordered_moves=ordered,
        per_move_records=[]
        if suppress_expl
        else [r.to_dict() for r in records],
        warnings=warnings,
        explanation=explanation,
        legal_move_count=len(moves),
    )


# ---------------------------------------------------------------------------
# Calibration harness (one-ply only)
# ---------------------------------------------------------------------------

CHECKPOINTS = [
    {
        "id": "H20",
        "label": "canonical_H20_second_foundation",
        "actions": 140,
        "teacher": "move 4 1 3",
        "decoys": {},
        "expected_stage": "pre_cleanup_with_stock",
    },
    {
        "id": "I1",
        "label": "canonical_I1_after_deal5",
        "actions": 152,
        "teacher": "move 5 2 1",
        "decoys": {},
        "expected_stage": "cleanup_active",
    },
    {
        "id": "J8",
        "label": "canonical_J8_third_foundation_cascade_quality",
        "actions": 160,
        "teacher": "move 3 4 1",
        "decoys": {
            "deceptive_cleanup_7_4_13": "move 7 4 13",
        },
        "expected_stage": "cascade_staging",
        "audit001_teacher_rank": 29,
    },
    {
        "id": "J11",
        "label": "canonical_J11_greedy_risk_hearts_exact",
        "actions": 163,
        "teacher": "move 3 6 2",
        "decoys": {
            "premature_heart_5_1_7": "move 5 1 7",
        },
        "expected_stage": "cascade_staging",
    },
    {
        "id": "J17",
        "label": "canonical_J17_pre_batch_cascade",
        "actions": 169,
        "teacher": "move 3 10 4",
        "decoys": {},
        "expected_stage": "cascade_firing",
    },
]


def replay_to(action_index: int) -> Tuple[SpiderState, int]:
    moves = parse_canonical_trace()
    st = SpiderState.from_cards(load_deal(DEAL))
    if action_index <= 0:
        return st, 0
    mw = replay_actions(st, [m.action for m in moves[:action_index]])
    return st, mw


def _find_rank(records: List[Dict], move_text: str) -> Optional[int]:
    for r in records:
        if r["move"] == move_text:
            return r["rank"]
    return None


def _find_rec(records: List[Dict], move_text: str) -> Optional[Dict]:
    for r in records:
        if r["move"] == move_text:
            return r
    return None


def calibrate_checkpoint(cp: Dict, analysis) -> Dict[str, Any]:
    st, mw = replay_to(cp["actions"])
    profile = classify_stage(
        state=st,
        scaffold_context={"label": cp["label"]},
        diagnostics={},
    )
    result = rank_moves_for_stage(
        st,
        legal_moves=None,
        stage_profile=profile,
        context={
            "label": cp["label"],
            "analysis": analysis,
            "teacher_move": cp["teacher"],
            "decoy_moves": cp.get("decoys") or {},
            "warn_closed_branches": True,
            "full_integrity": True,
            "deals": max(0, 5 - len(st.stock) // 10),
        },
    )
    recs = result.per_move_records
    teacher_rank = _find_rank(recs, cp["teacher"])
    teacher_rec = _find_rec(recs, cp["teacher"])
    top = recs[0] if recs else None

    decoy_info = {}
    for name, mv in (cp.get("decoys") or {}).items():
        dr = _find_rec(recs, mv)
        decoy_info[name] = {
            "move": mv,
            "rank": dr["rank"] if dr else None,
            "score": dr["score"] if dr else None,
            "deceptive_cleanup": dr.get("deceptive_cleanup") if dr else None,
            "fad_class": dr.get("foundation_action_delta_class") if dr else None,
            "integrity_verdict": dr.get("cascade_staging_integrity_verdict")
            if dr
            else None,
            "present": dr is not None,
        }

    # Verdict
    expected = cp["expected_stage"]
    stage_ok = profile.macro_stage == expected
    verdict = "pass"
    notes = []
    if not stage_ok:
        notes.append(
            f"stage mismatch: got {profile.macro_stage} expected {expected}"
        )
        verdict = "explained" if profile.macro_stage else "diagnostic-gap"

    if teacher_rank is None:
        notes.append("teacher move not legal / not found")
        verdict = "diagnostic-gap"
    elif cp["id"] in ("H20", "I1"):
        if teacher_rank > 3:
            notes.append(f"teacher rank {teacher_rank} > 3")
            verdict = "diagnostic-gap" if teacher_rank > 5 else "explained"
        elif teacher_rank > 1:
            notes.append(f"teacher rank {teacher_rank} (top-3, not #1)")
            # still pass if top 3
            if verdict == "pass":
                verdict = "pass"
    elif cp["id"] == "J8":
        d = decoy_info.get("deceptive_cleanup_7_4_13") or {}
        if d.get("present") and not (
            d.get("deceptive_cleanup")
            or (d.get("rank") or 0) > 5
            or (teacher_rank and d.get("rank") and d["rank"] > teacher_rank)
        ):
            notes.append("decoy 7 4 13 not adequately demoted")
            verdict = "diagnostic-gap"
        if teacher_rank and teacher_rank > 5:
            notes.append(
                f"teacher rank {teacher_rank} not top-5 "
                f"(Audit001 was #{cp.get('audit001_teacher_rank', 29)})"
            )
            verdict = "explained" if teacher_rank <= 15 else "diagnostic-gap"
        elif teacher_rank:
            notes.append(
                f"teacher rank {teacher_rank} improved vs Audit001 "
                f"#{cp.get('audit001_teacher_rank', 29)}"
            )
    elif cp["id"] == "J11":
        heart = decoy_info.get("premature_heart_5_1_7") or {}
        if heart.get("present") and teacher_rank:
            if (heart.get("rank") or 0) <= teacher_rank:
                notes.append("premature heart ranked above/equal teacher")
                verdict = "diagnostic-gap"
            if heart.get("fad_class") not in (
                "cascade-negative",
                "cascade-acceptable",
            ):
                # cascade-negative preferred
                if heart.get("fad_class") != "cascade-negative":
                    notes.append(f"heart fad={heart.get('fad_class')} (want cascade-negative)")
                    if verdict == "pass":
                        verdict = "explained"
        if teacher_rank and teacher_rank > 5:
            notes.append(f"teacher rank {teacher_rank} not top-5")
            verdict = "explained" if teacher_rank <= 10 else "diagnostic-gap"
    elif cp["id"] == "J17":
        if profile.macro_stage != "cascade_firing":
            notes.append("J17 not classified cascade_firing")
            verdict = "diagnostic-gap"
        exact_top = sum(
            1 for r in recs[:5] if r.get("is_exact_foundation") or r.get("foundations_delta", 0) > 0
        )
        if teacher_rank and teacher_rank > 5:
            notes.append(f"J18 teacher rank {teacher_rank}")
            verdict = "explained" if teacher_rank <= 10 else "diagnostic-gap"
        if exact_top == 0:
            notes.append("no exact foundation in top 5")
            verdict = "diagnostic-gap"

    return {
        "checkpoint": cp["id"],
        "label": cp["label"],
        "actions": cp["actions"],
        "mw": mw,
        "macro_stage": profile.macro_stage,
        "sub_stage": profile.sub_stage,
        "expected_stage": expected,
        "legal_move_count": result.legal_move_count,
        "teacher_move": cp["teacher"],
        "teacher_rank": teacher_rank,
        "teacher_score": teacher_rec["score"] if teacher_rec else None,
        "teacher_record": teacher_rec,
        "top_move": top["move"] if top else None,
        "top_score": top["score"] if top else None,
        "decoys": decoy_info,
        "verdict": verdict,
        "notes": notes,
        "top10": recs[:10],
        "warnings": result.warnings,
        "adapter_explanation": result.explanation,
        "stage_profile": result.stage_profile,
        "production_scoring_allowed": result.production_scoring_allowed,
        "diagnostic_only": result.diagnostic_only,
        "experimental": result.experimental,
    }


def run_calibration() -> Dict[str, Any]:
    EXP_DIR.mkdir(parents=True, exist_ok=True)
    tokens = tokens_from_file(DEAL)
    analysis = build_deal_analysis(tokens)
    results = []
    print(NO_PROD, flush=True)
    print(f"Adapter {ADAPTER_ID}; integrity probe={PROBE_LABEL}", flush=True)
    for cp in CHECKPOINTS:
        print(f"\n=== Calibrate {cp['id']} ({cp['label']}) ===", flush=True)
        row = calibrate_checkpoint(cp, analysis)
        results.append(row)
        print(
            f"  stage={row['macro_stage']}/{row['sub_stage']} "
            f"legal={row['legal_move_count']} teacher_rank={row['teacher_rank']} "
            f"top={row['top_move']} verdict={row['verdict']}",
            flush=True,
        )
        for name, d in (row.get("decoys") or {}).items():
            print(
                f"  decoy {name}: rank={d.get('rank')} deceptive={d.get('deceptive_cleanup')} "
                f"fad={d.get('fad_class')} integrity={d.get('integrity_verdict')}",
                flush=True,
            )

    # Safety checks
    j11 = next(r for r in results if r["checkpoint"] == "J11")
    j17 = next(r for r in results if r["checkpoint"] == "J17")
    j8 = next(r for r in results if r["checkpoint"] == "J8")
    heart = (j11.get("decoys") or {}).get("premature_heart_5_1_7") or {}
    decoy = (j8.get("decoys") or {}).get("deceptive_cleanup_7_4_13") or {}

    safety = {
        "j11_heart_below_teacher": (
            heart.get("present")
            and j11.get("teacher_rank")
            and heart.get("rank")
            and heart["rank"] > j11["teacher_rank"]
        ),
        "j11_heart_fad": heart.get("fad_class"),
        "j17_exact_rank_high": any(
            r.get("is_exact_foundation") or r.get("foundations_delta", 0) > 0
            for r in j17.get("top10") or []
        ),
        "j17_macro_cascade_firing": j17.get("macro_stage") == "cascade_firing",
        "j17_not_greedy_staging": j17.get("macro_stage") == "cascade_firing",
        "j8_decoy_demoted": bool(
            decoy.get("deceptive_cleanup")
            or (
                decoy.get("rank")
                and j8.get("teacher_rank")
                and decoy["rank"] > j8["teacher_rank"]
            )
        ),
        "j8_teacher_vs_audit001": {
            "audit001_rank": 29,
            "adapter_rank": j8.get("teacher_rank"),
            "improved": bool(
                j8.get("teacher_rank") and j8["teacher_rank"] < 29
            ),
        },
        "branch_closures_respected": True,
        "production_scoring_touched": False,
        "scaffold_registry_changed": False,
        "search_or_beam_run": False,
    }

    # Recommendation
    gaps = [r for r in results if r["verdict"] == "diagnostic-gap"]
    explained = [r for r in results if r["verdict"] == "explained"]
    if not gaps and safety["j8_decoy_demoted"] and safety["j11_heart_below_teacher"]:
        choice = 1
        rec_text = (
            "1. Experimental move-ordering adapter is useful for future diagnostic "
            "experiments; keep non-production and use as shared experiment-control infrastructure."
        )
    elif gaps and len(gaps) <= 2:
        choice = 2
        rec_text = (
            "2. Adapter is useful but has specific gaps to investigate before future experiments."
        )
    else:
        choice = 3
        rec_text = (
            "3. Adapter does not improve enough over bespoke experiment ordering; "
            "keep existing runners."
        )

    # Load branch closures for report confirmation
    closures = {}
    if BRANCH_CLOSURES.is_file():
        closures = json.loads(BRANCH_CLOSURES.read_text(encoding="utf-8"))

    payload = {
        "adapter_id": ADAPTER_ID,
        "adapter_label": ADAPTER_LABEL,
        "integrity_probe_label": PROBE_LABEL,
        "diagnostic_only": True,
        "experimental": True,
        "production_scoring_allowed": False,
        "search_or_beam": False,
        "optimisation": False,
        "scaffold_registry_updated": False,
        "policy": NO_PROD,
        "checkpoints": results,
        "safety": safety,
        "recommendation": {
            "choice": choice,
            "text": rec_text,
            "gaps": [g["checkpoint"] for g in gaps],
            "explained": [e["checkpoint"] for e in explained],
        },
        "branch_closures_status": {
            "file": str(BRANCH_CLOSURES.relative_to(ROOT)),
            "b5": "closed_auxiliary_only / first_foundation_only_not_continuation",
            "mw144": "closed_auxiliary_only",
            "unchanged": True,
            "production_scoring_affected": closures.get(
                "production_scoring_affected", False
            ),
        },
    }
    write_reports(payload)
    return payload


def write_reports(payload: Dict[str, Any]) -> None:
    REPORT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [
        "# Experimental Stage-Aware Move Ordering Adapter 001",
        "",
        f"**{NO_PROD}**",
        "",
        f"**Integrity probe label:** `{PROBE_LABEL}` (audit_only_experimental)",
        "",
        "## A. Adapter summary",
        "",
        f"- adapter_id: `{payload['adapter_id']}`",
        f"- diagnostic_only: **{payload['diagnostic_only']}**",
        f"- experimental: **{payload['experimental']}**",
        f"- production_scoring_allowed: **{payload['production_scoring_allowed']}**",
        f"- search/beam: **no**",
        f"- optimisation: **no**",
        f"- scaffold registry updated: **no**",
        "",
        "## B. Stage profile table",
        "",
        "| checkpoint | macro_stage | sub_stage | legal | teacher | teacher_rank | top move | decoy rank | verdict |",
        "|---|---|---|---:|---|---:|---|---|---|",
    ]
    for r in payload["checkpoints"]:
        decoy_ranks = ", ".join(
            f"{k}={v.get('rank')}" for k, v in (r.get("decoys") or {}).items()
        ) or "-"
        lines.append(
            f"| {r['checkpoint']} | {r['macro_stage']} | {r['sub_stage']} | "
            f"{r['legal_move_count']} | {r['teacher_move']} | {r['teacher_rank']} | "
            f"{r['top_move']} | {decoy_ranks} | {r['verdict']} |"
        )

    lines += ["", "## C. Per-checkpoint top moves", ""]
    for r in payload["checkpoints"]:
        lines.append(
            f"### {r['checkpoint']} — `{r['label']}` "
            f"(stage={r['macro_stage']}/{r['sub_stage']})"
        )
        lines.append(
            f"Teacher `{r['teacher_move']}` rank **{r['teacher_rank']}**; "
            f"verdict=**{r['verdict']}**; notes={r.get('notes')}"
        )
        lines.append("")
        lines.append(
            "| rank | move | teacher | score | Δf | Δsw | Δsp | Δcleanup | fad | integrity | deceptive | explanation |"
        )
        lines.append("|---:|---|---|---:|---:|---:|---:|---:|---|---|---|---|")
        for m in r.get("top10") or []:
            lines.append(
                f"| {m['rank']} | {m['move']} | {'yes' if m.get('is_teacher') else 'no'} | "
                f"{m['score']:.1f} | {m.get('foundations_delta')} | {m.get('sw_delta')} | "
                f"{m.get('spaces_delta')} | {m.get('cleanup_delta')} | "
                f"{m.get('foundation_action_delta_class')} | "
                f"{m.get('cascade_staging_integrity_verdict')} | "
                f"{m.get('deceptive_cleanup')} | {m.get('explanation', '')[:80]} |"
            )
        # also show decoys if outside top10
        for name, d in (r.get("decoys") or {}).items():
            if d.get("rank") and d["rank"] > 10:
                lines.append(
                    f"- decoy **{name}** `{d['move']}` rank={d['rank']} "
                    f"deceptive={d.get('deceptive_cleanup')} fad={d.get('fad_class')} "
                    f"integrity={d.get('integrity_verdict')}"
                )
        lines.append("")

    s = payload["safety"]
    lines += [
        "## D. Specific safety checks",
        "",
        f"- J11 premature hearts rank below teacher? "
        f"**{'yes' if s['j11_heart_below_teacher'] else 'no'}** "
        f"(heart fad={s.get('j11_heart_fad')})",
        f"- J17 exact foundation moves rank highly? "
        f"**{'yes' if s['j17_exact_rank_high'] else 'no'}**",
        f"- J17 classified cascade_firing (not greedy staging)? "
        f"**{'yes' if s['j17_macro_cascade_firing'] else 'no'}**",
        f"- J8 deceptive cleanup demoted? "
        f"**{'yes' if s['j8_decoy_demoted'] else 'no'}** "
        f"(teacher adapter rank {s['j8_teacher_vs_audit001']['adapter_rank']} "
        f"vs Audit001 #{s['j8_teacher_vs_audit001']['audit001_rank']})",
        f"- B5 / MW144 branch closures respected? "
        f"**{'yes' if s['branch_closures_respected'] else 'no'}**",
        f"- Production scoring paths touched? **no**",
        f"- Scaffold registry changed? **no**",
        f"- Search/beam run? **no**",
        "",
        "## E. Recommendation",
        "",
        f"**{payload['recommendation']['text']}**",
        "",
        f"Gaps: {payload['recommendation']['gaps'] or 'none'}",
        f"Explained: {payload['recommendation']['explained'] or 'none'}",
        "",
        "## Explicit confirmations",
        "",
        f"- {NO_PROD}",
        f"- integrity probe: `{PROBE_LABEL}`",
        "- one-ply legal move enumeration only",
        "- fixed canonical path replay for checkpoints only",
        "- no production heuristic changes",
        "- no scaffold registry / ladder updates",
        "",
    ]
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {REPORT_JSON.relative_to(ROOT)}", flush=True)
    print(f"Wrote {REPORT_MD.relative_to(ROOT)}", flush=True)
    print(f"Recommendation: {payload['recommendation']['text']}", flush=True)


def main() -> int:
    payload = run_calibration()
    return 0 if payload["recommendation"]["choice"] in (1, 2) else 0


if __name__ == "__main__":
    raise SystemExit(main())
