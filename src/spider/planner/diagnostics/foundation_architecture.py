"""Diagnostic foundation architecture scoring (not production scoring)."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from spider.deal_analysis import DealAnalysis
from spider.engine import SpiderState
from spider.heuristics import (
    _card_label,
    _completed_foundation_suits,
    _pattern_label,
    _rank_status_in_tableau,
    _ranks_in_stock_wave,
    _same_suit_desc_fragments_in_column,
    detect_foundation_completing_merge,
)

# Preferred spine high→low rank pairs (high rank, low rank)
SPINE_TARGETS = ((13, 3), (13, 4), (12, 3), (11, 3))


def _status_kind(status: str) -> str:
    if status.startswith("visible"):
        return "visible"
    if status.startswith("blocked"):
        return "blocked"
    if status.startswith("buried"):
        return "buried"
    return "absent"


def _find_spine_fragments(state: SpiderState, suit: str) -> List[Dict]:
    frags: List[Dict] = []
    for ci in range(10):
        for f in _same_suit_desc_fragments_in_column(state, ci, suit):
            frags.append(f)
    return sorted(frags, key=lambda x: (-x["length"], -x["high"]))


def _spine_match_score(high: int, low: int, length: int) -> Tuple[int, bool]:
    for th, tl in SPINE_TARGETS:
        if high >= th and low <= tl:
            span = high - low + 1
            if span >= 4:
                bonus = 30 if (th, tl) == (13, 3) else 25 if (th, tl) == (13, 4) else 20
                return length * 12 + bonus, True
    if length >= 6 and high >= 10:
        return length * 8, False
    return length * 4, False


def _find_tail_fragment(state: SpiderState, suit: str) -> Optional[Dict]:
    """Best low-tail candidate: prefer 2->A suffix runs."""
    best: Optional[Dict] = None
    best_sc = -1
    for ci in range(10):
        up = state.columns[ci].face_up
        if not up:
            continue
        for f in _same_suit_desc_fragments_in_column(state, ci, suit):
            if f["low"] > 3:
                continue
            sc = f["length"] * 15
            if f["low"] == 1 and f["high"] >= 2:
                sc += 40  # contains A
            if f["high"] == 2 or f["low"] == 2:
                sc += 25
            if f["low"] == 1 and f["high"] == 2:
                sc += 50  # 2->A run
            if sc > best_sc:
                best_sc = sc
                best = {**f, "tail_score": sc}
    return best


def _merge_gap(spine_low: int, tail_high: int) -> int:
    """Ranks needed to connect tail top to spine low (0 = adjacent)."""
    if tail_high == spine_low - 1:
        return 0
    if tail_high < spine_low - 1:
        return spine_low - 1 - tail_high
    return -1  # overlapping or invalid


def _low_tail_status(state: SpiderState, suit: str) -> str:
    s2 = _rank_status_in_tableau(state, suit, 2)
    sa = _rank_status_in_tableau(state, suit, 1)
    k2, ka = _status_kind(s2), _status_kind(sa)
    if k2 == "visible" and ka == "visible":
        return "2_and_A_visible"
    if ka == "visible" and k2 == "blocked":
        return "A_visible_2_blocked"
    if k2 == "visible" and ka == "blocked":
        return "2_visible_A_blocked"
    if k2 == "visible":
        return "2_visible"
    if ka == "visible":
        return "A_visible"
    return "tail_absent_or_buried"


def foundation_architecture_score(
    state: SpiderState,
    suit: str,
    *,
    analysis: Optional[DealAnalysis] = None,
    round_index: Optional[int] = None,
    lookahead: int = 2,
) -> Dict:
    """Score latent foundation architecture for one suit (diagnostic only)."""
    empty = {
        "score": 0,
        "suit": suit,
        "spine_fragment": None,
        "spine_col": None,
        "spine_high": None,
        "spine_low": None,
        "spine_length": 0,
        "tail_fragment": None,
        "tail_col": None,
        "tail_high": None,
        "tail_low": None,
        "tail_length": 0,
        "K_status": _rank_status_in_tableau(state, suit, 13),
        "A_status": _rank_status_in_tableau(state, suit, 1),
        "low_tail_status": _low_tail_status(state, suit),
        "merge_gap": None,
        "blockers": [],
        "reason": "suit_complete_or_no_structure",
    }
    if suit in _completed_foundation_suits(state):
        empty["reason"] = "suit_already_foundation"
        return empty

    merge = detect_foundation_completing_merge(state, suit)
    if merge.get("found"):
        return {
            **empty,
            "score": 1000,
            "spine_fragment": merge.get("source_run_high", "") + "->" + merge.get("source_run_low", ""),
            "tail_fragment": merge.get("source_run_high", "") + "->" + merge.get("source_run_low", ""),
            "merge_gap": 0,
            "reason": "exact_merge_available",
        }

    spines = _find_spine_fragments(state, suit)
    tail = _find_tail_fragment(state, suit)
    if not spines and not tail:
        empty["reason"] = "no_spine_or_tail"
        return empty

    spine = spines[0] if spines else None
    score = 0
    reasons: List[str] = []
    blockers: List[str] = []

    if spine:
        spine_sc, matched = _spine_match_score(spine["high"], spine["low"], spine["length"])
        score += spine_sc
        if matched:
            reasons.append(f"spine_{spine['pattern']}")
        else:
            reasons.append(f"long_frag_{spine['pattern']}")
        if spine["movable"]:
            score += 20
            reasons.append("spine_movable")
        k_st = _rank_status_in_tableau(state, suit, 13)
        if k_st.startswith("blocked") and spine["length"] >= 8:
            score += 25
            reasons.append("K_blocked_spine_intact")
            blockers.append(k_st)
        elif k_st.startswith("blocked"):
            blockers.append(k_st)

    tail_sc = 0
    merge_gap = None
    if tail:
        tail_sc = tail.get("tail_score", tail["length"] * 10)
        score += min(tail_sc, 80)
        reasons.append(f"tail_{tail['pattern']}")
        if tail["movable"]:
            score += 15
            reasons.append("tail_movable")
        if spine:
            merge_gap = _merge_gap(spine["low"], tail["high"])
            if merge_gap == 0:
                score += 60
                reasons.append("tail_adjacent_to_spine")
            elif merge_gap == 1:
                score += 30
                reasons.append("tail_one_gap_from_spine")
            elif merge_gap > 1:
                blockers.append(f"gap_{merge_gap}_ranks")

    lt = _low_tail_status(state, suit)
    if lt == "2_and_A_visible":
        score += 45
        reasons.append("2_A_both_visible")
    elif lt == "A_visible_2_blocked":
        score += 35
        reasons.append("A_visible")
    elif lt == "2_visible_A_blocked":
        score += 20
    elif lt == "A_visible":
        score += 30
        reasons.append("A_visible")

    if analysis is not None and round_index is not None:
        needed = []
        if spine and spine["high"] < 13:
            needed.append(13)
        if spine and spine["low"] > 1:
            needed.append(1)
        if merge_gap and merge_gap > 0:
            pass
        for wave in range(lookahead):
            ri = round_index + wave
            if ri >= len(analysis.incoming_by_round):
                break
            wave_ranks = _ranks_in_stock_wave(analysis, ri, suit)
            for r in needed:
                if r in wave_ranks:
                    score += 15
                    reasons.append(f"rank_{r}_in_stock_wave_{wave}")

    return {
        "score": score,
        "suit": suit,
        "spine_fragment": spine["pattern"] if spine else None,
        "spine_col": spine["col"] if spine else None,
        "spine_high": spine["high_card"] if spine else None,
        "spine_low": spine["low_card"] if spine else None,
        "spine_length": spine["length"] if spine else 0,
        "tail_fragment": tail["pattern"] if tail else None,
        "tail_col": tail["col"] if tail else None,
        "tail_high": tail["high_card"] if tail else None,
        "tail_low": tail["low_card"] if tail else None,
        "tail_length": tail["length"] if tail else 0,
        "K_status": _rank_status_in_tableau(state, suit, 13),
        "A_status": _rank_status_in_tableau(state, suit, 1),
        "low_tail_status": lt,
        "merge_gap": merge_gap,
        "blockers": blockers,
        "reason": "; ".join(reasons) if reasons else "minimal_structure",
    }


def all_suit_architecture_scores(
    state: SpiderState,
    *,
    analysis: Optional[DealAnalysis] = None,
    round_index: Optional[int] = None,
) -> Dict[str, Dict]:
    done = _completed_foundation_suits(state)
    return {
        s: foundation_architecture_score(
            state, s, analysis=analysis, round_index=round_index
        )
        for s in "schd"
        if s not in done
    }