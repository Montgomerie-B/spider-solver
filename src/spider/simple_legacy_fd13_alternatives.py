"""Research-only helpers for v0.23 legacy fd13 alternative-branch recovery.

No new search heuristic.  Classification uses ordered ``pack_state`` and
post-stock column-symmetry identity.  Fair viability testing is primitive-depth
layered BFS of every engine-legal tableau move.  Not imported by
``solve_progressive``.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from spider.engine import SpiderState
from spider.metrics import Action, replay_actions
from spider.packed_state import pack_state
from spider.simple_post_deal_audit import census_legal_by_tier, exposed_run_metrics
from spider.simple_target_clearance import (
    census_buried_targets,
    face_down_signature,
    signature_key,
)
from spider.simple_workspace_reachability import (
    empty_column_indices,
    engine_tableau_actions,
    face_down_count,
    layered_reachability,
    post_stock_identity,
)

CURRENT_FD13_CLASS = "CURRENT_FD13_CLASS"
ALTERNATIVE_FD13_CLASS = "ALTERNATIVE_FD13_CLASS"

PHASE3_MAX_UNIQUE = 1_000_000
PHASE3_TIME_S = 1200.0
PHASE3_RSS_MB = 3 * 1024.0
PHASE3_MAX_DEPTH = 10

PHASE4_MAX_UNIQUE = 750_000
PHASE4_TIME_S = 900.0
PHASE4_RSS_MB = 3 * 1024.0


def legal_tableau_count(state: SpiderState) -> int:
    actions, _surprises = engine_tableau_actions(state)
    return len(actions)


def buried_stack_records(state: SpiderState) -> List[dict]:
    return census_buried_targets(state)


def buried_signature_keys(state: SpiderState) -> List[str]:
    return [row["signature_key"] for row in buried_stack_records(state)]


def checkpoint_record(
    state: SpiderState,
    *,
    arm: str,
    path_length: int,
    cost: int,
    kind: str,
) -> dict:
    runs = exposed_run_metrics(state)
    census = census_legal_by_tier(state)
    buried = buried_stack_records(state)
    return {
        "arm": arm,
        "kind": kind,
        "total_primitive_path": path_length,
        "corrected_mw_cost": cost,
        "fd": face_down_count(state),
        "foundations": len(state.foundations),
        "stock": len(state.stock),
        "empties": list(empty_column_indices(state)),
        "empty_count": len(empty_column_indices(state)),
        "longest_run": runs["longest_exposed_same_suit_run"],
        "adjacencies": runs["exposed_same_suit_adjacencies"],
        "movable_blocks": runs["movable_same_suit_blocks"],
        "legal_action_count": legal_tableau_count(state),
        "census": census,
        "ordered_digest": pack_state(state).hex(),
        "symmetry_digest": post_stock_identity(state).hex(),
        "buried_face_down_stacks": buried,
    }


def reveal_target_from_transition(
    before: SpiderState, after: SpiderState
) -> dict:
    """Identify the buried stack exposed by a one-card fd drop.

    Identity is the exact face-down-stack signature at ``before``, not the
    physical column number.
    """

    before_rows = {row["signature_key"]: row for row in buried_stack_records(before)}
    after_rows = {row["signature_key"]: row for row in buried_stack_records(after)}
    missing = [key for key in before_rows if key not in after_rows]
    appeared = [key for key in after_rows if key not in before_rows]
    target_key = None
    prefix_key = None
    if len(missing) == 1:
        target_key = missing[0]
        sig = tuple(tuple(card) for card in before_rows[target_key]["signature"])
        if len(sig) >= 2:
            prefix_key = signature_key(sig[:-1])
        physical = before_rows[target_key]["physical_column_0"]
    else:
        physical = None
        # Fallback: column whose face-down length dropped.
        for index, (left, right) in enumerate(zip(before.columns, after.columns)):
            if len(left.face_down) > len(right.face_down):
                target_key = signature_key(face_down_signature(left))
                physical = index
                if len(left.face_down) >= 2:
                    prefix_key = signature_key(face_down_signature(left)[:-1])
                break
    return {
        "signature_key": target_key,
        "physical_column_0_at_before": physical,
        "physical_column_1_at_before": None if physical is None else physical + 1,
        "missing_before_signatures": missing,
        "appeared_after_signatures": appeared,
        "prefix_signature_key": prefix_key,
        "prefix_present_after": bool(prefix_key and prefix_key in after_rows),
        "fd_before": face_down_count(before),
        "fd_after": face_down_count(after),
    }


def classify_fd13_identity(current_symmetry_hex: str, candidate_symmetry_hex: str) -> str:
    if current_symmetry_hex == candidate_symmetry_hex:
        return CURRENT_FD13_CLASS
    return ALTERNATIVE_FD13_CLASS


def equivalence_classes(records: Sequence[dict], *, field: str = "symmetry_digest") -> Dict[str, List[str]]:
    groups: Dict[str, List[str]] = {}
    for rec in records:
        key = rec[field]
        groups.setdefault(key, []).append(rec.get("arm") or rec.get("name") or "?")
    return groups


def fair_short_horizon_fd13_search(
    seed: SpiderState,
    *,
    max_depth: int = PHASE3_MAX_DEPTH,
    max_unique: int = PHASE3_MAX_UNIQUE,
    time_limit_s: float = PHASE3_TIME_S,
    rss_abort_mb: float = PHASE3_RSS_MB,
    dead_identities: Optional[Set[bytes]] = None,
):
    """Exact primitive-depth BFS.  No heuristic ordering.  Fresh TT."""

    return layered_reachability(
        seed,
        max_depth=max_depth,
        max_unique=max_unique,
        time_limit_s=time_limit_s,
        rss_abort_mb=rss_abort_mb,
        identity_fn=post_stock_identity,
        all_legal_tableau=True,
        collect_fd=12,
        stop_after_collect_layer=True,
        dead_identities=dead_identities,
        checkpoints=(4, 8, 10),
    )


def fair_fd10_continuation(
    sources: Sequence[SpiderState],
    *,
    origin_paths: Optional[Sequence[Sequence[Action]]] = None,
    max_unique: int = PHASE4_MAX_UNIQUE,
    time_limit_s: float = PHASE4_TIME_S,
    rss_abort_mb: float = PHASE4_RSS_MB,
    dead_identities: Optional[Set[bytes]] = None,
):
    """Multi-source exact continuation toward fd<=10 / foundation."""

    return layered_reachability(
        sources=list(sources),
        origin_paths=origin_paths,
        max_depth=10_000,
        max_unique=max_unique,
        time_limit_s=time_limit_s,
        rss_abort_mb=rss_abort_mb,
        identity_fn=post_stock_identity,
        all_legal_tableau=True,
        dead_identities=dead_identities,
        checkpoints=(8, 16, 24, 32),
    )


def replay_combined(opening: SpiderState, actions: Sequence[Action]) -> Tuple[SpiderState, int]:
    end = opening.clone()
    cost = replay_actions(end, list(actions))
    return end, cost


def load_known_dead_hex(paths: Iterable) -> Set[str]:
    members: Set[str] = set()
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line[0] == "{":
                import json

                rec = json.loads(line)
                digest = rec.get("symmetry_digest") or rec.get("identity") or rec.get("digest")
                if digest:
                    members.add(digest)
            else:
                members.add(line)
    return members
