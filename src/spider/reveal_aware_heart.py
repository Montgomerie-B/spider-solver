"""Top heart run and a real reveal, together, after the fifth deal.

A seven-card heart run on a column top is not enough. The terminal also
has fewer face-down cards than the search root. Both facts are read from
that one state. A buried run does not count, and a reveal that is later
undone by covering the run again is not a terminal.

Search budgets below are the v0.139 caps. They are not raised here.
``run_reveal`` ordering lives on ``search_milestone`` and is opt-in.
"""

from __future__ import annotations

from typing import Callable, List, Sequence

from spider.engine import SpiderState
from spider.heart_run_followthrough import (
    HEART_RUN,
    HEART_SUIT,
    top_run_length,
    top_same_suit_run_at_least,
)
from spider.metrics import Action
from spider.post_deal_milestone import MilestoneEndpoint, route_for_endpoint
from spider.purposeful_macro import PostDealRoot
from spider.research_actions import face_down_count

# Gate B. Five paid moves from checkpoint 158. Proof ceiling stays 172.
CONTROL_INDEX = 158
CONTROL_END = 163
CONTROL_PAID = 5
CONTROL_DEPTH = 8
CONTROL_UNIQUE = 12_000
CONTROL_TIME_S = 12.0
CONTROL_RSS_MB = 512.0
CONTROL_PROOF = 172

# Gate C. Same tactic caps as v0.136 through v0.138.
TACTIC_PAID = 12
TACTIC_DEPTH = 18
TACTIC_UNIQUE = 6_000
TACTIC_TIME_S = 6.0
TACTIC_RSS_MB = 512.0
TACTIC_PROOF = 171

WORKERS = 1


def top_heart_span(state: SpiderState) -> dict:
    """Longest heart run that ends on a column top, with its high and low ranks."""

    best_len = 0
    best_high = 0
    best_low = 0
    for column in state.columns:
        up = column.face_up
        if not up or up[-1].suit != HEART_SUIT:
            continue
        end = len(up) - 1
        start = end
        while (
            start > 0
            and up[start - 1].suit == HEART_SUIT
            and up[start - 1].rank == up[start].rank + 1
        ):
            start -= 1
        length = end - start + 1
        high = int(up[start].rank)
        low = int(up[end].rank)
        if length > best_len or (length == best_len and high > best_high):
            best_len = length
            best_high = high
            best_low = low
    return {"length": best_len, "high": best_high, "low": best_low, "top": top_run_length(state, HEART_SUIT)}


def compound_heart_reveal(root_face_down: int) -> Callable[[SpiderState], bool]:
    """Seven hearts on a column top, and fewer face-down cards than ``root``.

    The comparison is the count at this state against the count at the
    search root. It does not name a card. Both parts have to be true on
    the same state. Column order does not matter.
    """

    root_hidden = int(root_face_down)

    def goal(state: SpiderState) -> bool:
        return bool(
            top_same_suit_run_at_least(state, HEART_SUIT, HEART_RUN)
            and face_down_count(state) < root_hidden
        )

    return goal


def as_compound_roots(endpoints: Sequence[MilestoneEndpoint]) -> List[PostDealRoot]:
    """Physical compound endpoints. The macro is only the pre-deal prefix."""

    roots = []
    for item in endpoints:
        roots.append(
            PostDealRoot(
                state=item.state,
                g=int(item.g),
                macro=tuple(item.pre_deal_macro),
                h=int(item.h),
                f=int(item.f),
                purpose="post-deal heart run and reveal",
                pack=item.pack,
                symmetry=item.symmetry,
            )
        )
    return roots


def compound_route_actions(
    canonical_actions: Sequence[Action],
    endpoint: MilestoneEndpoint,
    continuation: Sequence[Action] = (),
    suffix: Sequence[Action] = (),
) -> List[Action]:
    """Checkpoint-140 prefix, this root's macro, the deal, then the compound line."""

    return route_for_endpoint(canonical_actions, endpoint, continuation, suffix)
