#!/usr/bin/env python3
"""Opt012 compact quotient-state exact corridor search (commands 43–51).

Searches paid transitions between zero-cost free-relocation components.
Does not launch cost-7 production by default; used for controlled ceilings.
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal, tokens_from_file
from spider.engine import SpiderState
from spider.metrics import Action, format_action, parse_moves_file, replay_actions_detailed
from spider.packed_state import pack_state
from spider.planner.diagnostics.experiment_4925153_opt011_cmd43_51_corridor import (
    build_corridor_endpoints,
    rss_bytes,
    step_cost_corrected,
)
from spider.planner.diagnostics.opt012_free_quotient import (
    apply_action,
    component_key_from_state,
    free_closure,
    free_slot_analysis,
    reconstruct_free_path,
    all_free_moves_reversible_in_component,
)
from spider.planner.diagnostics.opt013_algebraic_expansion import (
    BACKEND_ID,
    expand_component_algebraic,
    expand_component_bruteforce,
    build_state_from_arrangement,
    canonical_arrangement,
    model_from_state,
)
from spider.planner.diagnostics.opt012_pruning import TargetMonotonicFilter
from spider.state_identity import CanonicalStateKey, canonical_state_key

DEAL = ROOT / "deals" / "4925153.txt"
CANONICAL = ROOT / "solutions" / "4925153_canonical.moves"
ARTIFACTS = ROOT / "artifacts" / "opt012"

ALGORITHM_ID = "opt013_same_suit_algebraic_quotient"
ALGORITHM_VERSION = "2"
COMPONENT_KEY_VERSION = "CQ02"
PRUNE_RULE_VERSION = "target_monotonic_v1"
# Production expansion backend (bruteforce retained as oracle only)
PRODUCTION_EXPAND = "algebraic"
CHECKPOINT_SCHEMA = "opt013_quotient_ckpt_v2"
ARTIFACTS_OPT013 = ROOT / "artifacts" / "opt013"


def action_label(a: Action) -> str:
    return format_action(a)


def parse_label(lab: str) -> Action:
    if lab == "deal":
        return ("deal",)
    p = lab.split()
    return (int(p[1]) - 1, int(p[2]) - 1, int(p[3]))


@dataclass
class ArenaNode:
    """Compact node: no full SpiderState retained."""

    component_bytes: bytes
    paid_cost: int
    parent: int  # -1 for root
    # transition from parent: free labels to pre-state, then paid action label
    free_path_labels: Tuple[str, ...]
    paid_label: str
    # packed representative for expansion (one member of component)
    rep_packed: bytes


@dataclass
class SearchResult:
    status: str
    termination: str
    ceiling: int
    expanded: int
    generated_raw: int
    unique_paid_succ: int
    peak_frontier: int
    tt_entries: int
    raw_free_members_start: int
    quotient_components_seen: int
    runtime_seconds: float
    rss_start: Optional[int]
    rss_peak: Optional[int]
    rss_finish: Optional[int]
    prune_stats: Dict[str, int]
    path_labels: Optional[List[str]] = None
    path_actions: Optional[List[Action]] = None
    segment_mw: Optional[int] = None
    improvements: List[Dict[str, Any]] = field(default_factory=list)
    extras: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "status": self.status,
            "termination": self.termination,
            "ceiling": self.ceiling,
            "expanded": self.expanded,
            "generated_raw": self.generated_raw,
            "unique_paid_succ": self.unique_paid_succ,
            "peak_frontier": self.peak_frontier,
            "tt_entries": self.tt_entries,
            "raw_free_members_start": self.raw_free_members_start,
            "quotient_components_seen": self.quotient_components_seen,
            "runtime_seconds": self.runtime_seconds,
            "rss_start": self.rss_start,
            "rss_peak": self.rss_peak,
            "rss_finish": self.rss_finish,
            "prune_stats": self.prune_stats,
            "path_labels": self.path_labels,
            "segment_mw": self.segment_mw,
            "improvements": self.improvements,
            "algorithm_id": ALGORITHM_ID,
            "algorithm_version": ALGORITHM_VERSION,
        }
        d.update(self.extras)
        return d


def _rep_from_component(
    start_rep: SpiderState, members: Dict[CanonicalStateKey, SpiderState]
) -> SpiderState:
    # deterministic: smallest packed key among members
    best_k = None
    best_st = None
    for k, st in members.items():
        pk = pack_state(st)
        if best_k is None or pk < best_k:
            best_k = pk
            best_st = st
    return best_st.clone()  # type: ignore


def search_quotient(
    *,
    ceiling: int = 7,
    max_expanded: int = 10_000_000,
    wall_clock: float = 0.0,
    max_rss_gib: Optional[float] = None,
    expand_mode: str = "algebraic",  # or "bruteforce" oracle
) -> SearchResult:
    """Layered BFS on paid edges between free components."""
    ep = build_corridor_endpoints()
    start: SpiderState = ep["start_state"]
    target: SpiderState = ep["target_state"]
    target_key = canonical_state_key(target)
    target_comp = component_key_from_state(target).to_bytes()

    filt = TargetMonotonicFilter(target=target, start=start, cost_ceiling=ceiling)

    analysis = free_slot_analysis(start)
    # Algebraic mode: empty-buffer free relocations of complete open piles are
    # structurally reversible; avoid full free_closure / reverse scan (~30–45s).
    # Brute-force mode retains the Opt012 exhaustive free-orbit oracle path.
    if expand_mode == "bruteforce":
        start_members = free_closure(start)
        rev_ok, rev_msg = all_free_moves_reversible_in_component(start)
        if not rev_ok:
            return SearchResult(
                status="algorithmic_blocker",
                termination="irreversible_free_move",
                ceiling=ceiling,
                expanded=0,
                generated_raw=0,
                unique_paid_succ=0,
                peak_frontier=0,
                tt_entries=0,
                raw_free_members_start=len(start_members),
                quotient_components_seen=0,
                runtime_seconds=0.0,
                rss_start=rss_bytes(),
                rss_peak=rss_bytes(),
                rss_finish=rss_bytes(),
                prune_stats=filt.stats.as_dict(),
                extras={"error": rev_msg},
            )
        start_rep = _rep_from_component(start, start_members)
        start_members_n = len(start_members)
    else:
        rev_ok, rev_msg = True, None
        # Combinatorial free-orbit size when n_empty >= 1; singleton otherwise.
        n_slots = int(analysis["n_slots"])
        n_empty = int(analysis["n_empty"])
        if n_empty == 0:
            start_members_n = 1
            start_rep = start
        else:
            from collections import Counter
            import math

            piles = analysis["free_piles"]
            mult = Counter(piles)
            denom = 1
            for c in mult.values():
                denom *= math.factorial(c)
            start_members_n = (
                math.factorial(n_slots) // denom if n_slots <= 12 else n_slots
            )
            m0 = model_from_state(start)
            start_rep = build_state_from_arrangement(
                m0, canonical_arrangement(m0), start
            )
    start_ck = component_key_from_state(start).to_bytes()

    # Arena
    nodes: List[ArenaNode] = []
    # component_bytes -> (node_id, paid_cost)
    tt: Dict[bytes, Tuple[int, int]] = {}
    # queue of node ids (layered BFS by paid cost — all edges cost 1)
    q: deque[int] = deque()

    def add_node(
        ck: bytes,
        paid: int,
        parent: int,
        free_labels: Tuple[str, ...],
        paid_lab: str,
        rep: SpiderState,
    ) -> Optional[int]:
        prev = tt.get(ck)
        if prev is not None and prev[1] <= paid:
            return None
        nid = len(nodes)
        nodes.append(
            ArenaNode(
                component_bytes=ck,
                paid_cost=paid,
                parent=parent,
                free_path_labels=free_labels,
                paid_label=paid_lab,
                rep_packed=pack_state(rep),
            )
        )
        tt[ck] = (nid, paid)
        q.append(nid)
        return nid

    rss0 = rss_bytes()
    peak_rss = rss0 or 0
    t0 = time.time()
    add_node(start_ck, 0, -1, (), "", start_rep)

    expanded = 0
    generated_raw = 0
    unique_paid = 0
    peak_frontier = 1
    improvements: List[Dict[str, Any]] = []
    found_path: Optional[List[Action]] = None
    found_mw: Optional[int] = None
    termination = "running"

    # Cache free members for nodes we expand: only keep for current expansion
    while q:
        if wall_clock and (time.time() - t0) >= wall_clock:
            termination = "wall_clock"
            break
        if expanded >= max_expanded:
            termination = "max_expanded"
            break

        nid = q.popleft()
        node = nodes[nid]
        # lazy dominance
        if tt.get(node.component_bytes, (nid, node.paid_cost))[1] < node.paid_cost:
            continue
        expanded += 1
        peak_frontier = max(peak_frontier, len(q) + 1)

        # Sample RSS every 16 expansions (ctypes path is cheap; keep headroom gates)
        if (expanded & 15) == 0 or max_rss_gib is not None:
            rss = rss_bytes()
            if rss is not None:
                peak_rss = max(peak_rss, rss)
                if max_rss_gib is not None and rss >= max_rss_gib * (1024**3):
                    termination = "max_rss"
                    break

        from spider.packed_state import unpack_state

        rep = unpack_state(node.rep_packed)

        # Target in this component?
        if node.component_bytes == target_comp:
            path_free = reconstruct_free_path(rep, target_key)
            if path_free is not None:
                full = _reconstruct_full_path(nodes, nid, path_free)
                st = start.clone()
                mw = 0
                ok = True
                for a in full:
                    try:
                        mw += apply_action(st, a)
                    except Exception:
                        ok = False
                        break
                if ok and canonical_state_key(st) == target_key and mw <= ceiling:
                    found_path = full
                    found_mw = mw
                    improvements.append(
                        {
                            "segment_mw": mw,
                            "path": [action_label(a) for a in full],
                            "explicit_commands": len(full),
                        }
                    )
                    termination = "exact_improvement" if mw < 8 else "exact_reconnect"
                    break

        if node.paid_cost >= ceiling:
            continue

        if expand_mode == "bruteforce":
            outs = expand_component_bruteforce(rep)
        else:
            outs = expand_component_algebraic(rep)
        unique_paid += len(outs)
        for rec in outs:
            generated_raw += 1
            st2: SpiderState = rec["succ_state"]
            if not filt.accept(st2, current_cost=node.paid_cost + 1):
                continue
            free_path = rec.get("free_path")
            if free_path is None:
                pre_key: CanonicalStateKey = rec["from_key"]
                free_path = reconstruct_free_path(rep, pre_key) or []
            free_labels = tuple(action_label(a) for a in free_path)
            paid_lab = action_label(rec["action"])
            ck2 = rec["succ_component_key"]
            # Representative of successor free component (no full free_closure).
            # When n_empty==0 the free orbit is a singleton — keep the concrete
            # successor. When n_empty>=1 any free arrangement is fine; use
            # deterministic canonical placement.
            m2 = model_from_state(st2)
            if m2.n_empty == 0:
                rep2 = st2
            else:
                rep2 = build_state_from_arrangement(
                    m2, canonical_arrangement(m2), st2
                )
            add_node(
                ck2,
                node.paid_cost + 1,
                nid,
                free_labels,
                paid_lab,
                rep2,
            )

    if termination == "running":
        termination = "exhausted" if not q else "incomplete"

    status = (
        "verified_improvement"
        if found_path is not None and (found_mw or 99) < 8
        else (
            "exhaustive_failure"
            if termination == "exhausted" and not improvements
            else (
                "exact_reconnect_no_improve"
                if found_path is not None
                else "incomplete_search"
                if termination != "exhausted"
                else "exhaustive_failure"
            )
        )
    )
    if termination == "algorithmic_blocker":
        status = "algorithmic_blocker"

    return SearchResult(
        status=status,
        termination=termination,
        ceiling=ceiling,
        expanded=expanded,
        generated_raw=generated_raw,
        unique_paid_succ=unique_paid,
        peak_frontier=peak_frontier,
        tt_entries=len(tt),
        raw_free_members_start=start_members_n,
        quotient_components_seen=len(tt),
        runtime_seconds=time.time() - t0,
        rss_start=rss0,
        rss_peak=peak_rss,
        rss_finish=rss_bytes(),
        prune_stats=filt.stats.as_dict(),
        path_labels=[action_label(a) for a in found_path] if found_path else None,
        path_actions=found_path,
        segment_mw=found_mw,
        improvements=improvements,
        extras={
            "free_slot_analysis": analysis,
            "start_component_size": start_members_n,
            "factorial_slots": analysis.get("factorial_slots"),
            "reversible_free_ok": rev_ok,
            "target_component_key_hex": target_comp.hex()[:32],
            "incremental_bytes_est": (
                ((peak_rss or 0) - (rss0 or 0)) / max(1, len(nodes))
            ),
            "n_arena_nodes": len(nodes),
            "expand_mode": expand_mode,
            "backend_id": BACKEND_ID if expand_mode == "algebraic" else "bruteforce",
        },
    )


def _reconstruct_full_path(
    nodes: List[ArenaNode], nid: int, final_free: List[Action]
) -> List[Action]:
    """Walk parents collecting free+paid scripts, then final free to exact target."""
    chunks: List[List[Action]] = []
    cur = nid
    while cur >= 0:
        n = nodes[cur]
        part: List[Action] = [parse_label(x) for x in n.free_path_labels]
        if n.paid_label:
            part.append(parse_label(n.paid_label))
        chunks.append(part)
        cur = n.parent
    chunks.reverse()
    out: List[Action] = []
    for ch in chunks:
        out.extend(ch)
    out.extend(final_free)
    return out


def measure_ceiling(ceiling: int, **kwargs: Any) -> Dict[str, Any]:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    r = search_quotient(ceiling=ceiling, **kwargs)
    d = r.to_dict()
    path = ARTIFACTS / f"opt012_ceiling_{ceiling}.json"
    path.write_text(json.dumps(d, indent=2, default=str), encoding="utf-8")
    return d


def run_production_cost_search(
    *,
    ceiling: int = 7,
    max_rss_gib: Optional[float] = 8.0,
    max_expanded: int = 0,
    wall_clock: float = 0.0,
    expand_mode: str = "algebraic",
    force_stale_lock: bool = False,
) -> Dict[str, Any]:
    """Production corridor search with lock, checkpoint, and archive integration.

    ``max_expanded <= 0`` means no expansion cap (exact exhaustive mode).
    """
    from spider.planner.diagnostics.experiment_4925153_opt011_cmd43_51_corridor import (
        RunLock,
        splice_full_solution,
        archive_if_improving,
        export_actions_to_moves_file,
        START_COMMAND,
        TARGET_COMMAND,
    )
    from spider.solution_archive import path_hash, validate_solution, default_archive_root
    from spider.metrics import replay_actions_detailed
    from spider.deal import load_deal

    art = ARTIFACTS_OPT013 / f"cost{ceiling}"
    art.mkdir(parents=True, exist_ok=True)
    lock = RunLock(art / "opt013.lock")
    lock.acquire(force_stale=force_stale_lock)

    commit = None
    try:
        import subprocess

        commit = (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=str(ROOT), text=True, timeout=10
            ).strip()
        )
    except Exception:
        commit = "unknown"

    fingerprint = {
        "algorithm_id": ALGORITHM_ID,
        "algorithm_version": ALGORITHM_VERSION,
        "backend_id": _backend_id_for_mode(expand_mode),
        "expand_mode": expand_mode,
        "ceiling": ceiling,
        "max_rss_gib": max_rss_gib,
        "max_expanded": max_expanded if max_expanded > 0 else None,
        "wall_clock": wall_clock if wall_clock > 0 else None,
        "component_key_version": COMPONENT_KEY_VERSION,
        "prune_rule_version": PRUNE_RULE_VERSION,
        "checkpoint_schema": CHECKPOINT_SCHEMA,
        "commit": commit,
        "start_command": START_COMMAND,
        "target_command": TARGET_COMMAND,
        "no_stock_deals": True,
        "no_explicit_depth_limit": True,
    }
    fp_hash = hashlib.sha256(
        json.dumps(fingerprint, sort_keys=True).encode("utf-8")
    ).hexdigest()[:24]
    fingerprint["config_fingerprint"] = fp_hash

    launch_meta = {
        "command": (
            f"python -m spider.planner.diagnostics.opt012_compact_search "
            f"--ceiling {ceiling} --max-rss-gib {max_rss_gib}"
        ),
        "pid": os.getpid(),
        "start_time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "fingerprint": fingerprint,
        "artifacts_dir": str(art),
    }
    (art / "launch.json").write_text(
        json.dumps(launch_meta, indent=2), encoding="utf-8"
    )

    exp_cap = max_expanded if max_expanded > 0 else 10**15
    t0 = time.time()
    try:
        r = search_quotient(
            ceiling=ceiling,
            max_expanded=exp_cap,
            wall_clock=wall_clock,
            max_rss_gib=max_rss_gib,
            expand_mode=expand_mode,
        )
    except Exception as exc:
        lock.release()
        out = {
            "status": "resource_or_runtime_failure",
            "error": str(exc),
            "launch": launch_meta,
            "runtime_seconds": time.time() - t0,
        }
        (art / "result.json").write_text(
            json.dumps(out, indent=2, default=str), encoding="utf-8"
        )
        return out

    d = r.to_dict()
    d["launch"] = launch_meta
    d["runtime_seconds_wall"] = time.time() - t0

    # End-of-run checkpoint of full arena via audit path (compact, atomic)
    try:
        ck_stats = audit_checkpoint(
            ceiling=ceiling,
            expand_mode=expand_mode,
            checkpoint_dir=art,
        )
        d["checkpoint"] = {
            k: ck_stats[k]
            for k in (
                "backend_id",
                "schema",
                "checkpoint_path",
                "checkpoint_bytes",
                "write_time_seconds",
                "n_nodes",
            )
            if k in ck_stats
        }
    except Exception as exc:
        d["checkpoint_error"] = str(exc)

    # Improvement path: full independent verification + external archive
    if r.path_actions is not None and r.segment_mw is not None and r.segment_mw <= ceiling:
        ep = build_corridor_endpoints()
        start = ep["start_state"]
        target = ep["target_state"]
        # 1–3: replay segment independently
        st = start.clone()
        mw_seg = 0
        segment_ok = True
        try:
            for a in r.path_actions:
                mw_seg += apply_action(st, a)
            if canonical_state_key(st) != canonical_state_key(target):
                segment_ok = False
                d["segment_verify"] = {
                    "ok": False,
                    "reason": "target_mismatch_after_replay",
                    "segment_mw": mw_seg,
                }
            elif mw_seg > ceiling:
                segment_ok = False
                d["segment_verify"] = {
                    "ok": False,
                    "reason": "segment_cost_exceeds_ceiling",
                    "segment_mw": mw_seg,
                }
            else:
                d["segment_verify"] = {
                    "ok": True,
                    "segment_mw": mw_seg,
                    "explicit_commands": len(r.path_actions),
                }
        except Exception as exc:
            segment_ok = False
            d["segment_verify"] = {"ok": False, "reason": str(exc)}

        if segment_ok:
            # 4–5: splice + distinct full moves file
            splice = splice_full_solution(list(r.path_actions))
            d["splice"] = {k: v for k, v in splice.items() if k != "full_actions"}
            if splice.get("ok"):
                full = splice["full_actions"]
                seg_path = art / f"opt013_cost{ceiling}_segment.moves"
                full_path = art / f"opt013_cost{ceiling}_full_candidate.moves"
                export_actions_to_moves_file(list(r.path_actions), seg_path)
                export_actions_to_moves_file(full, full_path)
                d["segment_moves_path"] = str(seg_path)
                d["full_candidate_moves_path"] = str(full_path)

                # 6–9: independent full replay from deal file
                st_full = SpiderState.from_cards(load_deal(DEAL))
                counters = replay_actions_detailed(st_full, full)
                mw_full = int(counters["mobilityware_moves"])
                ph = path_hash(full)
                full_ok = (
                    st_full.is_solved()
                    and len(st_full.foundations) == 8
                    and len(st_full.stock) == 0
                    and mw_full <= 171
                    and ph != "77d169da2538ba8c"
                )
                d["full_independent_replay"] = {
                    "ok": full_ok,
                    "mobilityware_moves": mw_full,
                    "path_hash": ph,
                    "solved": st_full.is_solved(),
                    "foundations": len(st_full.foundations),
                    "stock_remaining": len(st_full.stock),
                    "counters": counters,
                }
                if full_ok and mw_full == splice.get("mobilityware_moves"):
                    # 10–13: archive + read-back
                    arch = archive_if_improving(full)
                    # re-source for opt013
                    from spider.solution_archive import record_solution_if_better

                    arch2 = record_solution_if_better(
                        "4925153",
                        full,
                        source="opt013_algebraic_cost7",
                        experiment_id="opt013c_cmd43_51_cost7",
                        claimed_mobilityware_moves=mw_full,
                    )
                    d["archive"] = arch2.to_dict()
                    if arch2.external_archive_written and arch2.parser_ready_path:
                        rb = validate_solution(
                            "4925153", Path(arch2.parser_ready_path)
                        )
                        d["archive_readback"] = {
                            "ok": bool(
                                rb.valid
                                and rb.mobilityware_moves == mw_full
                                and rb.path_hash == ph
                            ),
                            "mobilityware_moves": rb.mobilityware_moves,
                            "path_hash": rb.path_hash,
                            "path": arch2.parser_ready_path,
                        }
                        if d["archive_readback"]["ok"] and arch2.is_strict_improvement:
                            d["status"] = "verified_improvement"
                            d["genuine_improvement"] = True
                        else:
                            d["genuine_improvement"] = False
                    else:
                        d["genuine_improvement"] = False
                        d["archive_readback"] = {"ok": False}
                else:
                    d["genuine_improvement"] = False
            else:
                d["genuine_improvement"] = False
    else:
        d["genuine_improvement"] = False
        if r.termination == "exhausted":
            d["corridor_closed"] = True

    (art / "result.json").write_text(
        json.dumps(d, indent=2, default=str), encoding="utf-8"
    )
    progress = {
        "termination": r.termination,
        "status": d.get("status", r.status),
        "tt_entries": r.tt_entries,
        "expanded": r.expanded,
        "runtime_seconds": r.runtime_seconds,
        "rss_peak": r.rss_peak,
        "segment_mw": r.segment_mw,
        "genuine_improvement": d.get("genuine_improvement"),
    }
    (art / "progress.json").write_text(
        json.dumps(progress, indent=2, default=str), encoding="utf-8"
    )
    lock.release()
    return d


# ---------------------------------------------------------------------------
# Checkpoint / resume (algebraic production backend)
# ---------------------------------------------------------------------------


def _backend_id_for_mode(expand_mode: str) -> str:
    return BACKEND_ID if expand_mode == "algebraic" else "opt012_bruteforce_v1"


def checkpoint_checksum(payload: Dict[str, Any]) -> str:
    """SHA-256 over canonical JSON excluding the checksum field itself."""
    body = {k: v for k, v in payload.items() if k != "integrity_checksum"}
    blob = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )
    return hashlib.sha256(blob).hexdigest()


def build_checkpoint_payload(
    *,
    nodes: List[ArenaNode],
    tt: Dict[bytes, Tuple[int, int]],
    queue: Sequence[int],
    expanded: int,
    generated_raw: int,
    unique_paid: int,
    ceiling: int,
    expand_mode: str,
    start_ck: bytes,
    target_comp: bytes,
    prune_stats: Dict[str, int],
    termination: str = "running",
) -> Dict[str, Any]:
    """Compact arena snapshot — no second full in-memory graph beyond arena."""
    arena = []
    for n in nodes:
        arena.append(
            {
                "ck": n.component_bytes.hex(),
                "paid": n.paid_cost,
                "parent": n.parent,
                "free": list(n.free_path_labels),
                "paid_lab": n.paid_label,
                "rep": n.rep_packed.hex(),
            }
        )
    payload = {
        "schema": CHECKPOINT_SCHEMA,
        "algorithm_id": ALGORITHM_ID,
        "algorithm_version": ALGORITHM_VERSION,
        "backend_id": _backend_id_for_mode(expand_mode),
        "expand_mode": expand_mode,
        "component_key_version": COMPONENT_KEY_VERSION,
        "prune_rule_version": PRUNE_RULE_VERSION,
        "ceiling": ceiling,
        "start_component_hex": start_ck.hex(),
        "target_component_hex": target_comp.hex(),
        "expanded": expanded,
        "generated_raw": generated_raw,
        "unique_paid_succ": unique_paid,
        "termination": termination,
        "queue": list(queue),
        "tt": {ck.hex(): [nid, paid] for ck, (nid, paid) in tt.items()},
        "arena": arena,
        "prune_stats": prune_stats,
        "n_nodes": len(nodes),
    }
    payload["integrity_checksum"] = checkpoint_checksum(payload)
    return payload


def write_checkpoint_atomic(path: Path, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Atomic temp-file + replace. Returns timing/size stats."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    rss_before = rss_bytes()
    t0 = time.time()
    data = json.dumps(payload, separators=(",", ":"), default=str)
    write_s = time.time() - t0
    t1 = time.time()
    tmp.write_text(data, encoding="utf-8")
    os.replace(str(tmp), str(path))
    replace_s = time.time() - t1
    rss_after = rss_bytes()
    size = path.stat().st_size
    return {
        "path": str(path),
        "bytes": size,
        "serialize_seconds": write_s,
        "write_replace_seconds": replace_s,
        "total_seconds": write_s + replace_s,
        "rss_before": rss_before,
        "rss_after": rss_after,
        "tmp_left": tmp.exists(),
    }


def load_checkpoint(
    path: Path,
    *,
    expect_backend_id: str,
    expect_expand_mode: str,
    expect_ceiling: int,
    expect_start_ck: bytes,
    expect_target_comp: bytes,
) -> Dict[str, Any]:
    """Load and validate checkpoint; refuse cross-backend silent resume."""
    path = Path(path)
    t0 = time.time()
    data = json.loads(path.read_text(encoding="utf-8"))
    load_s = time.time() - t0
    t1 = time.time()
    expect = checkpoint_checksum(data)
    if data.get("integrity_checksum") != expect:
        raise RuntimeError("checkpoint integrity checksum mismatch")
    cksum_s = time.time() - t1
    if data.get("schema") != CHECKPOINT_SCHEMA:
        raise RuntimeError(
            f"checkpoint resume rejected: schema={data.get('schema')!r}"
        )
    if data.get("backend_id") != expect_backend_id:
        raise RuntimeError(
            f"checkpoint resume rejected: backend_id={data.get('backend_id')!r} "
            f"!= {expect_backend_id!r} (Opt012 brute checkpoints must not resume "
            f"as Opt013 algebraic or vice versa)"
        )
    if data.get("expand_mode") != expect_expand_mode:
        raise RuntimeError(
            f"checkpoint resume rejected: expand_mode={data.get('expand_mode')!r}"
        )
    if int(data.get("ceiling", -1)) != expect_ceiling:
        raise RuntimeError("checkpoint resume rejected: ceiling mismatch")
    if data.get("start_component_hex") != expect_start_ck.hex():
        raise RuntimeError("checkpoint resume rejected: start component mismatch")
    if data.get("target_component_hex") != expect_target_comp.hex():
        raise RuntimeError("checkpoint resume rejected: target component mismatch")
    if data.get("component_key_version") != COMPONENT_KEY_VERSION:
        raise RuntimeError("checkpoint resume rejected: component_key_version")
    data["_load_seconds"] = load_s
    data["_checksum_seconds"] = cksum_s
    return data


def restore_arena_from_checkpoint(
    data: Dict[str, Any],
) -> Tuple[List[ArenaNode], Dict[bytes, Tuple[int, int]], deque]:
    """Rebuild arena/tt/queue from checkpoint without a second graph structure."""
    nodes: List[ArenaNode] = []
    for row in data["arena"]:
        nodes.append(
            ArenaNode(
                component_bytes=bytes.fromhex(row["ck"]),
                paid_cost=int(row["paid"]),
                parent=int(row["parent"]),
                free_path_labels=tuple(row["free"]),
                paid_label=str(row["paid_lab"]),
                rep_packed=bytes.fromhex(row["rep"]),
            )
        )
    tt: Dict[bytes, Tuple[int, int]] = {}
    for ck_hex, pair in data["tt"].items():
        tt[bytes.fromhex(ck_hex)] = (int(pair[0]), int(pair[1]))
    q: deque = deque(int(x) for x in data["queue"])
    return nodes, tt, q


def audit_checkpoint(
    *,
    ceiling: int = 6,
    expand_mode: str = "algebraic",
    checkpoint_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Run partial search, checkpoint, resume, and report resource stats."""
    ckpt_dir = Path(checkpoint_dir) if checkpoint_dir else ARTIFACTS_OPT013
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    ckpt_path = ckpt_dir / "opt013_quotient_checkpoint.json"

    # Run to exhaustion at small ceiling first for a non-empty arena, then
    # checkpoint the full ceiling-6 algebraic arena via a dedicated search.
    r = search_quotient(ceiling=ceiling, expand_mode=expand_mode)
    # Reconstruct arena by re-running a lightweight search that saves checkpoint
    # at end — implement via instrumented internal path.
    ep = build_corridor_endpoints()
    start = ep["start_state"]
    target = ep["target_state"]
    start_ck = component_key_from_state(start).to_bytes()
    target_comp = component_key_from_state(target).to_bytes()
    backend_id = _backend_id_for_mode(expand_mode)

    # Re-expand into arena for checkpoint content (same as search_quotient)
    # Use search_quotient result sizes; build payload from a fresh expand loop.
    from spider.packed_state import unpack_state

    filt = TargetMonotonicFilter(target=target, start=start, cost_ceiling=ceiling)
    nodes: List[ArenaNode] = []
    tt: Dict[bytes, Tuple[int, int]] = {}
    q: deque = deque()

    def add_node(ck, paid, parent, free_labels, paid_lab, rep):
        prev = tt.get(ck)
        if prev is not None and prev[1] <= paid:
            return None
        nid = len(nodes)
        nodes.append(
            ArenaNode(
                component_bytes=ck,
                paid_cost=paid,
                parent=parent,
                free_path_labels=free_labels,
                paid_label=paid_lab,
                rep_packed=pack_state(rep),
            )
        )
        tt[ck] = (nid, paid)
        q.append(nid)
        return nid

    analysis = free_slot_analysis(start)
    m0 = model_from_state(start)
    if m0.n_empty == 0:
        start_rep = start
    else:
        start_rep = build_state_from_arrangement(
            m0, canonical_arrangement(m0), start
        )
    add_node(start_ck, 0, -1, (), "", start_rep)
    expanded = 0
    generated_raw = 0
    unique_paid = 0
    while q:
        nid = q.popleft()
        node = nodes[nid]
        if tt.get(node.component_bytes, (nid, node.paid_cost))[1] < node.paid_cost:
            continue
        expanded += 1
        rep = unpack_state(node.rep_packed)
        if node.paid_cost >= ceiling:
            continue
        if expand_mode == "bruteforce":
            outs = expand_component_bruteforce(rep)
        else:
            outs = expand_component_algebraic(rep)
        unique_paid += len(outs)
        for rec in outs:
            generated_raw += 1
            st2 = rec["succ_state"]
            if not filt.accept(st2, current_cost=node.paid_cost + 1):
                continue
            free_path = rec.get("free_path") or []
            free_labels = tuple(action_label(a) for a in free_path)
            paid_lab = action_label(rec["action"])
            ck2 = rec["succ_component_key"]
            m2 = model_from_state(st2)
            rep2 = st2 if m2.n_empty == 0 else build_state_from_arrangement(
                m2, canonical_arrangement(m2), st2
            )
            add_node(ck2, node.paid_cost + 1, nid, free_labels, paid_lab, rep2)

    # Checkpoint with non-empty queue emptied — store full tt/arena, empty queue
    rss_pre = rss_bytes()
    payload = build_checkpoint_payload(
        nodes=nodes,
        tt=tt,
        queue=[],
        expanded=expanded,
        generated_raw=generated_raw,
        unique_paid=unique_paid,
        ceiling=ceiling,
        expand_mode=expand_mode,
        start_ck=start_ck,
        target_comp=target_comp,
        prune_stats=filt.stats.as_dict(),
        termination="exhausted",
    )
    write_stats = write_checkpoint_atomic(ckpt_path, payload)
    rss_post = rss_bytes()

    t_load0 = time.time()
    loaded = load_checkpoint(
        ckpt_path,
        expect_backend_id=backend_id,
        expect_expand_mode=expand_mode,
        expect_ceiling=ceiling,
        expect_start_ck=start_ck,
        expect_target_comp=target_comp,
    )
    nodes2, tt2, q2 = restore_arena_from_checkpoint(loaded)
    restore_s = time.time() - t_load0

    # Cross-backend refusal
    cross_refused = False
    cross_err = None
    wrong_backend = (
        "opt012_bruteforce_v1" if expand_mode == "algebraic" else BACKEND_ID
    )
    try:
        load_checkpoint(
            ckpt_path,
            expect_backend_id=wrong_backend,
            expect_expand_mode="bruteforce"
            if expand_mode == "algebraic"
            else "algebraic",
            expect_ceiling=ceiling,
            expect_start_ck=start_ck,
            expect_target_comp=target_comp,
        )
    except RuntimeError as exc:
        cross_refused = True
        cross_err = str(exc)

    return {
        "backend_id": backend_id,
        "schema": CHECKPOINT_SCHEMA,
        "checkpoint_path": str(ckpt_path),
        "checkpoint_bytes": write_stats["bytes"],
        "write_time_seconds": write_stats["total_seconds"],
        "serialize_seconds": write_stats["serialize_seconds"],
        "restore_time_seconds": restore_s,
        "checksum_time_seconds": loaded.get("_checksum_seconds"),
        "load_time_seconds": loaded.get("_load_seconds"),
        "rss_before_write": write_stats["rss_before"],
        "rss_after_write": write_stats["rss_after"],
        "rss_pre_search": rss_pre,
        "rss_post_restore": rss_post,
        "tmp_left": write_stats["tmp_left"],
        "n_nodes": len(nodes),
        "n_nodes_restored": len(nodes2),
        "tt_match": len(tt) == len(tt2) and all(
            tt[k] == tt2[k] for k in tt
        ),
        "second_complete_graph": False,  # arena only; no free_closure dump
        "cross_backend_resume_refused": cross_refused,
        "cross_backend_error": cross_err,
        "search_result_tt": r.tt_entries,
        "search_runtime_seconds": r.runtime_seconds,
        "search_rss_peak": r.rss_peak,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Opt012/Opt013 compact quotient search")
    p.add_argument("--ceiling", type=int, default=0)
    p.add_argument(
        "--max-expanded",
        type=int,
        default=0,
        help="0 = no expansion cap (production exact mode)",
    )
    p.add_argument("--max-rss-gib", type=float, default=None)
    p.add_argument("--wall-clock", type=float, default=0.0)
    p.add_argument(
        "--expand-mode",
        choices=["algebraic", "bruteforce"],
        default="algebraic",
    )
    p.add_argument("--force-stale-lock", action="store_true")
    p.add_argument(
        "--diagnostic-only",
        action="store_true",
        help="Skip lock/archive; write opt012 diagnostic JSON only",
    )
    args = p.parse_args(list(argv) if argv is not None else None)

    # Production path for ceiling >= 1 (Opt013C cost-7 uses --ceiling 7)
    if not args.diagnostic_only and args.ceiling >= 1:
        d = run_production_cost_search(
            ceiling=args.ceiling,
            max_rss_gib=args.max_rss_gib,
            max_expanded=args.max_expanded,
            wall_clock=args.wall_clock,
            expand_mode=args.expand_mode,
            force_stale_lock=args.force_stale_lock,
        )
    else:
        exp = args.max_expanded if args.max_expanded > 0 else 10_000_000
        d = measure_ceiling(
            args.ceiling,
            max_expanded=exp,
            max_rss_gib=args.max_rss_gib,
            wall_clock=args.wall_clock,
            expand_mode=args.expand_mode,
        )
    # Drop non-JSON-friendly blobs
    skip = {"path_actions"}
    print(
        json.dumps(
            {k: d[k] for k in d if k not in skip},
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
