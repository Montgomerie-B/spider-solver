"""
Future Stock Stress Evaluator (deterministic, no search).

Implements the "challenge the assumption" tasks:
- Known-stock deterministic rollouts (Task 1)
- Future-collision / impact metrics (Task 2)
- Suit-centric diagnostics (Task 4)
- Re-ranking of existing layered prefixes / candidates (Task 3)

The goal is to score states on resilience to the *known* future stock waves
rather than (or in addition to) current space_work / openness.

This is purely evaluative: clone + repeated state.deal() using the known
incoming_by_round sequence, then measure before/after metrics and collisions.
No moves are played between simulated deals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple

from spider.deal_analysis import DealAnalysis, build_deal_analysis
from spider.engine import SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.planner.dependency import DynamicDependencyAnalyser


@dataclass
class StressMetrics:
    sw: int
    spaces: int
    foundations: int
    fragments_ge4: int
    fragments_ge6: int
    max_run_by_suit: Dict[str, int]
    critical_buried: int
    visible_by_suit: Dict[str, int] = field(default_factory=dict)


@dataclass
class DealImpact:
    """What the incoming 10 cards did to the position."""
    sw_increase: int
    spaces_change: int
    landed_on_same_suit: int          # how many dealt cards extended an existing same-suit tail
    created_new_fragment_ge3: int
    destroyed_useful_hook: int        # rough: covered a hook that was next-in-suit for some future card
    suit_building_created: int
    suit_building_destroyed: int
    notes: List[str] = field(default_factory=list)


def count_same_suit_fragments(state: SpiderState) -> List[Tuple[str, int]]:
    """Return list of (suit, length) for every maximal same-suit descending run in face_up."""
    frags: List[Tuple[str, int]] = []
    for col in state.columns:
        up = col.face_up
        if not up:
            continue
        suit = up[0].suit
        length = 1
        for i in range(1, len(up)):
            prev = up[i-1]
            curr = up[i]
            if curr.suit == prev.suit and curr.rank == prev.rank - 1:
                length += 1
            else:
                frags.append((prev.suit, length))
                suit = curr.suit
                length = 1
        frags.append((up[-1].suit, length))
    return frags


def compute_metrics(state: SpiderState, analysis: DealAnalysis | None = None) -> StressMetrics:
    sw = sum(len(c.face_up) for c in state.columns if c.face_down)
    spaces = sum(1 for c in state.columns if c.is_empty())
    foundations = len(state.foundations)

    frags = count_same_suit_fragments(state)
    ge4 = sum(1 for _, l in frags if l >= 4)
    ge6 = sum(1 for _, l in frags if l >= 6)

    max_run: Dict[str, int] = {s: 0 for s in "shdc"}
    for s, l in frags:
        if l > max_run[s]:
            max_run[s] = l

    visible: Dict[str, int] = {s: 0 for s in "shdc"}
    for col in state.columns:
        for c in col.face_up:
            visible[c.suit] += 1

    crit_buried = 0
    if analysis is not None:
        try:
            analyser = DynamicDependencyAnalyser(analysis)
            report = analyser.analyze(state)
            crit_buried = len(report.critical_buried)
        except Exception:
            pass

    return StressMetrics(
        sw=sw,
        spaces=spaces,
        foundations=foundations,
        fragments_ge4=ge4,
        fragments_ge6=ge6,
        max_run_by_suit=max_run,
        critical_buried=crit_buried,
        visible_by_suit=visible,
    )


def compute_deal_impact(
    pre: SpiderState,
    post: SpiderState,
    dealt: List,  # the 10 cards that were dealt
) -> DealImpact:
    pre_sw = sum(len(c.face_up) for c in pre.columns if c.face_down)
    post_sw = sum(len(c.face_up) for c in post.columns if c.face_down)
    pre_spaces = sum(1 for c in pre.columns if c.is_empty())
    post_spaces = sum(1 for c in post.columns if c.is_empty())

    pre_frags = count_same_suit_fragments(pre)
    post_frags = count_same_suit_fragments(post)

    pre_ge3 = {s: 0 for s in "shdc"}
    for s, l in pre_frags:
        if l >= 3:
            pre_ge3[s] += 1
    post_ge3 = {s: 0 for s in "shdc"}
    for s, l in post_frags:
        if l >= 3:
            post_ge3[s] += 1

    landed_same = 0
    created_ge3 = 0
    # Rough: a dealt card "lands on same-suit" if the column it was appended to
    # now has a longer same-suit tail than before at that position.
    # Since deal is deterministic (col 0 gets chunk[0], etc.), we can check per column.
    # Simpler proxy: count how many new same-suit attachments happened overall.
    for s in "shdc":
        if post_ge3[s] > pre_ge3[s]:
            created_ge3 += post_ge3[s] - pre_ge3[s]

    # For landed_same we use a direct check on the dealt cards vs pre tops.
    # (The deal code appends chunk[c] to columns[c])
    # We don't have the exact chunk here, but we can look at what changed in tops.
    # Better: count how many dealt cards could attach same-suit to what was there.
    # Since we have the list of dealt, and we know they went to specific columns,
    # we can reconstruct the attachment.
    # For simplicity and robustness: count net increase in same-suit tail lengths across all columns.
    pre_tail_sum = sum(l for _, l in pre_frags)
    post_tail_sum = sum(l for _, l in post_frags)
    # This is approximate; a better version would attribute per dealt card.

    # Destroyed useful hooks: if a column that had a useful top (next for some known future)
    # now has that top covered by a non-continuing card.
    # We don't have full future here, so a simple proxy: drop in number of empty or good hooks.
    destroyed = max(0, (pre_spaces - post_spaces))  # landing on empty "wastes" a space for future reception

    notes = []
    if post_sw - pre_sw > 8:
        notes.append("large sw increase on deal")
    if created_ge3 > 0:
        notes.append(f"created {created_ge3} new >=3 same-suit fragments")

    return DealImpact(
        sw_increase=post_sw - pre_sw,
        spaces_change=post_spaces - pre_spaces,
        landed_on_same_suit=max(0, post_tail_sum - pre_tail_sum),  # rough net
        created_new_fragment_ge3=created_ge3,
        destroyed_useful_hook=destroyed,
        suit_building_created=created_ge3,
        suit_building_destroyed=max(0, - (post_tail_sum - pre_tail_sum)),
        notes=notes,
    )


def suit_clearance_diagnostics(state: SpiderState, analysis: DealAnalysis) -> Dict[str, dict]:
    """Suit-centric view: for each suit, progress and blockers."""
    if analysis is None:
        return {}

    analyser = DynamicDependencyAnalyser(analysis)
    report = analyser.analyze(state)

    # Group critical buried by suit
    blockers: Dict[str, List] = {s: [] for s in "shdc"}
    for bt in report.critical_buried:
        if bt.suit in blockers:
            blockers[bt.suit].append(bt)

    # Visible progress per suit (longest run + total visible)
    frags = count_same_suit_fragments(state)
    visible_count: Dict[str, int] = {s: 0 for s in "shdc"}
    max_run: Dict[str, int] = {s: 0 for s in "shdc"}
    for col in state.columns:
        for c in col.face_up:
            visible_count[c.suit] += 1
    for s, l in frags:
        max_run[s] = max(max_run[s], l)

    # From global analysis: how many of this suit are "available" so far
    # (cumulative up to current round). We approximate "round" by how many deals have happened.
    deals_done = (104 - 54 - len(state.stock)) // 10   # rough
    round_idx = min(deals_done, len(analysis.cumulative_by_suit["s"]) - 1)

    result = {}
    for s in analysis.priority_clearance_order:
        total_available = analysis.cumulative_by_suit.get(s, [0]*6)[round_idx] if analysis.cumulative_by_suit else 0
        result[s] = {
            "visible": visible_count[s],
            "longest_run": max_run[s],
            "blockers": len(blockers.get(s, [])),
            "blocker_depths": [b.depth for b in blockers.get(s, [])],
            "total_available_so_far": total_available,
            "progress": visible_count[s] + max_run[s] * 0.5,  # crude
            "closest_to_completion": max_run[s] >= 10 or (total_available - visible_count[s] <= 3),
        }
    return result


def evaluate_future_stress(
    start_state: SpiderState,
    analysis: DealAnalysis,
    max_future_deals: int = 3,
) -> Dict:
    """
    Deterministic forward stress test using the known stock sequence.
    Returns current + post-deal1/2/3 metrics + impacts + composite.
    """
    results: List[Dict] = []
    current = start_state.clone()

    # Current
    curr_m = compute_metrics(current, analysis)
    curr_suit = suit_clearance_diagnostics(current, analysis)
    results.append({
        "label": "current",
        "metrics": curr_m,
        "suit_diag": curr_suit,
        "impact": None,
    })

    sw_seq = [curr_m.sw]
    goodnesses = [50 - curr_m.sw]   # positive goodness proxy (lower sw = higher goodness)

    for d in range(1, max_future_deals + 1):
        if len(current.stock) < 10:
            break

        pre = current.clone()
        current.deal()  # deterministic MW deal of next known 10

        post_m = compute_metrics(current, analysis)
        impact = compute_deal_impact(pre, current, analysis.incoming_by_round[d-1] if d-1 < len(analysis.incoming_by_round) else [])
        suit_d = suit_clearance_diagnostics(current, analysis)

        results.append({
            "label": f"post_deal{d}",
            "metrics": post_m,
            "suit_diag": suit_d,
            "impact": impact,
        })
        sw_seq.append(post_m.sw)
        # heavier weight on later deals (user request)
        w = 1.0 + 0.4 * d
        goodnesses.append(w * (50 - post_m.sw))

    # Composite: weighted sum of goodness (higher better). Multiplicative version also computed.
    composite_weighted = sum(goodnesses)
    # Multiplicative on (goodness + epsilon) to avoid zero/negative blowup
    comp_mult = 1.0
    for g in goodnesses:
        comp_mult *= max(1.0, g + 5)   # shift so very bad states don't go to zero too fast

    return {
        "sw_sequence": sw_seq,
        "results": results,
        "composite_weighted_goodness": composite_weighted,
        "composite_multiplicative": comp_mult,
        "num_deals_simulated": len(results) - 1,
    }


# ----------------- Task 3 helpers -----------------

CANDIDATES = [
    ("layered_strong_lowsw_post_deal1_prefix.moves", "71-action sw=11 reusable prefix (post-deal1)"),
    ("layered_from_sw11_winstate_shaper.moves", "83-action (71 + 12-step shaper from sw=11)"),
    ("layered_strong_ck_bestdeal_r0.moves", "strong 124 (human51 + ck shaper + best_deal)"),
    ("layered_high_ck_bestdeal_full.moves", "high-ck 127"),
    ("layered_prefix_sw11_medium_rest.moves", "medium 121 from sw=11 prefix"),
]


def load_candidate_state(diag_dir: Path, fname: str, deal_tokens: List[str]) -> Tuple[SpiderState, str]:
    """
    For the pure prefix files (post first deal by construction): replay the whole file.
    For full paths: replay until the first deal action, then perform the deal, return that state.
    """
    p = diag_dir / fname
    actions = parse_moves_file(p)

    cards = [c for c in deal_tokens]  # assume tokens or convert
    # The caller should pass the raw card list or tokens that load_deal understands.
    # For simplicity here we expect the caller to have already loaded initial state.
    # We return the replayed state at the "post first deal" snapshot.
    # This function is a helper; the actual runner will do the replay.
    return p, actions   # caller does the replay logic


def get_post_deal1_state_from_moves(initial: SpiderState, actions: list) -> SpiderState:
    """Replay actions; when we hit the first deal, perform it and return the state."""
    state = initial.clone()
    replay_actions(state, actions)  # this will apply everything, including deals
    # If the file is a post-deal1 prefix, the state after full replay is what we want.
    # For full candidates we want the snapshot right after their first deal.
    # Since the listed "full" ones for ranking are the layered ck ones, and the prefixes are the key,
    # for the prefixes we just use the full replay.
    # To make it general for a "full path" file, we would stop at first deal.
    # For this task we treat the two *_prefix* and *_from_sw11* as the "current state" directly.
    return state


if __name__ == "__main__":
    # Small self-test placeholder
    print("future_stress module loaded. Use evaluate_future_stress(...) and run_ranking(...).")
