"""Research-only v0.25 new-fd13 portfolio conversion.

Multi-source layered BFS of an fd13/foundation-0 plateau.  fd12 children are
terminal boundary exits and are not expanded.  No strategic score.
Not imported by ``solve_progressive``.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from spider.engine import SpiderState
from spider.metrics import Action, replay_actions
from spider.packed_state import pack_state, unpack_state
from spider.rules import MW_RULES, MobilityWareRules
from spider.simple_legacy_fd13_alternatives import legal_tableau_count
from spider.simple_progressive_solver import _capture, _restore, _rss_mb, apply_action
from spider.simple_workspace_reachability import (
    _metrics,
    empty_column_indices,
    engine_tableau_actions,
    face_down_count,
    layered_reachability,
    post_stock_identity,
    reconstruct_actions,
)

KNOWN_DEAD_FD12 = "KNOWN_DEAD_FD12"
NEW_FD12_REGION = "NEW_FD12_REGION"
CURRENT_WATCH = "current_fd13"
EMPTY1_WATCH = "current_empty1"


def as_actions(raw) -> List[Action]:
    out: List[Action] = []
    for item in raw:
        if item == "deal" or item == ["deal"] or item == ("deal",):
            out.append(("deal",))
        else:
            src, dst, k = item
            out.append((int(src), int(dst), int(k)))
    return out


@dataclass
class Fd13PortfolioResult:
    unique: int
    generated: int
    duplicate_skips: int
    expanded: int
    exit_edges: int
    exit_classes: int
    completed_generated_depth: int
    completed_expanded_depth: int
    expansion_order: List[int]
    elapsed_s: float
    peak_rss_mb: Optional[float]
    stop_reason: str
    exhausted: bool
    min_fd: int
    max_foundations: int
    max_empties: int
    max_run: int
    max_adjacencies: int
    max_blocks: int
    source_count: int
    cross_origin_dups: int
    domain_violations: int
    classifier_surprises: int
    watch_hits: Dict[str, int] = field(default_factory=dict)
    first_watch: Dict[str, dict] = field(default_factory=dict)
    layers: List[dict] = field(default_factory=list)
    exits: List[dict] = field(default_factory=list)
    stronger_progress: Optional[dict] = None
    foundation_witness: Optional[dict] = None
    fresh_tt: bool = True
    all_legal_tableau: bool = True
    heuristic: bool = False
    plateau_fd: int = 13


def fd13_portfolio_plateau(
    sources: Sequence[SpiderState],
    *,
    origin_paths: Optional[Sequence[Sequence[Action]]] = None,
    plateau_fd: int = 13,
    identity_fn=None,
    max_depth: int = 12,
    max_unique: int = 1_250_000,
    time_limit_s: float = 1200.0,
    rss_abort_mb: float = 3 * 1024.0,
    rules: MobilityWareRules = MW_RULES,
    watch_identities: Optional[Dict[str, bytes]] = None,
    checkpoints: Sequence[int] = (4, 8, 12),
) -> Fd13PortfolioResult:
    """Layered BFS of the fd13 plateau.  fd12 children are exits, not expanded."""

    if identity_fn is None:
        identity_fn = post_stock_identity
    if not sources:
        raise ValueError("sources is empty")
    source_states = list(sources)
    source_paths: List[List[Action]] = [
        list(p) for p in (origin_paths if origin_paths is not None else [[] for _ in source_states])
    ]
    if len(source_paths) < len(source_states):
        source_paths.extend([] for _ in range(len(source_states) - len(source_paths)))
    for src in source_states:
        if src.stock:
            raise ValueError("portfolio search is post-stock only")
        metrics = _metrics(src)
        if metrics["fd"] != plateau_fd or metrics["foundations"] != 0:
            raise ValueError(
                f"source is fd={metrics['fd']} fnd={metrics['foundations']}, "
                f"expected fd={plateau_fd} fnd=0"
            )

    started = time.perf_counter()
    watches = dict(watch_identities or {})
    ids: Dict[bytes, int] = {}
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
        ids[ident] = node
        keys.append(concrete)
        parent.append(parent_id)
        src_a.append(src)
        dst_a.append(dst)
        k_a.append(k)
        depth_of.append(depth)
        origin_of.append(origin)
        empty_count_of.append(empties)
        return node

    layer0: List[int] = []
    cross_origin_dups = 0
    watch_hits = {name: 0 for name in watches}
    first_watch: Dict[str, dict] = {}
    for origin_id, source in enumerate(source_states):
        ident = identity_fn(source)
        if ident in ids:
            cross_origin_dups += 1
            continue
        metrics = _metrics(source)
        node = add_node(
            pack_state(source),
            ident,
            -1,
            -1,
            -1,
            -1,
            0,
            origin_id,
            len(metrics["empties"]),
        )
        layer0.append(node)
        for name, key in watches.items():
            if ident == key:
                watch_hits[name] += 1
                first_watch.setdefault(
                    name,
                    {"origin": origin_id, "depth": 0, "unique_before": len(keys)},
                )

    generated = 0
    duplicate_skips = 0
    expanded = 0
    exit_edges = 0
    exits: Dict[bytes, dict] = {}
    classifier_surprises = 0
    domain_violations = 0
    expansion_order: List[int] = []
    layer_reports: List[dict] = []
    min_fd = plateau_fd
    max_foundations = 0
    max_empties = max(empty_count_of) if empty_count_of else 0
    max_run = 0
    max_adjacencies = 0
    max_blocks = 0
    peak_rss = _rss_mb()
    stop_reason = "max depth"
    foundation_witness: Optional[dict] = None
    stronger: Optional[dict] = None
    layers: List[List[int]] = [layer0]
    last_expanded = -1
    last_generated = 0
    deadline = started + time_limit_s

    def note_rss() -> bool:
        nonlocal peak_rss
        rss = _rss_mb()
        if rss is not None and (peak_rss is None or rss > peak_rss):
            peak_rss = rss
        return rss_abort_mb is not None and rss is not None and rss >= rss_abort_mb

    found_stop = False
    incomplete = False
    for depth in range(0, max_depth):
        if found_stop:
            break
        if time.perf_counter() >= deadline:
            stop_reason = "time limit"
            incomplete = True
            break
        if note_rss():
            stop_reason = "rss abort"
            incomplete = True
            break
        if depth >= len(layers) or not layers[depth]:
            stop_reason = "frontier empty"
            break
        expansion_order.append(depth)
        frontier = layers[depth]
        next_ids: List[int] = []
        gen_here = 0
        dups_here = 0
        exits_here = 0
        for node in frontier:
            if found_stop:
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
            if face_down_count(state) != plateau_fd or state.foundations or state.stock:
                domain_violations += 1
                continue
            expanded += 1
            actions, surprises = engine_tableau_actions(state, rules=rules)
            classifier_surprises += len(surprises)
            for action in actions:
                src, dst, k = action  # type: ignore[misc]
                snap = _capture(state, action)
                try:
                    apply_action(state, action, rules=rules)
                    generated += 1
                    gen_here += 1
                    child_metrics = _metrics(state)
                    min_fd = min(min_fd, child_metrics["fd"])
                    max_foundations = max(max_foundations, child_metrics["foundations"])
                    max_empties = max(max_empties, len(child_metrics["empties"]))
                    max_run = max(max_run, child_metrics["longest_run"])
                    max_adjacencies = max(max_adjacencies, child_metrics["adjacencies"])
                    max_blocks = max(max_blocks, child_metrics["blocks"])
                    ident = identity_fn(state)
                    local = reconstruct_actions(node, parent, src_a, dst_a, k_a) + [action]
                    if child_metrics["foundations"] >= 1:
                        foundation_witness = {
                            "depth": depth + 1,
                            "fd": child_metrics["fd"],
                            "foundations": child_metrics["foundations"],
                            "actions": [list(a) for a in local],
                            "origin": origin_of[node],
                            "ordered_digest": pack_state(state).hex(),
                            "symmetry_digest": ident.hex(),
                        }
                        stop_reason = "foundation"
                        found_stop = True
                        break
                    if child_metrics["fd"] <= plateau_fd - 2:
                        if stronger is None:
                            stronger = {
                                "depth": depth + 1,
                                "fd": child_metrics["fd"],
                                "foundations": child_metrics["foundations"],
                                "actions": [list(a) for a in local],
                                "origin": origin_of[node],
                                "ordered_digest": pack_state(state).hex(),
                                "symmetry_digest": ident.hex(),
                            }
                        stop_reason = f"fd <= {plateau_fd - 2}"
                        found_stop = True
                        break
                    if child_metrics["fd"] == plateau_fd - 1 and child_metrics["foundations"] == 0:
                        exit_edges += 1
                        exits_here += 1
                        if ident not in exits:
                            exits[ident] = {
                                "symmetry_digest": ident.hex(),
                                "ordered_digest": pack_state(state).hex(),
                                "actions": [list(a) for a in local],
                                "depth": depth + 1,
                                "origin": origin_of[node],
                                "empties": list(child_metrics["empties"]),
                                "longest_run": child_metrics["longest_run"],
                                "adjacencies": child_metrics["adjacencies"],
                                "movable_blocks": child_metrics["blocks"],
                                "legal_action_count": legal_tableau_count(state),
                                "fd": child_metrics["fd"],
                                "foundations": child_metrics["foundations"],
                                "reveal_action": [src, dst, k],
                                "hits": 1,
                            }
                        else:
                            exits[ident]["hits"] += 1
                        continue
                    if child_metrics["fd"] != plateau_fd or child_metrics["foundations"] != 0 or state.stock:
                        domain_violations += 1
                        continue
                    if ident in ids:
                        duplicate_skips += 1
                        dups_here += 1
                        if origin_of[ids[ident]] != origin_of[node]:
                            cross_origin_dups += 1
                        continue
                    if len(keys) >= max_unique:
                        stop_reason = "unique limit"
                        incomplete = True
                        found_stop = True
                        break
                    child_id = add_node(
                        pack_state(state),
                        ident,
                        node,
                        src,
                        dst,
                        k,
                        depth + 1,
                        origin_of[node],
                        len(child_metrics["empties"]),
                    )
                    next_ids.append(child_id)
                    for name, key in watches.items():
                        if ident == key:
                            watch_hits[name] += 1
                            first_watch.setdefault(
                                name,
                                {
                                    "origin": origin_of[node],
                                    "depth": depth + 1,
                                    "unique_before": len(keys),
                                    "expanded_before": expanded,
                                },
                            )
                finally:
                    _restore(state, snap)
            if incomplete or found_stop:
                break
        origins_here = {origin_of[i] for i in frontier}
        layer_reports.append(
            {
                "depth": depth,
                "frontier_size": len(frontier),
                "cumulative_unique": len(keys),
                "generated_successors": gen_here,
                "exact_duplicate_skips": dups_here,
                "exit_edges": exits_here,
                "exit_classes": len(exits),
                "min_fd": min_fd,
                "origins_represented": len(origins_here),
                "expanded": not incomplete and not found_stop,
            }
        )
        if incomplete or found_stop:
            last_generated = max(last_generated, depth + 1)
            break
        last_expanded = depth
        if next_ids:
            layers.append(next_ids)
            last_generated = depth + 1
        else:
            stop_reason = "frontier empty"
            break
        if depth + 1 in checkpoints:
            print(
                f"CHECKPOINT fd13_depth={depth + 1} unique={len(keys)} frontier={len(next_ids)} "
                f"exits={len(exits)} edges={exit_edges} min_fd={min_fd} origins={len(origins_here)}",
                flush=True,
            )
        if depth + 1 >= max_depth:
            stop_reason = "max depth"
            break

    elapsed = time.perf_counter() - started
    exhausted = stop_reason == "frontier empty" and not incomplete and foundation_witness is None
    for rec in exits.values():
        origin = rec["origin"]
        walk = source_states[origin].clone()
        try:
            rec["local_cost"] = replay_actions(walk, as_actions(rec["actions"]))
            rec["replay_ok"] = True
        except (ValueError, AssertionError) as exc:
            rec["local_cost"] = None
            rec["replay_ok"] = False
            rec["replay_error"] = str(exc)

    return Fd13PortfolioResult(
        unique=len(keys),
        generated=generated,
        duplicate_skips=duplicate_skips,
        expanded=expanded,
        exit_edges=exit_edges,
        exit_classes=len(exits),
        completed_generated_depth=last_generated,
        completed_expanded_depth=last_expanded,
        expansion_order=expansion_order,
        elapsed_s=elapsed,
        peak_rss_mb=peak_rss if peak_rss is not None else _rss_mb(),
        stop_reason=stop_reason,
        exhausted=exhausted,
        min_fd=min_fd,
        max_foundations=max_foundations,
        max_empties=max_empties,
        max_run=max_run,
        max_adjacencies=max_adjacencies,
        max_blocks=max_blocks,
        source_count=len(source_states),
        cross_origin_dups=cross_origin_dups,
        domain_violations=domain_violations,
        classifier_surprises=classifier_surprises,
        watch_hits=watch_hits,
        first_watch=first_watch,
        layers=layer_reports,
        exits=list(exits.values()),
        stronger_progress=stronger,
        foundation_witness=foundation_witness,
        plateau_fd=plateau_fd,
    )


def load_dead_hex(path: Path) -> Set[str]:
    members: Set[str] = set()
    if not path.exists():
        return members
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        if line[0] == "{":
            rec = json.loads(line)
            digest = rec.get("symmetry_digest") or rec.get("identity") or rec.get("digest")
            if digest:
                members.add(digest)
        else:
            members.add(line)
    return members


def regenerate_known_dead_fd12(
    fd12_seed: SpiderState,
    extra_sources: Sequence[SpiderState],
    *,
    extra_paths: Optional[Sequence[Sequence[Action]]] = None,
    time_limit_s: float = 400.0,
    rss_abort_mb: float = 3 * 1024.0,
) -> dict:
    """Exact exhausted futures A (v0.12 fd12) and B (v0.19 new fd12 sources)."""

    print("REGEN known-dead A from v0.12 fd12", flush=True)
    a_reach = layered_reachability(
        fd12_seed,
        max_depth=10_000,
        max_unique=100_000,
        time_limit_s=time_limit_s,
        rss_abort_mb=rss_abort_mb,
        identity_fn=post_stock_identity,
        all_legal_tableau=True,
        include_visited_hex=True,
        checkpoints=(8, 16, 32),
    )
    set_a = set(a_reach.visited_identity_hex)
    print(f"A unique={a_reach.unique} stop={a_reach.stop_reason} min_fd={a_reach.min_fd}", flush=True)
    set_b: Set[str] = set()
    b_stop = None
    if extra_sources:
        print(f"REGEN known-dead B from {len(extra_sources)} new fd12 sources", flush=True)
        b_reach = layered_reachability(
            sources=list(extra_sources),
            origin_paths=extra_paths,
            max_depth=10_000,
            max_unique=200_000,
            time_limit_s=time_limit_s,
            rss_abort_mb=rss_abort_mb,
            identity_fn=post_stock_identity,
            all_legal_tableau=True,
            include_visited_hex=True,
            checkpoints=(8, 16, 32),
        )
        set_b = set(b_reach.visited_identity_hex)
        b_stop = b_reach.stop_reason
        print(f"B unique={b_reach.unique} stop={b_reach.stop_reason} min_fd={b_reach.min_fd}", flush=True)
    union = set_a | set_b
    return {
        "set_a": len(set_a),
        "set_b": len(set_b),
        "union": len(union),
        "overlap": len(set_a & set_b),
        "disjoint": len(set_a & set_b) == 0,
        "a_stop": a_reach.stop_reason,
        "b_stop": b_stop,
        "a_min_fd": a_reach.min_fd,
        "a_max_foundations": a_reach.max_foundations,
        "a_exhausted": a_reach.stop_reason == "frontier empty",
        "members": union,
    }


def classify_fd12_exits(exits: Sequence[dict], known_dead: Set[str]) -> List[dict]:
    rows = []
    for rec in exits:
        klass = KNOWN_DEAD_FD12 if rec["symmetry_digest"] in known_dead else NEW_FD12_REGION
        item = dict(rec)
        item["class"] = klass
        rows.append(item)
    return rows
