"""Autonomous continuation table: exact solved-subgraph remaining cost.

Machine solutions only. Keyed by ordered ``pack_state``. Suffixes use
physical column indices, so SPS1/TT identity is not a splice key.

A hit is ordinary transposition, not heuristic imitation:

    candidate = g_new + remaining_cost
    if candidate < incumbent: prefix_to_S + stored suffix, then replay
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Union

from spider.engine import SpiderState
from spider.metrics import Action, parse_moves_file, replay_actions
from spider.packed_state import pack_state
from spider.research_actions import (
    apply_action,
    as_actions,
    face_down_count,
    is_deal,
    step_cost,
    stock_rows,
)
from spider.search_kernel import reconstruct_path
from spider.whole_game_anytime import opening_state

ROOT = Path(__file__).resolve().parents[2]
DigestOrState = Union[str, SpiderState]

AUTONOMOUS_SOURCES = (
    ("v0.59", ROOT / "solutions" / "4925153_autonomous_v0_59.moves", 198),
    ("v0.67", ROOT / "solutions" / "4925153_autonomous_v0_67.moves", 192),
    ("v0.74_splice191", ROOT / "solutions" / "4925153_autonomous_v0_74_splice191.moves", 191),
    ("v0.74", ROOT / "solutions" / "4925153_autonomous_v0_74.moves", 187),
)


@dataclass
class ContinuationEntry:
    ordered_digest: str
    source_solution: str
    source_prefix_g: int
    source_total_g: int
    remaining_cost: int
    suffix_start_index: int
    suffix_actions: List[Action]
    stock_rows: int
    foundations: int
    face_down: int
    provenance: List[dict] = field(default_factory=list)

    @property
    def V(self) -> int:
        return self.remaining_cost

    @property
    def suffix(self) -> List[Action]:
        return self.suffix_actions

    @property
    def source(self) -> str:
        return self.source_solution

    @property
    def source_g(self) -> int:
        return self.source_prefix_g

    @property
    def source_total(self) -> int:
        return self.source_total_g


@dataclass
class ContinuationTable:
    entries: Dict[str, ContinuationEntry] = field(default_factory=dict)
    sources: List[dict] = field(default_factory=list)
    excluded: List[dict] = field(default_factory=list)
    ceiling: int = 186
    incumbent_g: int = 187
    lookups: int = 0
    hits: int = 0
    unique_matched: set = field(default_factory=set)
    hits_by_source: Dict[str, int] = field(default_factory=dict)
    equal_cost_hits: int = 0
    cheaper_prefix_hits: int = 0
    worse_prefix_hits: int = 0
    best_prefix_saving: Optional[int] = None
    best_candidate: Optional[int] = None
    splices_attempted: int = 0
    splices_ok: int = 0
    rejected_ceiling: int = 0
    rejected_reasons: Dict[str, int] = field(default_factory=dict)
    lookup_s: float = 0.0
    build_s: float = 0.0
    useful_hits: List[dict] = field(default_factory=list)
    improving_hits: List[dict] = field(default_factory=list)

    def get(self, digest: str) -> Optional[ContinuationEntry]:
        return self.entries.get(digest)

    def stats(self) -> dict:
        by_rows: Dict[int, int] = {}
        by_F: Dict[int, int] = {}
        min_V = None
        for ent in self.entries.values():
            by_rows[ent.stock_rows] = by_rows.get(ent.stock_rows, 0) + 1
            by_F[ent.foundations] = by_F.get(ent.foundations, 0) + 1
            min_V = ent.remaining_cost if min_V is None else min(min_V, ent.remaining_cost)
        return {
            "n_entries": len(self.entries),
            "n_sources": len(self.sources),
            "sources": list(self.sources),
            "excluded": list(self.excluded),
            "by_stock_rows": {str(k): v for k, v in sorted(by_rows.items(), reverse=True)},
            "by_F": {str(k): v for k, v in sorted(by_F.items())},
            "min_V": min_V,
            "lookups": self.lookups,
            "hits": self.hits,
            "unique_matched": len(self.unique_matched),
            "hits_by_source": dict(self.hits_by_source),
            "equal_cost_hits": self.equal_cost_hits,
            "cheaper_prefix_hits": self.cheaper_prefix_hits,
            "worse_prefix_hits": self.worse_prefix_hits,
            "best_prefix_saving": self.best_prefix_saving,
            "best_candidate": self.best_candidate,
            "splices_attempted": self.splices_attempted,
            "splices_ok": self.splices_ok,
            "rejected_ceiling": self.rejected_ceiling,
            "rejected_reasons": dict(self.rejected_reasons),
            "lookup_s": self.lookup_s,
            "build_s": self.build_s,
            "n_useful": len(self.useful_hits),
            "n_improving": len(self.improving_hits),
        }

    def consider(
        self,
        opening,
        *,
        digest: str,
        g: int,
        prefix_fn: Callable[[], Sequence[Action]],
        out,
        live_ceiling: int,
    ) -> Optional[int]:
        t0 = time.perf_counter()
        entry = self.entries.get(digest)
        self.lookup_s += time.perf_counter() - t0
        self.lookups += 1
        if entry is None:
            return None
        self.hits += 1
        self.unique_matched.add(digest)
        self.hits_by_source[entry.source_solution] = (
            self.hits_by_source.get(entry.source_solution, 0) + 1
        )
        prefix_saving = int(entry.source_prefix_g) - int(g)
        if prefix_saving > 0:
            kind = "CHEAPER_PREFIX_CONVERGENCE"
            self.cheaper_prefix_hits += 1
            if self.best_prefix_saving is None or prefix_saving > self.best_prefix_saving:
                self.best_prefix_saving = prefix_saving
        elif prefix_saving == 0:
            kind = "SAME_COST_CONVERGENCE"
            self.equal_cost_hits += 1
        else:
            kind = "WORSE_PREFIX_CONVERGENCE"
            self.worse_prefix_hits += 1
        cand = int(g) + int(entry.remaining_cost)
        if self.best_candidate is None or cand < self.best_candidate:
            self.best_candidate = cand
        rec = {
            "kind": kind,
            "g": int(g),
            "source_prefix_g": int(entry.source_prefix_g),
            "prefix_saving": prefix_saving,
            "remaining_cost": int(entry.remaining_cost),
            "candidate": cand,
            "source": entry.source_solution,
            "source_total": int(entry.source_total_g),
            "digest": digest,
            "stock_rows": entry.stock_rows,
            "foundations": entry.foundations,
            "face_down": entry.face_down,
        }
        if kind != "WORSE_PREFIX_CONVERGENCE":
            if len(self.useful_hits) < 64:
                self.useful_hits.append(rec)
        if cand > int(live_ceiling):
            self.rejected_ceiling += 1
            self.rejected_reasons["above_ceiling"] = self.rejected_reasons.get("above_ceiling", 0) + 1
            return None
        if out.solution_g is not None and cand >= int(out.solution_g):
            self.rejected_reasons["not_better_than_found"] = (
                self.rejected_reasons.get("not_better_than_found", 0) + 1
            )
            return None
        if int(entry.remaining_cost) < 0:
            self.rejected_reasons["negative_remaining"] = (
                self.rejected_reasons.get("negative_remaining", 0) + 1
            )
            return None
        prefix = list(prefix_fn())
        spliced = splice_candidate(prefix, int(g), entry)
        self.splices_attempted += 1
        verified = replay_spliced_candidate(opening, spliced)
        if not verified.get("ok"):
            self.rejected_reasons[verified.get("reason") or "replay_fail"] = (
                self.rejected_reasons.get(verified.get("reason") or "replay_fail", 0) + 1
            )
            return None
        self.splices_ok += 1
        rec = dict(rec)
        rec["kind"] = "NEW_BEST_SPLICE"
        rec["n_prefix"] = len(prefix)
        rec["n_suffix"] = len(entry.suffix_actions)
        rec["suffix_start_index"] = entry.suffix_start_index
        self.improving_hits.append(rec)
        out.solved = True
        out.solution_g = int(spliced["candidate_g"])
        out.solution_actions = list(spliced["actions"])
        out.replay_g = verified["g"]
        out.replay_ok = True
        out.continuation_hit = rec
        return int(spliced["candidate_g"])

    def consider_rec(self, opening, rec: dict, out, live_ceiling: int) -> Optional[int]:
        digest = rec.get("ordered_digest")
        if not digest or rec.get("full_actions") is None:
            return None
        prefix = as_actions(rec["full_actions"])
        return self.consider(
            opening,
            digest=str(digest),
            g=int(rec["g"]),
            prefix_fn=lambda: prefix,
            out=out,
            live_ceiling=live_ceiling,
        )

    def consider_generated(
        self, opening, rec: dict, g: int, kr, node: int, src_root, out, live_ceiling: int
    ) -> Optional[int]:
        digest = rec.get("ordered_digest")
        if not digest:
            return None

        def prefix_fn():
            root_actions = as_actions((src_root or {}).get("full_actions") or [])
            if kr is not None and node is not None and node < len(kr.nodes):
                return root_actions + reconstruct_path(kr.nodes, node)
            return root_actions

        return self.consider(
            opening,
            digest=str(digest),
            g=int(g),
            prefix_fn=prefix_fn,
            out=out,
            live_ceiling=live_ceiling,
        )


def lookup_continuation(table: ContinuationTable, state_or_digest: DigestOrState) -> Optional[ContinuationEntry]:
    if isinstance(state_or_digest, str):
        digest = state_or_digest
    else:
        digest = pack_state(state_or_digest).hex()
    return table.get(digest)


def splice_candidate(prefix_actions: Sequence[Action], prefix_g: int, entry: ContinuationEntry) -> dict:
    prefix = list(prefix_actions)
    suffix = list(entry.suffix_actions)
    return {
        "actions": prefix + suffix,
        "candidate_g": int(prefix_g) + int(entry.remaining_cost),
        "remaining_cost": int(entry.remaining_cost),
        "source": entry.source_solution,
        "matched_digest": entry.ordered_digest,
        "prefix_saving": int(entry.source_prefix_g) - int(prefix_g),
        "n_prefix": len(prefix),
        "n_suffix": len(suffix),
        "suffix_start_index": entry.suffix_start_index,
        "split_ok": True,
    }


def replay_spliced_candidate(opening, spliced: dict) -> dict:
    actions = as_actions(spliced["actions"])
    end = opening.clone()
    try:
        g = replay_actions(end, actions)
    except Exception as exc:
        return {"ok": False, "reason": f"illegal:{exc}"}
    expected = int(spliced["candidate_g"])
    deals = sum(1 for a in actions if is_deal(a))
    ok = (
        g == expected
        and end.is_solved()
        and len(end.foundations) == 8
        and not end.stock
        and all(c.is_empty() for c in end.columns)
        and deals == 5
    )
    return {
        "ok": ok,
        "g": g,
        "deals": deals,
        "solved": end.is_solved(),
        "reason": None if ok else "replay_mismatch",
    }


def _forbidden_path(path: Path) -> bool:
    name = path.name.lower()
    return "canonical" in name or "human" in name or name.endswith("live.moves")


def _ingest_source(table: ContinuationTable, opening, name: str, path: Path, expected_g: int) -> dict:
    if _forbidden_path(path):
        info = {"ok": False, "name": name, "reason": "forbidden_source", "path": str(path)}
        table.excluded.append(info)
        return info
    if not path.exists():
        info = {"ok": False, "name": name, "reason": "missing", "path": str(path)}
        table.excluded.append(info)
        return info
    actions = parse_moves_file(path)
    end = opening.clone()
    try:
        total = replay_actions(end, list(actions))
    except Exception as exc:
        info = {"ok": False, "name": name, "reason": f"replay_error:{exc}"}
        table.excluded.append(info)
        return info
    ok = (
        total == int(expected_g)
        and end.is_solved()
        and len(end.foundations) == 8
        and not end.stock
        and all(c.is_empty() for c in end.columns)
        and sum(1 for a in actions if is_deal(a)) == 5
    )
    if not ok:
        info = {
            "ok": False,
            "name": name,
            "reason": "replay_mismatch",
            "g": total,
            "expected": expected_g,
            "solved": end.is_solved(),
        }
        table.excluded.append(info)
        return info
    state = opening.clone()
    g = 0
    recorded = 0
    improved = 0

    def record(index: int) -> None:
        nonlocal recorded, improved
        digest = pack_state(state).hex()
        remaining = int(expected_g) - int(g)
        suffix = list(actions[index:])
        prov = {
            "source": name,
            "source_prefix_g": int(g),
            "source_total_g": int(expected_g),
            "remaining_cost": remaining,
            "suffix_start_index": index,
        }
        rec = ContinuationEntry(
            ordered_digest=digest,
            source_solution=name,
            source_prefix_g=int(g),
            source_total_g=int(expected_g),
            remaining_cost=remaining,
            suffix_start_index=index,
            suffix_actions=suffix,
            stock_rows=stock_rows(state),
            foundations=len(state.foundations),
            face_down=face_down_count(state),
            provenance=[prov],
        )
        prev = table.entries.get(digest)
        recorded += 1
        if prev is None:
            table.entries[digest] = rec
            return
        prev.provenance.append(prov)
        if remaining < prev.remaining_cost:
            rec.provenance = list(prev.provenance)
            table.entries[digest] = rec
            improved += 1

    record(0)
    for i, action in enumerate(actions):
        cost = 1 if is_deal(action) else step_cost(state, action)
        apply_action(state, action)
        g += int(cost)
        record(i + 1)
    src = {
        "ok": True,
        "name": name,
        "g": total,
        "n_actions": len(actions),
        "n_recorded": recorded,
        "n_min_updates": improved,
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
    }
    table.sources.append(src)
    return src


def build_autonomous_continuation_table(
    opening=None,
    *,
    sources=AUTONOMOUS_SOURCES,
    ceiling: int = 186,
    incumbent_g: int = 187,
) -> ContinuationTable:
    opening = opening or opening_state()
    table = ContinuationTable(ceiling=int(ceiling), incumbent_g=int(incumbent_g))
    t0 = time.perf_counter()
    for name, path, expected in sources:
        _ingest_source(table, opening, name, Path(path), int(expected))
    table.build_s = time.perf_counter() - t0
    return table


def table_built_ok(table: ContinuationTable) -> bool:
    return bool(table.entries) and bool(table.sources) and all(s.get("ok") for s in table.sources)


def search_with_continuation_table(
    *,
    opening=None,
    table: Optional[ContinuationTable] = None,
    max_unique: int = None,
    time_limit_s: float = None,
    rss_abort_mb: float = None,
    portfolio_width: int = None,
):
    """Whole-game search with continuation matching. Strategic/tactical policy unchanged."""

    from spider.tactical_integration import search_integrated_tactical
    from spider.whole_game_epoch_scheduler import (
        PORTFOLIO_WIDTH,
        SEARCH_RSS_MB,
        SEARCH_TIME_S,
        SEARCH_UNIQUE,
    )

    opening = opening or opening_state()
    table = table or build_autonomous_continuation_table(opening)
    result = search_integrated_tactical(
        opening=opening,
        max_unique=SEARCH_UNIQUE if max_unique is None else max_unique,
        time_limit_s=SEARCH_TIME_S if time_limit_s is None else time_limit_s,
        rss_abort_mb=SEARCH_RSS_MB if rss_abort_mb is None else rss_abort_mb,
        portfolio_width=PORTFOLIO_WIDTH if portfolio_width is None else portfolio_width,
        continuation_table=table,
    )
    result.continuation_stats = table.stats()
    result.continuation_table = table
    return result


def choose_continuation_verdict(p: dict) -> tuple:
    if p.get("incumbent_fail") or p.get("table_fail") or p.get("accounting_fail"):
        return (
            "CONTINUATION_TABLE_CONTRACT_FAILURE",
            p.get("contract_reason") or "incumbent, table, or replay contract failed",
        )
    if p.get("solved") and not p.get("replay_ok"):
        return "CONTINUATION_TABLE_CONTRACT_FAILURE", "solved but replay failed"
    elapsed = float(p.get("elapsed_s") or 0.0)
    lookup_s = float((p.get("table") or {}).get("lookup_s") or 0.0)
    if elapsed > 30.0 and lookup_s > 0.10 * elapsed:
        return (
            "CONTINUATION_TABLE_OVERHEAD_FAILURE",
            f"continuation lookup used {lookup_s:.2f}s of {elapsed:.1f}s",
        )
    inc = int(p.get("incumbent_g") or 187)
    best = p.get("solution_g")
    if p.get("solved") and p.get("replay_ok") and best is not None and int(best) < inc:
        return "CONTINUATION_TABLE_COST_IMPROVED", f"solved at g={best}"
    cheaper = int((p.get("table") or {}).get("cheaper_prefix_hits") or 0)
    hits = int((p.get("table") or {}).get("hits") or 0)
    if cheaper > 0:
        return (
            "CONTINUATION_TABLE_FINDS_CHEAPER_PREFIX_NO_BEST",
            "cheaper exact-state convergence found but no complete candidate beat 187",
        )
    if hits > 0:
        return (
            "CONTINUATION_TABLE_VALID_NO_IMPROVEMENT",
            "table matched known autonomous states but no cheaper complete route",
        )
    return "CONTINUATION_TABLE_NO_MATCHES", "no useful exact-state convergence in the whole-game search"
