#!/usr/bin/env python3
"""Diagnostic Gap Investigation 001 — J8 cascade-staging false-positive analysis.

Seed: canonical_J8_third_foundation_cascade_quality only.
One-ply metrics + fixed scripted teacher-suffix replay. No beam/search.

cascade_staging_integrity_probe is AUDIT-ONLY / EXPERIMENTAL and must not be
imported by production scoring or search runners.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal, tokens_from_file
from spider.deal_analysis import build_deal_analysis
from spider.engine import SpiderState
from spider.heuristics import next_foundation_completion_potential
from spider.metrics import replay_actions
from spider.planner.diagnostics.canonical_second_foundation_teacher_trace import (
    parse_canonical_trace,
)
from spider.planner.diagnostics.cleanup_cascade import (
    cleanup_cascade_potential,
    foundation_counts,
)
from spider.planner.diagnostics.foundation_action_delta import foundation_action_delta
from spider.planner.diagnostics.foundation_architecture import (
    all_suit_architecture_scores,
)
from spider.planner.diagnostics.stage_classifier import classify_stage

DEAL = ROOT / "deals" / "4925153.txt"
AUDIT_DIR = ROOT / "src" / "spider" / "planner" / "diagnostics" / "audits"
MANIFEST = AUDIT_DIR / "4925153_j8_gap_investigation_001.json"
AUDIT001 = AUDIT_DIR / "4925153_teacher_move_ranking_audit_001_results.json"
RESULTS_JSON = AUDIT_DIR / "4925153_j8_gap_investigation_001_results.json"
RESULTS_MD = AUDIT_DIR / "4925153_j8_gap_investigation_001_report.md"

SEED_ACTIONS = 160
TEACHER_MOVE = "move 3 4 1"
FALSE_POS = "move 7 4 13"
J17_CLEANUP = 1593
# After J8, full teacher path J9..J17 is actions 161..169
# Remaining suffix after first move (J10..J17) = actions 162..169
PROBE_LABEL = "audit_only_experimental"
NO_SEARCH = (
    "one-ply + fixed scripted teacher-suffix replay only; "
    "no beam/search/optimisation; cascade_staging_integrity_probe is "
    f"{PROBE_LABEL} and not production scoring"
)


def parse_move(text: str) -> Tuple[int, int, int]:
    p = text.strip().split()
    return int(p[1]) - 1, int(p[2]) - 1, int(p[3])


def move_label(a: Tuple[int, int, int]) -> str:
    return f"move {a[0]+1} {a[1]+1} {a[2]}"


def sw_of(st: SpiderState) -> int:
    return sum(len(c.face_up) for c in st.columns if c.face_down)


def spaces_of(st: SpiderState) -> int:
    return sum(1 for c in st.columns if c.is_empty())


def tops(st: SpiderState) -> List[str]:
    return [str(c.top()) if c.top() else "-" for c in st.columns]


def replay_j8() -> Tuple[SpiderState, int]:
    moves = parse_canonical_trace()
    st = SpiderState.from_cards(load_deal(DEAL))
    mw = replay_actions(st, [m.action for m in moves[:SEED_ACTIONS]])
    return st, mw


def teacher_suffix_after_first() -> List[Tuple[int, int, int]]:
    """Canonical moves J10..J17 after teacher J9 has been applied."""
    moves = parse_canonical_trace()
    # indices 161..168 inclusive (0-based) = actions 162..169
    return [m.action for m in moves[161:169]]


def full_teacher_j9_j17() -> List[Tuple[int, int, int]]:
    moves = parse_canonical_trace()
    return [m.action for m in moves[160:169]]


def load_candidate_moves() -> List[Dict[str, Any]]:
    """Load teacher + false positive + Audit001 top10; no invented moves."""
    out: List[Dict[str, Any]] = []
    seen = set()

    def add(move: str, *, teacher: bool = False, false_positive: bool = False, audit_rank: Optional[int] = None):
        if move in seen:
            # upgrade flags
            for x in out:
                if x["move"] == move:
                    x["teacher"] = x["teacher"] or teacher
                    x["false_positive"] = x["false_positive"] or false_positive
                    if audit_rank is not None:
                        x["audit001_rank"] = audit_rank
            return
        seen.add(move)
        out.append(
            {
                "move": move,
                "teacher": teacher,
                "false_positive": false_positive,
                "audit001_rank": audit_rank,
            }
        )

    add(TEACHER_MOVE, teacher=True, audit_rank=29)  # known from Audit001 summary
    add(FALSE_POS, false_positive=True, audit_rank=1)

    if AUDIT001.is_file():
        data = json.loads(AUDIT001.read_text(encoding="utf-8"))
        for cp in data.get("checkpoints", []):
            if cp.get("checkpoint") != "canonical_J8_third_foundation_cascade_quality":
                continue
            for m in (cp.get("ranked_moves") or [])[:10]:
                add(
                    m["move"],
                    teacher=bool(m.get("teacher")),
                    false_positive=(m["move"] == FALSE_POS or (m.get("rank") or 99) <= 3),
                    audit_rank=m.get("rank"),
                )
            # teacher may not be in top10 of stored ranks
            for m in cp.get("ranked_moves") or []:
                if m.get("teacher") or m.get("move") == TEACHER_MOVE:
                    add(m["move"], teacher=True, audit_rank=m.get("rank"))
            break
    return out


def snapshot(st: SpiderState, analysis, deals: int = 5) -> Dict:
    cc = cleanup_cascade_potential(
        st, analysis, deep_one_move=False, precise_merge=True
    )
    pot = next_foundation_completion_potential(
        st, analysis=analysis, round_index=deals, lookahead=1
    )
    bs = pot.get("best_suit")
    nfcp = int(pot.get("per_suit", {}).get(bs, {}).get("score", 0) if bs else pot.get("score", 0) or 0)
    arch = all_suit_architecture_scores(st, analysis=analysis, round_index=deals)
    ab, asc = None, 0
    if arch:
        ab = max(arch.keys(), key=lambda s: arch[s].get("score", 0))
        asc = int(arch[ab].get("score", 0))
    stage = classify_stage(
        scaffold_context={
            "label": "canonical_J8_third_foundation_cascade_quality"
            if len(st.foundations) == 3 and len(st.stock) == 0
            else None,
            "foundations": len(st.foundations),
            "stock_remaining": len(st.stock),
            "sw": sw_of(st),
            "spaces": spaces_of(st),
        },
        diagnostics={
            "stage": cc["stage"],
            "exact_suits": cc["exact_now_suits"],
            "greedy_risk": cc["greedy_risk"],
        },
    )
    return {
        "foundations": len(st.foundations),
        "sw": sw_of(st),
        "spaces": spaces_of(st),
        "stock": len(st.stock),
        "tops": tops(st),
        "cleanup": cc["score"],
        "stage": cc["stage"],
        "exact": list(cc["exact_now_suits"]),
        "near": list(cc["near_complete_suits"]),
        "greedy_risk": cc["greedy_risk"],
        "nfcp_best": bs,
        "nfcp_score": nfcp,
        "arch_best": ab,
        "arch_score": asc,
        "stage_classifier": {
            "macro_stage": stage.macro_stage,
            "sub_stage": stage.sub_stage,
        },
        "suit_copies": foundation_counts(st),
    }


def component_signature(st: SpiderState) -> Dict[str, Any]:
    """Approximate multi-suit staging components visible at tops/long face-up runs."""
    sig = {
        "spaces": spaces_of(st),
        "empty_cols": [i + 1 for i, c in enumerate(st.columns) if c.is_empty()],
        "tops": tops(st),
        "long_runs": [],  # (col1, length, high, low, suit)
        "heart_ah_visible": False,
        "diamond_5d_or_low": False,
        "spade_as_visible": False,
        "club_workspace": False,
    }
    for i, col in enumerate(st.columns):
        up = col.face_up
        if not up:
            continue
        # longest suffix same-suit desc
        k = 1
        while k < len(up) and up[-k - 1].suit == up[-1].suit and up[-k - 1].rank == up[-k].rank + 1:
            k += 1
        if k >= 5:
            sig["long_runs"].append(
                {
                    "col": i + 1,
                    "len": k,
                    "high": str(up[-k]),
                    "low": str(up[-1]),
                    "suit": up[-1].suit,
                }
            )
        for c in up:
            if c.suit == "h" and c.rank == 1:
                sig["heart_ah_visible"] = True
            if c.suit == "d" and c.rank <= 5:
                sig["diamond_5d_or_low"] = True
            if c.suit == "s" and c.rank == 1:
                sig["spade_as_visible"] = True
            if c.suit == "c":
                sig["club_workspace"] = True
    return sig


def component_preservation(before_sig: Dict, after_sig: Dict) -> Tuple[str, str]:
    """Return (verdict, explanation)."""
    notes = []
    score = 0
    if after_sig["spaces"] >= before_sig["spaces"]:
        score += 1
        notes.append("spaces preserved/increased")
    else:
        score -= 1
        notes.append("spaces decreased")
    # empty col set
    lost = set(before_sig["empty_cols"]) - set(after_sig["empty_cols"])
    gained = set(after_sig["empty_cols"]) - set(before_sig["empty_cols"])
    if lost:
        notes.append(f"consumed empty cols {sorted(lost)}")
        score -= 1
    if gained:
        notes.append(f"created empty cols {sorted(gained)}")
        score += 1
    # long runs moved - large growth may indicate dump
    before_max = max((r["len"] for r in before_sig["long_runs"]), default=0)
    after_max = max((r["len"] for r in after_sig["long_runs"]), default=0)
    if after_max >= before_max + 5:
        notes.append(f"long-run growth {before_max}->{after_max} (possible dump)")
        score -= 1
    for key in ("heart_ah_visible", "diamond_5d_or_low", "spade_as_visible"):
        if before_sig[key] and not after_sig[key]:
            notes.append(f"lost {key}")
            score -= 1
    if score >= 1:
        return "preserved", "; ".join(notes) or "ok"
    if score == 0:
        return "mixed", "; ".join(notes) or "neutral"
    return "disrupted", "; ".join(notes) or "damaged"


def workspace_pressure(
    before: SpiderState,
    after: SpiderState,
    move: Tuple[int, int, int],
    before_sig: Dict,
    after_sig: Dict,
) -> Tuple[str, str]:
    src, dst, k = move
    notes = []
    pressure = 0
    # consumes empty
    if before.columns[dst].is_empty() and not after.columns[dst].is_empty() and k >= 8:
        notes.append(f"long run k={k} parked into empty col {dst+1}")
        pressure += 2
    elif before.columns[dst].is_empty():
        notes.append(f"used empty col {dst+1}")
        pressure += 1
    if after_sig["spaces"] < before_sig["spaces"]:
        notes.append("net space loss")
        pressure += 1
    if k >= 10:
        notes.append("very long relocation")
        pressure += 2
    # creates empty from src
    if after.columns[src].is_empty() and not before.columns[src].is_empty():
        notes.append(f"emptied source col {src+1}")
        pressure -= 1
    if pressure >= 3:
        return "high", "; ".join(notes)
    if pressure >= 1:
        return "medium", "; ".join(notes)
    return "low", "; ".join(notes) or "light workspace impact"


def undo_burden(k: int, workspace: str, suffix_ok: int, suffix_total: int) -> Tuple[str, str]:
    if k >= 10 and suffix_ok < max(2, suffix_total // 2):
        return "high", f"long k={k} run likely needs re-park if suffix fails early ({suffix_ok}/{suffix_total})"
    if k >= 8 and suffix_ok < suffix_total:
        return "medium", f"k={k} relocation may need rework (suffix {suffix_ok}/{suffix_total})"
    if k <= 3 and suffix_ok >= suffix_total - 1:
        return "low", "short move, suffix highly compatible"
    return "low" if k <= 4 else "medium", f"k={k}; suffix {suffix_ok}/{suffix_total}"


def scripted_suffix_replay(
    st_after_first: SpiderState,
    suffix: Sequence[Tuple[int, int, int]],
) -> Dict:
    st = st_after_first.clone()
    replayed = 0
    first_fail = None
    for action in suffix:
        try:
            src, dst, k = action
            st.move(src, dst, k)
            replayed += 1
        except Exception as exc:
            first_fail = {
                "move": move_label(action),
                "error": str(exc),
                "after_replayed": replayed,
            }
            break
    return {
        "suffix_moves_total": len(suffix),
        "suffix_moves_replayed": replayed,
        "first_failure": first_fail,
        "final_sw": sw_of(st),
        "final_spaces": spaces_of(st),
        "final_foundations": len(st.foundations),
        "final_tops": tops(st),
        "reached_end": first_fail is None and len(suffix) > 0,
    }


def j17_equivalent(st: SpiderState, analysis) -> bool:
    if len(st.foundations) < 3 or sw_of(st) != 0 or spaces_of(st) < 2:
        return False
    cc = cleanup_cascade_potential(
        st, analysis, deep_one_move=False, precise_merge=True
    )
    if cc["stage"] != "cascade_firing":
        return False
    if cc["score"] < int(J17_CLEANUP * 0.95):
        return False
    exact = set(cc["exact_now_suits"])
    return len(exact & {"s", "h", "d"}) >= 2


# ---------------------------------------------------------------------------
# AUDIT-ONLY / EXPERIMENTAL prototype — do not import from production scoring
# or search runners.
# ---------------------------------------------------------------------------


@dataclass
class CascadeStagingIntegrityProbe:
    """AUDIT-ONLY / EXPERIMENTAL descriptor. Not production scoring."""

    label: str = PROBE_LABEL
    experimental: bool = True
    audit_only: bool = True
    score: float = 0.0
    positives: List[str] = field(default_factory=list)
    negatives: List[str] = field(default_factory=list)
    teacher_suffix_compatibility: float = 0.0
    component_preservation: str = "mixed"
    workspace_pressure: str = "medium"
    undo_burden: str = "medium"
    deceptive_cleanup: bool = False
    would_improve_audit001_j8_ranking: bool = False
    integrity_verdict: str = "neutral"
    explanation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def cascade_staging_integrity_probe(
    state: SpiderState,
    candidate_move: Optional[Tuple[int, int, int]] = None,
    teacher_suffix: Optional[Sequence[Tuple[int, int, int]]] = None,
    *,
    analysis=None,
    audit001_rank: Optional[int] = None,
    one_ply_cleanup_delta: Optional[int] = None,
    is_teacher: bool = False,
) -> CascadeStagingIntegrityProbe:
    """Prototype audit-only cascade staging integrity probe.

    Labelled experimental. Must NOT be used in production scoring paths.
    """
    probe = CascadeStagingIntegrityProbe()
    if analysis is None:
        analysis = build_deal_analysis(tokens_from_file(DEAL))
    suffix = list(teacher_suffix or teacher_suffix_after_first())
    before_sig = component_signature(state)

    if candidate_move is None:
        probe.explanation = "no candidate move"
        return probe

    try:
        after_st, _ = state.clone(), 0
        after_st = state.clone()
        s, d, k = candidate_move
        after_st.move(s, d, k)
    except Exception as exc:
        probe.score = -100
        probe.negatives.append(f"illegal: {exc}")
        probe.integrity_verdict = "reject"
        probe.explanation = f"illegal move {exc}"
        return probe

    after_sig = component_signature(after_st)
    comp_v, comp_e = component_preservation(before_sig, after_sig)
    wp_v, wp_e = workspace_pressure(state, after_st, candidate_move, before_sig, after_sig)
    suf = scripted_suffix_replay(after_st, suffix)
    compat = suf["suffix_moves_replayed"] / max(1, suf["suffix_moves_total"])
    ub_v, ub_e = undo_burden(
        candidate_move[2], wp_v, suf["suffix_moves_replayed"], suf["suffix_moves_total"]
    )

    dcl = one_ply_cleanup_delta
    if dcl is None:
        b = cleanup_cascade_potential(state, analysis, precise_merge=True)["score"]
        a = cleanup_cascade_potential(after_st, analysis, precise_merge=True)["score"]
        dcl = a - b

    # Score construction
    score = 0.0
    pos, neg = [], []
    score += 40 * compat
    if compat >= 0.99:
        pos.append(f"full teacher-suffix compatibility ({suf['suffix_moves_replayed']}/{suf['suffix_moves_total']})")
    elif compat >= 0.5:
        pos.append(f"partial suffix compatibility {compat:.2f}")
    else:
        neg.append(f"poor suffix compatibility {compat:.2f}")
        score -= 25

    if comp_v == "preserved":
        score += 15
        pos.append(f"components preserved: {comp_e}")
    elif comp_v == "disrupted":
        score -= 20
        neg.append(f"components disrupted: {comp_e}")
    else:
        pos.append(f"components mixed: {comp_e}")

    if wp_v == "low":
        score += 10
        pos.append(f"workspace pressure low: {wp_e}")
    elif wp_v == "high":
        score -= 25
        neg.append(f"workspace pressure high: {wp_e}")
    else:
        score -= 5
        neg.append(f"workspace pressure medium: {wp_e}")

    if ub_v == "low":
        score += 8
        pos.append(ub_e)
    elif ub_v == "high":
        score -= 20
        neg.append(ub_e)
    else:
        score -= 5
        neg.append(ub_e)

    deceptive = False
    if (dcl or 0) >= 100 and compat < 0.5:
        deceptive = True
        score -= 40
        neg.append(f"deceptive cleanup spike Δcleanup={dcl} with low suffix compatibility")
    elif (dcl or 0) >= 100 and compat >= 0.99:
        pos.append(f"cleanup gain Δcleanup={dcl} is constructive with full suffix")
        score += 10
    elif (dcl or 0) > 0 and compat >= 0.5:
        pos.append(f"modest cleanup Δ={dcl} with decent suffix")
        score += 5

    if is_teacher:
        pos.append("canonical teacher first move")
        score += 5

    # Would improve Audit001 if integrity preferred over raw cleanup for ranking
    improve = False
    if audit001_rank is not None and audit001_rank > 5 and score >= 30:
        improve = True
        pos.append("integrity probe would elevate this move vs Audit001 cleanup-spike ranking")
    if audit001_rank == 1 and deceptive:
        improve = True
        neg.append("integrity probe would demote Audit001 #1 false positive")

    if is_teacher and compat >= 0.99:
        verdict = "teacher-compatible"
    elif deceptive or (compat < 0.25 and (dcl or 0) >= 100):
        verdict = "false-positive"
    elif compat >= 0.75 and not deceptive:
        verdict = "genuinely-interesting"
    elif compat < 0.25 and comp_v == "disrupted":
        verdict = "reject"
    else:
        verdict = "neutral"

    j17_ok = False
    try:
        j17_ok = j17_equivalent(after_st if suf["reached_end"] else after_st, analysis)
        # better: check after full suffix if completed
        if suf["reached_end"]:
            st_end = after_st.clone()
            for a in suffix:
                st_end.move(*a)
            j17_ok = j17_equivalent(st_end, analysis)
    except Exception:
        j17_ok = False
    if j17_ok:
        pos.append("scripted suffix reaches J17-equivalent")
        score += 30
        if not is_teacher:
            verdict = "genuinely-interesting"

    probe.score = score
    probe.positives = pos
    probe.negatives = neg
    probe.teacher_suffix_compatibility = compat
    probe.component_preservation = comp_v
    probe.workspace_pressure = wp_v
    probe.undo_burden = ub_v
    probe.deceptive_cleanup = deceptive
    probe.would_improve_audit001_j8_ranking = improve
    probe.integrity_verdict = verdict
    probe.explanation = (
        f"audit_only_experimental integrity score={score:.1f}; "
        f"compat={compat:.2f}; components={comp_v}; workspace={wp_v}; "
        f"undo={ub_v}; deceptive_cleanup={deceptive}; verdict={verdict}"
    )
    return probe


def analyze_candidate(
    seed_st: SpiderState,
    seed_snap: Dict,
    seed_sig: Dict,
    cand: Dict,
    analysis,
    suffix: List[Tuple[int, int, int]],
) -> Dict:
    move = parse_move(cand["move"])
    before = seed_snap
    try:
        st2 = seed_st.clone()
        cost = st2.move(*move)
        legal = True
        err = None
    except Exception as exc:
        return {
            **cand,
            "legal": False,
            "error": str(exc),
            "integrity_verdict": "reject",
        }

    after = snapshot(st2, analysis)
    after_sig = component_signature(st2)
    dcl = (
        None
        if before["cleanup"] is None or after["cleanup"] is None
        else after["cleanup"] - before["cleanup"]
    )

    fad = None
    if after["foundations"] > before["foundations"]:
        try:
            fad = foundation_action_delta(
                seed_st, move, analysis=analysis, deals=5, estimate_horizon=False
            )
        except Exception as exc:
            fad = {"classification": None, "error": str(exc)}

    suf = scripted_suffix_replay(st2, suffix)
    # Also try full teacher path including teacher first if candidate is teacher
    j17_reached = False
    if suf["reached_end"]:
        try:
            st_end = st2.clone()
            for a in suffix:
                st_end.move(*a)
            j17_reached = j17_equivalent(st_end, analysis)
            cc_end = cleanup_cascade_potential(
                st_end, analysis, deep_one_move=False, precise_merge=True
            )
            suf["final_cleanup"] = cc_end["score"]
            suf["final_stage"] = cc_end["stage"]
            suf["final_exact"] = cc_end["exact_now_suits"]
            suf["final_sw"] = sw_of(st_end)
            suf["final_spaces"] = spaces_of(st_end)
        except Exception:
            pass

    comp_v, comp_e = component_preservation(seed_sig, after_sig)
    wp_v, wp_e = workspace_pressure(seed_st, st2, move, seed_sig, after_sig)
    ub_v, ub_e = undo_burden(
        move[2], wp_v, suf["suffix_moves_replayed"], suf["suffix_moves_total"]
    )

    deceptive = bool((dcl or 0) >= 100 and suf["suffix_moves_replayed"] < suf["suffix_moves_total"] // 2)

    probe = cascade_staging_integrity_probe(
        seed_st,
        candidate_move=move,
        teacher_suffix=suffix,
        analysis=analysis,
        audit001_rank=cand.get("audit001_rank"),
        one_ply_cleanup_delta=dcl,
        is_teacher=bool(cand.get("teacher")),
    )

    # integrity verdict for table
    if cand.get("teacher") and j17_reached:
        verdict = "teacher-compatible"
    elif deceptive:
        verdict = "false-positive"
    elif j17_reached:
        verdict = "genuinely-interesting"
    elif suf["suffix_moves_replayed"] >= suf["suffix_moves_total"] * 0.75:
        verdict = "genuinely-interesting" if not cand.get("teacher") else "teacher-compatible"
    elif suf["suffix_moves_replayed"] == 0 and (dcl or 0) >= 100:
        verdict = "false-positive"
    elif comp_v == "disrupted" and wp_v == "high":
        verdict = "reject"
    else:
        verdict = probe.integrity_verdict

    return {
        "move": cand["move"],
        "teacher": bool(cand.get("teacher")),
        "false_positive_flag": bool(cand.get("false_positive")),
        "audit001_rank": cand.get("audit001_rank"),
        "legal": legal,
        "mw_cost": cost,
        "one_ply": {
            "foundations": after["foundations"],
            "sw": after["sw"],
            "spaces": after["spaces"],
            "cleanup": after["cleanup"],
            "cleanup_delta": dcl,
            "stage": after["stage"],
            "exact": after["exact"],
            "near": after["near"],
            "greedy_risk": after["greedy_risk"],
            "nfcp_best": after["nfcp_best"],
            "nfcp_score": after["nfcp_score"],
            "arch_best": after["arch_best"],
            "arch_score": after["arch_score"],
            "stage_classifier": after["stage_classifier"],
            "tops": after["tops"],
        },
        "foundation_action_delta": {
            "classification": (fad or {}).get("classification"),
            "explanation": (fad or {}).get("explanation"),
        }
        if fad
        else None,
        "suffix_replay": suf,
        "reached_j17_equivalent": j17_reached,
        "component_preservation": comp_v,
        "component_preservation_detail": comp_e,
        "workspace_pressure": wp_v,
        "workspace_pressure_detail": wp_e,
        "undo_burden": ub_v,
        "undo_burden_detail": ub_e,
        "deceptive_cleanup": deceptive,
        "integrity_verdict": verdict,
        "cascade_staging_integrity_probe": probe.to_dict(),
        "explanation": (
            f"Δcleanup={dcl}; suffix {suf['suffix_moves_replayed']}/"
            f"{suf['suffix_moves_total']}; components={comp_v}; "
            f"workspace={wp_v}; undo={ub_v}; deceptive={deceptive}; "
            f"verdict={verdict}"
        ),
    }


def run_investigation() -> Dict:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    meta = json.loads(MANIFEST.read_text(encoding="utf-8"))
    tokens = tokens_from_file(DEAL)
    analysis = build_deal_analysis(tokens)

    print("J8 Gap Investigation 001", flush=True)
    print(NO_SEARCH, flush=True)

    seed_st, seed_mw = replay_j8()
    assert len(seed_st.foundations) == 3
    assert sw_of(seed_st) == 0
    seed_snap = snapshot(seed_st, analysis)
    seed_sig = component_signature(seed_st)
    suffix = teacher_suffix_after_first()
    print(
        f"Seed MW={seed_mw} f=3 sw=0 spaces={spaces_of(seed_st)} "
        f"cleanup={seed_snap['cleanup']} stage={seed_snap['stage']}",
        flush=True,
    )
    print(f"Suffix after first (J10-J17): {len(suffix)} moves", flush=True)

    candidates = load_candidate_moves()
    print(f"Candidates: {len(candidates)}", flush=True)
    results = []
    for c in candidates:
        print(f"  analyzing {c['move']} ...", flush=True)
        results.append(
            analyze_candidate(seed_st, seed_snap, seed_sig, c, analysis, suffix)
        )

    teacher = next((r for r in results if r.get("teacher")), None)
    fp = next((r for r in results if r.get("move") == FALSE_POS), None)

    # Conclusion
    if (
        teacher
        and teacher.get("reached_j17_equivalent")
        and fp
        and fp.get("deceptive_cleanup")
        and (fp.get("suffix_replay") or {}).get("suffix_moves_replayed", 0)
        < (teacher.get("suffix_replay") or {}).get("suffix_moves_replayed", 0)
    ):
        conclusion = 1
        conclusion_text = (
            "1. J8 gap is mostly explained by deceptive one-ply cleanup; recommend a later "
            "bounded task to formalise cascade_staging_integrity as a diagnostic feature."
        )
    elif teacher and not teacher.get("reached_j17_equivalent"):
        conclusion = 2
        conclusion_text = (
            "2. J8 gap is not explained; more state inspection needed."
        )
    elif any(
        r.get("integrity_verdict") == "genuinely-interesting" and not r.get("teacher")
        for r in results
    ):
        conclusion = 3
        conclusion_text = (
            "3. One or more false positives look genuinely promising; recommend later "
            "controlled experiment, but do not update scaffolds now."
        )
    else:
        conclusion = 4
        conclusion_text = (
            "4. Existing diagnostics are adequate; no further J8 work needed."
        )

    # Deep dive comparison
    deep = {
        "teacher": teacher,
        "false_positive": fp,
        "why_fp_ranked_high_in_audit001": (
            f"{FALSE_POS} produced a large one-ply cleanup spike "
            f"(Δcleanup={fp.get('one_ply', {}).get('cleanup_delta') if fp else 'n/a'}) "
            "while keeping sw=0 and spaces≈2, which the audit_only_composite rewarded."
            if fp
            else "false positive missing"
        ),
        "why_fp_damages_or_not": (
            f"Suffix compatibility {fp['suffix_replay']['suffix_moves_replayed']}/"
            f"{fp['suffix_replay']['suffix_moves_total']}; first_failure="
            f"{fp['suffix_replay'].get('first_failure')}; components="
            f"{fp.get('component_preservation')}; workspace={fp.get('workspace_pressure')}; "
            f"deceptive_cleanup={fp.get('deceptive_cleanup')}."
            if fp
            else ""
        ),
        "signal_to_demote_fp": (
            "Prefer cascade_staging_integrity_probe: demote large cleanup gains with low "
            "teacher-suffix compatibility / high workspace pressure / high undo burden."
        ),
        "signal_to_preserve_teacher": (
            "Reward full/near-full fixed teacher-suffix compatibility and low undo burden "
            "even when one-ply cleanup delta is modest."
        ),
    }

    report = {
        "investigation_id": meta["investigation_id"],
        "seed_scaffold": meta["seed_scaffold"],
        "seed_mw": seed_mw,
        "seed_snapshot": seed_snap,
        "teacher_move": TEACHER_MOVE,
        "known_false_positive": FALSE_POS,
        "source_audit": meta["source_audit"],
        "candidate_count": len(results),
        "note": NO_SEARCH,
        "search_invoked": False,
        "beam_invoked": False,
        "optimisation_invoked": False,
        "production_scoring_changed": False,
        "cascade_staging_integrity_probe_label": PROBE_LABEL,
        "suffix_definition": "canonical J10..J17 after candidate first move (fixed scripted)",
        "candidates": results,
        "deep_dive": {
            "why_fp_ranked_high_in_audit001": deep["why_fp_ranked_high_in_audit001"],
            "why_fp_damages_or_not": deep["why_fp_damages_or_not"],
            "signal_to_demote_fp": deep["signal_to_demote_fp"],
            "signal_to_preserve_teacher": deep["signal_to_preserve_teacher"],
            "teacher_summary": {
                "move": (teacher or {}).get("move"),
                "audit001_rank": (teacher or {}).get("audit001_rank"),
                "cleanup_delta": (teacher or {}).get("one_ply", {}).get("cleanup_delta"),
                "suffix": (teacher or {}).get("suffix_replay"),
                "j17": (teacher or {}).get("reached_j17_equivalent"),
                "verdict": (teacher or {}).get("integrity_verdict"),
            },
            "false_positive_summary": {
                "move": (fp or {}).get("move"),
                "audit001_rank": (fp or {}).get("audit001_rank"),
                "cleanup_delta": (fp or {}).get("one_ply", {}).get("cleanup_delta"),
                "suffix": (fp or {}).get("suffix_replay"),
                "j17": (fp or {}).get("reached_j17_equivalent"),
                "verdict": (fp or {}).get("integrity_verdict"),
            },
        },
        "conclusion": {"choice": conclusion, "text": conclusion_text},
        "meta": meta,
    }
    return report


def write_reports(report: Dict) -> None:
    RESULTS_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = [
        "# J8 Gap Investigation 001 — cascade-staging false-positive analysis",
        "",
        f"**{NO_SEARCH}**",
        "",
        f"**cascade_staging_integrity_probe label:** `{PROBE_LABEL}`",
        "",
        "## A. Investigation summary",
        "",
        f"- seed: `{report['seed_scaffold']}` MW={report['seed_mw']}",
        f"- candidates: {report['candidate_count']}",
        "- one-ply + fixed scripted suffix replay: **yes**",
        "- beam/search: **no**",
        "- production scoring changes: **no**",
        "",
        "## B. Candidate comparison table",
        "",
        "| move | teacher? | Audit001 rank | Δcleanup | 1-ply sw/sp | suffix ok | first fail | J17-eq? | components | workspace | undo | deceptive? | verdict |",
        "|---|---|---:|---:|---|---:|---|---|---|---|---|---|---|",
    ]
    for c in report["candidates"]:
        if not c.get("legal", True) and c.get("error"):
            lines.append(f"| {c['move']} | {c.get('teacher')} | {c.get('audit001_rank')} | — | — | — | illegal | no | — | — | — | — | reject |")
            continue
        suf = c.get("suffix_replay") or {}
        ff = suf.get("first_failure")
        ff_s = ff["move"] if ff else "-"
        op = c.get("one_ply") or {}
        lines.append(
            f"| {c['move']} | {c.get('teacher')} | {c.get('audit001_rank')} | "
            f"{op.get('cleanup_delta')} | {op.get('sw')}/{op.get('spaces')} | "
            f"{suf.get('suffix_moves_replayed')}/{suf.get('suffix_moves_total')} | "
            f"{ff_s} | {c.get('reached_j17_equivalent')} | "
            f"{c.get('component_preservation')} | {c.get('workspace_pressure')} | "
            f"{c.get('undo_burden')} | {c.get('deceptive_cleanup')} | "
            f"{c.get('integrity_verdict')} |"
        )

    dd = report["deep_dive"]
    lines += [
        "",
        "## C. Teacher vs top false-positive deep dive",
        "",
        f"### Teacher `{TEACHER_MOVE}`",
        f"- summary: {dd['teacher_summary']}",
        "",
        f"### False positive `{FALSE_POS}`",
        f"- summary: {dd['false_positive_summary']}",
        "",
        f"- Why Audit001 ranked FP high: {dd['why_fp_ranked_high_in_audit001']}",
        f"- Damage / not: {dd['why_fp_damages_or_not']}",
        f"- Signal to demote FP: {dd['signal_to_demote_fp']}",
        f"- Signal to preserve teacher: {dd['signal_to_preserve_teacher']}",
        "",
        "## D. Prototype cascade_staging_integrity_probe output",
        "",
        f"Label: **{PROBE_LABEL}** (must not enter production scoring / search runners).",
        "",
    ]
    for c in report["candidates"]:
        if not c.get("legal", True):
            continue
        p = c.get("cascade_staging_integrity_probe") or {}
        lines.append(
            f"- **{c['move']}** score={p.get('score')} verdict={p.get('integrity_verdict')} "
            f"improve_audit001={p.get('would_improve_audit001_j8_ranking')}"
        )
        lines.append(f"  - + {p.get('positives')}")
        lines.append(f"  - − {p.get('negatives')}")
    lines += [
        "",
        "## E. Diagnostic gap conclusion",
        "",
        report["conclusion"]["text"],
        "",
        "## Explicit confirmations",
        "",
        "- no beam/search/optimisation",
        "- no production scoring changes",
        "- no scaffold registry changes",
        f"- integrity probe is `{PROBE_LABEL}` only",
        "",
    ]
    RESULTS_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    report = run_investigation()
    write_reports(report)
    print(f"Wrote {RESULTS_JSON.relative_to(ROOT)}", flush=True)
    print(f"Wrote {RESULTS_MD.relative_to(ROOT)}", flush=True)
    print(report["conclusion"]["text"], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
