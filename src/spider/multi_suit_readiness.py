"""v0.70 multi-suit operational readiness at the final pre-Deal epoch.

Sparse readiness_r2 / readiness_r3 lanes follow operational rank, not suit
identity. Active only when stock_rows == 1. No canonical reads. No DURABILITY.
"""

from __future__ import annotations

from collections import Counter
from typing import Optional, Sequence, Tuple

from spider.deal_preview import compact_preview, preview_next_deal
from spider.engine import SpiderState
from spider.final_deal_transition import TransitionTracker
from spider.metrics import Action
from spider.operational_viability import compact_operational, rank_ready_suits
from spider.research_actions import (
    apply_action,
    foundation_suits,
    is_deal,
    step_cost,
    stock_rows,
    tableau_actions,
)
from spider.structural_analysis import current_tableau_summary


def _rank_snapshot(ranked: dict, g: int) -> dict:
    rows = []
    for i, v in enumerate(ranked.get("ranked") or []):
        rows.append(
            {
                "rank": i + 1,
                "suit": v.get("suit"),
                "cover": v.get("cover"),
                "relevant_blockers": v.get("relevant_blockers"),
                "k_min_blockers": v.get("k_min_blockers"),
                "a_min_blockers": v.get("a_min_blockers"),
                "gap": v.get("gap"),
                "legal_merge_edges": v.get("legal_merge_edges"),
                "key": list(v.get("key") or []),
                "compact": compact_operational(v),
            }
        )
    return {
        "g": g,
        "n_ready": ranked.get("n_ready"),
        "ready_suits": list(ranked.get("ready_suits") or []),
        "best_suit": ranked.get("best_suit"),
        "second_suit": ranked.get("second_suit"),
        "ranked": rows,
    }


def classify_target_rank(audit: dict) -> str:
    ranks = [r.get("eventual_suit_rank") for r in audit.get("states") or [] if r.get("eventual_suit_rank")]
    if not ranks:
        return "TARGET_RANK_UNKNOWN"
    primary = sum(1 for r in ranks if r == 1)
    alternate = sum(1 for r in ranks if r >= 2)
    uniq = sorted(set(ranks))
    if len(uniq) >= 2 and primary and alternate:
        return "TARGET_RANK_SWITCHED"
    if alternate > primary:
        return "TARGET_SUIT_WAS_ALTERNATE"
    return "TARGET_SUIT_WAS_PRIMARY"


def audit_rows1_ready_ranks(opening: SpiderState, actions: Sequence[Action]) -> dict:
    """Evaluation-only replay of one solution's rows=1 tableau segment."""

    state = opening.clone()
    g = 0
    states = []
    cashed = None
    cashed_g = None
    entry = None
    for action in actions:
        rows = stock_rows(state)
        if rows == 1:
            s = current_tableau_summary(state)
            ranked = rank_ready_suits(state, summary=s, g=g)
            snap = _rank_snapshot(ranked, g)
            snap.update(
                {
                    "F": s["foundations"],
                    "fd": s["face_down"],
                    "legal": len(tableau_actions(state)),
                    "empty": s["empty_n"],
                    "foundation_suits": list(s["foundation_suits"]),
                    "is_deal": is_deal(action),
                }
            )
            if entry is None:
                entry = {
                    "g": g,
                    "F": s["foundations"],
                    "fd": s["face_down"],
                    "legal": snap["legal"],
                    "empty": s["empty_n"],
                    "best_suit": snap["best_suit"],
                    "n_ready": snap["n_ready"],
                    "ready_suits": snap["ready_suits"],
                }
            f_before = s["foundations"]
            before_c = Counter(foundation_suits(state))
            cost = 1 if is_deal(action) else step_cost(state, action)
            apply_action(state, action)
            g += cost
            after_c = Counter(foundation_suits(state))
            added = None
            for suit, n in after_c.items():
                if n > before_c.get(suit, 0):
                    added = suit
                    break
            if added is not None:
                cashed = added
                cashed_g = g
                snap["cashed_suit"] = added
                snap["cashed_rank"] = next(
                    (row["rank"] for row in snap["ranked"] if row["suit"] == added),
                    None,
                )
            snap["F_after"] = len(state.foundations)
            states.append(snap)
            if is_deal(action):
                break
            continue
        cost = 1 if is_deal(action) else step_cost(state, action)
        apply_action(state, action)
        g += cost
    for rec in states:
        rec["eventual_suit"] = cashed
        rec["eventual_suit_rank"] = next(
            (row["rank"] for row in rec.get("ranked") or [] if row.get("suit") == cashed),
            None,
        )
    ranks = [r.get("eventual_suit_rank") for r in states if r.get("eventual_suit_rank")]
    n = len(ranks) or 1
    return {
        "entry": entry,
        "n_states": len(states),
        "cashed_suit": cashed,
        "cashed_g": cashed_g,
        "primary_frac": 0.0 if not ranks else sum(1 for r in ranks if r == 1) / float(n),
        "alternate_frac": 0.0 if not ranks else sum(1 for r in ranks if r >= 2) / float(n),
        "rank_set": sorted({r for r in ranks if r is not None}),
        "classification": classify_target_rank({"states": states}),
        "states": states,
    }


class MultiSuitTracker:
    """Telemetry wrapper around TransitionTracker. Does not change harvest keys."""

    def __init__(self, inner: Optional[TransitionTracker] = None) -> None:
        self.inner = inner or TransitionTracker()
        self.n_rows1 = 0
        self.n_ready_ge2 = 0
        self.n_ready_ge3 = 0
        self.n_rank_swaps = 0
        self._prev_best = None
        self.f2_rows1: list = []
        self.displaced = 0

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def __call__(self, tops, rec, min_root_g, class_best) -> None:
        self.inner(tops, rec, min_root_g, class_best)
        self.displaced = int(getattr(self.inner, "displaced", 0) or 0)
        if int(rec.get("stock_rows") or 0) != 1:
            return
        self.n_rows1 += 1
        ranked = list(rec.get("ready_ranked_suits") or rec.get("ready_suits") or [])
        n = len(ranked)
        if n >= 2:
            self.n_ready_ge2 += 1
        if n >= 3:
            self.n_ready_ge3 += 1
        best = ranked[0] if ranked else rec.get("best_ready_suit")
        if self._prev_best is not None and best is not None and best != self._prev_best:
            self.n_rank_swaps += 1
        if best is not None:
            self._prev_best = best
        if int(rec.get("foundations") or 0) >= 2:
            p = rec.get("preview") or {}
            self.f2_rows1.append(
                {
                    "g": rec.get("g"),
                    "F": rec.get("foundations"),
                    "fd": rec.get("face_down"),
                    "suits": rec.get("foundation_suits"),
                    "legal": rec.get("legal_tableau"),
                    "empty": rec.get("empty_n"),
                    "boundaries": rec.get("boundaries_total") or p.get("boundaries"),
                    "components": p.get("visible_components"),
                    "ready_ranked_suits": ranked,
                    "from_incumbent_ckpt": bool(rec.get("from_incumbent_ckpt")),
                    "preview": compact_preview(p) if p else None,
                }
            )

    def finalize(self, tops, roots, min_root_g, rows=None) -> None:
        return self.inner.finalize(tops, roots, min_root_g, rows)

    def on_harvest(self, rows, picked, cat_counts, attached) -> None:
        return self.inner.on_harvest(rows, picked, cat_counts, attached)

    def stats(self) -> dict:
        base = self.inner.stats() if hasattr(self.inner, "stats") else {}
        base.update(
            {
                "n_rows1": self.n_rows1,
                "n_ready_ge2": self.n_ready_ge2,
                "n_ready_ge3": self.n_ready_ge3,
                "n_rank_swaps": self.n_rank_swaps,
                "n_f2_rows1": len(self.f2_rows1),
            }
        )
        return base


def choose_multi_suit_verdict(p: dict) -> Tuple[str, str]:
    if p.get("incumbent_fail") or p.get("accounting_fail"):
        return "MULTI_SUIT_READINESS_CONTRACT_FAILURE", "replay, identity or accounting failed"
    inc = int(p.get("incumbent_g") or 192)
    best = p.get("solution_g")
    if p.get("solved") and p.get("replay_ok") and best is not None and int(best) < inc:
        return "MULTI_SUIT_READINESS_COST_IMPROVED", f"solved at g={best}"
    f2 = p.get("best_presd5_f2") or {}
    healthy = (
        f2.get("g") is not None
        and int(f2.get("stock_rows") or f2.get("rows") or -1) == 1
        and int(f2.get("F") or f2.get("foundations") or 0) >= 2
    )
    if healthy:
        return "MULTI_SUIT_READINESS_REDISCOVERS_F2", "autonomous pre-SD5 F2 recovered"
    r2 = int(((p.get("lanes") or {}).get("expansions") or {}).get("readiness_r2") or 0)
    r3 = int(((p.get("lanes") or {}).get("expansions") or {}).get("readiness_r3") or 0)
    cls = (p.get("audit") or {}).get("classification")
    if cls == "TARGET_SUIT_WAS_PRIMARY" and r2 + r3 > 0 and not healthy:
        improved = bool(p.get("transition_improved"))
        if not improved:
            return (
                "MULTI_SUIT_READINESS_HYPOTHESIS_FALSE",
                "192 cashed a primary-rank suit and alternate lanes did not recover F2",
            )
    if r2 + r3 > 0 and p.get("transition_improved"):
        return (
            "MULTI_SUIT_READINESS_IMPROVES_TRANSITION",
            "alternate lanes live and pre-SD5 structure/reception improved without F2",
        )
    if r2 + r3 > 0:
        return "MULTI_SUIT_READINESS_NO_GAIN", "alternate lanes live but no meaningful improvement"
    return "MULTI_SUIT_READINESS_NO_GAIN", "no meaningful improvement"
