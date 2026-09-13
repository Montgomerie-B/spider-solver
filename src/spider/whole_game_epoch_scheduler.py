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
) -> Tuple[List[dict], Dict[str, int]]:
    buckets: Dict[str, List[dict]] = {cat: tops[cat].best() for cat in tops}
    deal_now = [r for r in roots if int(r["g"]) == int(min_root_g)]
    buckets["deal_now"] = sorted(deal_now, key=lambda r: (r["g"], r.get("ordered_digest", "")))[:PER_CAT]
    pool = []
    seen_pool = set()
    for cat, rows in buckets.items():
        for rec in rows:
            ident = rec.get("ident") or rec.get("whole_game_identity")
            if ident in seen_pool:
                continue
            seen_pool.add(ident)
            pool.append(rec)
    pareto = []
    for rec in pool:
        if any(_dominates(o, rec) for o in pool if o is not rec):
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
    while len(picked) < width:
        progressed = False
        for cat in HARVEST_CATS:
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
        if rec["g"] < prev["g"]:
            item = dict(rec)
            item["categories"] = cats
            classes[ident] = item
        else:
            prev["categories"] = cats
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
) -> EpochPortfolioResult:
    opening = opening or opening_state()
    started = time.perf_counter()
    out = EpochPortfolioResult()
    out.opening_horizons = foundation_readiness(opening)
    roots = [opening_root(opening)]
    roots[0]["ident"] = roots[0]["whole_game_identity"]
    roots[0]["timings"] = ["OPENING"]
    roots[0]["categories"] = ["deal_now"]
    out.min_face_down = face_down_count(opening)
    out.max_empty = 0
    remaining_unique = max_unique
    stop = ""

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
        min_root_g = min(int(r["g"]) for r in roots)
        tops = {cat: _Top() for cat in HARVEST_CATS}
        epoch_min_fd = None
        epoch_max_f = 0
        epoch_max_empty = 0
        epoch_best_c = None
        epoch_best_r = None

        def on_progress(kr: KernelResult, state: SpiderState, g: int, node: int) -> None:
            nonlocal epoch_min_fd, epoch_max_f, epoch_max_empty, epoch_best_c, epoch_best_r
            if stock_rows(state) != rows:
                out.accounting_fail = True
            s = current_tableau_summary(state)
            rdy = foundation_readiness(state)
            rec = _snapshot_rec(state, g, node, rdy, s)
            rec["origin"] = kr.nodes[node].origin if node < len(kr.nodes) else 0
            elapsed = time.perf_counter() - started
            _note_foundation(out, rec, elapsed, kr.unique, kr.expanded)
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
            tops["cheap"].add((rec["g"], rec["ordered_digest"]), rec)
            tops["foundations"].add((-rec["foundations"], rec["g"], rec["ordered_digest"]), rec)
            tops["min_fd"].add((rec["face_down"], rec["g"], rec["ordered_digest"]), rec)
            tops["workspace"].add((-rec["empty_n"], rec["face_down"], rec["g"]), rec)
            tops["construction"].add((-rec["bonds"], -rec["longest"], -rec["merges"], rec["g"]), rec)
            if rec["n_ready"]:
                tops["readiness"].add(
                    (
                        _n(rec.get("cover")),
                        _n(rec.get("ready_fd")),
                        -int(rec.get("ready_edges") or 0),
                        rec["g"],
                    ),
                    rec,
                )
                suit = rec.get("best_ready_suit") or "_"
                tops["ready_div"].add((_n(rec.get("cover")), rec["g"], suit), rec)
            else:
                tops["horizon"].add(
                    (_n(rec.get("nearest_horizon")), -rec["bonds"], rec["g"]),
                    rec,
                )
            if rec["g"] == min_root_g:
                tops["deal_now"].add((rec["g"], rec["ordered_digest"]), rec)

        kr = run_search(
            roots,
            limits=SearchLimits(
                max_unique=alloc_u,
                time_limit_s=alloc_t,
                rss_abort_mb=rss_abort_mb,
                cost_ceiling=cost_ceiling,
            ),
            identity_fn=pack_whole_game_identity,
            store_fn=pack_state,
            unpack_fn=unpack_state,
            lane_names=LANES,
            lane_keys_fn=epoch_lane_keys,
            is_terminal=lambda st: st.is_solved(),
            actions_fn=tableau_actions,
            on_progress=on_progress,
        )
        out.unique += kr.unique
        remaining_unique = max_unique - out.unique
        out.expanded += kr.expanded
        out.generated += kr.generated
        out.duplicate_skips += kr.duplicate_skips
        out.stale_skips += kr.stale_skips
        if kr.peak_rss_mb is not None and (out.peak_rss_mb is None or kr.peak_rss_mb > out.peak_rss_mb):
            out.peak_rss_mb = kr.peak_rss_mb
        for name in LANES:
            out.lane_exp[name] = out.lane_exp.get(name, 0) + kr.lane_exp.get(name, 0)
            out.lane_pops[name] = out.lane_pops.get(name, 0) + kr.lane_pops.get(name, 0)
            out.lane_stale[name] = out.lane_stale.get(name, 0) + kr.lane_stale.get(name, 0)
        out.min_g = kr.min_g if out.min_g is None else min(out.min_g, kr.min_g if kr.min_g is not None else out.min_g)
        out.max_g = kr.max_g if out.max_g is None else max(out.max_g, kr.max_g if kr.max_g is not None else out.max_g)

        if kr.terminals:
            best = min(kr.terminals, key=lambda t: (t["g"], t["store"]))
            kn = kr.nodes[best["node"]]
            src = roots[kn.origin]
            path = reconstruct_path(kr.nodes, best["node"])
            full = as_actions(src.get("full_actions") or []) + path
            out.solved = True
            out.solution_g = int(best["g"])
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
            stop = "solved"
            out.epochs.append(
                {
                    "stock_rows": rows,
                    "input_roots": len(roots),
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
                }
            )
            break

        picked, cat_counts = harvest_portfolio(tops, roots, min_root_g, width=portfolio_width)
        attached = _attach_paths(picked, roots, kr)
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
                "input_roots": len(roots),
                "alloc_unique": alloc_u,
                "alloc_s": alloc_t,
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
                "n_ready": n_ready,
                "ready_suits": ready0.get("ready_suits"),
                "nearest_horizon": ready0.get("nearest_horizon"),
                "nearest_suits": ready0.get("nearest_suits"),
                "lane_exp": kr.lane_exp,
                "lane_pops": kr.lane_pops,
                "lane_stale": kr.lane_stale,
                "portfolio": len(attached),
                "portfolio_cats": cat_counts,
                "deal_now_kept": cat_counts.get("deal_now", 0),
                "after_deal_raw": dedup["raw"] if rows > 0 else 0,
                "after_deal_unique": dedup["unique"] if rows > 0 else 0,
                "after_deal_convergences": dedup["convergences"] if rows > 0 else 0,
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


def save_solution(actions: Sequence[Action], path: Path, *, g: int) -> None:
    deals = sum(1 for a in actions if is_deal(a))
    header = (
        f"Autonomous v0.59 epoch-portfolio solution. Corrected MW={g}. "
        f"tableau={len(actions) - deals} deals={deals}."
    )
    export_actions_to_moves_file(list(actions), path, header=header)
