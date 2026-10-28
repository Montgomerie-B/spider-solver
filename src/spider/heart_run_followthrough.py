"""Top-anchored heart-run target after the fifth deal.

``evaluate_target(..., "same_suit_run_at_least")`` accepts a buried run.
On the canonical stock-empty position that buried run is already seven
hearts long, so the additional obligation is the same descending sequence
sitting on a column top, where it can move as one stack. The predicate is
not a solved game and it is not a proof bound.

Search budgets below are the v0.138 caps. They are not raised here.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Sequence, Tuple

from spider.engine import SpiderState
from spider.metrics import Action, format_action
from spider.planner.strategic_objectives import evaluate_target
from spider.post_deal_milestone import (
    ENDPOINT_LIMIT,
    MilestoneEndpoint,
    has_proof_eligible_child,
    route_for_endpoint,
)
from spider.purposeful_macro import PostDealRoot

HEART_SUIT = "h"
HEART_RUN = 7

# Gate A. Proof ceiling stays 172 so a paid cap of three cannot prune the root.
CONTROL_PAID = 3
CONTROL_DEPTH = 6
CONTROL_UNIQUE = 2_000
CONTROL_TIME_S = 4.0
CONTROL_RSS_MB = 512.0
CONTROL_PROOF = 172

# Gate B repair budget from the five-move shortcut. Not a portfolio search.
REPAIR_PAID = 6
REPAIR_DEPTH = 12
REPAIR_UNIQUE = 6_000
REPAIR_TIME_S = 6.0
REPAIR_RSS_MB = 512.0
REPAIR_PROOF = 172
CANONICAL_ASSEMBLY_G = 161

# Gate C. Same tactic caps as v0.136 and v0.137, proof ceiling 171.
TACTIC_PAID = 12
TACTIC_DEPTH = 18
TACTIC_UNIQUE = 6_000
TACTIC_TIME_S = 6.0
TACTIC_RSS_MB = 512.0
TACTIC_PROOF = 171

SCREEN_SLACK = 1
WORKERS = 1


def anywhere_same_suit_run_at_least(state: SpiderState, suit: str, min_len: int) -> bool:
    """Buried or exposed. This is the existing strategic predicate."""

    return bool(
        evaluate_target(
            state,
            "same_suit_run_at_least",
            {"suit": suit, "min_len": int(min_len)},
        )
    )


def top_run_length(state: SpiderState, suit: str) -> int:
    """Longest descending ``suit`` run that ends on a column top."""

    best = 0
    for column in state.columns:
        up = column.face_up
        if not up or up[-1].suit != suit:
            continue
        length = 1
        index = len(up) - 1
        while (
            index > 0
            and up[index - 1].suit == suit
            and up[index - 1].rank == up[index].rank + 1
        ):
            length += 1
            index -= 1
        if length > best:
            best = length
    return best


def top_same_suit_run_at_least(state: SpiderState, suit: str, min_len: int) -> bool:
    """Contiguous descending run of ``suit`` that is the movable top suffix.

    Cards of that suit buried under a different card do not count, and two
    shorter runs in different columns do not add together.
    """

    return top_run_length(state, suit) >= int(min_len)


def heart_goal(state: SpiderState) -> bool:
    """At least seven descending hearts on one column top.

    The canonical window builds 7H through AH. Any other top run of seven
    hearts meets the same structural predicate. A buried run does not.
    """

    return top_same_suit_run_at_least(state, HEART_SUIT, HEART_RUN)


def choose_heart_obligation(before: SpiderState, after: SpiderState) -> dict:
    """Pick the obligation the three-action window actually adds.

    If a top run of seven hearts is already present, there is no new
    target in this predicate family. If the anywhere-run is still false,
    that existing predicate is the obligation. If a buried run is already
    true and the top run becomes true only after the window, the top run
    is the additional obligation.
    """

    buried_before = anywhere_same_suit_run_at_least(before, HEART_SUIT, HEART_RUN)
    top_before = heart_goal(before)
    buried_after = anywhere_same_suit_run_at_least(after, HEART_SUIT, HEART_RUN)
    top_after = heart_goal(after)
    if top_before:
        mode = "already_satisfied"
        goal: Optional[Callable[[SpiderState], bool]] = None
    elif buried_before and top_after:
        mode = "top_same_suit_run_at_least"
        goal = heart_goal
    elif (not buried_before) and buried_after:
        mode = "same_suit_run_at_least"
        goal = lambda state: anywhere_same_suit_run_at_least(state, HEART_SUIT, HEART_RUN)
    else:
        mode = "not_established"
        goal = None
    return {
        "mode": mode,
        "goal": goal,
        "buried_before": buried_before,
        "top_before": top_before,
        "buried_after": buried_after,
        "top_after": top_after,
        "top_length_before": top_run_length(before, HEART_SUIT),
        "top_length_after": top_run_length(after, HEART_SUIT),
    }


def select_heart_endpoints(
    items: Sequence[MilestoneEndpoint],
    *,
    ceiling: int = TACTIC_PROOF,
    limit: int = ENDPOINT_LIMIT,
    goal: Optional[Callable[[SpiderState], bool]] = None,
) -> Tuple[List[MilestoneEndpoint], List[dict], dict]:
    """Keep diverse low-``f`` heart endpoints.

    Symmetry duplicates keep the lower ``f``, then the lower ``g``, and
    that physical prefix's own pre-deal macro. ``f`` is a lower bound.
    Dropping a higher ``f`` does not prove that state cannot finish.
    """

    eligible = []
    for item in items:
        if not item.replay_ok or int(item.f) > int(ceiling):
            continue
        if goal is not None and not goal(item.state):
            continue
        eligible.append(item)
    eligible.sort(key=lambda item: (int(item.f), int(item.g), item.pack))
    winners: Dict[str, MilestoneEndpoint] = {}
    dominated: List[dict] = []
    for item in eligible:
        previous = winners.get(item.symmetry)
        if previous is None:
            winners[item.symmetry] = item
            continue
        dominated.append(
            {
                "reason": "symmetry-dominated",
                "dropped_g": item.g,
                "kept_g": previous.g,
                "dropped_f": item.f,
                "kept_f": previous.f,
                "dropped_root": item.root_index,
                "kept_root": previous.root_index,
                "dropped_macro": [format_action(action) for action in item.pre_deal_macro],
                "kept_macro": [format_action(action) for action in previous.pre_deal_macro],
            }
        )
    pool = sorted(winners.values(), key=lambda item: (int(item.f), int(item.g), item.pack, int(item.root_index)))
    chosen: List[MilestoneEndpoint] = []
    seen_roots = set()
    for item in pool:
        if item.root_index in seen_roots:
            continue
        chosen.append(item)
        seen_roots.add(item.root_index)
        if len(chosen) >= int(limit):
            break
    if len(chosen) < int(limit):
        for item in pool:
            if item in chosen:
                continue
            chosen.append(item)
            if len(chosen) >= int(limit):
                break
    reason = "lowest f, then g; one prefix per symmetry, then one per root"
    dropped = len(pool) - len(chosen)
    if dropped > 0:
        reason += f"; truncated {dropped} higher-f states"
    if dominated:
        reason += f"; {len(dominated)} symmetry duplicates kept the lower f"
    info = {
        "eligible": len(eligible),
        "symmetries": len(pool),
        "retained": len(chosen),
        "truncated": max(0, dropped),
        "reason": reason,
        "f_is_not_a_predicted_cost": True,
    }
    return chosen, dominated, info


def screen_heart_endpoint(
    endpoint: MilestoneEndpoint,
    *,
    ceiling: int = TACTIC_PROOF,
    excluded_packs: Sequence[str] = (),
    excluded_symmetries: Sequence[str] = (),
    goal: Callable[[SpiderState], bool] = heart_goal,
) -> dict:
    """Experimental screen. ``f <= ceiling - 1`` is not a finishability proof."""

    screen = int(ceiling) - int(SCREEN_SLACK)
    reasons: List[str] = []
    if endpoint.pack in set(excluded_packs) or endpoint.symmetry in set(excluded_symmetries):
        reasons.append("previously exhausted identity")
    if int(endpoint.f) > screen:
        reasons.append("f above screen")
    if not endpoint.replay_ok or not goal(endpoint.state):
        reasons.append("heart run absent")
    affordable = False
    if not reasons:
        affordable = has_proof_eligible_child(endpoint.state, int(endpoint.g), int(ceiling))
        if not affordable:
            reasons.append("no proof-eligible successor")
    return {
        "accepted": not reasons,
        "reasons": reasons,
        "screen_f": screen,
        "proof": False,
        "affordable_successor": affordable,
        "f": int(endpoint.f),
        "g": int(endpoint.g),
        "h": int(endpoint.h),
        "pack": endpoint.pack,
        "symmetry": endpoint.symmetry,
        "root_index": int(endpoint.root_index),
    }


def as_heart_roots(endpoints: Sequence[MilestoneEndpoint]) -> List[PostDealRoot]:
    """Physical heart-run states. The macro is only the pre-deal prefix."""

    roots = []
    for item in endpoints:
        roots.append(
            PostDealRoot(
                state=item.state,
                g=int(item.g),
                macro=tuple(item.pre_deal_macro),
                h=int(item.h),
                f=int(item.f),
                purpose="post-deal heart run",
                pack=item.pack,
                symmetry=item.symmetry,
            )
        )
    return roots


def heart_route_actions(
    canonical_actions: Sequence[Action],
    endpoint: MilestoneEndpoint,
    continuation: Sequence[Action] = (),
    suffix: Sequence[Action] = (),
) -> List[Action]:
    """Checkpoint-140 prefix, this root's macro, the deal, then the heart run."""

    return route_for_endpoint(canonical_actions, endpoint, continuation, suffix)
