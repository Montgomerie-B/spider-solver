"""v0.59 epoch-portfolio whole-game scheduler.

Heuristic frontier management: tableau-only search within a stock epoch,
then a diverse Deal transition. Not proof pruning. Deal remains fully
legal under the engine; it is simply not expanded as an ordinary child
inside ``run_search``.

Terminal success is ``state.is_solved()`` only. No ``simple_*`` imports.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from spider.engine import SpiderState
from spider.metrics import Action, export_actions_to_moves_file, replay_actions
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.research_actions import (
    apply_action,
    as_actions,
    dump_actions,
    empty_column_indices,
    face_down_count,
    is_deal,
    opening_from_deal,
    stock_rows,
    tableau_actions,
)
from spider.search_kernel import KernelResult, SearchLimits, reconstruct_path, run_search
from spider.structural_analysis import (
    INF,
    SUITS,
    current_tableau_summary,
    foundation_readiness,
)
from spider.whole_game_anytime import DEAL_PATH, opening_root, opening_state

PORTFOLIO_WIDTH = 256
COST_CEILING = 300
SEARCH_UNIQUE = 800_000
SEARCH_TIME_S = 900.0
SEARCH_RSS_MB = 2.5 * 1024.0
AUGMENT_FRACTION = 0.25
LANES = ("cost", "reveal", "workspace", "construction", "readiness", "horizon")
HARVEST_CATS = (
    "cheap",
    "foundations",
    "min_fd",
    "workspace",
    "construction",
    "readiness",
    "horizon",
    "ready_div",
    "pareto",
    "deal_now",
)
PER_CAT = 40


def _n(v, default: int = INF) -> int:
    return default if v is None else int(v)


def _lb_epoch_fields(kr: KernelResult) -> dict:
    """Lower-bound telemetry copied onto every epoch record, including thin exits."""

    return {
        "lower_bound_prunes": int(getattr(kr, "lower_bound_prunes", 0) or 0),
        "lower_bound_calls": int(getattr(kr, "lower_bound_calls", 0) or 0),
        "lower_bound_s": float(getattr(kr, "lower_bound_s", 0.0) or 0.0),
        "min_h": getattr(kr, "min_h", None),
        "max_h": getattr(kr, "max_h", None),
        "min_f": getattr(kr, "min_f", None),
        "prunes_by_F": dict(getattr(kr, "prunes_by_F", None) or {}),
    }


def reconcile_lower_bound_telemetry(result) -> dict:
    """Cumulative kernel totals must equal the sum of per-epoch fields."""

    epochs = list(getattr(result, "epochs", None) or [])
    sum_prunes = sum(int(ep.get("lower_bound_prunes") or 0) for ep in epochs)
    sum_calls = sum(int(ep.get("lower_bound_calls") or 0) for ep in epochs)
    sum_s = sum(float(ep.get("lower_bound_s") or 0.0) for ep in epochs)
    by_f: Dict[int, int] = {}
    for ep in epochs:
        for fk, fv in (ep.get("prunes_by_F") or {}).items():
            by_f[int(fk)] = by_f.get(int(fk), 0) + int(fv)
    cum_prunes = int(getattr(result, "lower_bound_prunes", 0) or 0)
    cum_calls = int(getattr(result, "lower_bound_calls", 0) or 0)
    cum_s = float(getattr(result, "lower_bound_s", 0.0) or 0.0)
    cum_f = {int(k): int(v) for k, v in (getattr(result, "prunes_by_F", None) or {}).items()}
    return {
        "ok": sum_prunes == cum_prunes and sum_calls == cum_calls and by_f == cum_f,
        "epoch_prunes": sum_prunes,
        "cumulative_prunes": cum_prunes,
        "epoch_calls": sum_calls,
        "cumulative_calls": cum_calls,
        "epoch_seconds": sum_s,
        "cumulative_seconds": cum_s,
        "epoch_prunes_by_F": by_f,
        "cumulative_prunes_by_F": cum_f,
        "seconds_match": abs(sum_s - cum_s) < 1e-6,
    }


def epoch_lane_keys(state: SpiderState, g: int) -> Dict[str, Optional[tuple]]:
    """Intra-epoch lanes. ``None`` means the state does not join that heap."""

    s = current_tableau_summary(state)
    r = foundation_readiness(state)
    fd = int(s["face_down"])
    empty = int(s["empty_n"])
    keys: Dict[str, Optional[tuple]] = {
        "cost": (int(g),),
        "reveal": (fd, -empty, int(g)),
        "workspace": (-empty, fd, -int(s["run_compression"]), int(g)),
        "construction": (
            -int(s["same_suit_bonds"]),
            -int(s["longest_run"]),
            -int(s["merge_edges"]),
            fd,
            int(g),
        ),
        "readiness": None,
        "horizon": None,
    }
    if r["n_ready"] > 0:
        best = r["best_ready"] or {}
        keys["readiness"] = (
            -int(s["foundations"]),
            _n(best.get("cover")),
            _n(best.get("fd")),
            -int(best.get("edges") or 0),
            -int(best.get("cond_len") or 0),
            _n(best.get("gap")),
            int(g),
        )
    else:
        nearest = r["nearest_horizon"]
        if nearest is None:
            nearest = INF
        keys["horizon"] = (
            int(nearest),
            -int(r["horizon_bonds"]),
            -int(r["horizon_longest"]),
            -int(r["horizon_edges"]),
            fd,
            int(g),
        )
    return keys


def epoch_weight(stock_row_count: int, n_ready: int) -> int:
    return 1 + (1 if n_ready else 0) + (2 if stock_row_count == 0 else 0)


def future_epoch_weight(stock_row_count: int) -> int:
    total = 0
    for rows in range(stock_row_count - 1, -1, -1):
        total += 1 + (2 if rows == 0 else 0)
    return total


def allocate_budget(stock_row_count: int, n_ready: int, remain_unique: int, remain_s: float) -> Tuple[int, float]:
    this = epoch_weight(stock_row_count, n_ready)
    future = future_epoch_weight(stock_row_count)
    if future <= 0:
        return max(1, remain_unique), max(0.05, remain_s)
    share = this / (this + future)
    return max(1, int(remain_unique * share)), max(0.05, remain_s * share)


class _Top:
    def __init__(self, n: int = PER_CAT):
        self.n = n
        self.items: List[tuple] = []

    def add(self, key: tuple, rec: dict) -> None:
        self.items.append((key, rec))
        if len(self.items) > self.n * 4:
            self.items.sort(key=lambda t: t[0])
            self.items = self.items[: self.n]

    def best(self) -> List[dict]:
        self.items.sort(key=lambda t: t[0])
        out = []
        seen = set()
        for _k, rec in self.items:
            ident = rec["ident"]
            if ident in seen:
                continue
            seen.add(ident)
            out.append(rec)
            if len(out) >= self.n:
                break
        return out


def _vec(rec: dict) -> tuple:
    return (
        int(rec.get("g") or 0),
        int(rec.get("face_down") or 0),
        -int(rec.get("foundations") or 0),
        -int(rec.get("bonds") or 0),
        -int(rec.get("empty_n") or 0),
    )


def _dominates(a: dict, b: dict) -> bool:
    va, vb = _vec(a), _vec(b)
    return all(x <= y for x, y in zip(va, vb)) and any(x < y for x, y in zip(va, vb))


def _snapshot_rec(state: SpiderState, g: int, node: int, ready: dict, summary: dict) -> dict:
    best = ready.get("best_ready") or {}
    return {
        "node": node,
        "g": int(g),
        "ident": pack_whole_game_identity(state).hex(),
        "ordered_digest": pack_state(state).hex(),
        "foundations": int(summary["foundations"]),
        "foundation_suits": list(summary["foundation_suits"]),
        "face_down": int(summary["face_down"]),
        "empty_n": int(summary["empty_n"]),
        "stock_rows": int(summary["stock_rows"]),
        "bonds": int(summary["same_suit_bonds"]),
        "longest": int(summary["longest_run"]),
        "merges": int(summary["merge_edges"]),
        "n_ready": int(ready["n_ready"]),
        "ready_suits": list(ready["ready_suits"]),
        "nearest_horizon": ready.get("nearest_horizon"),
        "nearest_suits": list(ready.get("nearest_suits") or []),
        "cover": best.get("cover"),
        "ready_fd": best.get("fd"),
        "ready_edges": best.get("edges"),
        "ready_cond": best.get("cond_len"),
        "ready_gap": best.get("gap"),
        "best_ready_suit": ready.get("best_ready_suit"),
    }


def harvest_portfolio(
    tops: Dict[str, _Top],
    roots: Sequence[dict],
    min_root_g: int,
    *,
    width: int = PORTFOLIO_WIDTH,
    cats: Sequence[str] = HARVEST_CATS,
    incumbent: Optional[dict] = None,
    vec_fn=None,
    split_pareto: bool = False,
) -> Tuple[List[dict], Dict[str, int]]:
    buckets: Dict[str, List[dict]] = {cat: tops[cat].best() for cat in tops}
    deal_now = [r for r in roots if int(r["g"]) == int(min_root_g)]
    buckets["deal_now"] = sorted(deal_now, key=lambda r: (r["g"], r.get("ordered_digest", "")))[:PER_CAT]
    if incumbent is not None:
        buckets["incumbent"] = [incumbent]
    pool = []
    seen_pool = set()
    for cat, rows in buckets.items():
        for rec in rows:
            ident = rec.get("ident") or rec.get("whole_game_identity")
            if ident in seen_pool:
                continue
            seen_pool.add(ident)
            pool.append(rec)
    def _dom(a: dict, b: dict) -> bool:
        if vec_fn is None:
            return _dominates(a, b)
        va, vb = vec_fn(a), vec_fn(b)
        return all(x <= y for x, y in zip(va, vb)) and any(x < y for x, y in zip(va, vb))

    groups = [pool]
    if split_pareto:
        groups = [
            [r for r in pool if r.get("n_ready")],
            [r for r in pool if not r.get("n_ready")],
        ]
    pareto = []
    for grp in groups:
        for rec in grp:
            if any(_dom(o, rec) for o in grp if o is not rec):
                continue
            pareto.append(rec)
    buckets["pareto"] = pareto[:PER_CAT]
    picked: List[dict] = []
    seen = set()
    counts: Dict[str, int] = defaultdict(int)

    def take(rec: dict, cat: str) -> bool:
        ident = rec.get("ident") or rec.get("whole_game_identity")
        if ident in seen:
            return False
        seen.add(ident)
        item = dict(rec)
        item["portfolio_cat"] = cat
        item["ident"] = ident
        picked.append(item)
        counts[cat] += 1
        return True

    for rec in buckets["deal_now"][: max(8, width // 16)]:
        take(rec, "deal_now")
        if len(picked) >= width:
            return picked, dict(counts)
    if incumbent is not None:
        take(incumbent, "incumbent")
        if len(picked) >= width:
            return picked, dict(counts)
    while len(picked) < width:
        progressed = False
        for cat in cats:
            rows = buckets.get(cat) or []
            while rows:
                rec = rows.pop(0)
                if take(rec, cat):
                    progressed = True
                    break
            if len(picked) >= width:
                break
        if not progressed:
            break
    return picked[:width], dict(counts)


def _attach_paths(picked: Sequence[dict], roots: Sequence[dict], kr: KernelResult) -> List[dict]:
    out = []
    for rec in picked:
        if rec.get("full_actions") and rec.get("node") is None:
            item = dict(rec)
            item.setdefault("ident", rec.get("whole_game_identity"))
            out.append(item)
            continue
        node = rec.get("node")
        if node is None or node >= len(kr.nodes):
            continue
        kn = kr.nodes[node]
        src = roots[kn.origin]
        path = reconstruct_path(kr.nodes, node)
        prefix = as_actions(src.get("full_actions") or [])
        item = dict(rec)
        item["full_actions"] = dump_actions(prefix + path)
        item["g"] = kn.g
        item["origin"] = kn.origin
        item["ordered_digest"] = kn.store.hex()
        item["ident"] = kn.ident.hex()
        item["whole_game_identity"] = kn.ident.hex()
        item["lineage"] = list(rec.get("lineage") or src.get("lineage") or [])
        out.append(item)
    return out


def _verify_and_deal(opening: SpiderState, rec: dict) -> Optional[dict]:
    end = opening.clone()
    try:
        cost = replay_actions(end, as_actions(rec["full_actions"]))
    except Exception:
        return None
    if cost != int(rec["g"]):
        return None
    if pack_state(end).hex() != rec["ordered_digest"]:
        return None
    if stock_rows(end) <= 0:
        return dict(rec)
    if not end.can_deal():
        return None
    before_f = len(end.foundations)
    try:
        deal_c = apply_action(end, ("deal",))
    except Exception:
        return None
    item = dict(rec)
    item["g"] = cost + deal_c
    item["full_actions"] = dump_actions(as_actions(rec["full_actions"]) + [("deal",)])
    item["ordered_digest"] = pack_state(end).hex()
    item["ident"] = pack_whole_game_identity(end).hex()
    item["whole_game_identity"] = item["ident"]
    item["stock_rows"] = stock_rows(end)
    item["foundations"] = len(end.foundations)
    item["foundation_suits"] = [run[0].suit for run in end.foundations if run]
    item["face_down"] = face_down_count(end)
    item["empty_n"] = len(empty_column_indices(end))
    item["deal_auto_foundation"] = len(end.foundations) > before_f
    item["solved"] = end.is_solved()
    item["timings"] = list(rec.get("timings") or [])
    item["categories"] = list(rec.get("categories") or ([rec.get("portfolio_cat")] if rec.get("portfolio_cat") else []))
    item["lineage"] = list(rec.get("lineage") or [])
    return item


def _dedup_roots(rows: Sequence[dict]) -> dict:
    classes: Dict[str, dict] = {}
    conv = 0
    for rec in rows:
        ident = rec["ident"]
        prev = classes.get(ident)
        if prev is None:
            item = dict(rec)
            item["timings"] = list(rec.get("timings") or [])
            item["categories"] = list(rec.get("categories") or [])
            classes[ident] = item
            continue
        conv += 1
        cats = sorted(set((prev.get("categories") or []) + (rec.get("categories") or [])))
        lineage = []
        for tag in list(prev.get("lineage") or []) + list(rec.get("lineage") or []):
            if tag not in lineage:
                lineage.append(tag)
        if rec["g"] < prev["g"]:
            item = dict(rec)
            item["categories"] = cats
            item["lineage"] = lineage
            classes[ident] = item
        else:
            prev["categories"] = cats
            prev["lineage"] = lineage
    kept = sorted(classes.values(), key=lambda r: (r["g"], r["ordered_digest"]))
    return {
        "raw": len(rows),
        "unique": len(kept),
        "convergences": conv,
        "states": kept,
    }


@dataclass
class EpochPortfolioResult:
    unique: int = 0
    expanded: int = 0
    generated: int = 0
    duplicate_skips: int = 0
    stale_skips: int = 0
    elapsed_s: float = 0.0
    peak_rss_mb: Optional[float] = None
    stop_reason: str = ""
    min_g: Optional[int] = None
    max_g: Optional[int] = None
    solved: bool = False
    solution_g: Optional[int] = None
    solution_actions: List[Action] = field(default_factory=list)
    replay_ok: bool = False
    replay_g: Optional[int] = None
    accounting_fail: bool = False
    deal_illegal: bool = False
    max_foundations: int = 0
    min_face_down: Optional[int] = None
    max_empty: Optional[int] = None
    foundations_first: Dict[int, dict] = field(default_factory=dict)
    foundations_cheap: Dict[int, dict] = field(default_factory=dict)
    epochs: List[dict] = field(default_factory=list)
    lane_exp: Dict[str, int] = field(default_factory=dict)
    lane_pops: Dict[str, int] = field(default_factory=dict)
    lane_stale: Dict[str, int] = field(default_factory=dict)
    best_state: Optional[dict] = None
    best_readiness: Optional[dict] = None
    states_per_s: float = 0.0
    opening_horizons: Optional[dict] = None
    class_displaced: int = 0
    incumbent_injected: int = 0
    incumbent_survived: int = 0
    candidate_ceiling: Optional[int] = None
    incumbent_g: Optional[int] = None
    best_durability: Optional[dict] = None
    lower_bound_prunes: int = 0
    lower_bound_calls: int = 0
    lower_bound_s: float = 0.0
    min_h: Optional[int] = None
    max_h: Optional[int] = None
    min_f: Optional[int] = None
    prunes_by_F: Dict[int, int] = field(default_factory=dict)


def _note_foundation(out: EpochPortfolioResult, rec: dict, elapsed: float, unique: int, expanded: int) -> None:
    n = int(rec.get("foundations") or 0)
    if n <= 0:
        return
    snap = dict(rec)
    snap["elapsed_s"] = elapsed
    snap["unique"] = unique
    snap["expanded"] = expanded
    if n not in out.foundations_first:
        out.foundations_first[n] = snap
    prev = out.foundations_cheap.get(n)
    if prev is None or int(rec["g"]) < int(prev["g"]):
        out.foundations_cheap[n] = snap
    if n > out.max_foundations:
        out.max_foundations = n


def search_epoch_portfolio(
    *,
    opening: Optional[SpiderState] = None,
    max_unique: int = SEARCH_UNIQUE,
    time_limit_s: float = SEARCH_TIME_S,
    rss_abort_mb: float = SEARCH_RSS_MB,
    cost_ceiling: int = COST_CEILING,
    portfolio_width: int = PORTFOLIO_WIDTH,
    lane_names: Sequence[str] = LANES,
    keys_fn=epoch_lane_keys,
    harvest_cats: Sequence[str] = HARVEST_CATS,
    harvest_slack: Optional[int] = None,
    remaining_deal_bound: bool = False,
    incumbent_by_rows: Optional[Dict[int, dict]] = None,
    continue_after_solve: bool = False,
    extra_track: Optional[object] = None,
    harvest_vec_fn=None,
    split_pareto: bool = False,
    enrich_fn=None,
    initial_roots: Optional[Sequence[dict]] = None,
    abort_when=None,
    on_harvest=None,
    lower_bound_fn=None,
    finalize_track=None,
    epoch_augment_fn=None,
    augment_fraction: float = AUGMENT_FRACTION,
    augment_when=None,
) -> EpochPortfolioResult:
    opening = opening or opening_state()
    started = time.perf_counter()
    out = EpochPortfolioResult()
    out.opening_horizons = foundation_readiness(opening)
    if initial_roots:
        roots = [dict(r) for r in initial_roots]
        for rec in roots:
            rec.setdefault("ident", rec.get("whole_game_identity") or rec.get("ident"))
            rec.setdefault("timings", list(rec.get("timings") or []))
            rec.setdefault("categories", list(rec.get("categories") or []))
            rec.setdefault("lineage", list(rec.get("lineage") or []))
    else:
        roots = [opening_root(opening)]
        roots[0]["ident"] = roots[0]["whole_game_identity"]
        roots[0]["timings"] = ["OPENING"]
        roots[0]["categories"] = ["deal_now"]
        roots[0]["lineage"] = []
    out.min_face_down = face_down_count(opening)
    out.max_empty = 0
    out.candidate_ceiling = cost_ceiling
    remaining_unique = max_unique
    live_ceiling = cost_ceiling
    stop = ""
    class_best: Dict[tuple, dict] = {}

    while roots and remaining_unique > 0:
        now = time.perf_counter()
        remain_t = time_limit_s - (now - started)
        if remain_t <= 0:
            stop = "time limit"
            break
        st0 = unpack_state(bytes.fromhex(roots[0]["ordered_digest"]))
        rows = stock_rows(st0)
        ready0 = foundation_readiness(st0)
        n_ready = int(ready0["n_ready"])
        alloc_u, alloc_t = allocate_budget(rows, n_ready, remaining_unique, remain_t)
        alloc_u = min(alloc_u, remaining_unique)
        alloc_t = min(alloc_t, remain_t)
        epoch_ceil = live_ceiling - rows if remaining_deal_bound else live_ceiling
        epoch_ceil = max(0, int(epoch_ceil))
        epoch_roots = [r for r in roots if int(r["g"]) <= epoch_ceil]
        epoch_incumbent = None
        if incumbent_by_rows and rows in incumbent_by_rows:
            ck = dict(incumbent_by_rows[rows])
            ck.setdefault("ident", ck.get("whole_game_identity"))
            epoch_incumbent = ck
            if int(ck["g"]) <= epoch_ceil:
                ids = {r.get("ident") or r.get("whole_game_identity") for r in epoch_roots}
                if ck.get("ident") not in ids:
                    epoch_roots.append(ck)
                    out.incumbent_injected += 1
        if not epoch_roots:
            stop = "ceiling exhausted"
            break
        min_root_g = min(int(r["g"]) for r in epoch_roots)
        tops = {cat: _Top() for cat in harvest_cats}
        epoch_min_fd = None
        epoch_max_f = 0
        epoch_max_empty = 0
        epoch_best_c = None
        epoch_best_r = None
        epoch_best_d = None
        epoch_debt_n = 0
        epoch_debt_sum = 0
        epoch_debt_min = None
        epoch_debt_samples: List[int] = []

        def on_progress(kr: KernelResult, state: SpiderState, g: int, node: int) -> None:
            nonlocal epoch_min_fd, epoch_max_f, epoch_max_empty, epoch_best_c, epoch_best_r
            nonlocal epoch_best_d, epoch_debt_n, epoch_debt_sum, epoch_debt_min
            if stock_rows(state) != rows:
                out.accounting_fail = True
            s = current_tableau_summary(state)
            rdy = foundation_readiness(state)
            rec = _snapshot_rec(state, g, node, rdy, s)
            if enrich_fn is not None:
                enrich_fn(state, rec)
            rec["origin"] = kr.nodes[node].origin if node < len(kr.nodes) else 0
            src_root = epoch_roots[rec["origin"]] if rec["origin"] < len(epoch_roots) else None
            rec["lineage"] = list((src_root or {}).get("lineage") or [])
            rec["root_g"] = int(src_root["g"]) if src_root else min_root_g
            rec["delta_g"] = int(g) - int(rec["root_g"])
            rec["from_incumbent_ckpt"] = bool((src_root or {}).get("incumbent_control"))
            rec["root_ident"] = (src_root or {}).get("ident") or (src_root or {}).get("whole_game_identity")
            if int(rec.get("foundations") or 0) > 0 and node < len(kr.nodes):
                prefix = as_actions((src_root or {}).get("full_actions") or [])
                rec["full_actions"] = dump_actions(prefix + reconstruct_path(kr.nodes, node))
            elapsed = time.perf_counter() - started
            _note_foundation(out, rec, elapsed, kr.unique, kr.expanded)
            if abort_when is not None and abort_when(out, rec):
                kr.stop_reason = "abort"
            if out.min_face_down is None or rec["face_down"] < out.min_face_down:
                out.min_face_down = rec["face_down"]
            if rec["empty_n"] > (out.max_empty or 0):
                out.max_empty = rec["empty_n"]
            if epoch_min_fd is None or rec["face_down"] < epoch_min_fd:
                epoch_min_fd = rec["face_down"]
            epoch_max_f = max(epoch_max_f, rec["foundations"])
            epoch_max_empty = max(epoch_max_empty, rec["empty_n"])
            if epoch_best_c is None or (
                -rec["bonds"],
                -rec["longest"],
                -rec["merges"],
                rec["g"],
            ) < (
                -epoch_best_c["bonds"],
                -epoch_best_c["longest"],
                -epoch_best_c["merges"],
                epoch_best_c["g"],
            ):
                epoch_best_c = rec
            if rec["n_ready"] and (
                epoch_best_r is None
                or (
                    _n(rec.get("cover")),
                    _n(rec.get("ready_fd")),
                    -int(rec.get("ready_edges") or 0),
                    rec["g"],
                )
                < (
                    _n(epoch_best_r.get("cover")),
                    _n(epoch_best_r.get("ready_fd")),
                    -int(epoch_best_r.get("ready_edges") or 0),
                    epoch_best_r["g"],
                )
            ):
                epoch_best_r = rec
                out.best_readiness = rec
            if out.best_state is None or (
                -rec["foundations"],
                rec["face_down"],
                rec["stock_rows"],
                rec["g"],
            ) < (
                -out.best_state["foundations"],
                out.best_state["face_down"],
                out.best_state["stock_rows"],
                out.best_state["g"],
            ):
                out.best_state = rec
            if "cheap" in tops:
                tops["cheap"].add((rec["g"], rec["ordered_digest"]), rec)
            if "foundations" in tops:
                tops["foundations"].add((-rec["foundations"], rec["g"], rec["ordered_digest"]), rec)
            if "min_fd" in tops:
                tops["min_fd"].add((rec["face_down"], rec["g"], rec["ordered_digest"]), rec)
            if "workspace" in tops:
                tops["workspace"].add((-rec["empty_n"], rec["face_down"], rec["g"]), rec)
            if "construction" in tops:
                tops["construction"].add((-rec["bonds"], -rec["longest"], -rec["merges"], rec["g"]), rec)
            if rec["n_ready"]:
                if "readiness" in tops:
                    tops["readiness"].add(
                        (
                            _n(rec.get("cover")),
                            _n(rec.get("ready_fd")),
                            -int(rec.get("ready_edges") or 0),
                            rec["g"],
                        ),
                        rec,
                    )
                if "ready_div" in tops:
                    suit = rec.get("best_ready_suit") or "_"
                    tops["ready_div"].add((_n(rec.get("cover")), rec["g"], suit), rec)
            elif "horizon" in tops:
                tops["horizon"].add(
                    (_n(rec.get("nearest_horizon")), -rec["bonds"], rec["g"]),
                    rec,
                )
            if rec["g"] == min_root_g and "deal_now" in tops:
                tops["deal_now"].add((rec["g"], rec["ordered_digest"]), rec)
            if extra_track is not None:
                extra_track(tops, rec, min_root_g, class_best)
            if "boundaries_total" in rec:
                b = int(rec["boundaries_total"])
                epoch_debt_n += 1
                epoch_debt_sum += b
                if epoch_debt_min is None or b < epoch_debt_min:
                    epoch_debt_min = b
                if len(epoch_debt_samples) < 8192:
                    epoch_debt_samples.append(b)
                dkey = (
                    -int(rec["foundations"]),
                    b,
                    int(rec.get("component_layers") or 0),
                    int(rec.get("mixed_supports") or 0),
                    int(rec["face_down"]),
                    int(rec["g"]),
                )
                if epoch_best_d is None or dkey < epoch_best_d["durability_key"]:
                    snap = dict(rec)
                    snap["durability_key"] = dkey
                    epoch_best_d = snap
                    out.best_durability = snap

        will_augment = epoch_augment_fn is not None and (
            augment_when is None or bool(augment_when(rows, epoch_roots))
        )
        strategic_u, strategic_t = alloc_u, alloc_t
        augment_u, augment_t = 0, 0.0
        if will_augment:
            frac = min(max(float(augment_fraction), 0.0), 0.9)
            strategic_t = max(0.05, alloc_t * (1.0 - frac))
            augment_t = max(0.0, alloc_t - strategic_t)
            strategic_u = max(1, int(alloc_u * (1.0 - frac)))
            augment_u = max(0, alloc_u - strategic_u)
        kr = run_search(
            epoch_roots,
            limits=SearchLimits(
                max_unique=strategic_u,
                time_limit_s=strategic_t,
                rss_abort_mb=rss_abort_mb,
                cost_ceiling=epoch_ceil,
                harvest_slack=harvest_slack,
            ),
            identity_fn=pack_whole_game_identity,
            store_fn=pack_state,
            unpack_fn=unpack_state,
            lane_names=list(lane_names),
            lane_keys_fn=keys_fn,
            is_terminal=lambda st: st.is_solved(),
            actions_fn=tableau_actions,
            on_progress=on_progress,
            lower_bound_fn=lower_bound_fn,
        )
        out.unique += kr.unique
        remaining_unique = max_unique - out.unique
        out.expanded += kr.expanded
        out.generated += kr.generated
        out.duplicate_skips += kr.duplicate_skips
        out.stale_skips += kr.stale_skips
        if kr.peak_rss_mb is not None and (out.peak_rss_mb is None or kr.peak_rss_mb > out.peak_rss_mb):
            out.peak_rss_mb = kr.peak_rss_mb
        for name in lane_names:
            out.lane_exp[name] = out.lane_exp.get(name, 0) + kr.lane_exp.get(name, 0)
            out.lane_pops[name] = out.lane_pops.get(name, 0) + kr.lane_pops.get(name, 0)
            out.lane_stale[name] = out.lane_stale.get(name, 0) + kr.lane_stale.get(name, 0)
        out.min_g = kr.min_g if out.min_g is None else min(out.min_g, kr.min_g if kr.min_g is not None else out.min_g)
        out.max_g = kr.max_g if out.max_g is None else max(out.max_g, kr.max_g if kr.max_g is not None else out.max_g)
        out.lower_bound_prunes += int(kr.lower_bound_prunes or 0)
        out.lower_bound_calls += int(kr.lower_bound_calls or 0)
        out.lower_bound_s += float(kr.lower_bound_s or 0.0)
        if kr.min_h is not None:
            out.min_h = kr.min_h if out.min_h is None else min(out.min_h, kr.min_h)
        if kr.max_h is not None:
            out.max_h = kr.max_h if out.max_h is None else max(out.max_h, kr.max_h)
        if kr.min_f is not None:
            out.min_f = kr.min_f if out.min_f is None else min(out.min_f, kr.min_f)
        for fk, fv in (kr.prunes_by_F or {}).items():
            out.prunes_by_F[int(fk)] = out.prunes_by_F.get(int(fk), 0) + int(fv)

        if kr.stop_reason == "abort":
            stop = "abort"
            rec = {
                "stock_rows": rows,
                "input_roots": len(epoch_roots),
                "unique": kr.unique,
                "expanded": kr.expanded,
                "generated": kr.generated,
                "elapsed_s": kr.elapsed_s,
                "stop_reason": "abort",
                "min_g": kr.min_g,
                "max_g": kr.max_g,
                "min_face_down": epoch_min_fd,
                "max_foundations": epoch_max_f,
                "n_ready": n_ready,
                "lineage_roots": sum(1 for r in epoch_roots if r.get("lineage")),
            }
            rec.update(_lb_epoch_fields(kr))
            out.epochs.append(rec)
            break

        if kr.terminals:
            best = min(kr.terminals, key=lambda t: (t["g"], t["store"]))
            kn = kr.nodes[best["node"]]
            src = epoch_roots[kn.origin]
            path = reconstruct_path(kr.nodes, best["node"])
            full = as_actions(src.get("full_actions") or []) + path
            cand_g = int(best["g"])
            if out.solution_g is None or cand_g < out.solution_g:
                out.solved = True
                out.solution_g = cand_g
                out.solution_actions = full
                end = opening.clone()
                try:
                    cost = replay_actions(end, full)
                except Exception:
                    out.accounting_fail = True
                else:
                    out.replay_g = cost
                    out.replay_ok = (
                        cost == out.solution_g
                        and end.is_solved()
                        and len(end.foundations) == 8
                        and stock_rows(end) == 0
                    )
                    if not out.replay_ok:
                        out.accounting_fail = True
            if continue_after_solve:
                live_ceiling = min(live_ceiling, cand_g - 1)
                out.candidate_ceiling = live_ceiling
            if not continue_after_solve or rows == 0:
                stop = "solved"
                rec = {
                    "stock_rows": rows,
                    "input_roots": len(epoch_roots),
                    "alloc_unique": alloc_u,
                    "alloc_s": alloc_t,
                    "unique": kr.unique,
                    "expanded": kr.expanded,
                    "generated": kr.generated,
                    "elapsed_s": kr.elapsed_s,
                    "stop_reason": kr.stop_reason,
                    "lane_exp": kr.lane_exp,
                    "min_g": kr.min_g,
                    "max_g": kr.max_g,
                    "min_face_down": epoch_min_fd,
                    "max_foundations": epoch_max_f,
                    "n_ready": n_ready,
                    "nearest_horizon": ready0.get("nearest_horizon"),
                    "ready_suits": ready0.get("ready_suits"),
                    "solved": True,
                    "candidate_ceiling": live_ceiling,
                }
                rec.update(_lb_epoch_fields(kr))
                out.epochs.append(rec)
                break

        if finalize_track is not None:
            finalize_track(tops, epoch_roots, min_root_g, rows)
        picked, cat_counts = harvest_portfolio(
            tops,
            epoch_roots,
            min_root_g,
            width=portfolio_width,
            cats=harvest_cats,
            incumbent=epoch_incumbent if epoch_incumbent and int(epoch_incumbent["g"]) <= epoch_ceil else None,
            vec_fn=harvest_vec_fn,
            split_pareto=split_pareto,
        )
        attached = _attach_paths(picked, epoch_roots, kr)
        if on_harvest is not None:
            on_harvest(rows, picked, cat_counts, attached)
        augment_stats = {
            "called": False,
            "n_probes": 0,
            "n_terminals": 0,
            "unique": 0,
            "expanded": 0,
            "generated": 0,
            "elapsed_s": 0.0,
            "alloc_s": augment_t,
            "alloc_unique": augment_u,
            "lane_exp": {},
        }
        if will_augment:
            leftover_t = max(0.0, strategic_t - float(kr.elapsed_s or 0.0))
            remain_wall = max(0.0, time_limit_s - (time.perf_counter() - started))
            budget_s = min(augment_t + leftover_t, remain_wall)
            leftover_u = max(0, strategic_u - int(kr.unique or 0))
            unique_budget = min(augment_u + leftover_u, max(0, max_unique - out.unique))
            ctx = {
                "opening": opening,
                "epoch_roots": epoch_roots,
                "min_root_g": min_root_g,
                "epoch_ceil": epoch_ceil,
                "cost_ceiling": live_ceiling,
                "rss_abort_mb": rss_abort_mb,
                "unique_budget": unique_budget,
                "kernel": kr,
                "extra_track": extra_track,
            }
            raw = epoch_augment_fn(rows, attached, budget_s, ctx)
            extra = []
            stats: dict = {}
            if isinstance(raw, dict):
                extra = list(raw.get("attached") or raw.get("roots") or [])
                stats = raw
            elif raw:
                extra = list(raw)
            seen_att = {
                rec.get("ident") or rec.get("whole_game_identity") for rec in attached
            }
            n_add = 0
            for rec in extra:
                ident = rec.get("ident") or rec.get("whole_game_identity")
                if ident in seen_att:
                    continue
                seen_att.add(ident)
                item = dict(rec)
                item.setdefault("portfolio_cat", "tactical_cashout")
                item.setdefault("ident", ident)
                attached.append(item)
                n_add += 1
                _note_foundation(
                    out,
                    item,
                    time.perf_counter() - started,
                    out.unique,
                    out.expanded,
                )
            aug_unique = int(stats.get("unique") or 0)
            out.unique += aug_unique
            remaining_unique = max_unique - out.unique
            out.expanded += int(stats.get("expanded") or 0)
            out.generated += int(stats.get("generated") or 0)
            out.duplicate_skips += int(stats.get("duplicate_skips") or 0)
            out.stale_skips += int(stats.get("stale_skips") or 0)
            for name, n in (stats.get("lane_exp") or {}).items():
                out.lane_exp[name] = out.lane_exp.get(name, 0) + int(n)
            augment_stats = {
                "called": True,
                "n_probes": int(stats.get("n_probes") or stats.get("n_roots") or 0),
                "n_terminals": n_add,
                "unique": aug_unique,
                "expanded": int(stats.get("expanded") or 0),
                "generated": int(stats.get("generated") or 0),
                "elapsed_s": float(stats.get("elapsed_s") or 0.0),
                "alloc_s": budget_s,
                "alloc_unique": unique_budget,
                "lane_exp": dict(stats.get("lane_exp") or {}),
                "found": int(stats.get("n_found") or 0),
                "n_selected": int(stats.get("n_selected") or 0),
                "n_ready_roots": int(stats.get("n_ready_roots") or 0),
                "n_terminals_raw": int(stats.get("n_terminals_raw") or n_add),
                "probes": list(stats.get("probes") or []),
            }
        if epoch_incumbent is not None:
            iid = epoch_incumbent.get("ident")
            if any((r.get("ident") or r.get("whole_game_identity")) == iid for r in attached):
                out.incumbent_survived += 1
        verified = []
        next_raw = []
        for rec in attached:
            live = _verify_and_deal(opening, rec) if rows > 0 else rec
            if live is None:
                if rows > 0:
                    out.deal_illegal = True
                    out.accounting_fail = True
                continue
            verified.append(rec)
            if rows > 0:
                next_raw.append(live)
                if live.get("deal_auto_foundation") or live.get("foundations"):
                    elapsed = time.perf_counter() - started
                    _note_foundation(out, live, elapsed, out.unique, out.expanded)
                if live.get("solved") and not out.solved:
                    out.solved = True
                    out.solution_g = int(live["g"])
                    out.solution_actions = as_actions(live["full_actions"])
                    end = opening.clone()
                    try:
                        cost = replay_actions(end, out.solution_actions)
                    except Exception:
                        out.accounting_fail = True
                    else:
                        out.replay_g = cost
                        out.replay_ok = cost == out.solution_g and end.is_solved()
                        if not out.replay_ok:
                            out.accounting_fail = True
                    stop = "solved"
            else:
                next_raw.append(rec)
        dedup = _dedup_roots(next_raw) if rows > 0 else {"raw": len(next_raw), "unique": len(next_raw), "convergences": 0, "states": list(next_raw)}
        out.epochs.append(
            {
                "stock_rows": rows,
                "input_roots": len(epoch_roots),
                "epoch_ceiling": epoch_ceil,
                "alloc_unique": alloc_u,
                "alloc_s": alloc_t,
                "alloc_unique_strategic": strategic_u,
                "alloc_s_strategic": strategic_t,
                "augment": augment_stats,
                "weight": epoch_weight(rows, n_ready),
                "unique": kr.unique,
                "expanded": kr.expanded,
                "generated": kr.generated,
                "duplicate_skips": kr.duplicate_skips,
                "stale_skips": kr.stale_skips,
                "elapsed_s": kr.elapsed_s,
                "stop_reason": kr.stop_reason,
                "min_g": kr.min_g,
                "max_g": kr.max_g,
                "min_face_down": epoch_min_fd,
                "max_foundations": epoch_max_f,
                "max_empty": epoch_max_empty,
                "best_construction": epoch_best_c,
                "best_readiness": epoch_best_r,
                "best_durability": epoch_best_d,
                "interference": None
                if epoch_debt_n == 0
                else {
                    "n": epoch_debt_n,
                    "min_boundaries": epoch_debt_min,
                    "mean_boundaries": epoch_debt_sum / epoch_debt_n,
                    "median_boundaries": sorted(epoch_debt_samples)[len(epoch_debt_samples) // 2]
                    if epoch_debt_samples
                    else None,
                    "selected_boundaries": None
                    if epoch_best_d is None
                    else epoch_best_d.get("boundaries_total"),
                },
                "n_ready": n_ready,
                "ready_suits": ready0.get("ready_suits"),
                "nearest_horizon": ready0.get("nearest_horizon"),
                "nearest_suits": ready0.get("nearest_suits"),
                "lane_exp": kr.lane_exp,
                "lane_pops": kr.lane_pops,
                "lane_stale": kr.lane_stale,
                "lower_bound_prunes": kr.lower_bound_prunes,
                "lower_bound_calls": kr.lower_bound_calls,
                "lower_bound_s": kr.lower_bound_s,
                "min_h": kr.min_h,
                "max_h": kr.max_h,
                "min_f": kr.min_f,
                "prunes_by_F": dict(kr.prunes_by_F),
                "portfolio": len(attached),
                "portfolio_cats": cat_counts,
                "deal_now_kept": cat_counts.get("deal_now", 0),
                "after_deal_raw": dedup["raw"] if rows > 0 else 0,
                "after_deal_unique": dedup["unique"] if rows > 0 else 0,
                "after_deal_convergences": dedup["convergences"] if rows > 0 else 0,
                "lineage_roots": sum(1 for r in epoch_roots if r.get("lineage")),
                "lineage_after_deal": 0
                if rows == 0
                else sum(1 for r in dedup["states"] if r.get("lineage")),
            }
        )
        if kr.stop_reason == "rss abort":
            stop = "rss abort"
            break
        if rows == 0:
            stop = kr.stop_reason or "complete"
            break
        if stop == "solved":
            break
        roots = dedup["states"]
        if not roots:
            stop = "no next-epoch roots"
            break
        if remaining_unique <= 0:
            stop = "unique limit"
            break

    out.elapsed_s = time.perf_counter() - started
    out.stop_reason = stop or "complete"
    out.states_per_s = 0.0 if out.elapsed_s <= 0 else out.expanded / out.elapsed_s
    if extra_track is not None:
        out.class_displaced = int(getattr(extra_track, "displaced", 0) or 0)
    if out.deal_illegal:
        out.accounting_fail = True
    return out


def choose_verdict(p: dict) -> Tuple[str, str]:
    if p.get("accounting_fail") or p.get("deal_illegal") or (p.get("solved") and not p.get("replay_ok")):
        return "EPOCH_PORTFOLIO_CONTRACT_FAILURE", "identity, Deal, provenance or replay contract failed"
    if p.get("solved") and p.get("replay_ok"):
        return "EPOCH_PORTFOLIO_AUTONOMOUS_SOLVE", "independently replayed complete solution"
    max_f = int(p.get("max_foundations") or 0)
    if max_f >= 2:
        return "EPOCH_PORTFOLIO_REACHES_F2_OR_BEYOND", f"max foundations {max_f}, unsolved"
    if max_f == 1:
        return "EPOCH_PORTFOLIO_REDISCOVERS_F1", "exactly one foundation from the opening"
    readiness = p.get("best_readiness") or {}
    cover = readiness.get("cover")
    min_fd = p.get("min_face_down")
    n_ready_any = any(int(ep.get("n_ready") or 0) > 0 for ep in (p.get("epochs") or []))
    if n_ready_any or (cover is not None and int(cover) <= 6) or (min_fd is not None and min_fd <= 16):
        return (
            "EPOCH_PORTFOLIO_IMPROVES_READINESS_NO_FOUNDATION",
            "no foundation, but material readiness / excavation improved versus inert F0 search",
        )
    return "EPOCH_PORTFOLIO_NO_MATERIAL_IMPROVEMENT", "no foundation and no meaningful readiness gain"


def save_solution(
    actions: Sequence[Action],
    path: Path,
    *,
    g: int,
    label: str = "Autonomous epoch-portfolio solution",
) -> None:
    deals = sum(1 for a in actions if is_deal(a))
    header = (
        f"{label}. Corrected MW={g}. "
        f"tableau={len(actions) - deals} deals={deals}."
    )
    export_actions_to_moves_file(list(actions), path, header=header)
