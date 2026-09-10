"""Research-only target-directed fd13 plateau search.

Heuristic priority is TARGET_FACE_UP_COUNT then primitive depth.  It has no
proof or pruning authority.  Legal actions are never dropped because they
increase the target face-up count.  Not imported by ``solve_progressive``.
"""

from __future__ import annotations

import heapq
import time
from collections import Counter
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
    empty_transition_events,
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
    """v0.20 FU-only heuristic: fewer face-up cards above the target, then depth, then seq."""

    return (int(target_fu), int(depth), int(seq))


LANDING_SENTINEL = 99


def movable_blocks(cards: Sequence) -> List[list]:
    """Maximal same-suit descending-by-one blocks, top-first.

    ``cards[0]`` is the column bottom; ``cards[-1]`` is the exposed top.
    """

    blocks: List[list] = []
    i = len(cards)
    while i > 0:
        run = 1
        while i - run > 0:
            below = cards[i - run - 1]
            head = cards[i - run]
            if below.suit == head.suit and below.rank == head.rank + 1:
                run += 1
            else:
                break
        blocks.append(list(cards[i - run : i]))
        i -= run
    return blocks


def block_head_rank(block: Sequence) -> Optional[int]:
    if not block:
        return None
    return int(block[0].rank)


def legal_target_landings(state: SpiderState, target_col: int, head_rank: int) -> List[int]:
    """Physical columns that can currently receive the target's top block."""

    dests = []
    for index, col in enumerate(state.columns):
        if index == target_col:
            continue
        top = col.top()
        if top is None or top.rank == head_rank + 1:
            dests.append(index)
    return dests


def blocks_above_rank(cards: Sequence, rank: int) -> Optional[int]:
    """Movable-block count of face-up cards strictly above the topmost ``rank``.

    Returns None if that rank is not face-up in ``cards``.
    """

    topmost = None
    for index in range(len(cards) - 1, -1, -1):
        if int(cards[index].rank) == rank:
            topmost = index
            break
    if topmost is None:
        return None
    above = list(cards[topmost + 1 :])
    if not above:
        return 0
    return len(movable_blocks(above))


def next_landing_obstruction(state: SpiderState, target: FdSignature) -> int:
    """Optimistic one-step estimate of setup needed to land the current top block."""

    col_i = locate_target(state, target)
    if col_i is None:
        return LANDING_SENTINEL
    col = state.columns[col_i]
    blocks = movable_blocks(col.face_up)
    if not blocks:
        return 0
    head = block_head_rank(blocks[0])
    if head is None:
        return LANDING_SENTINEL
    if legal_target_landings(state, col_i, head):
        return 0
    candidates: List[int] = []
    if head < 13:
        for index, other in enumerate(state.columns):
            if index == col_i:
                continue
            n = blocks_above_rank(other.face_up, head + 1)
            if n is not None:
                candidates.append(n)
    for index, other in enumerate(state.columns):
        if index == col_i:
            continue
        if other.face_down:
            continue
        if other.is_empty():
            candidates.append(0)
            continue
        candidates.append(len(movable_blocks(other.face_up)))
    if not candidates:
        return LANDING_SENTINEL
    return min(candidates)


def target_block_count(state: SpiderState, target: FdSignature) -> Optional[int]:
    col_i = locate_target(state, target)
    if col_i is None:
        return None
    up = state.columns[col_i].face_up
    if not up:
        return 0
    return len(movable_blocks(up))


def relaxed_clearance(state: SpiderState, target: FdSignature) -> Optional[int]:
    blocks = target_block_count(state, target)
    if blocks is None:
        return None
    return int(blocks) + int(next_landing_obstruction(state, target))


def landing_priority_key(
    relaxed: int, blocks: int, obst: int, fu: int, depth: int, seq: int
) -> Tuple[int, int, int, int, int, int]:
    """v0.21 landing-aware order.  Heuristic only; never prunes."""

    return (int(relaxed), int(blocks), int(obst), int(fu), int(depth), int(seq))


def target_stack_audit(state: SpiderState, target: FdSignature) -> dict:
    """Descriptive partition of the target face-up stack and current landings."""

    col_i = locate_target(state, target)
    if col_i is None:
        return {"present": False}
    col = state.columns[col_i]
    blocks = movable_blocks(col.face_up)
    dests = []
    if blocks:
        dests = legal_target_landings(state, col_i, block_head_rank(blocks[0]))
    obst = next_landing_obstruction(state, target)
    return {
        "present": True,
        "physical_column_0": col_i,
        "physical_column_1": col_i + 1,
        "face_up": [[c.suit, int(c.rank)] for c in col.face_up],
        "face_up_count": len(col.face_up),
        "blocks": [
            {
                "cards": [[c.suit, int(c.rank)] for c in block],
                "head_rank": block_head_rank(block),
                "length": len(block),
            }
            for block in blocks
        ],
        "block_count": len(blocks),
        "top_block_head": None if not blocks else block_head_rank(blocks[0]),
        "top_block_length": 0 if not blocks else len(blocks[0]),
        "legal_destinations": dests,
        "legal_landing": bool(dests),
        "empty_columns": list(empty_column_indices(state)),
        "landing_obstruction": obst,
        "relaxed_clearance": len(blocks) + obst,
    }


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
    min_block_count: Optional[int] = None
    min_obstruction: Optional[int] = None
    min_relaxed: Optional[int] = None
    mode: str = "fu"
    records: List[dict] = field(default_factory=list)
    fu7_witness: Optional[dict] = None
    stall_sample: List[dict] = field(default_factory=list)
    root_audit: Optional[dict] = None


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
    mode: str = "fu",
) -> TargetClearanceResult:
    """Best-first fd-preserving search.

    ``mode="fu"`` is the v0.20 TARGET_FACE_UP_COUNT order.
    ``mode="landing"`` is v0.21 RELAXED_CLEARANCE order.  Neither prunes.
    """

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

    landing = mode == "landing"
    root_fu = len(seed.columns[root_col].face_up)
    root_ident = identity_fn(seed)
    add_node(pack_state(seed), root_ident, -1, -1, -1, -1, 0, root_fu)
    root_audit = target_stack_audit(seed, target)
    root_blocks = int(root_audit.get("block_count") or 0)
    root_obst = int(root_audit.get("landing_obstruction") or 0)
    root_relaxed = int(root_audit.get("relaxed_clearance") or root_blocks + root_obst)
    if landing:
        heap: List[tuple] = [(*landing_priority_key(root_relaxed, root_blocks, root_obst, root_fu, 0, 0), 0)]
    else:
        heap = [(*priority_key(root_fu, 0, 0), 0)]
    seq = 1
    generated = 0
    duplicate_skips = 0
    expansions = 0
    fu_decreases = 0
    fu_increases = 0
    fu_returns = 0
    seen_fu: Set[int] = {root_fu}
    min_target_fu = root_fu
    min_block_count = root_blocks
    min_obstruction = root_obst
    min_relaxed = root_relaxed
    rec_min_fu = root_fu
    rec_min_blocks = root_blocks
    rec_min_obst = root_obst
    rec_min_relaxed = root_relaxed
    records: List[dict] = []
    fu7_witness: Optional[dict] = None
    stall_sample: List[dict] = []
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
        item = heapq.heappop(heap)
        node = item[-1]
        expansions += 1
        state = unpack_state(keys[node])
        if landing:
            audit = target_stack_audit(state, target)
            row = {
                "relaxed": audit.get("relaxed_clearance"),
                "fu": audit.get("face_up_count"),
                "block_count": audit.get("block_count"),
                "top_block_head": audit.get("top_block_head"),
                "top_block_length": audit.get("top_block_length"),
                "legal_landing": audit.get("legal_landing"),
                "empty_exists": bool(audit.get("empty_columns")),
                "landing_obstruction": audit.get("landing_obstruction"),
                "depth": depth_of[node],
                "expansion": expansions,
            }
            stall_sample.append(row)
            stall_sample.sort(
                key=lambda item: (
                    999 if item["relaxed"] is None else item["relaxed"],
                    item["depth"],
                )
            )
            del stall_sample[32:]
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
                if landing:
                    child_audit = target_stack_audit(state, target)
                    blocks_n = int(child_audit.get("block_count") or 0)
                    obst_n = int(child_audit.get("landing_obstruction") or LANDING_SENTINEL)
                    relaxed_n = int(child_audit.get("relaxed_clearance") or blocks_n + obst_n)
                    heapq.heappush(
                        heap,
                        (*landing_priority_key(relaxed_n, blocks_n, obst_n, child_fu, depth_of[node] + 1, seq), child_id),
                    )
                    rec = {
                        "kind": "record",
                        "expansion": expansions,
                        "unique": len(keys),
                        "depth": depth_of[node] + 1,
                        "target_fu": child_fu,
                        "block_count": blocks_n,
                        "landing_obstruction": obst_n,
                        "relaxed_clearance": relaxed_n,
                        "face_up": child_audit.get("face_up"),
                        "blocks": child_audit.get("blocks"),
                        "top_block_head": child_audit.get("top_block_head"),
                        "top_block_length": child_audit.get("top_block_length"),
                        "legal_destinations": child_audit.get("legal_destinations"),
                        "empty_columns": child_audit.get("empty_columns"),
                        "actions": [list(a) for a in reconstruct_actions(child_id, parent, src_a, dst_a, k_a)],
                    }
                    new_fu = child_fu < rec_min_fu
                    new_blocks = blocks_n < rec_min_blocks
                    new_obst = obst_n < rec_min_obst
                    new_rel = relaxed_n < rec_min_relaxed
                    rec_min_fu = min(rec_min_fu, child_fu)
                    rec_min_blocks = min(rec_min_blocks, blocks_n)
                    rec_min_obst = min(rec_min_obst, obst_n)
                    rec_min_relaxed = min(rec_min_relaxed, relaxed_n)
                    min_block_count = rec_min_blocks
                    min_obstruction = rec_min_obst
                    min_relaxed = rec_min_relaxed
                    if new_fu or new_blocks or new_obst or new_rel:
                        records.append(rec)
                    if fu7_witness is None and child_fu <= 7:
                        fu7_witness = rec
                else:
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
        min_block_count=min_block_count if landing else None,
        min_obstruction=min_obstruction if landing else None,
        min_relaxed=min_relaxed if landing else None,
        mode=mode,
        records=records,
        fu7_witness=fu7_witness,
        stall_sample=stall_sample,
        root_audit=root_audit,
    )


@dataclass
class TargetConversionResult:
    unique: int
    generated: int
    duplicate_skips: int
    completed_generated_depth: int
    completed_expanded_depth: int
    elapsed_s: float
    peak_rss_mb: Optional[float]
    stop_reason: str
    min_target_fu: int
    min_block_count: int
    min_fd: int
    target_exits: List[dict] = field(default_factory=list)
    off_target_exits: List[dict] = field(default_factory=list)
    fu_records: Dict[int, dict] = field(default_factory=dict)
    foundation_witness: Optional[dict] = None
    fd_le_11_witness: Optional[dict] = None
    layers: List[dict] = field(default_factory=list)
    expansion_order: List[int] = field(default_factory=list)
    reveal_depth: Optional[int] = None


def target_conversion_bfs(
    seed: SpiderState,
    target: FdSignature,
    *,
    plateau_fd: int = 13,
    max_depth: int = 16,
    max_unique: int = 1_000_000,
    time_limit_s: float = 1200.0,
    rss_abort_mb: float = 3 * 1024.0,
    identity_fn=None,
    rules: MobilityWareRules = MW_RULES,
    checkpoints: Sequence[int] = (4, 8, 12, 16),
) -> TargetConversionResult:
    """Fair primitive-depth BFS on the fd plateau.  No heuristic ordering."""

    if identity_fn is None:
        identity_fn = post_stock_identity
    if seed.stock:
        raise ValueError("target_conversion_bfs is post-stock only")
    root_metrics = _metrics(seed)
    if root_metrics["fd"] != plateau_fd or root_metrics["foundations"] != 0:
        raise ValueError("seed is not on the requested plateau")
    if locate_target(seed, target) is None:
        raise ValueError("target signature missing from seed")

    started = time.perf_counter()
    ids: Dict[bytes, int] = {}
    keys: List[bytes] = []
    parent: List[int] = []
    src_a: List[int] = []
    dst_a: List[int] = []
    k_a: List[int] = []
    depth_of: List[int] = []
    fu_of: List[int] = []
    blocks_of: List[int] = []
    empty_count_of: List[int] = []

    def add_node(concrete, ident, parent_id, src, dst, k, depth, fu, blocks, empty_n) -> int:
        node = len(keys)
        ids[ident] = node
        keys.append(concrete)
        parent.append(parent_id)
        src_a.append(src)
        dst_a.append(dst)
        k_a.append(k)
        depth_of.append(depth)
        fu_of.append(fu)
        blocks_of.append(blocks)
        empty_count_of.append(empty_n)
        return node

    root_fu = target_face_up_count(seed, target) or 0
    root_blocks = target_block_count(seed, target) or 0
    add_node(pack_state(seed), identity_fn(seed), -1, -1, -1, -1, 0, root_fu, root_blocks, len(root_metrics["empties"]))
    layers_ids: List[List[int]] = [[0]]
    generated = 0
    duplicate_skips = 0
    min_target_fu = root_fu
    min_block_count = root_blocks
    min_fd = root_metrics["fd"]
    fu_records: Dict[int, dict] = {}
    target_exits: Dict[bytes, dict] = {}
    off_target_exits: Dict[bytes, dict] = {}
    foundation_witness = None
    fd_le_11_witness = None
    layer_reports: List[dict] = []
    expansion_order: List[int] = []
    reveal_depth: Optional[int] = None
    peak_rss = _rss_mb()
    stop_reason = "max depth"
    deadline = started + time_limit_s
    last_expanded = -1
    last_generated = 0

    def note_rss() -> bool:
        nonlocal peak_rss
        rss = _rss_mb()
        if rss is not None and (peak_rss is None or rss > peak_rss):
            peak_rss = rss
        return rss_abort_mb is not None and rss is not None and rss >= rss_abort_mb

    def snapshot(node: int, extra: dict) -> dict:
        actions = reconstruct_actions(node, parent, src_a, dst_a, k_a)
        return {"actions": [list(a) for a in actions], "depth": depth_of[node], **extra}

    found_foundation = False
    incomplete = False

    for depth in range(0, max_depth):
        if found_foundation:
            break
        if reveal_depth is not None and depth >= reveal_depth:
            stop_reason = "target reveal"
            break
        if time.perf_counter() >= deadline:
            stop_reason = "time limit"
            incomplete = True
            break
        if note_rss():
            stop_reason = "rss abort"
            incomplete = True
            break
        if depth >= len(layers_ids) or not layers_ids[depth]:
            stop_reason = "frontier empty"
            break
        frontier = layers_ids[depth]
        expansion_order.append(depth)
        next_ids: List[int] = []
        gen_here = 0
        dups_here = 0
        exits_here = 0
        off_here = 0
        for node in frontier:
            if found_foundation:
                break
            if time.perf_counter() >= deadline:
                stop_reason = "time limit"
                incomplete = True
                break
            if (len(keys) & 2047) == 0 and note_rss():
                stop_reason = "rss abort"
                incomplete = True
                break
            state = unpack_state(keys[node])
            parent_fd = face_down_count(state)
            parent_sigs = tuple(face_down_signature(col) for col in state.columns)
            actions, _s = engine_tableau_actions(state, rules=rules)
            for action in actions:
                src, dst, k = action  # type: ignore[misc]
                snap = _capture(state, action)
                try:
                    apply_action(state, action, rules=rules)
                    generated += 1
                    gen_here += 1
                    child_metrics = _metrics(state)
                    ident = identity_fn(state)
                    min_fd = min(min_fd, child_metrics["fd"])
                    if child_metrics["foundations"] >= 1:
                        found_foundation = True
                        stop_reason = "foundation"
                        foundation_witness = {
                            "depth": depth + 1,
                            "fd": child_metrics["fd"],
                            "foundations": child_metrics["foundations"],
                            "actions": [list(a) for a in reconstruct_actions(node, parent, src_a, dst_a, k_a)]
                            + [[src, dst, k]],
                            "ordered_digest": pack_state(state).hex(),
                            "symmetry_digest": ident.hex(),
                        }
                        break
                    if child_metrics["fd"] <= plateau_fd - 2:
                        if fd_le_11_witness is None:
                            fd_le_11_witness = {
                                "depth": depth + 1,
                                "fd": child_metrics["fd"],
                                "actions": [list(a) for a in reconstruct_actions(node, parent, src_a, dst_a, k_a)]
                                + [[src, dst, k]],
                            }
                        continue
                    if child_metrics["fd"] == plateau_fd - 1 and child_metrics["foundations"] == 0:
                        changed = [
                            i for i in range(10) if face_down_signature(state.columns[i]) != parent_sigs[i]
                        ]
                        hit = child_metrics["fd"] == parent_fd - 1 and len(changed) == 1 and parent_sigs[changed[0]] == target
                        rec = {
                            "symmetry_digest": ident.hex(),
                            "ordered_digest": pack_state(state).hex(),
                            "actions": [list(a) for a in reconstruct_actions(node, parent, src_a, dst_a, k_a)]
                            + [[src, dst, k]],
                            "depth": depth + 1,
                            "empties": list(child_metrics["empties"]),
                            "longest_run": child_metrics["longest_run"],
                            "adjacencies": child_metrics["adjacencies"],
                            "blocks": child_metrics["blocks"],
                            "fd": child_metrics["fd"],
                            "reveal_action": [src, dst, k],
                            "hits": 1,
                        }
                        if hit:
                            exits_here += 1
                            if reveal_depth is None:
                                reveal_depth = depth + 1
                            if ident not in target_exits:
                                target_exits[ident] = rec
                            else:
                                target_exits[ident]["hits"] += 1
                        else:
                            off_here += 1
                            if ident not in off_target_exits:
                                off_target_exits[ident] = rec
                            else:
                                off_target_exits[ident]["hits"] += 1
                        continue
                    if child_metrics["fd"] != plateau_fd or child_metrics["foundations"] != 0:
                        continue
                    child_fu = target_face_up_count(state, target)
                    if child_fu is None:
                        continue
                    child_blocks = target_block_count(state, target) or 0
                    min_target_fu = min(min_target_fu, child_fu)
                    min_block_count = min(min_block_count, child_blocks)
                    if ident in ids:
                        duplicate_skips += 1
                        dups_here += 1
                        continue
                    if len(keys) >= max_unique:
                        stop_reason = "unique limit"
                        incomplete = True
                        break
                    child_id = add_node(
                        pack_state(state),
                        ident,
                        node,
                        src,
                        dst,
                        k,
                        depth + 1,
                        child_fu,
                        child_blocks,
                        len(child_metrics["empties"]),
                    )
                    next_ids.append(child_id)
                    for thresh in (4, 3, 2, 1):
                        if child_fu <= thresh and thresh not in fu_records:
                            audit = target_stack_audit(state, target)
                            fu_records[thresh] = {
                                "threshold": thresh,
                                "target_fu": child_fu,
                                "depth": depth + 1,
                                "block_count": child_blocks,
                                "face_up": audit.get("face_up"),
                                "blocks": audit.get("blocks"),
                                "top_block_head": audit.get("top_block_head"),
                                "legal_destinations": audit.get("legal_destinations"),
                                "empty_columns": audit.get("empty_columns"),
                                "actions": [list(a) for a in reconstruct_actions(child_id, parent, src_a, dst_a, k_a)],
                            }
                finally:
                    _restore(state, snap)
            if incomplete or found_foundation:
                break
        fu_hist = Counter()
        for nid in frontier:
            fu_hist[fu_of[nid]] += 1
        n_zero = sum(1 for i in frontier if empty_count_of[i] == 0)
        n_one = sum(1 for i in frontier if empty_count_of[i] == 1)
        n_two = sum(1 for i in frontier if empty_count_of[i] >= 2)
        layer_reports.append(
            {
                "depth": depth,
                "frontier_size": len(frontier),
                "cumulative_unique": len(keys),
                "generated_successors": gen_here,
                "exact_duplicate_skips": dups_here,
                "min_target_fu": min((fu_of[i] for i in frontier), default=min_target_fu),
                "min_block_count": min((blocks_of[i] for i in frontier), default=min_block_count),
                "states_fu5": fu_hist.get(5, 0),
                "states_fu4": fu_hist.get(4, 0),
                "states_fu3": fu_hist.get(3, 0),
                "states_fu2": fu_hist.get(2, 0),
                "states_fu1": fu_hist.get(1, 0),
                "states_empty_0": n_zero,
                "states_empty_1": n_one,
                "states_empty_ge2": n_two,
                "target_exits": exits_here,
                "off_target_exits": off_here,
                "min_fd": min_fd,
                "expanded": not incomplete and not found_foundation,
            }
        )
        if incomplete or found_foundation:
            last_generated = max(last_generated, depth + 1)
            break
        last_expanded = depth
        if next_ids:
            layers_ids.append(next_ids)
            last_generated = depth + 1
        else:
            stop_reason = "frontier empty"
            break
        if depth + 1 in checkpoints:
            print(
                f"CHECKPOINT depth={depth + 1} unique={len(keys)} frontier={len(next_ids)} "
                f"min_fu={min_target_fu} exits={len(target_exits)} min_fd={min_fd}",
                flush=True,
            )
        if reveal_depth is not None:
            stop_reason = "target reveal"
            break

    if last_generated == max_depth and last_generated < len(layers_ids) and last_generated not in {r["depth"] for r in layer_reports}:
        frontier = layers_ids[last_generated]
        fu_hist = Counter()
        for nid in frontier:
            fu_hist[fu_of[nid]] += 1
        layer_reports.append(
            {
                "depth": last_generated,
                "frontier_size": len(frontier),
                "cumulative_unique": len(keys),
                "generated_successors": 0,
                "exact_duplicate_skips": 0,
                "min_target_fu": min((fu_of[i] for i in frontier), default=min_target_fu),
                "min_block_count": min((blocks_of[i] for i in frontier), default=min_block_count),
                "states_fu5": fu_hist.get(5, 0),
                "states_fu4": fu_hist.get(4, 0),
                "states_fu3": fu_hist.get(3, 0),
                "states_fu2": fu_hist.get(2, 0),
                "states_fu1": fu_hist.get(1, 0),
                "states_empty_0": sum(1 for i in frontier if empty_count_of[i] == 0),
                "states_empty_1": sum(1 for i in frontier if empty_count_of[i] == 1),
                "states_empty_ge2": sum(1 for i in frontier if empty_count_of[i] >= 2),
                "target_exits": 0,
                "off_target_exits": 0,
                "min_fd": min_fd,
                "expanded": False,
            }
        )

    def enrich(rec: dict) -> dict:
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
        return rec

    elapsed = time.perf_counter() - started
    return TargetConversionResult(
        unique=len(keys),
        generated=generated,
        duplicate_skips=duplicate_skips,
        completed_generated_depth=last_generated,
        completed_expanded_depth=last_expanded,
        elapsed_s=elapsed,
        peak_rss_mb=peak_rss if peak_rss is not None else _rss_mb(),
        stop_reason=stop_reason,
        min_target_fu=min_target_fu,
        min_block_count=min_block_count,
        min_fd=min_fd,
        target_exits=[enrich(dict(r)) for r in target_exits.values()],
        off_target_exits=[enrich(dict(r)) for r in off_target_exits.values()],
        fu_records=fu_records,
        foundation_witness=foundation_witness,
        fd_le_11_witness=fd_le_11_witness,
        layers=layer_reports,
        expansion_order=expansion_order,
        reveal_depth=reveal_depth,
    )
