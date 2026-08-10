#!/usr/bin/env python3
"""Opt011A — exact micro-corridor scan (commands 43–51), deal 4925153.

Two modes
---------
* ``exact`` (default, correctness mode): complete enumeration of all states
  reachable with corrected segment ``mobilityware_moves <= 7`` and no stock
  deals, via 0–1 BFS. **No explicit-depth cutoff.** May report
  exhaustive failure only when the frontier empties under this cost ceiling.

* ``bounded`` (diagnostic): optional explicit-depth bound (e.g. 24). May find
  candidates but **must never** claim corridor exhaustion. Label:

      bounded scan: corrected cost <= 7, explicit depth <= 24

Metric is hard-locked to corrected ``mobilityware_moves``. ``legacy_mw`` cannot
be selected. Hybrid adapter orders successors within an equal-cost class only;
it does not change the reachable set, costs, or dominance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Deque, Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal, tokens_from_file
from spider.deal_analysis import build_deal_analysis
from spider.engine import SpiderState
from spider.hash import zobrist
from spider.metrics import (
    CANONICAL_MOBILITYWARE_MOVES,
    Action,
    export_actions_to_moves_file,
    format_action,
    parse_moves_file,
    replay_actions_detailed,
)
from spider.planner.diagnostics.experimental_move_ordering import (
    ADAPTER_ID,
    HYBRID_TOP_K,
    rank_moves_for_stage,
    reset_ordering_stats,
)
from spider.planner.diagnostics.stage_classifier import classify_stage
from spider.rules import deal_cost, mobilityware_move_cost
from spider.solution_archive import path_hash as archive_path_hash
from spider.solution_archive import record_solution_if_better, validate_solution
from spider.state_identity import (
    CanonicalStateKey,
    CollisionSafeTT,
    canonical_state_key,
    states_structurally_equal as structural_eq,
)

# ---------------------------------------------------------------------------
# Identity / versions
# ---------------------------------------------------------------------------

DEAL = ROOT / "deals" / "4925153.txt"
CANONICAL = ROOT / "solutions" / "4925153_canonical.moves"
ARTIFACTS = ROOT / "artifacts" / "opt011"
RUNTIME_DIR = (
    ROOT / "src/spider/planner/diagnostics/checkpoints/runtime_opt011"
)
EXP_DIR = ROOT / "src/spider/planner/diagnostics/experiments"

DEAL_ID = "4925153"
EXPERIMENT_ID = "4925153_opt011_cmd43_51_corridor"
ALGORITHM_ID = "opt011_exact_01bfs"
ALGORITHM_VERSION = "3"  # collision-safe structural TT keys
CHECKPOINT_SCHEMA_VERSION = 3
ORDERING_MODE = "hybrid_adapter"
OPTIMISATION_METRIC = "mobilityware_moves"
LEGACY_METRIC_FORBIDDEN = "legacy_mw"

START_COMMAND = 42
TARGET_COMMAND = 51
CANONICAL_CORRIDOR_EXPLICIT = 9
CANONICAL_CORRIDOR_MW = 8
SUCCESS_MW_CEILING = 7
SEED = 4_925_153_043_051

MODE_EXACT = "exact"
MODE_BOUNDED = "bounded"
BOUNDED_LABEL = "bounded scan: corrected cost <= 7, explicit depth <= 24"

LOCK_FILENAME = "opt011.lock"
CHECKPOINT_NAME = "opt011_checkpoint.json"
PROGRESS_NAME = "opt011_progress.jsonl"

CANONICAL_SEGMENT_LABELS = [
    "move 1 9 1",
    "move 1 5 1",
    "move 8 1 6",
    "move 9 8 1",
    "move 5 9 9",
    "move 5 9 1",
    "move 10 5 1",
    "move 8 10 1",
    "move 1 8 7",
]


# ---------------------------------------------------------------------------
# Small pure 0–1 graph search (unit-testable completeness primitive)
# ---------------------------------------------------------------------------


def exact_01_bfs(
    *,
    start: Any,
    is_goal: Callable[[Any], bool],
    successors: Callable[[Any], Iterable[Tuple[Any, int, Any]]],
    cost_ceiling: int,
) -> Dict[str, Any]:
    """Complete 0–1 BFS over non-negative integer edge costs in {0, 1}.

    ``successors(state)`` yields ``(next_state, edge_cost, edge_label)``.
    States must be hashable. Returns first optimal path to a goal under the
    ceiling, or exhaustion info. Completeness holds for all goals reachable
    with total cost ``<= cost_ceiling``; there is **no** explicit-depth bound.
    """
    if cost_ceiling < 0:
        raise ValueError("cost_ceiling must be >= 0")

    best: Dict[Any, int] = {start: 0}
    parent: Dict[Any, Tuple[Any, Any]] = {}
    dq: Deque[Any] = deque([start])
    expanded = generated = 0
    goal_state = None

    while dq:
        u = dq.popleft()
        cu = best[u]
        expanded += 1
        if is_goal(u):
            goal_state = u
            break
        for v, e, lab in successors(u):
            if e not in (0, 1):
                raise ValueError(f"edge cost must be 0 or 1, got {e}")
            nv = cu + e
            if nv > cost_ceiling:
                continue
            generated += 1
            prev = best.get(v)
            if prev is not None and prev <= nv:
                continue  # higher or equal cost / zero-cost cycle
            best[v] = nv
            parent[v] = (u, lab)
            if e == 0:
                dq.appendleft(v)
            else:
                dq.append(v)

    path_labels: List[Any] = []
    if goal_state is not None:
        cur = goal_state
        while cur in parent:
            p, lab = parent[cur]
            path_labels.append(lab)
            cur = p
        path_labels.reverse()

    return {
        "found": goal_state is not None,
        "goal": goal_state,
        "cost": best.get(goal_state) if goal_state is not None else None,
        "path_labels": path_labels,
        "expanded": expanded,
        "generated": generated,
        "states_seen": len(best),
        "exhausted": goal_state is None and len(dq) == 0,
        "best": best,
    }


# ---------------------------------------------------------------------------
# Spider helpers
# ---------------------------------------------------------------------------


def sw_of(st: SpiderState) -> int:
    return sum(len(c.face_up) for c in st.columns if c.face_down)


def spaces_of(st: SpiderState) -> int:
    return sum(1 for c in st.columns if c.is_empty())


def apply_action(st: SpiderState, a: Action) -> int:
    if a == ("deal",):
        return st.deal()
    s, d, k = a  # type: ignore
    return st.move(s, d, k)


def step_cost_corrected(st: SpiderState, a: Action) -> int:
    if a == ("deal",):
        return deal_cost()
    s, d, k = a  # type: ignore
    return mobilityware_move_cost(
        cards_moved=k,
        source_face_up_count=len(st.columns[s].face_up),
        dest_was_empty=st.columns[d].is_empty(),
        source_face_down_count=len(st.columns[s].face_down),
    )


def action_label(a: Action) -> str:
    return format_action(a)


def parse_label(lab: str) -> Action:
    if lab == "deal":
        return ("deal",)
    p = lab.split()
    return (int(p[1]) - 1, int(p[2]) - 1, int(p[3]))


def path_hash(actions: Sequence[Action]) -> str:
    return archive_path_hash(actions)


def state_fingerprint(st: SpiderState) -> str:
    parts: List[str] = []
    for col in st.columns:
        fd = ",".join(f"{c.rank}{c.suit}" for c in col.face_down)
        fu = ",".join(f"{c.rank}{c.suit}" for c in col.face_up)
        parts.append(f"{fd}|{fu}")
    found = sorted(tuple(f"{c.rank}{c.suit}" for c in seq) for seq in st.foundations)
    stock = ",".join(f"{c.rank}{c.suit}" for c in st.stock)
    payload = "\n".join(parts) + "\nF:" + repr(found) + "\nS:" + stock
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def states_structurally_equal(a: SpiderState, b: SpiderState) -> bool:
    """Exact structural equality via collision-safe canonical keys."""
    return structural_eq(a, b)


def states_exactly_equal(a: SpiderState, b: SpiderState) -> bool:
    """Exact identity: structural equality required. Zobrist alone is never enough."""
    return states_structurally_equal(a, b)


def order_moves_hybrid_complete(st: SpiderState, analysis) -> List[Action]:
    """Hybrid ranks preference; full legal set is always retained (no deals)."""
    profile = classify_stage(
        state=st,
        scaffold_context={
            "foundations": len(st.foundations),
            "stock_remaining": len(st.stock) // 10,
            "sw": sw_of(st),
            "spaces": spaces_of(st),
        },
    )
    res = rank_moves_for_stage(
        st,
        stage_profile=profile,
        context={
            "analysis": analysis,
            "teacher_move": None,
            "ordering_mode": ORDERING_MODE,
            "cheap_expansion": True,
            "full_integrity": False,
            "hot_path": True,
            "suppress_explanations": True,
            "suppress_hot_path_warnings": True,
            "use_order_cache": True,
            "use_feature_cache": True,
            "deals": max(0, 5 - len(st.stock) // 10),
        },
    )
    ordered: List[Action] = []
    seen = set()
    for lab in res.ordered_moves:
        try:
            a = parse_label(lab)
        except Exception:
            continue
        if a == ("deal",) or a in seen:
            continue
        seen.add(a)
        ordered.append(a)
    for a in st.enumerate_moves():
        if a not in seen:
            seen.add(a)
            ordered.append(a)
    return ordered


def order_moves_engine_only(st: SpiderState, analysis=None) -> List[Action]:
    """Deterministic engine order (no hybrid) — same reachable set."""
    return list(st.enumerate_moves())


# ---------------------------------------------------------------------------
# Corridor endpoints
# ---------------------------------------------------------------------------


def load_canonical_actions() -> List[Action]:
    return parse_moves_file(CANONICAL)


def replay_prefix(actions: Sequence[Action], n: int) -> Tuple[SpiderState, Dict[str, int]]:
    st = SpiderState.from_cards(load_deal(DEAL))
    counters = replay_actions_detailed(st, list(actions[:n]))
    return st, counters


def build_corridor_endpoints() -> Dict[str, Any]:
    actions = load_canonical_actions()
    assert len(actions) == 174
    start_st, start_c = replay_prefix(actions, START_COMMAND)
    target_st, target_c = replay_prefix(actions, TARGET_COMMAND)
    segment = list(actions[START_COMMAND:TARGET_COMMAND])
    assert len(segment) == CANONICAL_CORRIDOR_EXPLICIT
    seg_mw = int(target_c["mobilityware_moves"]) - int(start_c["mobilityware_moves"])
    assert seg_mw == CANONICAL_CORRIDOR_MW

    st = start_st.clone()
    per_cmd: List[Dict[str, Any]] = []
    for i, a in enumerate(segment):
        cost = step_cost_corrected(st, a)
        s, d, k = a  # type: ignore
        fd = len(st.columns[s].face_down)
        fu = len(st.columns[s].face_up)
        empty = st.columns[d].is_empty()
        apply_action(st, a)
        per_cmd.append(
            {
                "command": START_COMMAND + 1 + i,
                "label": action_label(a),
                "mobilityware_cost": cost,
                "source_face_up": fu,
                "source_face_down": fd,
                "dest_was_empty": empty,
                "paid_reveal": cost == 1 and empty and fd > 0,
                "zero_cost_full_column": cost == 0,
            }
        )
    assert states_exactly_equal(st, target_st)
    return {
        "actions": actions,
        "segment": segment,
        "segment_labels": [action_label(a) for a in segment],
        "start": {
            "command_index": START_COMMAND,
            "mobilityware_moves": int(start_c["mobilityware_moves"]),
            "explicit_commands": int(start_c["explicit_commands"]),
            "z": zobrist(start_st),
            "z_hex": format(zobrist(start_st), "x"),
            "fingerprint": state_fingerprint(start_st),
            "foundations": len(start_st.foundations),
            "stock": len(start_st.stock),
            "sw": sw_of(start_st),
            "spaces": spaces_of(start_st),
            "counters": start_c,
        },
        "target": {
            "command_index": TARGET_COMMAND,
            "mobilityware_moves": int(target_c["mobilityware_moves"]),
            "explicit_commands": int(target_c["explicit_commands"]),
            "z": zobrist(target_st),
            "z_hex": format(zobrist(target_st), "x"),
            "fingerprint": state_fingerprint(target_st),
            "foundations": len(target_st.foundations),
            "stock": len(target_st.stock),
            "sw": sw_of(target_st),
            "spaces": spaces_of(target_st),
            "counters": target_c,
        },
        "canonical_corridor_mw": seg_mw,
        "canonical_corridor_explicit": len(segment),
        "per_command_costs": per_cmd,
        "success_mw_ceiling": SUCCESS_MW_CEILING,
        "start_state": start_st,
        "target_state": target_st,
    }


# ---------------------------------------------------------------------------
# Lock / RSS / atomic IO
# ---------------------------------------------------------------------------


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            SYNCHRONIZE = 0x00100000
            handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        else:
            os.kill(pid, 0)
            return True
    except Exception:
        return False


class RunLock:
    """Single-writer lock for Opt011 runtime directory."""

    def __init__(self, runtime_dir: Path, *, owner: str = "opt011") -> None:
        self.runtime_dir = Path(runtime_dir)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.runtime_dir / LOCK_FILENAME
        self.owner = owner
        self.held = False

    def acquire(self, *, force_stale: bool = False) -> None:
        if self.held:
            return
        payload = {
            "pid": os.getpid(),
            "owner": self.owner,
            "lock_token": f"{os.getpid()}-{id(self)}",
            "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "experiment_id": EXPERIMENT_ID,
        }
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                opid = int(data.get("pid") or 0)
            except Exception as exc:
                raise RuntimeError(
                    f"corrupt lock file {self.path}: {exc}; "
                    "remove explicitly after diagnosing"
                ) from exc
            # Existing lock file means another acquisition (same or other process).
            if _pid_alive(opid):
                raise RuntimeError(
                    f"Opt011 lock held by live PID {opid} ({self.path}). "
                    "Refuse second writer."
                )
            if not force_stale:
                raise RuntimeError(
                    f"stale Opt011 lock from dead PID {opid} at {self.path}. "
                    "Pass force_stale=True / --force-stale-lock after confirming."
                )
            # explicit stale recovery
            self.path.unlink(missing_ok=True)
        tmp = self.path.with_suffix(".lock.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)
        self.held = True

    def release(self) -> None:
        if not self.held:
            return
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if int(data.get("pid") or 0) == os.getpid():
                    self.path.unlink(missing_ok=True)
        except Exception:
            pass
        self.held = False

    def __enter__(self) -> "RunLock":
        self.acquire()
        return self

    def __exit__(self, *args: Any) -> None:
        self.release()


_RSS_GETTER = None  # cached callable for fast repeated RSS samples


def _make_rss_getter():
    try:
        import psutil  # type: ignore

        proc = psutil.Process(os.getpid())
        return lambda: int(proc.memory_info().rss)
    except Exception:
        pass
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
                _fields_ = [
                    ("cb", ctypes.c_ulong),
                    ("PageFaultCount", ctypes.c_ulong),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                    ("PrivateUsage", ctypes.c_size_t),
                ]

            psapi = ctypes.WinDLL("psapi")
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            gpm = psapi.GetProcessMemoryInfo
            gpm.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(PROCESS_MEMORY_COUNTERS_EX),
                wintypes.DWORD,
            ]
            gpm.restype = wintypes.BOOL
            handle = kernel32.GetCurrentProcess()
            size = ctypes.sizeof(PROCESS_MEMORY_COUNTERS_EX)

            def _ctypes_rss() -> int:
                counters = PROCESS_MEMORY_COUNTERS_EX()
                counters.cb = size
                if not gpm(handle, ctypes.byref(counters), size):
                    raise OSError("GetProcessMemoryInfo failed")
                return int(counters.WorkingSetSize)

            # probe once
            _ctypes_rss()
            return _ctypes_rss
        except Exception:
            pass
    try:
        import resource  # type: ignore

        # Linux: ru_maxrss is KiB; macOS: bytes. Report peak-ish value.
        def _res_rss() -> int:
            r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            return int(r * 1024) if r < 10**9 else int(r)

        return _res_rss
    except Exception:
        pass
    return None


def rss_bytes() -> Optional[int]:
    """Current process RSS in bytes. Prefer fast local APIs; avoid PowerShell."""
    global _RSS_GETTER
    if _RSS_GETTER is None:
        _RSS_GETTER = _make_rss_getter()
        if _RSS_GETTER is None:
            _RSS_GETTER = False  # type: ignore
    if _RSS_GETTER is False or _RSS_GETTER is None:
        return None
    try:
        return int(_RSS_GETTER())  # type: ignore
    except Exception:
        return None




def atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    text = json.dumps(data, indent=2, default=str)
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def checkpoint_checksum(payload: Dict[str, Any]) -> str:
    body = {k: v for k, v in payload.items() if k != "integrity_checksum"}
    blob = json.dumps(body, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


# ---------------------------------------------------------------------------
# Search nodes
# ---------------------------------------------------------------------------


@dataclass
class SearchNode:
    state: SpiderState
    mw: int
    depth: int  # explicit commands (diagnostic only in exact mode)
    path: List[Action]
    z: int  # Zobrist for progress/metrics only — not TT identity
    key: CanonicalStateKey


def reference_dijkstra_exact(
    *,
    start: SpiderState,
    is_goal: Callable[[SpiderState], bool],
    successors: Callable[[SpiderState], Iterable[Tuple[SpiderState, int, Any]]],
    cost_ceiling: int,
) -> Dict[str, Any]:
    """Independent Dijkstra on structural keys — test reference only."""
    import heapq

    start_k = canonical_state_key(start)
    best: Dict[CanonicalStateKey, int] = {start_k: 0}
    # store one representative state per key for goal check
    rep: Dict[CanonicalStateKey, SpiderState] = {start_k: start}
    heap: List[Tuple[int, int, CanonicalStateKey]] = []
    seq = 0
    heapq.heappush(heap, (0, seq, start_k))
    expanded = generated = 0
    goal_key = None
    while heap:
        c, _, k = heapq.heappop(heap)
        if c != best.get(k):
            continue
        expanded += 1
        st = rep[k]
        if is_goal(st):
            goal_key = k
            break
        for st2, e, _lab in successors(st):
            if e not in (0, 1):
                raise ValueError(e)
            nc = c + e
            if nc > cost_ceiling:
                continue
            generated += 1
            k2 = canonical_state_key(st2)
            prev = best.get(k2)
            if prev is not None and prev <= nc:
                continue
            best[k2] = nc
            rep[k2] = st2
            seq += 1
            heapq.heappush(heap, (nc, seq, k2))
    return {
        "found": goal_key is not None,
        "cost": best.get(goal_key) if goal_key is not None else None,
        "expanded": expanded,
        "generated": generated,
        "states_seen": len(best),
        "exhausted": goal_key is None and not heap,
        "best": best,
    }


def config_identity(
    *,
    mode: str,
    success_ceiling: int,
    max_depth: Optional[int],
    start_z: int,
    target_z: int,
) -> str:
    payload = {
        "algorithm_id": ALGORITHM_ID,
        "algorithm_version": ALGORITHM_VERSION,
        "schema": CHECKPOINT_SCHEMA_VERSION,
        "deal_id": DEAL_ID,
        "experiment_id": EXPERIMENT_ID,
        "mode": mode,
        "metric": OPTIMISATION_METRIC,
        "ordering_mode": ORDERING_MODE,
        "adapter_id": ADAPTER_ID,
        "hybrid_top_k": dict(HYBRID_TOP_K),
        "success_ceiling": success_ceiling,
        "max_depth": max_depth,
        "stock_deals_allowed": False,
        "start_z": start_z,
        "target_z": target_z,
        "seed": SEED,
    }
    blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:24]


# ---------------------------------------------------------------------------
# Exact / bounded search
# ---------------------------------------------------------------------------


def search_corridor(
    *,
    mode: str = MODE_EXACT,
    analysis=None,
    max_expanded: int = 5_000_000,
    success_ceiling: int = SUCCESS_MW_CEILING,
    max_depth: Optional[int] = None,
    wall_clock: float = 0.0,
    max_rss_gib: Optional[float] = None,
    checkpoint_rss_headroom_gib: float = 0.5,
    enable_checkpoint: bool = True,
    checkpoint_dir: Optional[Path] = None,
    progress_path: Optional[Path] = None,
    resume: bool = False,
    force_stale_lock: bool = False,
    use_hybrid_ordering: bool = True,
    runtime_dir: Optional[Path] = None,
    hash_fn: Optional[Callable[[CanonicalStateKey], int]] = None,
) -> Dict[str, Any]:
    """Run corridor search.

    ``mode=exact``: 0–1 BFS, no depth cutoff (max_depth ignored unless mode=bounded).
    ``mode=bounded``: depth-limited diagnostic; never reports exhaustive_failure.

    Transposition uses ``CollisionSafeTT`` / structural ``CanonicalStateKey``.
    Bare Zobrist is never a TT identity. ``hash_fn`` is test-only for forced collisions.
    """
    assert OPTIMISATION_METRIC == "mobilityware_moves"
    if mode not in (MODE_EXACT, MODE_BOUNDED):
        raise ValueError(f"unknown mode {mode}")

    if mode == MODE_EXACT:
        active_max_depth: Optional[int] = None  # correctness: no depth bound
    else:
        active_max_depth = max_depth if max_depth is not None else 24

    reset_ordering_stats()
    if analysis is None:
        analysis = build_deal_analysis(tokens_from_file(DEAL))

    ep = build_corridor_endpoints()
    start_st: SpiderState = ep["start_state"]
    target_st: SpiderState = ep["target_state"]
    target_z = int(ep["target"]["z"])
    target_fp = ep["target"]["fingerprint"]
    start_z = int(ep["start"]["z"])
    target_key = canonical_state_key(target_st)
    start_key = canonical_state_key(start_st)

    rt = Path(runtime_dir) if runtime_dir else RUNTIME_DIR
    art = ARTIFACTS
    art.mkdir(parents=True, exist_ok=True)
    rt.mkdir(parents=True, exist_ok=True)
    ckpt_path = (Path(checkpoint_dir) if checkpoint_dir else art) / CHECKPOINT_NAME
    prog_path = progress_path or (art / PROGRESS_NAME)

    lock = RunLock(rt)
    lock.acquire(force_stale=force_stale_lock)

    ident = config_identity(
        mode=mode,
        success_ceiling=success_ceiling,
        max_depth=active_max_depth,
        start_z=start_z,
        target_z=target_z,
    )

    order_fn = order_moves_hybrid_complete if use_hybrid_ordering else order_moves_engine_only

    t0 = time.time()
    # Collision-safe TT: structural keys only (Zobrist never dominates)
    tt = CollisionSafeTT(hash_fn=hash_fn)
    expanded = generated = 0
    peak_frontier = peak_tt = 1
    termination = "running"
    improvements: List[Dict[str, Any]] = []
    best_near: Optional[Dict[str, Any]] = None
    cost_hist: Counter = Counter()
    last_ckpt = time.time()
    last_progress = 0.0
    peak_rss = rss_bytes() or 0
    rss_start = peak_rss

    # 0-1 BFS deque of SearchNode
    dq: Deque[SearchNode] = deque()

    def is_target(st: SpiderState) -> bool:
        # Structural exact match only — Zobrist equality alone is insufficient
        return canonical_state_key(st) == target_key

    def target_distance(st: SpiderState) -> Tuple[int, ...]:
        return (
            0 if is_target(st) else 1,
            abs(len(st.foundations) - len(target_st.foundations)),
            abs(len(st.stock) - len(target_st.stock)),
            abs(sw_of(st) - sw_of(target_st)),
            abs(spaces_of(st) - spaces_of(target_st)),
            abs(
                sum(len(c.face_up) for c in st.columns)
                - sum(len(c.face_up) for c in target_st.columns)
            ),
        )

    def push_node(n: SearchNode, edge_cost: int) -> None:
        # 0–1 BFS: zero-cost edges to the front, unit-cost to the back
        if edge_cost == 0:
            dq.appendleft(n)
        else:
            dq.append(n)

    def serialize_frontier_iter():
        """Yield frontier records without building a second full state graph."""
        for n in dq:
            yield {
                "mw": n.mw,
                "depth": n.depth,
                "z": n.z,
                "key": n.key.to_jsonable(),
                "path": [action_label(a) for a in n.path],
            }

    def write_checkpoint(term: str) -> Path:
        # Build payload using TT serializable rows (list of key/cost). This is the
        # retained set once; we do not clone SpiderState graphs for TT.
        frontier_list = list(serialize_frontier_iter())
        tt_list = tt.to_serializable()
        payload = {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "algorithm_id": ALGORITHM_ID,
            "algorithm_version": ALGORITHM_VERSION,
            "tt_identity": "canonical_structural_key_v1",
            "experiment_id": EXPERIMENT_ID,
            "deal_id": DEAL_ID,
            "mode": mode,
            "mode_label": BOUNDED_LABEL if mode == MODE_BOUNDED else "exact cost-complete",
            "config_identity": ident,
            "ordering_mode": ORDERING_MODE,
            "adapter_id": ADAPTER_ID,
            "hybrid_top_k": dict(HYBRID_TOP_K),
            "metric": OPTIMISATION_METRIC,
            "success_ceiling": success_ceiling,
            "max_depth": active_max_depth,
            "stock_deals_allowed": False,
            "start_z": start_z,
            "start_z_hex": format(start_z, "x"),
            "start_fingerprint": ep["start"]["fingerprint"],
            "start_key": start_key.to_jsonable(),
            "target_z": target_z,
            "target_z_hex": format(target_z, "x"),
            "target_fingerprint": target_fp,
            "target_key": target_key.to_jsonable(),
            "seed": SEED,
            "expanded": expanded,
            "generated": generated,
            "termination": term,
            "frontier": frontier_list,
            "transposition": tt_list,
            "best_near": (
                {
                    **{k: (list(v) if isinstance(v, tuple) else v) for k, v in best_near.items()},
                }
                if best_near
                else None
            ),
            "best_near_mw": best_near["mw"] if best_near else None,
            "cost_hist": {str(k): v for k, v in cost_hist.items()},
            "written_at": time.time(),
            "runtime_seconds": time.time() - t0,
            "peak_rss_bytes": peak_rss,
        }
        # Checksum over payload without materializing a second full copy of states
        payload["integrity_checksum"] = checkpoint_checksum(payload)
        atomic_write_json(ckpt_path, payload)
        atomic_write_json(rt / CHECKPOINT_NAME, payload)
        return ckpt_path

    def load_checkpoint() -> Optional[Dict[str, Any]]:
        if not ckpt_path.is_file():
            alt = rt / CHECKPOINT_NAME
            if not alt.is_file():
                return None
            path = alt
        else:
            path = ckpt_path
        data = json.loads(path.read_text(encoding="utf-8"))
        got = data.get("integrity_checksum")
        expect = checkpoint_checksum(data)
        if got and got != expect:
            raise RuntimeError("checkpoint integrity checksum mismatch")
        required = {
            "algorithm_id": ALGORITHM_ID,
            "algorithm_version": ALGORITHM_VERSION,
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "deal_id": DEAL_ID,
            "metric": OPTIMISATION_METRIC,
            "config_identity": ident,
            "tt_identity": "canonical_structural_key_v1",
        }
        for k, v in required.items():
            if data.get(k) != v:
                raise RuntimeError(
                    f"checkpoint resume rejected: {k}={data.get(k)!r} != {v!r}"
                )
        if data.get("success_ceiling") != success_ceiling:
            raise RuntimeError("checkpoint resume rejected: success_ceiling mismatch")
        if int(data.get("start_z") or 0) != start_z:
            raise RuntimeError("checkpoint resume rejected: start hash mismatch")
        if int(data.get("target_z") or 0) != target_z:
            raise RuntimeError("checkpoint resume rejected: target hash mismatch")
        if data.get("metric") == LEGACY_METRIC_FORBIDDEN:
            raise RuntimeError("checkpoint resume rejected: legacy_mw metric")
        if data.get("adapter_id") != ADAPTER_ID:
            raise RuntimeError("checkpoint resume rejected: adapter_id mismatch")
        if data.get("hybrid_top_k") != dict(HYBRID_TOP_K):
            raise RuntimeError("checkpoint resume rejected: HYBRID_TOP_K mismatch")
        return data

    def restore_from_checkpoint(data: Dict[str, Any]) -> None:
        nonlocal expanded, generated, best_near, tt
        expanded = int(data.get("expanded") or 0)
        generated = int(data.get("generated") or 0)
        tt = CollisionSafeTT.from_serializable(
            data.get("transposition") or [], hash_fn=hash_fn
        )
        bn = data.get("best_near")
        if isinstance(bn, dict) and bn:
            best_near = dict(bn)
            if isinstance(best_near.get("dist"), list):
                best_near["dist"] = tuple(best_near["dist"])
            if "mw" in best_near:
                best_near["mw"] = int(best_near["mw"])
        restored: List[SearchNode] = []
        for rec in data.get("frontier") or []:
            path = [parse_label(x) for x in rec.get("path") or []]
            st = start_st.clone()
            mw = 0
            ok = True
            for a in path:
                if a == ("deal",):
                    ok = False
                    break
                try:
                    mw += apply_action(st, a)
                except Exception:
                    ok = False
                    break
            if not ok or mw != int(rec.get("mw") or -1):
                continue
            key = canonical_state_key(st)
            if rec.get("key"):
                # Prefer stored structural key when present
                try:
                    key = CanonicalStateKey.from_jsonable(rec["key"])
                except Exception:
                    pass
            restored.append(
                SearchNode(st, mw, len(path), path, zobrist(st), key)
            )
        restored.sort(key=lambda n: (n.mw, n.depth, n.z))
        for n in restored:
            dq.append(n)

    try:
        if resume:
            data = load_checkpoint()
            if data is None:
                raise RuntimeError("resume requested but no checkpoint found")
            restore_from_checkpoint(data)
            if not dq and not improvements:
                if mode == MODE_EXACT:
                    termination = "exhausted"
                else:
                    termination = "bounded_incomplete"
        else:
            z0 = zobrist(start_st)
            tt.store(start_key, 0)
            dq.append(SearchNode(start_st.clone(), 0, 0, [], z0, start_key))
            if prog_path:
                prog_path.parent.mkdir(parents=True, exist_ok=True)
                prog_path.write_text("", encoding="utf-8")

        def emit_progress(force: bool = False) -> None:
            nonlocal last_progress, peak_rss
            now = time.time()
            if not force and (now - last_progress) < 2.0:
                return
            last_progress = now
            rss = rss_bytes()
            if rss is not None:
                peak_rss = max(peak_rss, rss)
            row = {
                "t": round(now - t0, 3),
                "mode": mode,
                "expanded": expanded,
                "generated": generated,
                "frontier": len(dq),
                "transposition": len(tt),
                "best_target_distance": best_near["dist"] if best_near else None,
                "best_near_mw": best_near["mw"] if best_near else None,
                "best_near_exact": best_near.get("exact") if best_near else None,
                "corrected_cost_distribution": dict(cost_hist),
                "peak_frontier": peak_frontier,
                "peak_tt": peak_tt,
                "improvements": len(improvements),
                "rss_bytes": rss,
            }
            if prog_path:
                prog_path.parent.mkdir(parents=True, exist_ok=True)
                with open(prog_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(row, default=str) + "\n")
            print(
                f"  [opt011 {mode}] exp={expanded} fr={len(dq)} tt={len(tt)} "
                f"near_mw={row['best_near_mw']} t={row['t']:.1f}s",
                flush=True,
            )

        while dq:
            now = time.time()
            if wall_clock and (now - t0) >= wall_clock:
                termination = "wall_clock"
                break
            if expanded >= max_expanded:
                termination = "max_expanded"
                break
            if max_rss_gib is not None:
                rss = rss_bytes()
                if rss is None:
                    raise RuntimeError(
                        "--max-rss-gib set but RSS cannot be measured on this platform"
                    )
                peak_rss = max(peak_rss, rss)
                # Stop before hard ceiling so checkpoint serialization has headroom
                stop_at = (max_rss_gib - checkpoint_rss_headroom_gib) * (1024**3)
                if stop_at < 0:
                    stop_at = max_rss_gib * (1024**3)
                if rss >= stop_at:
                    termination = "max_rss"
                    break

            node = dq.popleft()
            # Lazy dominance on structural key
            bc = tt.get(node.key)
            if bc is not None and bc < node.mw:
                continue
            expanded += 1
            cost_hist[node.mw] += 1
            peak_frontier = max(peak_frontier, len(dq) + 1)
            peak_tt = max(peak_tt, len(tt))

            dist = target_distance(node.state)
            near = {
                "mw": node.mw,
                "depth": node.depth,
                "dist": dist,
                "z": node.z,
                "exact": is_target(node.state),
                "path_labels": [action_label(a) for a in node.path],
            }
            if best_near is None or dist < tuple(best_near["dist"]) or (
                dist == tuple(best_near["dist"]) and node.mw < best_near["mw"]
            ):
                best_near = near

            if is_target(node.state):
                # independent replay
                st_chk = start_st.clone()
                mw_chk = 0
                ok = True
                for a in node.path:
                    if a == ("deal",):
                        ok = False
                        break
                    try:
                        mw_chk += apply_action(st_chk, a)
                    except Exception:
                        ok = False
                        break
                if (
                    ok
                    and states_exactly_equal(st_chk, target_st)
                    and mw_chk == node.mw
                    and state_fingerprint(st_chk) == target_fp
                    and node.mw <= success_ceiling
                ):
                    improvements.append(
                        {
                            "segment_mw": node.mw,
                            "canonical_mw": CANONICAL_CORRIDOR_MW,
                            "saving": CANONICAL_CORRIDOR_MW - node.mw,
                            "explicit_commands": node.depth,
                            "path": [action_label(a) for a in node.path],
                            "path_actions": list(node.path),
                            "path_hash": path_hash(node.path),
                            "independent_replay_ok": True,
                        }
                    )
                    termination = "exact_improvement"
                    break
                continue

            if node.mw > success_ceiling:
                continue
            if active_max_depth is not None and node.depth >= active_max_depth:
                continue

            try:
                ordered = order_fn(node.state, analysis)
            except Exception:
                ordered = list(node.state.enumerate_moves())

            for a in ordered:
                if a == ("deal",):
                    continue
                try:
                    cost = step_cost_corrected(node.state, a)
                except Exception:
                    continue
                if cost not in (0, 1):
                    # corrected MW is always 0 or 1 for legal tableau moves
                    continue
                new_mw = node.mw + cost
                if new_mw > success_ceiling:
                    continue
                if active_max_depth is not None and node.depth + 1 > active_max_depth:
                    continue
                st2 = node.state.clone()
                try:
                    got = apply_action(st2, a)
                except Exception:
                    continue
                if got != cost:
                    new_mw = node.mw + got
                    if new_mw > success_ceiling:
                        continue
                    cost = got
                generated += 1
                z2 = zobrist(st2)
                key2 = canonical_state_key(st2)
                # Structural dominance only — never Zobrist-alone
                if not tt.store(key2, new_mw):
                    continue
                child = SearchNode(
                    state=st2,
                    mw=new_mw,
                    depth=node.depth + 1,
                    path=node.path + [a],
                    z=z2,
                    key=key2,
                )
                push_node(child, cost)

            if enable_checkpoint and (time.time() - last_ckpt) >= 300.0:
                write_checkpoint(termination)
                last_ckpt = time.time()
            if expanded % 500 == 0:
                emit_progress()

        if termination == "running":
            if not dq:
                if mode == MODE_EXACT:
                    termination = "exhausted"
                else:
                    # bounded must never claim exhaustion of the unrestricted corridor
                    termination = "bounded_frontier_empty"
            else:
                termination = "incomplete"

        if enable_checkpoint:
            write_checkpoint(termination)
        emit_progress(force=True)

        status = (
            "verified_improvement"
            if improvements
            else (
                "exhaustive_failure"
                if termination == "exhausted" and mode == MODE_EXACT
                else "incomplete_search"
            )
        )
        # bounded never exhaustive_failure
        if mode == MODE_BOUNDED and status == "exhaustive_failure":
            status = "incomplete_search"

        runtime = time.time() - t0
        return {
            "experiment_id": EXPERIMENT_ID,
            "deal_id": DEAL_ID,
            "mode": mode,
            "mode_label": BOUNDED_LABEL if mode == MODE_BOUNDED else "exact cost-complete 0-1 BFS",
            "algorithm_id": ALGORITHM_ID,
            "algorithm_version": ALGORITHM_VERSION,
            "tt_identity": "canonical_structural_key_v1",
            "zobrist_alone_is_tt_identity": False,
            "optimisation_metric": OPTIMISATION_METRIC,
            "legacy_mw_used_for_search": False,
            "rss_start_bytes": rss_start,
            "rss_peak_bytes": peak_rss,
            "rss_finish_bytes": rss_bytes(),
            "ordering_mode": ORDERING_MODE,
            "adapter_id": ADAPTER_ID,
            "use_hybrid_ordering": use_hybrid_ordering,
            "seed": SEED,
            "config_identity": ident,
            "success_mw_ceiling": success_ceiling,
            "max_depth_active": active_max_depth,
            "exact_mode_has_depth_cutoff": mode == MODE_EXACT and active_max_depth is not None,
            "start": {k: v for k, v in ep["start"].items() if k != "counters"},
            "target": {k: v for k, v in ep["target"].items() if k != "counters"},
            "canonical_corridor_mw": CANONICAL_CORRIDOR_MW,
            "canonical_corridor_explicit": CANONICAL_CORRIDOR_EXPLICIT,
            "per_command_costs": ep["per_command_costs"],
            "termination": termination,
            "status": status,
            "expanded": expanded,
            "generated": generated,
            "runtime_seconds": runtime,
            "expansions_per_sec": (expanded / runtime) if runtime > 0 else 0.0,
            "peak_frontier": peak_frontier,
            "peak_tt": peak_tt,
            "final_frontier": len(dq),
            "final_tt": len(tt),
            "corrected_cost_distribution": dict(cost_hist),
            "best_near": best_near,
            "improvements": [
                {k: v for k, v in r.items() if k != "path_actions"} for r in improvements
            ],
            "improvement_raw": improvements,
            "checkpoint_path": str(ckpt_path),
            "completeness_claim": (
                "complete for corrected cost <= ceiling, no stock deals, exact start/target"
                if mode == MODE_EXACT and termination == "exhausted"
                else (
                    "bounded scan incomplete for unrestricted cost<=7"
                    if mode == MODE_BOUNDED
                    else "incomplete"
                )
            ),
        }
    finally:
        lock.release()


# ---------------------------------------------------------------------------
# Splice / archive
# ---------------------------------------------------------------------------


def splice_full_solution(shortcut: List[Action]) -> Dict[str, Any]:
    actions = load_canonical_actions()
    full = list(actions[:START_COMMAND]) + list(shortcut) + list(actions[TARGET_COMMAND:])
    st = SpiderState.from_cards(load_deal(DEAL))
    try:
        counters = replay_actions_detailed(st, full)
    except Exception as exc:
        return {"ok": False, "failure_reason": str(exc), "full_actions": full}
    mw = int(counters["mobilityware_moves"])
    ok = (
        st.is_solved()
        and len(st.foundations) == 8
        and len(st.stock) == 0
        and mw <= 171
        and mw < CANONICAL_MOBILITYWARE_MOVES
    )
    return {
        "ok": ok,
        "solved": st.is_solved(),
        "foundations": len(st.foundations),
        "stock_remaining": len(st.stock),
        "mobilityware_moves": mw,
        "path_hash": path_hash(full),
        "full_actions": full,
        "counters": counters,
    }


def archive_if_improving(
    full_actions: List[Action], *, archive_root: Optional[Path] = None
) -> Dict[str, Any]:
    r = record_solution_if_better(
        DEAL_ID,
        full_actions,
        source="opt011_cmd43_51_corridor",
        experiment_id=EXPERIMENT_ID,
        archive_root=archive_root,
        claimed_mobilityware_moves=None,
    )
    out = r.to_dict()
    if r.external_archive_written and r.parser_ready_path:
        rb = validate_solution(DEAL_ID, Path(r.parser_ready_path))
        out["readback_ok"] = bool(
            rb.valid
            and rb.mobilityware_moves == r.candidate_mobilityware_moves
            and rb.path_hash == r.path_hash
        )
    else:
        out["readback_ok"] = False
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Opt011A exact/bounded corridor scan")
    p.add_argument("--mode", choices=[MODE_EXACT, MODE_BOUNDED], default=MODE_EXACT)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--max-expanded", type=int, default=5_000_000)
    p.add_argument("--max-depth", type=int, default=None, help="Only for --mode bounded")
    p.add_argument("--wall-clock", type=float, default=0.0)
    p.add_argument("--max-rss-gib", type=float, default=None)
    p.add_argument("--success-ceiling", type=int, default=SUCCESS_MW_CEILING)
    p.add_argument(
        "--metric",
        choices=["mobilityware_moves"],
        default="mobilityware_moves",
    )
    p.add_argument("--no-checkpoint", action="store_true")
    p.add_argument("--force-stale-lock", action="store_true")
    p.add_argument("--no-hybrid", action="store_true")
    p.add_argument("--smoke", action="store_true")
    args = p.parse_args(list(argv) if argv is not None else None)

    if args.metric != OPTIMISATION_METRIC:
        print("FATAL: only mobilityware_moves allowed", file=sys.stderr)
        return 2
    if os.environ.get("SPIDER_OPT_METRIC") == "legacy_mw":
        print("FATAL: legacy_mw forbidden", file=sys.stderr)
        return 2

    mode = args.mode
    max_depth = args.max_depth
    if mode == MODE_BOUNDED and max_depth is None:
        max_depth = 24
    if mode == MODE_EXACT and max_depth is not None:
        print(
            "NOTE: exact mode ignores --max-depth (correctness: no depth cutoff)",
            flush=True,
        )
        max_depth = None

    max_exp = 2000 if args.smoke else args.max_expanded
    wall = 30.0 if args.smoke else args.wall_clock

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    result = search_corridor(
        mode=mode,
        max_expanded=max_exp,
        success_ceiling=args.success_ceiling,
        max_depth=max_depth,
        wall_clock=wall,
        max_rss_gib=args.max_rss_gib,
        enable_checkpoint=not args.no_checkpoint,
        resume=args.resume,
        force_stale_lock=args.force_stale_lock,
        use_hybrid_ordering=not args.no_hybrid,
    )

    raw = result.get("improvement_raw") or []
    if raw:
        best = min(raw, key=lambda r: (r["segment_mw"], r["explicit_commands"]))
        splice = splice_full_solution(best["path_actions"])
        if splice.get("ok"):
            arch = archive_if_improving(splice["full_actions"])
            result["splice"] = {k: v for k, v in splice.items() if k != "full_actions"}
            result["archive"] = arch
            export_actions_to_moves_file(
                best["path_actions"],
                ARTIFACTS / "opt011_candidate_segment.moves",
            )
            export_actions_to_moves_file(
                splice["full_actions"],
                ARTIFACTS / "opt011_full_candidate.moves",
            )
            if arch.get("readback_ok") and arch.get("is_strict_improvement"):
                result["status"] = "verified_improvement"

    out = {k: v for k, v in result.items() if k != "improvement_raw"}
    (ARTIFACTS / "opt011_exhaustion_or_result.json").write_text(
        json.dumps(out, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps({
        "status": result["status"],
        "termination": result["termination"],
        "mode": result["mode"],
        "expanded": result["expanded"],
        "improvements": len(result.get("improvements") or []),
        "completeness_claim": result.get("completeness_claim"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
