#!/usr/bin/env python3
"""Diagnostic-only cleanup_cascade_potential for multi-foundation staging.

Not production scoring. Models post-deal#5 / foundations>=2 cleanup cascade
readiness, including second-copy foundations for suits that already have one
completed pile (nfcp treats those suits as done).
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from spider.deal_analysis import DealAnalysis
from spider.engine import SpiderState
from spider.heuristics import (
    _pattern_label,
    _same_suit_desc_fragments_in_column,
    detect_foundation_completing_merge,
)


def foundation_counts(state: SpiderState) -> Dict[str, int]:
    counts = {s: 0 for s in "schd"}
    for pile in state.foundations:
        if pile:
            counts[pile[0].suit] += 1
    return counts


def remaining_suits(state: SpiderState) -> List[str]:
    """Suits that still need at least one more foundation (max 2 per suit)."""
    counts = foundation_counts(state)
    return [s for s in "schd" if counts[s] < 2]


def _spaces(state: SpiderState) -> int:
    return sum(1 for c in state.columns if c.is_empty())


def _sw(state: SpiderState) -> int:
    return sum(len(c.face_up) for c in state.columns if c.face_down)


def _best_fragments(state: SpiderState, suit: str) -> List[Dict]:
    frags: List[Dict] = []
    for ci in range(10):
        for f in _same_suit_desc_fragments_in_column(state, ci, suit):
            frags.append(f)
    frags.sort(key=lambda x: (-x["length"], -int(x["movable"]), -x["high"]))
    return frags


def _cheap_exact_merge(state: SpiderState, suit: str) -> bool:
    """Faster exact-merge probe: only try same-suit suffix runs onto matching tops.

    Avoids full cross-product clone search used by detect_foundation_completing_merge.
    """
    # Collect candidate source runs (same-suit descending suffixes)
    sources: List[Tuple[int, int, int, int]] = []  # src, k, high, low
    for src in range(10):
        up = state.columns[src].face_up
        if not up:
            continue
        # longest same-suit desc suffix
        k = 1
        while k < len(up) and up[-k - 1].suit == suit and up[-k - 1].rank == up[-k].rank + 1:
            k += 1
        run = up[-k:]
        if run[0].suit != suit:
            continue
        if not state.is_desc_run(run):
            continue
        sources.append((src, k, run[0].rank, run[-1].rank))

    if not sources:
        return False

    for src, k, high, low in sources:
        need_high = high + k  # if attaching under dest, dest should be high+1... wait
        # Completing K-A means after merge the column has ranks 13..1 same suit.
        # Dest top must be high+1 of same suit, and combined span must include K and A
        # with length 13.
        for dst in range(10):
            if src == dst:
                continue
            dest = state.columns[dst]
            top = dest.top()
            if top is None:
                # empty dest: only completes if moved run itself is full K-A
                if k == 13 and high == 13 and low == 1:
                    if state.can_move(src, dst, k):
                        return True
                continue
            if top.suit != suit or top.rank != high + 1:
                continue
            if not state.can_move(src, dst, k):
                continue
            # Combined run length on dest after move
            # Walk dest face_up same-suit desc from top upward
            up = dest.face_up
            span = k + 1  # at least top + run
            # extend into dest below top
            i = len(up) - 2
            expect = top.rank + 1
            while i >= 0 and up[i].suit == suit and up[i].rank == expect:
                span += 1
                expect += 1
                i -= 1
            dest_high = expect - 1
            dest_low = low
            if span >= 13 and dest_high == 13 and dest_low == 1:
                return True
            # Engine removes only if last 13 cards are K-A same suit — verify via one clone
            # when span looks plausible
            if dest_high >= 13 and dest_low <= 1 and span >= 13:
                sim = state.clone()
                f0 = len(sim.foundations)
                try:
                    sim.move(src, dst, k)
                except Exception:
                    continue
                if len(sim.foundations) > f0:
                    return True
    return False


def _suit_readiness(state: SpiderState, suit: str, *, precise: bool = False) -> Dict:
    """Per-suit cascade readiness (diagnostic)."""
    frags = _best_fragments(state, suit)
    best = frags[0] if frags else None
    merge = None
    if precise:
        merge = detect_foundation_completing_merge(state, suit)
        exact_now = bool(merge.get("found") and merge.get("legal"))
    else:
        exact_now = _cheap_exact_merge(state, suit)

    long_movable = False
    long_spine = False
    near_ka = False
    low_tail = False
    spine_len = 0
    tail_len = 0
    pattern = None
    movable = False

    if best:
        pattern = best["pattern"]
        spine_len = best["length"]
        movable = bool(best["movable"])
        high, low = best["high"], best["low"]
        if best["length"] >= 8 and movable:
            long_movable = True
        if best["length"] >= 8 and high >= 11:
            long_spine = True
        # Near K→A: length>=10 ending near A, or K→2 / K→3 / K→4
        if high == 13 and low <= 4 and best["length"] >= 9:
            near_ka = True
        if high == 13 and low == 1 and best["length"] >= 12:
            near_ka = True
        if low <= 3 and best["length"] >= 2:
            # 2→A, 3→A, 4→A, 7→A, 8→A style tails
            if low == 1 and high <= 8:
                low_tail = True
            elif low <= 2 and high <= 4:
                low_tail = True

    # Secondary tail scan
    for f in frags[1:4]:
        if f["low"] == 1 and f["high"] <= 8 and f["length"] >= 2:
            low_tail = True
            tail_len = max(tail_len, f["length"])
        if f["high"] == 13 and f["length"] >= 8:
            long_spine = True
            spine_len = max(spine_len, f["length"])

    readiness = 0
    tags: List[str] = []
    if exact_now:
        readiness += 100
        tags.append("exact_now")
    if near_ka:
        readiness += 55
        tags.append("near_KA")
    if long_movable:
        readiness += 40
        tags.append("long_movable")
    elif long_spine:
        readiness += 28
        tags.append("long_spine")
    if low_tail:
        readiness += 18
        tags.append("low_tail")
    if movable and spine_len >= 6:
        readiness += 10
        tags.append("movable_mid")
    if spine_len >= 11:
        readiness += 15
        tags.append("very_long")

    near_complete = (
        exact_now
        or near_ka
        or (long_movable and spine_len >= 8)
        or (long_spine and spine_len >= 10)
        or (low_tail and spine_len >= 7)
        or readiness >= 45
    )

    return {
        "suit": suit,
        "exact_now": exact_now,
        "near_complete": near_complete,
        "readiness": readiness,
        "spine_length": spine_len,
        "tail_length": tail_len,
        "pattern": pattern,
        "movable": movable,
        "merge": merge if (exact_now and merge) else None,
        "tags": tags,
    }


def _exact_after_one_move_suits(state: SpiderState, remaining: List[str]) -> Set[str]:
    """Suits that become foundation-completing after some single legal move.

    Expensive; only used when stock==0 and foundations>=2 for calibration quality.
    Caps move enumeration to keep diagnostic latency acceptable.
    """
    already = {
        s
        for s in remaining
        if detect_foundation_completing_merge(state, s).get("found")
    }
    found: Set[str] = set()
    moves = state.enumerate_moves()
    # Prefer longer moves and empty-dest moves first
    def _prio(m: Tuple[int, int, int]) -> Tuple[int, int]:
        src, dst, k = m
        empty = 1 if state.columns[dst].is_empty() else 0
        return (-empty, -k)

    moves = sorted(moves, key=_prio)[:40]
    for src, dst, k in moves:
        sim = state.clone()
        f0 = len(sim.foundations)
        try:
            sim.move(src, dst, k)
        except Exception:
            continue
        if len(sim.foundations) > f0:
            # Identify which suit(s) completed
            for pile in sim.foundations[f0:]:
                if pile:
                    s = pile[0].suit
                    if s in remaining and s not in already:
                        found.add(s)
            if len(found) + len(already) >= len(remaining):
                break
            continue
        # No auto-complete: check if a new exact merge opened (cheap only for remaining)
        for s in remaining:
            if s in already or s in found:
                continue
            m = detect_foundation_completing_merge(sim, s)
            if m.get("found"):
                found.add(s)
        if len(found) >= 3:
            break
    return found


def _cascade_horizon_estimate(
    state: SpiderState,
    suit_info: Dict[str, Dict],
    exact_now: List[str],
    near: List[str],
    spaces: int,
) -> Dict:
    """Rough 1/2/5-move cascade availability estimate (heuristic, not search)."""
    n_exact = len(exact_now)
    n_near = len(near)
    # Within 1 move: exact merges + possibly one chain if spaces help
    within_1 = n_exact
    # Within 2: exact + suits that are near_KA / long movable with spaces
    near_hot = [
        s
        for s in near
        if s not in exact_now
        and (
            "near_KA" in suit_info[s]["tags"]
            or "long_movable" in suit_info[s]["tags"]
            or suit_info[s]["readiness"] >= 70
        )
    ]
    within_2 = min(len(remaining_suits(state)), n_exact + len(near_hot) + (1 if spaces >= 2 else 0))
    # Within 5: all near_complete plus exact, scaled by spaces
    space_boost = 1 if spaces >= 2 else 0
    space_boost += 1 if spaces >= 3 else 0
    within_5 = min(
        len(remaining_suits(state)),
        n_exact + n_near + space_boost,
    )
    # Completing a foundation frees a column if the whole column was the run
    expected_space_gain = n_exact  # each completion typically frees source/dest structure
    if spaces >= 1 and n_exact >= 1:
        expected_space_gain += min(2, n_near)  # chain unlocks
    unlock_chain = n_exact >= 1 and (n_near >= 2 or (n_exact >= 2))
    return {
        "within_1": within_1,
        "within_2": within_2,
        "within_5": within_5,
        "expected_space_gain": expected_space_gain,
        "unlock_chain": unlock_chain,
    }


def cleanup_cascade_potential(
    state: SpiderState,
    analysis: Optional[DealAnalysis] = None,
    *,
    deep_one_move: bool = False,
    precise_merge: bool = False,
) -> Dict:
    """Score multi-suit cleanup cascade readiness (diagnostic only).

    Activates primarily when foundations>=2, stock empty (or final wave), and
    multi-suit near-complete structure exists.

    ``precise_merge`` / ``deep_one_move`` enable slower engine-validated probes
    (use for calibration / top candidates only, not beam expansion).
    """
    n_found = len(state.foundations)
    stock = len(state.stock)
    spaces = _spaces(state)
    sw = _sw(state)
    remaining = remaining_suits(state)
    counts = foundation_counts(state)

    # --- A. Stage/context ---
    stage_score = 0
    stage_tags: List[str] = []
    if stock == 0:
        stage_score += 80
        stage_tags.append("stock_empty")
    elif stock <= 10:
        stage_score += 25
        stage_tags.append("final_stock_wave")
    if n_found >= 2:
        stage_score += 40
        stage_tags.append("f>=2")
    if n_found >= 3:
        stage_score += 50
        stage_tags.append("f>=3")
    if n_found >= 4:
        stage_score += 25
        stage_tags.append("f>=4")
    if spaces >= 1:
        stage_score += 25
        stage_tags.append("spaces>=1")
    if spaces >= 2:
        stage_score += 35
        stage_tags.append("spaces>=2")
    if spaces >= 3:
        stage_score += 40
        stage_tags.append("spaces>=3")
    if spaces >= 5:
        stage_score += 20
        stage_tags.append("spaces>=5")
    if sw == 0:
        stage_score += 45
        stage_tags.append("sw0")
    elif sw <= 2:
        stage_score += 20
        stage_tags.append("sw_low")
    elif sw <= 4:
        stage_score += 8
    if stock == 0 and n_found >= 2:
        stage_score += 30
        stage_tags.append("post_final_deal_cleanup")

    # Activation gate
    active = False
    stage = "inactive"
    if n_found >= 2 and stock == 0:
        active = True
        stage = "cleanup_active"
    elif n_found >= 3 and stock == 0:
        active = True
        stage = "cascade_active"
    elif n_found >= 2 and stock <= 10:
        active = spaces >= 1 or sw <= 3
        stage = "pre_final_wave" if active else "pre_final_wave_weak"
    elif n_found >= 2:
        stage = "post_second_foundation"
        active = False

    if n_found >= 3 and stock == 0 and spaces >= 2:
        stage = "cascade_staging" if n_found < 6 else "cascade_firing"
        active = True
    if n_found >= 6 and stock == 0:
        stage = "cascade_firing"
        active = True
    if n_found >= 8:
        stage = "solved"
        active = False

    # --- B. Multi-suit readiness ---
    suit_info: Dict[str, Dict] = {}
    for s in remaining:
        suit_info[s] = _suit_readiness(state, s, precise=precise_merge)

    exact_now_suits = [s for s, info in suit_info.items() if info["exact_now"]]
    near_complete_suits = [s for s, info in suit_info.items() if info["near_complete"]]

    readiness_score = 0
    readiness_score += sum(info["readiness"] for info in suit_info.values())
    # Multi-suit bonus: reward having several near-complete suits simultaneously
    n_near = len(near_complete_suits)
    n_exact = len(exact_now_suits)
    if n_near >= 2:
        readiness_score += 40
    if n_near >= 3:
        readiness_score += 55
    if n_near >= 4:
        readiness_score += 40
    if n_exact >= 2:
        readiness_score += 80
    if n_exact >= 3:
        readiness_score += 60

    # Second-copy awareness: suits with count==1 still in remaining
    second_copy = [s for s in remaining if counts[s] == 1]
    if second_copy:
        readiness_score += 15 * len(second_copy)
        stage_tags.append(f"second_copy:{','.join(second_copy)}")

    # Optional exact-after-one-move (only when cleanup-relevant; slow)
    exact_after_one: List[str] = []
    if deep_one_move and n_found >= 2 and stock == 0 and remaining:
        try:
            after_set = _exact_after_one_move_suits(state, remaining)
            exact_after_one = sorted(after_set)
            readiness_score += 35 * len(exact_after_one)
        except Exception:
            exact_after_one = []

    # --- C. Cascade gain ---
    horizon = _cascade_horizon_estimate(
        state, suit_info, exact_now_suits, near_complete_suits, spaces
    )
    cascade_score = (
        horizon["within_1"] * 50
        + horizon["within_2"] * 30
        + horizon["within_5"] * 15
        + horizon["expected_space_gain"] * 20
        + (40 if horizon["unlock_chain"] else 0)
    )

    # --- D. Non-greedy staging warning ---
    greedy_risk = False
    best_delayed_suit: Optional[str] = None
    greedy_note = ""
    non_exact_near = [s for s in near_complete_suits if s not in exact_now_suits]
    # Also count high-readiness non-exact suits as staging partners
    staging_partners = [
        s
        for s, info in suit_info.items()
        if s not in exact_now_suits and (info["near_complete"] or info["readiness"] >= 40)
    ]
    if (
        n_exact >= 1
        and len(staging_partners) >= 2
        and stock == 0
        and n_found >= 2
    ):
        greedy_risk = True
        # Prefer delaying the exact suit with shortest "must take now" pressure
        # and flag the best staging suit (highest readiness among non-exact)
        staging_partners_sorted = sorted(
            staging_partners, key=lambda s: suit_info[s]["readiness"], reverse=True
        )
        best_delayed_suit = staging_partners_sorted[0]
        greedy_note = (
            f"exact_now={exact_now_suits} but staging_partners={staging_partners_sorted[:3]}; "
            f"delay greedy foundation, stage {best_delayed_suit}"
        )
        # Staging bonus: multi-suit assembly in progress is GOOD for cascade
        readiness_score += 50
        stage_tags.append("non_greedy_staging")
    elif n_exact == 1 and len(staging_partners) == 1 and stock == 0 and n_found >= 3:
        # Mild risk: one other suit nearly ready
        greedy_risk = True
        best_delayed_suit = staging_partners[0]
        greedy_note = (
            f"exact_now={exact_now_suits} with partner {best_delayed_suit}; "
            "consider staging before taking exact"
        )
        readiness_score += 25
        stage_tags.append("mild_staging")

    # When many exact available, cascade is firing — not "risk", it's execution
    if n_exact >= 2 and n_found >= 3:
        greedy_risk = False  # firing phase; taking foundations is correct
        greedy_note = "multi_exact_cascade_firing"
        stage = "cascade_firing"
        stage_tags.append("multi_exact_fire")

    # --- Total score ---
    score = stage_score + readiness_score + cascade_score

    # Inactive / weak dampening
    if not active and stock > 10:
        score = int(score * 0.35)
    elif not active and stock > 0:
        score = int(score * 0.55)
    elif stage == "pre_final_wave_weak":
        score = int(score * 0.7)

    # Strong activation boost for post-3rd multi-space
    if n_found >= 3 and stock == 0 and spaces >= 3:
        score += 60
        stage_tags.append("post_third_multi_space")

    reasons: List[str] = []
    reasons.extend(stage_tags)
    if exact_now_suits:
        reasons.append(f"exact={','.join(exact_now_suits)}")
    if near_complete_suits:
        reasons.append(f"near={','.join(near_complete_suits)}")
    if exact_after_one:
        reasons.append(f"exact+1={','.join(exact_after_one)}")
    if greedy_risk:
        reasons.append("greedy_risk")
    if greedy_note:
        reasons.append(greedy_note)
    reasons.append(
        f"w1={horizon['within_1']}/w2={horizon['within_2']}/w5={horizon['within_5']}"
    )

    return {
        "score": int(score),
        "active": active,
        "stage": stage,
        "foundations": n_found,
        "foundation_counts": counts,
        "stock_remaining": stock,
        "spaces": spaces,
        "sw": sw,
        "remaining_suits": remaining,
        "exact_now_suits": exact_now_suits,
        "exact_after_one_move_suits": exact_after_one,
        "near_complete_suits": near_complete_suits,
        "cascade_count_estimate": {
            "within_1": horizon["within_1"],
            "within_2": horizon["within_2"],
            "within_5": horizon["within_5"],
        },
        "expected_space_gain": horizon["expected_space_gain"],
        "greedy_risk": greedy_risk,
        "best_delayed_suit": best_delayed_suit,
        "suit_info": {
            s: {
                "readiness": info["readiness"],
                "exact_now": info["exact_now"],
                "near_complete": info["near_complete"],
                "pattern": info["pattern"],
                "spine_length": info["spine_length"],
                "tags": info["tags"],
            }
            for s, info in suit_info.items()
        },
        "stage_score": stage_score,
        "readiness_score": readiness_score,
        "cascade_score": cascade_score,
        "reason": "; ".join(reasons),
    }


def cleanup_score(state: SpiderState, analysis: Optional[DealAnalysis] = None, **kw) -> int:
    return int(cleanup_cascade_potential(state, analysis, **kw)["score"])
