#!/usr/bin/env python3
"""Diagnostic-only stage classifier / feature arbitration for deal 4925153.

Explains which diagnostic signals should dominate at each accepted scaffold stage.
Does NOT affect production scoring or search. Interpretability + experiment control only.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[4]
SCAFFOLD_DIR = ROOT / "src" / "spider" / "planner" / "diagnostics" / "scaffolds"
LADDER_PATH = SCAFFOLD_DIR / "4925153_deal_scaffold_ladder.json"
REPORT_JSON = SCAFFOLD_DIR / "4925153_stage_classification_report.json"
REPORT_MD = SCAFFOLD_DIR / "4925153_stage_classification_report.md"

# Diagnostic signal names (non-production)
DIAG_MOBILITY = "mobility_basic_legal_moves"
DIAG_STOCK_ASSISTED = "stock_assisted_merge_detection"
DIAG_FCP = "foundation_completion_potential"
DIAG_NFCP = "next_foundation_completion_potential"
DIAG_ARCHITECTURE = "foundation_architecture_score"
DIAG_CLEANUP = "cleanup_cascade_potential"
DIAG_DELTA = "foundation_action_delta"
DIAG_TRANSITION = "scaffold_transition_bench_comparison"
DIAG_SW = "sw_count"
DIAG_EXACT = "exact_foundation_now"


@dataclass
class StageProfile:
    """Diagnostic stage profile (metadata only; not production scoring)."""

    macro_stage: str
    sub_stage: str
    primary_objective: str
    preferred_diagnostics: List[str] = field(default_factory=list)
    suppressed_or_low_trust_diagnostics: List[str] = field(default_factory=list)
    major_risks: List[str] = field(default_factory=list)
    seed_policy: str = "yes"
    continuation_policy: str = "yes"
    target_kind: str = ""
    confidence: float = 0.9
    explanation: str = ""
    scaffold_label: Optional[str] = None
    diagnostic_only: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# Explicit ladder calibrations (frozen control spine for deal 4925153)
_LADDER_PROFILES: Dict[str, StageProfile] = {
    "canonical_start": StageProfile(
        macro_stage="opening",
        sub_stage="deal_start",
        primary_objective="reveal cards and build mobility / same-suit runs",
        preferred_diagnostics=[DIAG_MOBILITY, DIAG_SW],
        suppressed_or_low_trust_diagnostics=[
            DIAG_CLEANUP,
            DIAG_DELTA,
            DIAG_ARCHITECTURE,
            "low_sw_alone_as_objective",
        ],
        major_risks=["overfitting low_sw without foundation path", "premature stock deal"],
        seed_policy="yes",
        continuation_policy="yes",
        target_kind="first stock boundary / first foundation planning",
        confidence=0.95,
        explanation=(
            "Opening layout. Prefer mobility/reveal structure. Low sw is useful but "
            "insufficient as a sole objective. Cleanup/cascade diagnostics are not yet trusted."
        ),
        scaffold_label="canonical_start",
    ),
    "canonical_deal1_or_section_A_end": StageProfile(
        macro_stage="first_foundation_planning",
        sub_stage="post_deal1_boundary",
        primary_objective="build first spade foundation route after stock deal #1",
        preferred_diagnostics=[DIAG_STOCK_ASSISTED, DIAG_FCP, DIAG_MOBILITY],
        suppressed_or_low_trust_diagnostics=[
            DIAG_CLEANUP,
            DIAG_DELTA,
            "exact_now_alone_implies_take",
            "low_sw_alone_as_objective",
        ],
        major_risks=["chasing low sw without stock-assisted merge path"],
        seed_policy="yes",
        continuation_policy="yes",
        target_kind="build first spade foundation route",
        confidence=0.93,
        explanation=(
            "First-foundation planning after deal #1. Stock-assisted merge detection and "
            "foundation_completion_potential matter; cleanup cascade is not yet the regime."
        ),
        scaffold_label="canonical_deal1_or_section_A_end",
    ),
    "canonical_B5_or_B5_seed": StageProfile(
        macro_stage="first_foundation_planning",
        sub_stage="divergence_seed",
        primary_objective="evaluate first-foundation divergence / stock-assisted spade merge",
        preferred_diagnostics=[DIAG_STOCK_ASSISTED, DIAG_FCP, DIAG_MOBILITY],
        suppressed_or_low_trust_diagnostics=[
            DIAG_CLEANUP,
            DIAG_ARCHITECTURE,
            "continuation_from_any_first_foundation_shortcut",
        ],
        major_risks=[
            "accepting MW-shortcut first foundation as continuation scaffold",
            "losing Section D structure",
        ],
        seed_policy="yes",
        continuation_policy="yes",
        target_kind="first foundation completion (canonical or auxiliary shortcut)",
        confidence=0.95,
        explanation=(
            "Canonical B5 divergence seed for first-foundation beams. Preferred diagnostics "
            "include stock-assisted merge detection. Shortcuts from here may be first-foundation-only."
        ),
        scaffold_label="canonical_B5_or_B5_seed",
    ),
    "B5_shortcut_first_foundation": StageProfile(
        macro_stage="auxiliary_branch",
        sub_stage="first_foundation_only_shortcut",
        primary_objective="record MW-optimised first foundation (not continuation)",
        preferred_diagnostics=[DIAG_FCP, DIAG_STOCK_ASSISTED, DIAG_TRANSITION],
        suppressed_or_low_trust_diagnostics=[
            "use_as_continuation_scaffold",
            "section_d_compatibility_assumed",
            DIAG_CLEANUP,
        ],
        major_risks=[
            "wrong continuation structure",
            "cannot reuse canonical Section D",
            "exposes wrong 6-card / lacks 7S-6S structure",
        ],
        seed_policy="auxiliary-only",
        continuation_policy="not accepted continuation",
        target_kind="first-foundation-only optimisation evidence",
        confidence=0.98,
        explanation=(
            "Auxiliary first-foundation-only shortcut (MW=56). Valid optimisation evidence but "
            "NOT an accepted continuation scaffold: cannot reuse canonical Section D; wrong "
            "continuation structure (wrong 6-card, lacks required 7S-6S)."
        ),
        scaffold_label="B5_shortcut_first_foundation",
    ),
    "canonical_first_foundation_D1": StageProfile(
        macro_stage="post_first_foundation",
        sub_stage="first_foundation_complete",
        primary_objective="shape second-foundation architecture (prefer diamond path for this deal)",
        preferred_diagnostics=[DIAG_ARCHITECTURE, DIAG_NFCP, DIAG_STOCK_ASSISTED],
        suppressed_or_low_trust_diagnostics=[
            "nfcp_best_suit_alone_without_architecture",
            DIAG_CLEANUP,
            "exact_now_alone_implies_take",
            "low_sw_alone_as_objective",
        ],
        major_risks=[
            "nfcp chasing decoy suits (e.g. hearts) over architecture",
            "reopening B5 as continuation",
        ],
        seed_policy="yes",
        continuation_policy="yes",
        target_kind="second foundation architecture",
        confidence=0.96,
        explanation=(
            "Canonical first foundation complete (spades). Enter post-first-foundation planning. "
            "Architecture score is needed because nfcp can chase decoy suits toward H:20."
        ),
        scaffold_label="canonical_first_foundation_D1",
    ),
    "canonical_H20_second_foundation": StageProfile(
        macro_stage="pre_cleanup_with_stock",
        sub_stage="second_foundation_complete",
        primary_objective="transition toward stock-empty cleanup while preserving cascade structure",
        preferred_diagnostics=[
            DIAG_ARCHITECTURE,
            DIAG_NFCP,
            DIAG_CLEANUP,
            DIAG_TRANSITION,
        ],
        suppressed_or_low_trust_diagnostics=[
            "section_f_second_foundation_divergence_reopen",
            "replace_h20_scaffold",
            "exact_now_alone_implies_take",
        ],
        major_risks=[
            "reopening frozen Section F second-foundation divergence",
            "damaging spaces/sw before deal #5",
        ],
        seed_policy="yes",
        continuation_policy="yes",
        target_kind="transition toward stock-empty cleanup",
        confidence=0.97,
        explanation=(
            "Accepted gold second-foundation scaffold (H:20; s+d). Stock remains. Prefer "
            "architecture + next-stage cleanup readiness; do not reopen Section F divergence."
        ),
        scaffold_label="canonical_H20_second_foundation",
    ),
    "canonical_I1_after_deal5": StageProfile(
        macro_stage="cleanup_active",
        sub_stage="stock_empty_cleanup_seed",
        primary_objective="multi-suit cleanup cascade readiness; third foundation without greed",
        preferred_diagnostics=[DIAG_CLEANUP, DIAG_DELTA, DIAG_ARCHITECTURE, DIAG_TRANSITION],
        suppressed_or_low_trust_diagnostics=[
            "nfcp_greedy_next_foundation_alone",
            "exact_now_alone_implies_take",
            DIAG_STOCK_ASSISTED,
            "low_sw_alone_as_objective",
        ],
        major_risks=[
            "single-suit nfcp greed after stock empty",
            "ignoring multi-suit cascade readiness",
        ],
        seed_policy="yes",
        continuation_policy="yes",
        target_kind="third foundation / cascade staging (prefer J:8 quality)",
        confidence=0.97,
        explanation=(
            "Stock empty; cleanup_active. cleanup_cascade_potential dominates over next-foundation "
            "greed; foundation_action_delta required for exact foundation decisions. Stock-assisted "
            "gates are low-trust (no stock left)."
        ),
        scaffold_label="canonical_I1_after_deal5",
    ),
    "beam_MW144_club_third_foundation": StageProfile(
        macro_stage="auxiliary_branch",
        sub_stage="MW_optimised_third_foundation",
        primary_objective="record faster third foundation without claiming cascade gold",
        preferred_diagnostics=[DIAG_CLEANUP, DIAG_TRANSITION, DIAG_DELTA],
        suppressed_or_low_trust_diagnostics=[
            "use_as_j8_replacement",
            "mw_alone_as_cascade_quality",
            "reopen_mw144_as_replacement_without_control_plane",
        ],
        major_risks=[
            "replacing J:8 gold despite weaker sw/spaces/cleanup",
            "confusing MW optimisation with cascade quality",
            "reopening closed mw144_rescue_branch without authorisation",
        ],
        seed_policy="auxiliary-only",
        continuation_policy="auxiliary-only",
        target_kind="MW-optimised third-foundation seed only (branch closed_auxiliary_only after Exp002)",
        confidence=0.99,
        explanation=(
            "Auxiliary MW-optimised third foundation (MW=144). Faster than J:8 (MW=149) but "
            "weaker cascade structure (seed sw=3, spaces=1, cleanup=544 vs J:8 sw=0, spaces=3, cleanup=838). "
            "Exp002 (depth≤14/beam≤150) recovered sw=0 by MW≈148 but stayed spaces=1, cleanup≈581, "
            "cleanup_active — not J17-equivalent. Branch status closed_auxiliary_only; replacement_candidate=false. "
            "Future MW144 experiments require explicit control-plane authorisation and cannot auto-promote."
        ),
        scaffold_label="beam_MW144_club_third_foundation",
    ),
    "canonical_J8_third_foundation_cascade_quality": StageProfile(
        macro_stage="cascade_staging",
        sub_stage="gold_third_foundation_scaffold",
        primary_objective="stage multi-suit cascade toward J:17 without premature exact hearts",
        preferred_diagnostics=[DIAG_CLEANUP, DIAG_DELTA, DIAG_TRANSITION],
        suppressed_or_low_trust_diagnostics=[
            "exact_now_alone_implies_take",
            "nfcp_greedy_next_foundation_alone",
            "low_sw_alone_as_objective",
        ],
        major_risks=[
            "premature heart foundation when exact later (J:11)",
            "collapsing spaces/sw during staging",
        ],
        seed_policy="yes",
        continuation_policy="accepted continuation",
        target_kind="pre-batch cascade (J:17 gold)",
        confidence=0.98,
        explanation=(
            "Gold cascade-quality third-foundation scaffold. Preferred diagnostics: "
            "cleanup_cascade_potential + foundation_action_delta. Exact foundation availability "
            "is useful but insufficient — do not take hearts solely because exact_now."
        ),
        scaffold_label="canonical_J8_third_foundation_cascade_quality",
    ),
    "canonical_J11_greedy_risk_hearts_exact": StageProfile(
        macro_stage="cascade_staging",
        sub_stage="anti_greedy_checkpoint",
        primary_objective="continue multi-suit staging; deprioritise premature heart exact",
        preferred_diagnostics=[DIAG_CLEANUP, DIAG_DELTA, DIAG_TRANSITION],
        suppressed_or_low_trust_diagnostics=[
            "exact_now_alone_implies_take",
            "greedy_risk_as_hard_ban",
            "nfcp_hearts_1000_as_must_take",
        ],
        major_risks=[
            "premature heart foundation",
            "greedy exact foundation completion",
            "treating exact hearts as automatically preferred",
        ],
        seed_policy="yes",
        continuation_policy="yes",
        target_kind="delayed-heart cascade staging to multi-exact J:17",
        confidence=0.99,
        explanation=(
            "Anti-greedy calibration checkpoint. Exact hearts are available (move 5 1 7) but not "
            "automatically preferred — foundation_action_delta classifies immediate hearts as "
            "cascade-negative while staging partners remain. greedy_risk is a warning, not a hard prune. "
            "Preferred diagnostics: cleanup_cascade_potential and foundation_action_delta."
        ),
        scaffold_label="canonical_J11_greedy_risk_hearts_exact",
    ),
    "canonical_J17_pre_batch_cascade": StageProfile(
        macro_stage="cascade_firing",
        sub_stage="gold_pre_batch_scaffold",
        primary_objective="execute multi-exact foundation firing cascade to solved",
        preferred_diagnostics=[DIAG_DELTA, DIAG_CLEANUP, "cascade_firing_recognition", DIAG_TRANSITION],
        suppressed_or_low_trust_diagnostics=[
            "treat_as_greedy_risk_staging",
            "delay_foundations_unnecessarily",
            "nfcp_single_suit_planning",
        ],
        major_risks=[
            "misclassifying multi-exact firing as greedy risk",
            "unwinding multi-suit readiness",
        ],
        seed_policy="yes",
        continuation_policy="accepted gold pre-batch scaffold",
        target_kind="batch cascade to solved (J:18–J:22)",
        confidence=0.99,
        explanation=(
            "Gold pre-batch cascade_firing scaffold. Exact suits s,h,d present; multi-exact means "
            "firing, not greedy-risk staging. foundation_action_delta classifies exact foundations "
            "here as cascade-firing (same heart move 5 1 7 is negative at J:11, firing here)."
        ),
        scaffold_label="canonical_J17_pre_batch_cascade",
    ),
    "canonical_J22_solved": StageProfile(
        macro_stage="solved",
        sub_stage="endpoint",
        primary_objective="endpoint validation only",
        preferred_diagnostics=[DIAG_TRANSITION, "solved_check"],
        suppressed_or_low_trust_diagnostics=[
            DIAG_NFCP,
            DIAG_CLEANUP,
            DIAG_STOCK_ASSISTED,
        ],
        major_risks=[],
        seed_policy="no",
        continuation_policy="no",
        target_kind="endpoint",
        confidence=1.0,
        explanation="Solved endpoint. No planning diagnostics dominate; use for replay validation only.",
        scaffold_label="canonical_J22_solved",
    ),
}


def _profile_from_ladder_entry(entry: Dict[str, Any]) -> Optional[StageProfile]:
    label = entry.get("label")
    if label in _LADDER_PROFILES:
        p = _LADDER_PROFILES[label]
        # attach label ensure
        p = StageProfile(**{**p.to_dict(), "scaffold_label": label})
        return p
    return None


def _heuristic_from_metrics(
    *,
    foundations: int,
    stock: Optional[int],
    sw: Optional[int],
    spaces: Optional[int],
    stage_diag: Optional[str],
    exact: Optional[Sequence[str]],
    greedy_risk: Optional[bool],
    status: Optional[str],
    role: Optional[str],
) -> StageProfile:
    """Fallback when no scaffold label — still diagnostic-only."""
    status_l = (status or "").lower()
    role_l = (role or "").lower()
    if "auxiliary" in status_l or "auxiliary" in role_l:
        return StageProfile(
            macro_stage="auxiliary_branch",
            sub_stage="unnamed_auxiliary",
            primary_objective="treat as non-gold branch until proven",
            preferred_diagnostics=[DIAG_TRANSITION, DIAG_CLEANUP],
            suppressed_or_low_trust_diagnostics=["auto_promotion_to_gold"],
            major_risks=["accidental gold promotion"],
            seed_policy="auxiliary-only",
            continuation_policy="auxiliary-only",
            target_kind="auxiliary study",
            confidence=0.6,
            explanation="Heuristic auxiliary_branch from status/role text.",
        )
    if foundations >= 8 or stage_diag == "solved":
        return StageProfile(
            macro_stage="solved",
            sub_stage="endpoint",
            primary_objective="endpoint",
            preferred_diagnostics=["solved_check"],
            confidence=0.9,
            explanation="Foundations complete / solved stage.",
            seed_policy="no",
            continuation_policy="no",
            target_kind="endpoint",
        )
    if stage_diag == "cascade_firing" or (
        foundations >= 3 and exact and len(exact) >= 2 and stock == 0
    ):
        return StageProfile(
            macro_stage="cascade_firing",
            sub_stage="multi_exact_or_diag_firing",
            primary_objective="fire multi-exact foundations",
            preferred_diagnostics=[DIAG_DELTA, DIAG_CLEANUP],
            suppressed_or_low_trust_diagnostics=["treat_as_greedy_risk_staging"],
            major_risks=["misread as greedy staging"],
            seed_policy="yes",
            continuation_policy="yes",
            target_kind="batch cascade",
            confidence=0.75,
            explanation="Multi-exact / cascade_firing diagnostics — firing, not greedy risk.",
        )
    if stage_diag == "cascade_staging" or (foundations >= 3 and stock == 0):
        risks = []
        if greedy_risk or (exact and "h" in exact):
            risks.append("premature heart foundation")
        return StageProfile(
            macro_stage="cascade_staging",
            sub_stage="stock_empty_post_third",
            primary_objective="stage cascade; use foundation_action_delta for exact moves",
            preferred_diagnostics=[DIAG_CLEANUP, DIAG_DELTA],
            suppressed_or_low_trust_diagnostics=["exact_now_alone_implies_take"],
            major_risks=risks or ["premature exact foundation"],
            seed_policy="yes",
            continuation_policy="yes",
            target_kind="pre-batch cascade",
            confidence=0.7,
            explanation=(
                "Cascade staging after third foundation. exact_now insufficient; "
                "cleanup_cascade_potential + foundation_action_delta preferred."
            ),
        )
    if stock == 0 and foundations >= 2:
        return StageProfile(
            macro_stage="cleanup_active",
            sub_stage="stock_empty",
            primary_objective="cleanup cascade readiness",
            preferred_diagnostics=[DIAG_CLEANUP, DIAG_DELTA],
            suppressed_or_low_trust_diagnostics=[DIAG_STOCK_ASSISTED, "nfcp_greedy_next_foundation_alone"],
            major_risks=["single-suit greed"],
            seed_policy="yes",
            continuation_policy="yes",
            target_kind="third foundation / cascade",
            confidence=0.7,
            explanation="Stock empty with foundations>=2 → cleanup_active.",
        )
    if foundations >= 2 and stock and stock > 0:
        return StageProfile(
            macro_stage="pre_cleanup_with_stock",
            sub_stage="post_second_with_stock",
            primary_objective="preserve structure into final stock wave",
            preferred_diagnostics=[DIAG_ARCHITECTURE, DIAG_NFCP, DIAG_CLEANUP],
            suppressed_or_low_trust_diagnostics=["exact_now_alone_implies_take"],
            major_risks=["damaging structure before final deal"],
            seed_policy="yes",
            continuation_policy="yes",
            target_kind="stock-empty cleanup",
            confidence=0.65,
            explanation="Second foundation done with stock remaining → pre_cleanup_with_stock.",
        )
    if foundations == 1:
        return StageProfile(
            macro_stage="post_first_foundation",
            sub_stage="first_complete",
            primary_objective="second foundation architecture",
            preferred_diagnostics=[DIAG_ARCHITECTURE, DIAG_NFCP],
            suppressed_or_low_trust_diagnostics=["nfcp_best_suit_alone_without_architecture"],
            major_risks=["decoy suit chase"],
            seed_policy="yes",
            continuation_policy="yes",
            target_kind="second foundation",
            confidence=0.65,
            explanation="One foundation complete → post_first_foundation; architecture needed.",
        )
    if foundations == 0:
        return StageProfile(
            macro_stage="first_foundation_planning",
            sub_stage="pre_first",
            primary_objective="first foundation via stock-assisted path",
            preferred_diagnostics=[DIAG_STOCK_ASSISTED, DIAG_FCP],
            suppressed_or_low_trust_diagnostics=[DIAG_CLEANUP, "low_sw_alone_as_objective"],
            major_risks=["low sw without merge path"],
            seed_policy="yes",
            continuation_policy="yes",
            target_kind="first foundation",
            confidence=0.6,
            explanation="No foundations yet → first_foundation_planning. Low sw insufficient alone.",
        )
    return StageProfile(
        macro_stage="rejected_or_noncontinuation",
        sub_stage="unknown",
        primary_objective="manual review",
        preferred_diagnostics=[DIAG_TRANSITION],
        confidence=0.3,
        explanation="Could not confidently classify stage.",
        seed_policy="no",
        continuation_policy="no",
        target_kind="unknown",
    )


def classify_stage(
    state: Any = None,
    scaffold_context: Optional[Dict[str, Any]] = None,
    diagnostics: Optional[Dict[str, Any]] = None,
) -> StageProfile:
    """Classify diagnostic stage for a state and/or scaffold context.

    Parameters
    ----------
    state:
        Optional SpiderState (unused for ladder-label path; reserved for future
        metric-based refinement). Not used by production scoring.
    scaffold_context:
        Optional dict with keys such as label, status, role, mw, foundations,
        stock_remaining, sw, spaces, diagnostics.
    diagnostics:
        Optional dict with cleanup stage/exact/greedy_risk etc.

    Returns
    -------
    StageProfile
        Diagnostic metadata only.
    """
    ctx = dict(scaffold_context or {})
    diag = dict(diagnostics or {})
    if ctx.get("diagnostics") and isinstance(ctx["diagnostics"], dict):
        # ladder entry nested diagnostics
        for k, v in ctx["diagnostics"].items():
            diag.setdefault(k, v)

    label = ctx.get("label") or ctx.get("scaffold_label")
    if label and label in _LADDER_PROFILES:
        return StageProfile(**{**_LADDER_PROFILES[label].to_dict(), "scaffold_label": label})

    # Try ladder entry match without full profile table
    if label:
        # Unknown label but auxiliary cues
        status = str(ctx.get("status") or "")
        role = str(ctx.get("role") or "")
        if "auxiliary" in status.lower() or "auxiliary" in role.lower():
            p = _heuristic_from_metrics(
                foundations=int(ctx.get("foundations") or 0),
                stock=ctx.get("stock_remaining"),
                sw=ctx.get("sw"),
                spaces=ctx.get("spaces"),
                stage_diag=(diag.get("stage") if diag else None),
                exact=diag.get("exact_suits") or diag.get("exact"),
                greedy_risk=diag.get("greedy_risk"),
                status=status,
                role=role,
            )
            p.scaffold_label = label
            return p

    # Metric / diagnostics path
    foundations = int(ctx.get("foundations") if ctx.get("foundations") is not None else 0)
    if state is not None:
        try:
            foundations = len(state.foundations)
        except Exception:
            pass
    stock = ctx.get("stock_remaining")
    if stock is None and state is not None:
        try:
            stock = len(state.stock)
        except Exception:
            stock = None
    sw = ctx.get("sw")
    spaces = ctx.get("spaces")
    stage_diag = diag.get("stage") or (ctx.get("diagnostics") or {}).get("stage") if isinstance(ctx.get("diagnostics"), dict) else diag.get("stage")
    exact = diag.get("exact_suits") or diag.get("exact")
    greedy_risk = diag.get("greedy_risk")

    p = _heuristic_from_metrics(
        foundations=foundations,
        stock=stock,
        sw=sw,
        spaces=spaces,
        stage_diag=stage_diag,
        exact=exact,
        greedy_risk=greedy_risk,
        status=ctx.get("status"),
        role=ctx.get("role"),
    )
    p.scaffold_label = label
    return p


def classify_ladder(
    ladder_path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    path = ladder_path or LADDER_PATH
    ladder = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for entry in ladder["ladder"]:
        profile = classify_stage(scaffold_context=entry)
        rows.append(
            {
                "label": entry["label"],
                "ladder_status": entry.get("status"),
                "ladder_role": entry.get("role"),
                "mw": entry.get("mw"),
                "foundations": entry.get("foundations"),
                "profile": profile.to_dict(),
            }
        )
    return rows


def feature_arbitration_summary() -> Dict[str, Any]:
    return {
        "first_foundation_phase": {
            "preferred": [DIAG_STOCK_ASSISTED, DIAG_FCP, DIAG_MOBILITY],
            "low_trust": [DIAG_CLEANUP, "low_sw_alone_as_objective", "exact_now_alone_implies_take"],
            "notes": (
                "Stock-assisted merge detection matters. B5 shortcut is first-foundation-only "
                "optimisation, not continuation scaffold."
            ),
        },
        "second_foundation_phase": {
            "preferred": [DIAG_ARCHITECTURE, DIAG_NFCP],
            "low_trust": ["nfcp_best_suit_alone_without_architecture", DIAG_CLEANUP],
            "notes": (
                "Architecture score is needed because nfcp can chase decoy suits. "
                "H:20 is gold; Section F divergence frozen."
            ),
        },
        "stock_empty_cleanup_phase": {
            "preferred": [DIAG_CLEANUP, DIAG_DELTA, DIAG_ARCHITECTURE],
            "low_trust": [
                "nfcp_greedy_next_foundation_alone",
                DIAG_STOCK_ASSISTED,
                "exact_now_alone_implies_take",
            ],
            "notes": (
                "cleanup_cascade_potential dominates next-foundation greed. "
                "foundation_action_delta required for exact foundation decisions."
            ),
        },
        "anti_greedy_cascade_staging_phase": {
            "preferred": [DIAG_CLEANUP, DIAG_DELTA],
            "low_trust": ["exact_now_alone_implies_take", "greedy_risk_as_hard_ban"],
            "notes": (
                "J:11: exact hearts available but not automatically preferred. "
                "greedy_risk is a warning, not a hard prune. Same physical move may "
                "classify differently by context."
            ),
        },
        "cascade_firing_phase": {
            "preferred": [DIAG_DELTA, "cascade_firing_recognition", DIAG_CLEANUP],
            "low_trust": ["treat_as_greedy_risk_staging", "nfcp_single_suit_planning"],
            "notes": (
                "Multi-exact states are firing, not greedy risk. J:17 is cascade_firing; "
                "J:17→J:22 is foundation firing cascade, not a planning phase."
            ),
        },
        "global_lessons": [
            "Low sw is useful but insufficient.",
            "Exact foundation availability is useful but insufficient.",
            "greedy_risk is a warning, not a hard prune.",
            "foundation_action_delta classifications are context-dependent.",
            "This layer is diagnostic-only and does not change production scoring.",
        ],
    }


def write_reports(rows: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    rows = rows or classify_ladder()
    report = {
        "deal": "4925153",
        "diagnostic_only": True,
        "production_scoring_changed": False,
        "search_invoked": False,
        "beam_invoked": False,
        "optimisation_invoked": False,
        "note": "stage classifier is interpretability/experiment-control only; no search run",
        "milestones": rows,
        "feature_arbitration_summary": feature_arbitration_summary(),
    }
    REPORT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines = [
        "# Deal 4925153 — Diagnostic stage classification report",
        "",
        "**Diagnostic only. No production scoring changes. No search/beam/optimisation was run.**",
        "",
        "## Milestone classifications",
        "",
        "| label | macro_stage | sub_stage | preferred diagnostics | suppressed / low-trust | risks | continuation | confidence | explanation |",
        "|---|---|---|---|---|---|---|---:|---|",
    ]
    for row in rows:
        p = row["profile"]
        lines.append(
            f"| {row['label']} | {p['macro_stage']} | {p['sub_stage']} | "
            f"{', '.join(p['preferred_diagnostics'])} | "
            f"{', '.join(p['suppressed_or_low_trust_diagnostics'])} | "
            f"{', '.join(p['major_risks']) or '-'} | "
            f"{p['continuation_policy']} | {p['confidence']:.2f} | "
            f"{p['explanation'][:120]} |"
        )

    lines += ["", "## Feature arbitration summary", ""]
    fas = report["feature_arbitration_summary"]
    for phase, body in fas.items():
        if phase == "global_lessons":
            continue
        lines.append(f"### {phase.replace('_', ' ')}")
        lines.append(f"- preferred: {', '.join(body['preferred'])}")
        lines.append(f"- low-trust: {', '.join(body['low_trust'])}")
        lines.append(f"- notes: {body['notes']}")
        lines.append("")
    lines.append("### global lessons")
    for g in fas["global_lessons"]:
        lines.append(f"- {g}")
    lines += [
        "",
        "## Explicit confirmations",
        "",
        "- no search was run",
        "- no beam search was run",
        "- no optimisation was run",
        "- no production scoring changed",
        "- no scaffold registry decisions changed",
        "",
    ]
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    return report


def main() -> int:
    print("Stage classifier — diagnostic only; no search", flush=True)
    report = write_reports()
    print(f"Classified {len(report['milestones'])} milestones", flush=True)
    for row in report["milestones"]:
        p = row["profile"]
        print(
            f"  {row['label']}: {p['macro_stage']}/{p['sub_stage']} "
            f"cont={p['continuation_policy']}",
            flush=True,
        )
    print(f"Wrote {REPORT_JSON.relative_to(ROOT)}", flush=True)
    print(f"Wrote {REPORT_MD.relative_to(ROOT)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
