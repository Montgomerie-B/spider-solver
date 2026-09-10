"""Research-only target-directed fd13 plateau search.

Heuristic priority is TARGET_FACE_UP_COUNT then primitive depth.  It has no
proof or pruning authority.  Legal actions are never dropped because they
increase the target face-up count.  Not imported by ``solve_progressive``.
"""

from __future__ import annotations

import heapq
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from spider.engine import Column, SpiderState
from spider.metrics import Action, replay_actions
from spider.packed_state import pack_state, unpack_state
from spider.rules import MW_RULES, MobilityWareRules
from spider.simple_progressive_solver import _capture, _restore, _rss_mb, apply_action
from spider.simple_workspace_reachability import (
    _metrics,
    empty_column_indices,
    engine_tableau_actions,
    face_down_count,
    post_stock_identity,
    reconstruct_actions,
)
from spider.state_identity import card_tuple

FdSignature = Tuple[Tuple[str, int], ...]


def face_down_signature(col: Column) -> FdSignature:
    return tuple(card_tuple(c) for c in col.face_down)


def signature_key(sig: FdSignature) -> str:
    return ",".join(f"{suit}{rank}" for suit, rank in sig)


def exposed_run_length(col: Column) -> int:
    up = col.face_up
    if not up:
        return 0
    run = 1
    for index in range(len(up) - 1, 0, -1):
        left, right = up[index - 1], up[index]
        if left.suit == right.suit and left.rank == right.rank + 1:
            run += 1
        else:
            break
    return run


def census_buried_targets(state: SpiderState) -> List[dict]:
    """Every column with a non-empty face-down stack."""

    rows = []
    for index, col in enumerate(state.columns):
        if not col.face_down:
            continue
        sig = face_down_signature(col)
        rows.append(
            {
                "physical_column_0": index,
                "physical_column_1": index + 1,
                "signature": [list(card) for card in sig],
                "signature_key": signature_key(sig),
                "fd_count": len(col.face_down),
                "face_up_count": len(col.face_up),
                "exposed_run": exposed_run_length(col),
            }
        )
    return rows


def locate_target(state: SpiderState, target: FdSignature) -> Optional[int]:
    """Physical column carrying ``target``.  None if already revealed/absent."""

    for index, col in enumerate(state.columns):
        if face_down_signature(col) == target:
            return index
    return None


def target_face_up_count(state: SpiderState, target: FdSignature) -> Optional[int]:
    index = locate_target(state, target)
    if index is None:
        return None
    return len(state.columns[index].face_up)


def priority_key(target_fu: int, depth: int, seq: int) -> Tuple[int, int, int]:
    """Sole heuristic: fewer face-up cards above the target, then depth, then seq."""

    return (int(target_fu), int(depth), int(seq))


def changed_face_down_columns(parent: SpiderState, child: SpiderState) -> List[int]:
    changed = []
    for index in range(10):
        if face_down_signature(parent.columns[index]) != face_down_signature(child.columns[index]):
            changed.append(index)
    return changed


def is_target_reveal(parent: SpiderState, child: SpiderState, target: FdSignature) -> bool:
    """True iff fd dropped by one and the selected buried stack is the one that changed."""

    if face_down_count(child) != face_down_count(parent) - 1:
        return False
    if len(child.foundations) != len(parent.foundations):
        return False
    changed = changed_face_down_columns(parent, child)
    if len(changed) != 1:
        return False
    return face_down_signature(parent.columns[changed[0]]) == target


def revealed_target_signature(parent: SpiderState, child: SpiderState) -> Optional[FdSignature]:
    if face_down_count(child) != face_down_count(parent) - 1:
        return None
    changed = changed_face_down_columns(parent, child)
    if len(changed) != 1:
        return None
    return face_down_signature(parent.columns[changed[0]])


@dataclass
class TargetClearanceResult:
    target_key: str
    unique: int
    generated: int
    duplicate_skips: int
    max_depth: int
    min_target_fu: Optional[int]
    first_reveal_unique: Optional[int]
    first_reveal_depth: Optional[int]
    first_reveal_expansions: Optional[int]
    exit_classes: int
    off_target_reveals: int
    fu_decreases: int
    fu_increases: int
    fu_returns: int
    elapsed_s: float
    peak_rss_mb: Optional[float]
    stop_reason: str
    expansions: int
    exits: List[dict] = field(default_factory=list)
    foundation_witness: Optional[dict] = None
    root_target_fu: Optional[int] = None
    root_physical_column: Optional[int] = None


def target_directed_plateau(
    seed: SpiderState,
    target: FdSignature,
    *,
    max_unique: int = 500_000,
    time_limit_s: float = 600.0,
    rss_abort_mb: float = 2 * 1024.0,
    max_exits: int = 64,
    plateau_fd: int = 13,
    identity_fn=None,
    rules: MobilityWareRules = MW_RULES,
) -> TargetClearanceResult:
    """Best-first fd-preserving search ordered by face-up cards above ``target``."""

    if identity_fn is None:
        identity_fn = post_stock_identity
    if seed.stock:
        raise ValueError("target_directed_plateau is post-stock only")
    root_metrics = _metrics(seed)
    if root_metrics["fd"] != plateau_fd or root_metrics["foundations"] != 0:
        raise ValueError("seed is not on the requested plateau")
    root_col = locate_target(seed, target)
    if root_col is None:
        raise ValueError("target face-down signature is not present in the seed")

    started = time.perf_counter()
    ids: Dict[bytes, int] = {}
    keys: List[bytes] = []
    parent: List[int] = []
    src_a: List[int] = []
    dst_a: List[int] = []
    k_a: List[int] = []
    depth_of: List[int] = []
    fu_of: List[int] = []

    def add_node(concrete: bytes, ident: bytes, parent_id: int, src: int, dst: int, k: int, depth: int, fu: int) -> int:
        node = len(keys)
        ids[ident] = node
        keys.append(concrete)
        parent.append(parent_id)
        src_a.append(src)
        dst_a.append(dst)
        k_a.append(k)
        depth_of.append(depth)
        fu_of.append(fu)
        return node

    root_fu = len(seed.columns[root_col].face_up)
    root_ident = identity_fn(seed)
    add_node(pack_state(seed), root_ident, -1, -1, -1, -1, 0, root_fu)
    heap: List[Tuple[int, int, int, int]] = [(*priority_key(root_fu, 0, 0), 0)]
    seq = 1
    generated = 0
    duplicate_skips = 0
    expansions = 0
    fu_decreases = 0
    fu_increases = 0
    fu_returns = 0
    seen_fu: Set[int] = {root_fu}
    min_target_fu = root_fu
    exits: Dict[bytes, dict] = {}
    off_target_reveals = 0
    first_reveal_unique: Optional[int] = None
    first_reveal_depth: Optional[int] = None
    first_reveal_expansions: Optional[int] = None
    foundation_witness: Optional[dict] = None
    peak_rss = _rss_mb()
    stop_reason = "frontier empty"
    deadline = started + time_limit_s
    max_depth = 0

    def note_rss() -> bool:
        nonlocal peak_rss
        rss = _rss_mb()
        if rss is not None and (peak_rss is None or rss > peak_rss):
            peak_rss = rss
        return rss_abort_mb is not None and rss is not None and rss >= rss_abort_mb

    while heap:
        if time.perf_counter() >= deadline:
            stop_reason = "time limit"
            break
        if note_rss():
            stop_reason = "rss abort"
            break
        if len(exits) >= max_exits:
            stop_reason = "exit harvest"
            break
        _fu, _d, _s, node = heapq.heappop(heap)
        expansions += 1
        state = unpack_state(keys[node])
        parent_fu = fu_of[node]
        parent_fd = face_down_count(state)
        parent_sigs = tuple(face_down_signature(col) for col in state.columns)
        max_depth = max(max_depth, depth_of[node])
        actions, _surprises = engine_tableau_actions(state, rules=rules)
        for action in actions:
            src, dst, k = action  # type: ignore[misc]
            snap = _capture(state, action)
            try:
                apply_action(state, action, rules=rules)
                generated += 1
                child_metrics = _metrics(state)
                ident = identity_fn(state)
                if child_metrics["foundations"] >= 1:
                    foundation_witness = {
                        "depth": depth_of[node] + 1,
                        "fd": child_metrics["fd"],
                        "foundations": child_metrics["foundations"],
                        "actions": [list(a) for a in reconstruct_actions(node, parent, src_a, dst_a, k_a)]
                        + [[src, dst, k]],
                        "ordered_digest": pack_state(state).hex(),
                        "symmetry_digest": ident.hex(),
                    }
                    stop_reason = "foundation"
                    break
                if child_metrics["fd"] == plateau_fd - 1 and child_metrics["foundations"] == 0:
                    changed = [
                        index
                        for index in range(10)
                        if face_down_signature(state.columns[index]) != parent_sigs[index]
                    ]
                    target_hit = (
                        child_metrics["fd"] == parent_fd - 1
                        and len(changed) == 1
                        and parent_sigs[changed[0]] == target
                    )
                    if target_hit:
                        if ident not in exits:
                            path = reconstruct_actions(node, parent, src_a, dst_a, k_a) + [(src, dst, k)]
                            if first_reveal_unique is None:
                                first_reveal_unique = len(keys)
                                first_reveal_depth = depth_of[node] + 1
                                first_reveal_expansions = expansions
                            exits[ident] = {
                                "symmetry_digest": ident.hex(),
                                "ordered_digest": pack_state(state).hex(),
                                "actions": [list(a) for a in path],
                                "depth": depth_of[node] + 1,
                                "empties": list(child_metrics["empties"]),
                                "longest_run": child_metrics["longest_run"],
                                "adjacencies": child_metrics["adjacencies"],
                                "blocks": child_metrics["blocks"],
                                "fd": child_metrics["fd"],
                                "foundations": 0,
                                "reveal_action": [src, dst, k],
                                "target_key": signature_key(target),
                                "hits": 1,
                            }
                        else:
                            exits[ident]["hits"] += 1
                    else:
                        off_target_reveals += 1
                    continue
                if child_metrics["fd"] != plateau_fd or child_metrics["foundations"] != 0:
                    continue
                child_fu = target_face_up_count(state, target)
                if child_fu is None:
                    continue
                if child_fu < parent_fu:
                    fu_decreases += 1
                elif child_fu > parent_fu:
                    fu_increases += 1
                if child_fu in seen_fu and child_fu != parent_fu:
                    fu_returns += 1
                seen_fu.add(child_fu)
                min_target_fu = min(min_target_fu, child_fu)
                if ident in ids:
                    duplicate_skips += 1
                    continue
                if len(keys) >= max_unique:
                    stop_reason = "unique limit"
                    break
                child_id = add_node(
                    pack_state(state), ident, node, src, dst, k, depth_of[node] + 1, child_fu
                )
                heapq.heappush(heap, (*priority_key(child_fu, depth_of[node] + 1, seq), child_id))
                seq += 1
            finally:
                _restore(state, snap)
            if stop_reason in ("unique limit", "foundation"):
                break
        if stop_reason in ("unique limit", "foundation"):
            break

    for rec in exits.values():
        walk = seed.clone()
        try:
            rec["local_cost"] = replay_actions(walk, [tuple(a) for a in rec["actions"]])
            rec["legal"] = len(engine_tableau_actions(walk)[0])
            rec["replay_ok"] = True
        except (ValueError, AssertionError) as exc:
            rec["local_cost"] = None
            rec["legal"] = None
            rec["replay_ok"] = False
            rec["replay_error"] = str(exc)

    if stop_reason == "frontier empty" and heap:
        stop_reason = "frontier empty"
    elif not heap and stop_reason not in ("exit harvest", "foundation", "unique limit", "time limit", "rss abort"):
        stop_reason = "frontier empty"

    elapsed = time.perf_counter() - started
    return TargetClearanceResult(
        target_key=signature_key(target),
        unique=len(keys),
        generated=generated,
        duplicate_skips=duplicate_skips,
        max_depth=max_depth,
        min_target_fu=min_target_fu,
        first_reveal_unique=first_reveal_unique,
        first_reveal_depth=first_reveal_depth,
        first_reveal_expansions=first_reveal_expansions,
        exit_classes=len(exits),
        off_target_reveals=off_target_reveals,
        fu_decreases=fu_decreases,
        fu_increases=fu_increases,
        fu_returns=fu_returns,
        elapsed_s=elapsed,
        peak_rss_mb=peak_rss if peak_rss is not None else _rss_mb(),
        stop_reason=stop_reason,
        expansions=expansions,
        exits=list(exits.values()),
        foundation_witness=foundation_witness,
        root_target_fu=root_fu,
        root_physical_column=root_col,
    )
