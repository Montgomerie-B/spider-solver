"""Research-only fd14 plateau boundary search.

Round-robin DFS of the fd14 / foundations-0 / stock-0 plateau.  fd13 children
are recorded as terminal boundary exits and are not expanded.  Duplicate
detection uses post-stock column symmetry.  Concrete ordered representatives
and physical-index paths are retained for replay.

Not imported by ``solve_progressive``.  No strategic score.  Successor order
is engine legal-action order.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from spider.engine import SpiderState
from spider.metrics import Action, replay_actions
from spider.packed_state import pack_state, unpack_state
from spider.rules import MW_RULES, MobilityWareRules
from spider.simple_legacy_fd13_alternatives import (
    legal_tableau_count,
    reveal_target_from_transition,
)
from spider.simple_progressive_solver import _capture, _restore, _rss_mb, apply_action
from spider.simple_target_clearance import face_down_signature, signature_key
from spider.simple_workspace_reachability import (
    _metrics,
    empty_column_indices,
    engine_tableau_actions,
    face_down_count,
    post_stock_identity,
    reconstruct_actions,
)

CURRENT_FD13_EXIT = "CURRENT_FD13_EXIT"
NEW_FD13_EXIT = "NEW_FD13_EXIT"
SLICE_SIZE = 10_000
MAX_UNIQUE = 1_500_000
TIME_LIMIT_S = 1800.0
RSS_ABORT_MB = 3 * 1024.0
MAX_NEW_EXITS = 16
ROTATION_PREFIX = 256


def face_down_column_census(state: SpiderState) -> List[dict]:
    """Telemetry: every face-down-bearing column, identified by exact fd sequence."""

    rows = []
    for index, col in enumerate(state.columns):
        if not col.face_down:
            continue
        sig = face_down_signature(col)
        rows.append(
            {
                "physical_column_0": index,
                "physical_column_1": index + 1,
                "face_down": [[c.suit, int(c.rank)] for c in col.face_down],
                "face_up": [[c.suit, int(c.rank)] for c in col.face_up],
                "fd_count": len(col.face_down),
                "fu_count": len(col.face_up),
                "signature_key": signature_key(sig),
            }
        )
    return rows


def enumerate_root_child_classes(
    seed: SpiderState, *, rules: MobilityWareRules = MW_RULES
) -> dict:
    """Legal root tableau actions grouped by post-stock symmetry class."""

    if seed.stock:
        raise ValueError("fd14 boundary search is post-stock only")
    actions, surprises = engine_tableau_actions(seed, rules=rules)
    classes: List[dict] = []
    by_ident: Dict[bytes, int] = {}
    members: List[list] = []
    for action in actions:
        src, dst, k = action  # type: ignore[misc]
        snap = _capture(seed, action)
        try:
            apply_action(seed, action, rules=rules)
            ident = post_stock_identity(seed)
            ordered = pack_state(seed)
            metrics = _metrics(seed)
            rec = {
                "action": [src, dst, k],
                "ordered_digest": ordered.hex(),
                "symmetry_digest": ident.hex(),
                "fd": metrics["fd"],
                "foundations": metrics["foundations"],
                "empties": list(metrics["empties"]),
                "longest_run": metrics["longest_run"],
            }
        finally:
            _restore(seed, snap)
        if ident in by_ident:
            classes[by_ident[ident]]["equivalent_actions"].append([src, dst, k])
            members[by_ident[ident]].append([src, dst, k])
            continue
        by_ident[ident] = len(classes)
        rec["equivalent_actions"] = [[src, dst, k]]
        rec["class_id"] = len(classes)
        classes.append(rec)
        members.append([[src, dst, k]])
    return {
        "legal_actions": [list(a) for a in actions],  # type: ignore[arg-type]
        "n_legal": len(actions),
        "n_classes": len(classes),
        "classes": classes,
        "classifier_surprises": surprises,
    }


def _reveal_signature(parent: SpiderState, child: SpiderState) -> Optional[str]:
    rec = reveal_target_from_transition(parent, child)
    return rec.get("signature_key")


@dataclass
class Fd14BoundaryResult:
    unique: int
    expanded: int
    generated: int
    duplicate_skips: int
    max_depth: int
    elapsed_s: float
    peak_rss_mb: Optional[float]
    stop_reason: str
    exhausted: bool
    domain_violations: int
    classifier_surprises: int
    root_actions: List[list]
    root_classes: List[dict]
    n_root_classes: int
    rotation_prefix: List[int]
    slice_origins: List[int]
    empty0: int
    empty1: int
    empty_ge2: int
    max_empties: int
    max_run: int
    max_adjacencies: int
    max_blocks: int
    min_fd: int
    max_foundations: int
    exit_edges: int
    exit_classes: int
    current_exit_classes: int
    current_exit_hits: int
    new_exit_classes: int
    first_current: Optional[dict] = None
    first_new: Optional[dict] = None
    exits: List[dict] = field(default_factory=list)
    new_exits: List[dict] = field(default_factory=list)
    per_frontier: List[dict] = field(default_factory=list)
    reveal_target_counts: Dict[str, int] = field(default_factory=dict)
    stronger_progress: Optional[dict] = None
    foundation_witness: Optional[dict] = None
    fresh_tt: bool = True
    all_legal_tableau: bool = True
    heuristic: bool = False
    plateau_fd: int = 14


def fd14_boundary_search(
    seed: SpiderState,
    *,
    current_fd13_symmetry: bytes,
    rules: MobilityWareRules = MW_RULES,
    slice_size: int = SLICE_SIZE,
    max_unique: int = MAX_UNIQUE,
    time_limit_s: float = TIME_LIMIT_S,
    rss_abort_mb: float = RSS_ABORT_MB,
    max_new_exits: int = MAX_NEW_EXITS,
    record_rotation: int = ROTATION_PREFIX,
    plateau_fd: int = 14,
    max_depth: Optional[int] = None,
) -> Fd14BoundaryResult:
    """Round-robin DFS of the fd14 plateau.  Fresh global symmetry seen-set.

    Successors are generated in engine legal-action order and pushed so the
    first engine action is expanded first (standard DFS).  ``max_depth`` is a
    graph-scheduling backtrack cap so a 2000-ply C-move spine cannot starve
    shallower siblings; it is not a Spider heuristic.
    """

    started = time.perf_counter()
    if seed.stock:
        raise ValueError("fd14 boundary search is post-stock only")
    root_concrete = pack_state(seed)
    root_metrics = _metrics(seed)
    if root_metrics["fd"] != plateau_fd or root_metrics["foundations"] != 0:
        raise ValueError(
            f"seed is fd={root_metrics['fd']} fnd={root_metrics['foundations']}, "
            f"expected fd={plateau_fd} fnd=0"
        )

    root_info = enumerate_root_child_classes(seed, rules=rules)
    identity_fn = post_stock_identity
    seen: Dict[bytes, int] = {}

    keys: List[bytes] = []
    parent: List[int] = []
    src_a: List[int] = []
    dst_a: List[int] = []
    k_a: List[int] = []
    depth_of: List[int] = []
    origin_of: List[int] = []
    empty_count_of: List[int] = []

    def add_node(
        concrete: bytes,
        ident: bytes,
        parent_id: int,
        src: int,
        dst: int,
        k: int,
        depth: int,
        origin: int,
        empties: int,
    ) -> int:
        node = len(keys)
        seen[ident] = node
        keys.append(concrete)
        parent.append(parent_id)
        src_a.append(src)
        dst_a.append(dst)
        k_a.append(k)
        depth_of.append(depth)
        origin_of.append(origin)
        empty_count_of.append(empties)
        return node

    stacks: List[List[int]] = []
    per_frontier: List[dict] = []
    add_node(
        root_concrete,
        identity_fn(seed),
        -1,
        -1,
        -1,
        -1,
        0,
        -1,
        len(root_metrics["empties"]),
    )
    for rec in root_info["classes"]:
        if rec["fd"] != plateau_fd or rec["foundations"] != 0:
            continue
        child = unpack_state(bytes.fromhex(rec["ordered_digest"]))
        ident = bytes.fromhex(rec["symmetry_digest"])
        src, dst, k = rec["action"]
        origin = len(stacks)
        node = add_node(
            pack_state(child),
            ident,
            0,
            src,
            dst,
            k,
            1,
            origin,
            len(rec["empties"]),
        )
        stacks.append([node])
        per_frontier.append(
            {
                "class_id": rec["class_id"],
                "root_action": rec["action"],
                "expanded": 0,
                "unique": 1,
                "generated": 0,
                "duplicate_skips": 0,
                "max_depth": 1,
                "exit_edges": 0,
                "current_hits": 0,
                "new_classes": 0,
                "frontier_size": 1,
            }
        )

    # Root children that immediately reveal are handled below via a synthetic expand? 
    # Enumerate them as exits by applying from seed without a frontier.
    immediate_exits = [
        rec
        for rec in root_info["classes"]
        if rec["fd"] < plateau_fd or rec["foundations"] > 0
    ]

    generated = 0
    duplicate_skips = 0
    expanded = 0
    domain_violations = 0
    classifier_surprises = 0
    exit_edges = 0
    exits: Dict[bytes, dict] = {}
    reveal_counts: Dict[str, int] = {}
    first_current: Optional[dict] = None
    first_new: Optional[dict] = None
    stronger: Optional[dict] = None
    foundation: Optional[dict] = None
    rotation_prefix: List[int] = []
    slice_origins: List[int] = []
    min_fd = plateau_fd
    max_foundations = 0
    max_empties = max(empty_count_of) if empty_count_of else 0
    max_run = root_metrics["longest_run"]
    max_adjacencies = root_metrics["adjacencies"]
    max_blocks = root_metrics["blocks"]
    peak_rss = _rss_mb()
    stop_reason = "frontier empty"
    found_new = False
    harvest_origin: Optional[int] = None
    deadline = started + time_limit_s

    def note_rss() -> bool:
        nonlocal peak_rss
        rss = _rss_mb()
        if rss is not None and (peak_rss is None or rss > peak_rss):
            peak_rss = rss
        return rss_abort_mb is not None and rss is not None and rss >= rss_abort_mb

    def local_path(node: int, extra: Optional[Action] = None) -> List[Action]:
        actions = reconstruct_actions(node, parent, src_a, dst_a, k_a)
        if extra is not None:
            actions = list(actions) + [extra]
        return actions

    def record_exit(
        parent_node: int,
        parent_state: SpiderState,
        child_state: SpiderState,
        action: Action,
        ident: bytes,
        metrics: dict,
        origin: int,
    ) -> None:
        nonlocal first_current, first_new, exit_edges
        src, dst, k = action  # type: ignore[misc]
        exit_edges += 1
        per_frontier[origin]["exit_edges"] += 1
        reveal = _reveal_signature(parent_state, child_state) or ""
        reveal_counts[reveal] = reveal_counts.get(reveal, 0) + 1
        is_current = ident == current_fd13_symmetry
        klass = CURRENT_FD13_EXIT if is_current else NEW_FD13_EXIT
        if ident in exits:
            exits[ident]["hits"] += 1
            if is_current:
                per_frontier[origin]["current_hits"] += 1
            return
        depth = depth_of[parent_node] + 1 if parent_node >= 0 else 1
        path = local_path(parent_node, action)
        rec = {
            "class": klass,
            "symmetry_digest": ident.hex(),
            "ordered_digest": pack_state(child_state).hex(),
            "actions": [list(a) for a in path],
            "local_depth": depth,
            "reveal_action": [src, dst, k],
            "reveal_target": reveal,
            "origin": origin,
            "origin_action": list(per_frontier[origin]["root_action"]),
            "fd": metrics["fd"],
            "foundations": metrics["foundations"],
            "empties": list(metrics["empties"]),
            "longest_run": metrics["longest_run"],
            "adjacencies": metrics["adjacencies"],
            "movable_blocks": metrics["blocks"],
            "legal_action_count": legal_tableau_count(child_state),
            "expanded_before": expanded,
            "unique_before": len(keys),
            "hits": 1,
        }
        try:
            walk = unpack_state(root_concrete)
            rec["local_cost"] = replay_actions(walk, path)
            rec["replay_ok"] = True
        except (ValueError, AssertionError) as exc:
            rec["local_cost"] = None
            rec["replay_ok"] = False
            rec["replay_error"] = str(exc)
        exits[ident] = rec
        if is_current:
            per_frontier[origin]["current_hits"] += 1
            if first_current is None:
                first_current = rec
                print(
                    f"CURRENT_EXIT origin={origin} action={rec['origin_action']} "
                    f"depth={depth} expanded={expanded} unique={len(keys)} reveal={reveal}",
                    flush=True,
                )
        else:
            per_frontier[origin]["new_classes"] += 1
            if first_new is None:
                first_new = rec
                print(
                    f"NEW_EXIT origin={origin} action={rec['origin_action']} "
                    f"depth={depth} expanded={expanded} unique={len(keys)} reveal={reveal}",
                    flush=True,
                )

    # Immediate root exits (none expected for the historical fd14 seed).
    for rec in immediate_exits:
        src, dst, k = rec["action"]
        action = (src, dst, k)
        parent_clone = seed.clone()
        snap = _capture(seed, action)
        try:
            apply_action(seed, action, rules=rules)
            ident = post_stock_identity(seed)
            metrics = _metrics(seed)
            min_fd = min(min_fd, metrics["fd"])
            max_foundations = max(max_foundations, metrics["foundations"])
            origin = len(per_frontier)
            per_frontier.append(
                {
                    "class_id": rec["class_id"],
                    "root_action": rec["action"],
                    "expanded": 0,
                    "unique": 0,
                    "generated": 0,
                    "duplicate_skips": 0,
                    "max_depth": 1,
                    "exit_edges": 0,
                    "current_hits": 0,
                    "new_classes": 0,
                    "frontier_size": 0,
                }
            )
            record_exit(0, parent_clone, seed, action, ident, metrics, origin)
            if ident != current_fd13_symmetry and metrics["fd"] == 13:
                found_new = True
                harvest_origin = origin
        finally:
            _restore(seed, snap)

    def expand(node: int, origin: int) -> Optional[str]:
        nonlocal generated, duplicate_skips, domain_violations, classifier_surprises
        nonlocal min_fd, max_foundations, max_empties, max_run, max_adjacencies, max_blocks
        nonlocal stronger, foundation, found_new, harvest_origin, stop_reason
        state = unpack_state(keys[node])
        if (
            face_down_count(state) != plateau_fd
            or len(state.foundations) != 0
            or state.stock
        ):
            domain_violations += 1
            return None
        actions, surprises = engine_tableau_actions(state, rules=rules)
        classifier_surprises += len(surprises)
        per_frontier[origin]["generated"] += len(actions)
        # Push last-to-first so LIFO expands engine order first-to-last.
        for action in reversed(actions):
            src, dst, k = action  # type: ignore[misc]
            snap = _capture(state, action)
            try:
                apply_action(state, action, rules=rules)
                generated += 1
                metrics = _metrics(state)
                min_fd = min(min_fd, metrics["fd"])
                max_foundations = max(max_foundations, metrics["foundations"])
                max_empties = max(max_empties, len(metrics["empties"]))
                max_run = max(max_run, metrics["longest_run"])
                max_adjacencies = max(max_adjacencies, metrics["adjacencies"])
                max_blocks = max(max_blocks, metrics["blocks"])
                ident = identity_fn(state)
                if metrics["foundations"] >= 1:
                    foundation = {
                        "fd": metrics["fd"],
                        "foundations": metrics["foundations"],
                        "actions": [list(a) for a in local_path(node, action)],
                        "ordered_digest": pack_state(state).hex(),
                        "symmetry_digest": ident.hex(),
                        "origin": origin,
                    }
                    stop_reason = "foundation"
                    return "foundation"
                if metrics["fd"] <= plateau_fd - 2:
                    if stronger is None:
                        stronger = {
                            "fd": metrics["fd"],
                            "foundations": metrics["foundations"],
                            "actions": [list(a) for a in local_path(node, action)],
                            "ordered_digest": pack_state(state).hex(),
                            "symmetry_digest": ident.hex(),
                            "origin": origin,
                        }
                    stop_reason = f"fd <= {plateau_fd - 2}"
                    return "stronger"
                if metrics["fd"] == plateau_fd - 1 and metrics["foundations"] == 0:
                    before = unpack_state(keys[node])
                    record_exit(node, before, state, action, ident, metrics, origin)
                    if ident != current_fd13_symmetry:
                        found_new = True
                        harvest_origin = origin
                        if sum(1 for row in exits.values() if row["class"] == NEW_FD13_EXIT) >= max_new_exits:
                            stop_reason = "max_new_exits"
                            return "max_new"
                    continue
                if metrics["fd"] != plateau_fd or metrics["foundations"] != 0 or state.stock:
                    domain_violations += 1
                    continue
                if ident in seen:
                    duplicate_skips += 1
                    per_frontier[origin]["duplicate_skips"] += 1
                    continue
                if max_depth is not None and depth_of[node] + 1 > max_depth:
                    continue
                if len(keys) >= max_unique:
                    stop_reason = "unique limit"
                    return "unique"
                child_id = add_node(
                    pack_state(state),
                    ident,
                    node,
                    src,
                    dst,
                    k,
                    depth_of[node] + 1,
                    origin,
                    len(metrics["empties"]),
                )
                stacks[origin].append(child_id)
                per_frontier[origin]["unique"] += 1
                per_frontier[origin]["max_depth"] = max(
                    per_frontier[origin]["max_depth"], depth_of[node] + 1
                )
            finally:
                _restore(state, snap)
        return None

    # Main round-robin over plateau root-child frontiers.
    while True:
        if found_new and harvest_origin is not None and harvest_origin >= len(stacks):
            stop_reason = "new_exit_slice"
            break
        if time.perf_counter() >= deadline:
            stop_reason = "time limit"
            break
        if note_rss():
            stop_reason = "rss abort"
            break
        live = [i for i, stack in enumerate(stacks) if stack]
        if not live:
            stop_reason = "frontier empty"
            break
        if found_new and harvest_origin is not None:
            live = [harvest_origin] if 0 <= harvest_origin < len(stacks) and stacks[harvest_origin] else []
            if not live:
                if stop_reason not in ("max_new_exits", "foundation", "fd <= 12"):
                    stop_reason = "new_exit_slice"
                break
        halt = None
        for origin in live:
            slice_origins.append(origin)
            slice_exp = 0
            while stacks[origin] and slice_exp < slice_size:
                if time.perf_counter() >= deadline:
                    halt = "time limit"
                    break
                if (expanded & 2047) == 0 and note_rss():
                    halt = "rss abort"
                    break
                if len(keys) >= max_unique:
                    halt = "unique limit"
                    break
                node = stacks[origin].pop()
                expanded += 1
                slice_exp += 1
                per_frontier[origin]["expanded"] += 1
                if len(rotation_prefix) < record_rotation:
                    rotation_prefix.append(origin)
                halt = expand(node, origin)
                if halt:
                    break
            per_frontier[origin]["frontier_size"] = len(stacks[origin])
            if expanded and expanded % 25000 == 0:
                print(
                    f"CHECKPOINT expanded={expanded} unique={len(keys)} generated={generated} "
                    f"dups={duplicate_skips} exits={len(exits)} edges={exit_edges} "
                    f"new={sum(1 for r in exits.values() if r['class']==NEW_FD13_EXIT)} "
                    f"depth={max(depth_of) if depth_of else 0} rss={peak_rss}",
                    flush=True,
                )
            if halt:
                stop_reason = halt
                break
            if found_new:
                if stop_reason not in ("max_new_exits", "foundation", "fd <= 12"):
                    stop_reason = "new_exit_slice"
                halt = stop_reason
                break
        if halt:
            break

    for row, stack in zip(per_frontier, stacks):
        row["frontier_size"] = len(stack)

    empty0 = sum(1 for n in empty_count_of if n == 0)
    empty1 = sum(1 for n in empty_count_of if n == 1)
    empty_ge2 = sum(1 for n in empty_count_of if n >= 2)
    elapsed = time.perf_counter() - started
    new_rows = [row for row in exits.values() if row["class"] == NEW_FD13_EXIT]
    current_rows = [row for row in exits.values() if row["class"] == CURRENT_FD13_EXIT]
    exhausted = stop_reason == "frontier empty" and foundation is None and stronger is None
    max_depth = max(depth_of) if depth_of else 0

    return Fd14BoundaryResult(
        unique=len(keys),
        expanded=expanded,
        generated=generated,
        duplicate_skips=duplicate_skips,
        max_depth=max_depth,
        elapsed_s=elapsed,
        peak_rss_mb=peak_rss if peak_rss is not None else _rss_mb(),
        stop_reason=stop_reason,
        exhausted=exhausted,
        domain_violations=domain_violations,
        classifier_surprises=classifier_surprises,
        root_actions=root_info["legal_actions"],
        root_classes=root_info["classes"],
        n_root_classes=root_info["n_classes"],
        rotation_prefix=rotation_prefix,
        slice_origins=slice_origins,
        empty0=empty0,
        empty1=empty1,
        empty_ge2=empty_ge2,
        max_empties=max_empties,
        max_run=max_run,
        max_adjacencies=max_adjacencies,
        max_blocks=max_blocks,
        min_fd=min_fd,
        max_foundations=max_foundations,
        exit_edges=exit_edges,
        exit_classes=len(exits),
        current_exit_classes=len(current_rows),
        current_exit_hits=sum(r["hits"] for r in current_rows),
        new_exit_classes=len(new_rows),
        first_current=first_current,
        first_new=first_new,
        exits=list(exits.values()),
        new_exits=new_rows,
        per_frontier=per_frontier,
        reveal_target_counts=reveal_counts,
        stronger_progress=stronger,
        foundation_witness=foundation,
        plateau_fd=plateau_fd,
    )
