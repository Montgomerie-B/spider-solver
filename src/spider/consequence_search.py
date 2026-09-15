"""Lean stock-empty consequence search.

Runs exact best-g search directly on ``run_search`` without epoch/portfolio
harvesting. No deal-id literals. Canonical 172 is not read.
"""

from __future__ import annotations

import hashlib
import time
from typing import Callable, Dict, List, Optional, Sequence

from spider.assembly_lower_bound import stock_empty_assembly_h
from spider.assembly_policy import COMPLETION_LANES
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.research_actions import is_deal, tableau_actions
from spider.search_kernel import SearchLimits, run_search
from spider.tactical_integration import strategic_lane_keys
from spider.whole_game_epoch_scheduler import SEARCH_RSS_MB


class MinimalConsequenceObserver:
    """Cheap F-milestone observer. Does not affect queue order."""

    def __init__(self, *, compute_h: bool = True, trace: bool = False) -> None:
        self.compute_h = bool(compute_h)
        self.trace_enabled = bool(trace)
        self.t0 = time.perf_counter()
        self.n_progress = 0
        self.n_h_calls = 0
        self.max_F = 0
        self.first_F: Dict[int, dict] = {}
        self.cheap_F: Dict[int, dict] = {}
        self.minf_F: Dict[int, dict] = {}
        self.terminal: Optional[dict] = None
        self._hasher = hashlib.sha256()

    def on_progress(self, kr, state, g: int, node_i: int) -> None:
        self.n_progress += 1
        n_f = len(state.foundations)
        elapsed = time.perf_counter() - self.t0
        node = kr.nodes[node_i] if 0 <= node_i < len(kr.nodes) else None
        ident = node.ident.hex() if node is not None else ""
        parent = node.parent if node is not None else -1
        action = node.action if node is not None else None
        if self.trace_enabled:
            self._hasher.update(f"{ident}|{int(g)}|{parent}|{action!r}".encode("utf-8"))
        if n_f > self.max_F:
            self.max_F = n_f
        blob = {"g": int(g), "elapsed_s": elapsed, "ident": ident, "node": int(node_i), "foundations": n_f}
        if n_f not in self.first_F:
            self.first_F[n_f] = dict(blob)
            self._maybe_h(state, int(g), self.first_F[n_f])
        if n_f not in self.cheap_F or int(g) < int(self.cheap_F[n_f]["g"]):
            self.cheap_F[n_f] = dict(blob)
            self._maybe_h(state, int(g), self.cheap_F[n_f])
        prev_f = None if n_f not in self.minf_F else self.minf_F[n_f].get("f")
        if self.compute_h and (prev_f is None or int(g) < int(prev_f)):
            h = self._h(state, int(g))
            f = int(g) + int(h)
            if prev_f is None or f < int(prev_f):
                rec = dict(blob)
                rec["h"] = h
                rec["f"] = f
                rec["slack_187"] = 187 - f
                self.minf_F[n_f] = rec
        if state.is_solved() and self.terminal is None:
            rec = dict(blob)
            rec["h"] = 0
            rec["f"] = int(g)
            self.terminal = rec

    def _h(self, state, g: int) -> int:
        self.n_h_calls += 1
        return int(stock_empty_assembly_h(state, int(g)))

    def _maybe_h(self, state, g: int, rec: dict) -> None:
        if not self.compute_h:
            return
        h = self._h(state, g)
        rec["h"] = h
        rec["f"] = int(g) + h
        rec["slack_187"] = 187 - rec["f"]

    def trace_hex(self) -> str:
        return self._hasher.hexdigest()


def tableau_actions_no_deal(state) -> list:
    acts = tableau_actions(state)
    return [a for a in acts if not is_deal(a)]


def run_stockempty_consequence(
    roots: Sequence[dict],
    *,
    ceiling: int,
    time_limit_s: float,
    max_unique: int,
    rss_abort_mb: float = SEARCH_RSS_MB,
    stop_on_first_terminal: bool = True,
    observer: Optional[MinimalConsequenceObserver] = None,
    lower_bound_fn: Callable = stock_empty_assembly_h,
    lane_names: Sequence[str] = COMPLETION_LANES,
    lane_keys_fn=strategic_lane_keys,
    identity_fn=pack_whole_game_identity,
):
    """Exact stock-empty consequence search. No epoch/portfolio harvest."""

    kernel_roots = []
    for rec in roots:
        kernel_roots.append(
            {
                "g": int(rec["g"]),
                "ordered_digest": rec.get("ordered_digest") or rec.get("post_digest"),
                "symmetry_digest": rec.get("ident") or rec.get("whole_game_identity") or rec.get("ordered_digest"),
            }
        )
    kr = run_search(
        kernel_roots,
        limits=SearchLimits(
            max_unique=int(max_unique),
            time_limit_s=float(time_limit_s),
            rss_abort_mb=float(rss_abort_mb),
            cost_ceiling=int(ceiling),
            harvest_slack=None,
        ),
        identity_fn=identity_fn,
        store_fn=pack_state,
        unpack_fn=unpack_state,
        lane_names=list(lane_names),
        lane_keys_fn=lane_keys_fn,
        is_terminal=lambda st: st.is_solved(),
        actions_fn=tableau_actions,
        on_progress=None if observer is None else observer.on_progress,
        lower_bound_fn=lower_bound_fn,
        stop_on_first_terminal=bool(stop_on_first_terminal),
    )
    kr.observer = observer
    return kr
