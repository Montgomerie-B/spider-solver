"""Research-only v0.56 component-aware Foundation-2 search.

Compact multi-lane best-first search over v0.55 portfolio + DEAL_NOW
controls.  Shared exact TT is pack_post_stock_symmetry_state + cheapest g.
Lane keys order only.  Search execution lives in search_kernel.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from spider.packed_state import unpack_state
from spider.research_actions import (
    as_actions,
    dump_actions,
    empty_column_indices,
    face_down_count,
    foundation_suits,
    opening_from_deal,
)
from spider.research_roots import dedup_roots, load_json_records, replay_root
from spider.search_kernel import SearchLimits, reconstruct_path, run_search
from spider.structural_analysis import INF, SUITS, all_lane_metrics, suit_lane_key

ROOT = Path(__file__).resolve().parents[2]
DEAL_PATH = ROOT / "deals" / "4925153.txt"
DEAL_NOW_PATH = ROOT / "docs" / "research" / "post_sd5_deal_now_roots_v0_44.json"
PORT_V055 = ROOT / "docs" / "research" / "sd5_component_aware_portfolio_v0_55.json"
EXPECTED_DEAL_NOW = 720
LANES = ("cost", "s", "h", "d", "c", "work")
COST_CEILING = 110
SEARCH_UNIQUE = 600_000
SEARCH_TIME_S = 420.0
SEARCH_RSS_MB = 2.5 * 1024.0
HARVEST_SLACK = 3
HARVEST_LIMIT = 128
SUIT_NAMES = {"s": "Spades", "h": "Hearts", "d": "Diamonds", "c": "Clubs"}


def opening_state():
    return opening_from_deal(DEAL_PATH)


def load_deal_now_roots(opening=None) -> dict:
    opening = opening or opening_state()
    fail = 0
    kept = []
    for rec in load_json_records(DEAL_NOW_PATH):
        item = replay_root(opening, rec, require_stock_zero=True, require_foundation_count=1, require_foundation_suit="s")
        if item is None:
            fail += 1
            continue
        item["timing"] = "DEAL_NOW"
        item["timings"] = ["DEAL_NOW"]
        item["prep_depth"] = 0
        item["prep_cost"] = 0
        kept.append(item)
    return {
        "raw": len(kept) + fail,
        "n": len(kept),
        "replay_fail": fail,
        "all_replay_ok": fail == 0 and len(kept) == 720,
        "states": kept,
    }


def union_roots(deal_now, prep):
    tagged = []
    for r in deal_now:
        tagged.append(r)
    for r in prep:
        tagged.append(r)
    out = dedup_roots(tagged)
    out["raw_deal_now"] = len(deal_now)
    out["raw_prep"] = len(prep)
    return out


def load_v055_portfolio(opening) -> dict:
    rows = load_json_records(PORT_V055)
    fail = 0
    kept = []
    for rec in rows:
        timing = rec.get("timing") or "PREP_THEN_DEAL"
        item = replay_root(
            opening,
            rec,
            require_stock_zero=True,
            require_foundation_count=1,
            require_foundation_suit="s",
        )
        if item is None:
            fail += 1
            continue
        item["timing"] = timing
        item["timings"] = [timing]
        item["category"] = rec.get("portfolio_cat")
        item["categories"] = [rec.get("portfolio_cat")] if rec.get("portfolio_cat") else []
        kept.append(item)
    return {
        "raw": len(rows),
        "n": len(kept),
        "replay_fail": fail,
        "all_replay_ok": fail == 0 and bool(kept),
        "timing": dict(Counter(r["timing"] for r in kept)),
        "categories": dict(Counter(r.get("category") for r in kept)),
        "states": kept,
    }


def _n(v, default=INF) -> int:
    return default if v is None else int(v)


def workspace_key(metrics_by_suit: dict, fd: int, empties: int, g: int) -> tuple:
    covers = [_n((metrics_by_suit.get(s) or {}).get("cover")) for s in SUITS]
    edges = sum(int((metrics_by_suit.get(s) or {}).get("edges") or 0) for s in SUITS)
    return (-int(empties), int(fd), min(covers), -edges, int(g))


def _better_progress(old: Optional[dict], new: dict, g: int) -> bool:
    if old is None:
        return True
    a = (
        _n(new.get("cover")),
        _n(new.get("visible")),
        -int(new.get("edges") or 0),
        -int(new.get("cond_len") or 0),
        _n(new.get("gap")),
        _n(new.get("fd")),
        g,
    )
    b = (
        _n(old.get("cover")),
        _n(old.get("visible")),
        -int(old.get("edges") or 0),
        -int(old.get("cond_len") or 0),
        _n(old.get("gap")),
        _n(old.get("fd")),
        int(old.get("g") or INF),
    )
    return a < b


@dataclass
class LaneF2Result:
    unique: int = 0
    expanded: int = 0
    generated: int = 0
    duplicate_skips: int = 0
    stale_skips: int = 0
    elapsed_s: float = 0.0
    peak_rss_mb: Optional[float] = None
    stop_reason: str = ""
    incumbent: Optional[int] = None
    first_s: Optional[float] = None
    first_unique: Optional[int] = None
    first_g: Optional[int] = None
    first_suit: Optional[str] = None
    first_timing: Optional[str] = None
    first_category: Optional[str] = None
    first_root_g: Optional[int] = None
    min_g: Optional[int] = None
    max_g: Optional[int] = None
    min_live_g: Optional[int] = None
    closed_g: Optional[int] = None
    sd5_expanded: bool = False
    accounting_fail: bool = False
    lane_pops: Dict[str, int] = field(default_factory=dict)
    lane_exp: Dict[str, int] = field(default_factory=dict)
    lane_stale: Dict[str, int] = field(default_factory=dict)
    best_progress: Dict[str, dict] = field(default_factory=dict)
    witnesses: List[dict] = field(default_factory=list)



def search_component_aware_f2(
    roots: Sequence[dict],
    *,
    max_unique: int = SEARCH_UNIQUE,
    time_limit_s: float = SEARCH_TIME_S,
    rss_abort_mb: float = SEARCH_RSS_MB,
    cost_ceiling: int = COST_CEILING,
    harvest_slack: int = HARVEST_SLACK,
    harvest_limit: int = HARVEST_LIMIT,
) -> LaneF2Result:
    progress: Dict[str, dict] = {}

    def on_child(state, g, _node):
        by = all_lane_metrics(state)
        for suit in SUITS:
            m = dict(by[suit])
            m["g"] = g
            if _better_progress(progress.get(suit), m, g):
                progress[suit] = m

    def lane_keys(state, g):
        by = all_lane_metrics(state)
        fd = face_down_count(state)
        empties = len(empty_column_indices(state))
        keys = {"cost": (g,)}
        for suit in SUITS:
            keys[suit] = suit_lane_key(by[suit], g)
        keys["work"] = workspace_key(by, fd, empties, g)
        return keys

    kr = run_search(
        roots,
        limits=SearchLimits(
            max_unique=max_unique,
            time_limit_s=time_limit_s,
            rss_abort_mb=rss_abort_mb,
            cost_ceiling=cost_ceiling,
            harvest_slack=harvest_slack,
        ),
        lane_names=LANES,
        lane_keys_fn=lane_keys,
        is_terminal=lambda st: len(st.foundations) == 2,
        on_child=on_child,
    )
    result = LaneF2Result(
        unique=kr.unique,
        expanded=kr.expanded,
        generated=kr.generated,
        duplicate_skips=kr.duplicate_skips,
        stale_skips=kr.stale_skips,
        elapsed_s=kr.elapsed_s,
        peak_rss_mb=kr.peak_rss_mb,
        stop_reason=kr.stop_reason,
        incumbent=kr.incumbent_g,
        min_g=kr.min_g,
        max_g=kr.max_g,
        min_live_g=kr.min_live_g,
        closed_g=kr.closed_g,
        first_s=kr.first_s,
        first_unique=kr.first_unique,
        lane_pops=kr.lane_pops,
        lane_exp=kr.lane_exp,
        lane_stale=kr.lane_stale,
        best_progress=progress,
    )
    witnesses = []
    for term in kr.terminals:
        st = unpack_state(bytes.fromhex(term["store"]))
        if len(st.foundations) != 2:
            result.accounting_fail = True
            continue
        src = roots[term["origin"]]
        suits = foundation_suits(st)
        new_suit = suits[-1] if suits else None
        path = reconstruct_path(kr.nodes, term["node"])
        rec_w = {
            "origin": term["origin"],
            "g": term["g"],
            "root_g": int(src["g"]),
            "continuation_mw": term["g"] - int(src["g"]),
            "actions": dump_actions(path),
            "full_actions": dump_actions(as_actions(src["full_actions"]) + path),
            "final_action": dump_actions([term["action"]])[0],
            "ordered_digest": term["store"],
            "symmetry_digest": term["ident"],
            "suit": new_suit,
            "suit_name": SUIT_NAMES.get(new_suit or "", new_suit),
            "foundation_count": len(st.foundations),
            "foundation_suits": suits,
            "timing": src.get("timing"),
            "category": src.get("category"),
            "prep_depth": src.get("prep_depth"),
            "prep_cost": src.get("prep_cost"),
            "fd": face_down_count(st),
            "empties": [i + 1 for i in empty_column_indices(st)],
        }
        witnesses.append(rec_w)
        if result.first_g is None:
            result.first_g = term["g"]
            result.first_suit = new_suit
            result.first_timing = src.get("timing")
            result.first_category = src.get("category")
            result.first_root_g = int(src["g"])
    witnesses.sort(key=lambda w: (w["g"], w.get("suit") or "", w["ordered_digest"]))
    if result.incumbent is not None:
        f = result.incumbent
        witnesses = [w for w in witnesses if w["g"] <= f + harvest_slack][:harvest_limit]
    result.witnesses = witnesses
    return result

def choose_verdict(p: dict) -> Tuple[str, str]:
    if not p.get("all_replay_ok"):
        return "CONTRACT_FAILURE", "root replay failed"
    if p.get("accounting_fail") or p.get("replay_fail"):
        return "CONTRACT_FAILURE", "Foundation-2 replay or accounting disagreed with the engine"
    if p.get("reached"):
        return "COMPONENT_AWARE_FOUNDATION2_REACHED", "replay-valid second foundation found"
    improved = p.get("topology_improved")
    stop = p.get("stop_reason")
    if improved:
        return "COMPONENT_AWARE_SEARCH_IMPROVES_TOPOLOGY_NO_F2", "no F2, but descendants beat v0.55 root component classes"
    if stop in ("unique limit", "rss abort"):
        return "COMPONENT_AWARE_SEARCH_STATE_EXPLOSION", "unique/RSS envelope exhausted without Foundation 2"
    return "COMPONENT_AWARE_FOUNDATION2_NOT_FOUND", "bounded experiment finished without F2 or a new topology class"
