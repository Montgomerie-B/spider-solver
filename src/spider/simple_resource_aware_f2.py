"""Research-only v0.54 resource-aware post-SD5 Foundation-2 search.

Exact UCS from all 720 DEAL_NOW roots plus the v0.53 PREP_THEN_DEAL
portfolio members.  Identity is pack_post_stock_symmetry_state.
No suit target, no low-tail constraint, no Deal, no Foundation 3.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from spider.engine import SpiderState
from spider.metrics import Action
from spider.packed_state import unpack_state
from spider.research_actions import (
    as_actions,
    dump_actions,
    empty_column_indices,
    face_down_count,
    foundation_suits,
    opening_from_deal,
)
from spider.research_roots import replay_root
from spider.search_kernel import SearchLimits, reconstruct_path, run_search
from spider.structural_analysis import same_suit_components

ROOT = Path(__file__).resolve().parents[2]
DEAL_PATH = ROOT / "deals" / "4925153.txt"
DEAL_NOW_PATH = ROOT / "docs" / "research" / "post_sd5_deal_now_roots_v0_44.json"
PORT_V053 = ROOT / "docs" / "research" / "sd5_resource_aware_portfolio_v0_53.json"


def opening_state():
    return opening_from_deal(DEAL_PATH)
EXPECTED_DEAL_NOW = 720
EXPECTED_PREP_APPROX = 244
COST_CEILING = 110
SEARCH_UNIQUE = 600_000
SEARCH_TIME_S = 420.0
SEARCH_RSS_MB = 2.5 * 1024.0
HARVEST_SLACK = 3
HARVEST_LIMIT = 128
SUIT_NAMES = {"s": "Spades", "h": "Hearts", "d": "Diamonds", "c": "Clubs"}

RANK_F2 = 0
RANK_JOIN = 1
RANK_REVEAL = 2
RANK_EMPTY = 3
RANK_LONG = 4
RANK_OTHER = 5


def would_remove_foundation(state: SpiderState, action: Action) -> bool:
    if action == ("deal",):
        return False
    src, dst, k = action
    run = state.columns[src].face_up[-k:]
    combined = state.columns[dst].face_up + run
    if len(combined) < 13:
        return False
    tail = combined[-13:]
    return tail[0].rank == 13 and SpiderState.is_movable_run(tail)


def annotate_f2_order(state: SpiderState, action: Action) -> int:
    """Ordering only. Never legality."""

    if action == ("deal",):
        return 9
    if would_remove_foundation(state, action):
        return RANK_F2
    src, dst, k = action
    sc = state.columns[src]
    dc = state.columns[dst]
    run = sc.face_up[-k:]
    head = run[0]
    dest_top = dc.top()
    if dest_top is not None and dest_top.suit == head.suit and dest_top.rank == head.rank + 1:
        return RANK_JOIN
    if k == len(sc.face_up) and sc.face_down:
        return RANK_REVEAL
    if k == len(sc.face_up) and not sc.face_down:
        return RANK_EMPTY
    if k >= 3 and all(c.suit == head.suit for c in run):
        return RANK_LONG
    return RANK_OTHER


def _replay_root(opening: SpiderState, rec: dict, *, timing: str) -> Optional[dict]:
    item = replay_root(
        opening,
        rec,
        require_stock_zero=True,
        require_foundation_count=1,
        require_foundation_suit="s",
    )
    if item is None:
        return None
    item["timing"] = timing
    item["timings"] = [timing]
    item["category"] = rec.get("portfolio_cat") or rec.get("category")
    item["categories"] = [item["category"]] if item.get("category") else list(rec.get("categories") or [])
    item["lineages"] = list(rec.get("lineages") or [])
    item["prep_depth"] = rec.get("prep_depth", 0 if timing == "DEAL_NOW" else rec.get("prep_depth"))
    item["prep_cost"] = rec.get("prep_cost", 0 if timing == "DEAL_NOW" else rec.get("prep_cost"))
    return item


def load_deal_now_roots(opening: Optional[SpiderState] = None) -> dict:
    opening = opening or opening_state()
    raw = json.loads(DEAL_NOW_PATH.read_text(encoding="utf-8"))
    rows = list(raw.get("states") or [])
    fail = 0
    kept = []
    for rec in rows:
        item = _replay_root(opening, rec, timing="DEAL_NOW")
        if item is None:
            fail += 1
            continue
        item["prep_depth"] = 0
        item["prep_cost"] = 0
        kept.append(item)
    return {
        "raw": len(rows),
        "expected": EXPECTED_DEAL_NOW,
        "n": len(kept),
        "replay_fail": fail,
        "all_replay_ok": fail == 0 and len(rows) == EXPECTED_DEAL_NOW,
        "cost_counts": {str(k): int(v) for k, v in sorted(Counter(r["g"] for r in kept).items())},
        "states": kept,
    }


def load_prep_roots(opening: Optional[SpiderState] = None) -> dict:
    opening = opening or opening_state()
    raw = json.loads(PORT_V053.read_text(encoding="utf-8"))
    rows = [r for r in list(raw.get("states") or []) if r.get("timing") == "PREP_THEN_DEAL"]
    fail = 0
    kept = []
    for rec in rows:
        item = _replay_root(opening, rec, timing="PREP_THEN_DEAL")
        if item is None:
            fail += 1
            continue
        kept.append(item)
    return {
        "raw": len(rows),
        "expected_approx": EXPECTED_PREP_APPROX,
        "n": len(kept),
        "replay_fail": fail,
        "all_replay_ok": fail == 0 and bool(kept),
        "categories": dict(Counter(r.get("category") for r in kept)),
        "cost_counts": {str(k): int(v) for k, v in sorted(Counter(r["g"] for r in kept).items())},
        "states": kept,
    }


def union_roots(deal_now: Sequence[dict], prep: Sequence[dict]) -> dict:
    classes: Dict[bytes, dict] = {}
    convergences = 0
    for rec in list(deal_now) + list(prep):
        ident = bytes.fromhex(rec["symmetry_digest"])
        prev = classes.get(ident)
        if prev is None:
            item = dict(rec)
            item["timings"] = list(rec.get("timings") or [rec["timing"]])
            item["categories"] = list(rec.get("categories") or [])
            item["lineages"] = list(rec.get("lineages") or [])
            classes[ident] = item
            continue
        timings = sorted(set(prev["timings"]) | set(rec.get("timings") or [rec["timing"]]))
        if rec["timing"] != prev["timing"] or (len(timings) > 1):
            convergences += 1
        if rec["g"] < prev["g"]:
            item = dict(rec)
            item["timings"] = timings
            item["categories"] = sorted(set((prev.get("categories") or []) + (rec.get("categories") or [])))
            item["lineages"] = sorted(set((prev.get("lineages") or []) + (rec.get("lineages") or [])))
            item["timing"] = "MULTIPLE" if len(timings) > 1 else rec["timing"]
            classes[ident] = item
        else:
            prev["timings"] = timings
            prev["categories"] = sorted(set((prev.get("categories") or []) + (rec.get("categories") or [])))
            prev["lineages"] = sorted(set((prev.get("lineages") or []) + (rec.get("lineages") or [])))
            if len(timings) > 1:
                prev["timing"] = "MULTIPLE"
    kept = sorted(classes.values(), key=lambda r: (r["g"], r["ordered_digest"]))
    return {
        "raw_deal_now": len(deal_now),
        "raw_prep": len(prep),
        "combined_raw": len(deal_now) + len(prep),
        "symmetry_unique": len(kept),
        "convergences": convergences,
        "cost_counts": {str(k): int(v) for k, v in sorted(Counter(r["g"] for r in kept).items())},
        "timing": dict(Counter(r["timing"] for r in kept)),
        "prep_categories": dict(Counter(c for r in kept if r["timing"] != "DEAL_NOW" for c in (r.get("categories") or []))),
        "states": kept,
    }


@dataclass
class F2Result:
    unique: int = 0
    expanded: int = 0
    generated: int = 0
    duplicate_skips: int = 0
    elapsed_s: float = 0.0
    peak_rss_mb: Optional[float] = None
    stop_reason: str = ""
    incumbent: Optional[int] = None
    first_s: Optional[float] = None
    first_unique: Optional[int] = None
    first_g: Optional[int] = None
    first_suit: Optional[str] = None
    first_timing: Optional[str] = None
    first_root_g: Optional[int] = None
    first_continuation: Optional[int] = None
    first_action: Optional[list] = None
    sd5_expanded: bool = False
    witnesses: List[dict] = field(default_factory=list)
    min_live_g: Optional[int] = None
    closed_g: Optional[int] = None
    accounting_fail: bool = False


def search_foundation2(
    roots: Sequence[dict],
    *,
    max_unique: int = SEARCH_UNIQUE,
    time_limit_s: float = SEARCH_TIME_S,
    rss_abort_mb: float = SEARCH_RSS_MB,
    cost_ceiling: int = COST_CEILING,
    harvest_slack: int = HARVEST_SLACK,
    harvest_limit: int = HARVEST_LIMIT,
) -> F2Result:
    result = F2Result()
    witnesses: Dict[bytes, dict] = {}
    baseline = 1

    def is_terminal(state):
        return len(state.foundations) > baseline

    def action_order(state, actions):
        ranked = []
        for action in actions:
            if action == ("deal",):
                result.sd5_expanded = True
                continue
            ranked.append((annotate_f2_order(state, action), action))
        ranked.sort(key=lambda t: (t[0], t[1]))
        return [a for _r, a in ranked]

    def on_child(state, _g, _node):
        if state.stock:
            result.sd5_expanded = True

    kr = run_search(
        roots,
        limits=SearchLimits(
            max_unique=max_unique,
            time_limit_s=time_limit_s,
            rss_abort_mb=rss_abort_mb,
            cost_ceiling=cost_ceiling,
            harvest_slack=harvest_slack,
        ),
        lane_names=("cost",),
        lane_key_fns=[lambda st, g: (g,)],
        is_terminal=is_terminal,
        action_order=action_order,
        on_child=on_child,
    )
    result.unique = kr.unique
    result.expanded = kr.expanded
    result.generated = kr.generated
    result.duplicate_skips = kr.duplicate_skips
    result.elapsed_s = kr.elapsed_s
    result.peak_rss_mb = kr.peak_rss_mb
    result.stop_reason = kr.stop_reason
    result.incumbent = kr.incumbent_g
    result.min_live_g = kr.min_live_g
    result.closed_g = kr.closed_g
    result.first_s = kr.first_s
    result.first_unique = kr.first_unique
    current_incumbent = kr.incumbent_g

    for term in kr.terminals:
        st = unpack_state(bytes.fromhex(term["store"]))
        hit = len(st.foundations) > baseline
        if hit:
            if len(st.foundations) != 2:
                result.accounting_fail = True
        else:
            result.accounting_fail = True
            continue
        src = roots[term["origin"]]
        suits = foundation_suits(st)
        new_suit = suits[-1] if suits else None
        path = reconstruct_path(kr.nodes, term["node"])
        child_sym = bytes.fromhex(term["ident"])
        rec_w = {
            "origin": term["origin"],
            "g": term["g"],
            "root_g": int(src["g"]),
            "continuation_mw": term["g"] - int(src["g"]),
            "depth": len(path),
            "actions": dump_actions(path),
            "full_actions": dump_actions(as_actions(src["full_actions"]) + path),
            "final_action": dump_actions([term["action"]])[0],
            "ordered_digest": term["store"],
            "symmetry_digest": term["ident"],
            "suit": new_suit,
            "suit_name": SUIT_NAMES.get(new_suit or "", new_suit),
            "foundation_count": len(st.foundations),
            "foundation_suits": suits,
            "timing": src["timing"],
            "timings": list(src.get("timings") or [src["timing"]]),
            "category": src.get("category"),
            "categories": list(src.get("categories") or []),
            "lineages": list(src.get("lineages") or []),
            "prep_depth": src.get("prep_depth"),
            "prep_cost": src.get("prep_cost"),
            "fd": face_down_count(st),
            "empties": [i + 1 for i in empty_column_indices(st)],
            "components": same_suit_components(st),
        }
        if child_sym not in witnesses or term["g"] < witnesses[child_sym]["g"]:
            witnesses[child_sym] = rec_w
        if result.first_g is None:
            result.first_g = term["g"]
            result.first_suit = new_suit
            result.first_timing = src["timing"]
            result.first_root_g = int(src["g"])
            result.first_continuation = term["g"] - int(src["g"])
            result.first_action = dump_actions([term["action"]])[0]

    f = current_incumbent
    kept: List[dict] = []
    if f is not None:
        eligible = [w for w in witnesses.values() if w["g"] <= f + harvest_slack]
        eligible.sort(key=lambda w: (w["g"], w.get("suit") or "", w.get("timing") or "", w["ordered_digest"]))
        buckets: Dict[tuple, List[dict]] = defaultdict(list)
        for w in eligible:
            buckets[(w.get("suit"), w.get("timing"), w["g"] - f)].append(w)
        seen = set()
        while len(kept) < harvest_limit:
            progressed = False
            for key in sorted(buckets, key=str):
                while buckets[key]:
                    w = buckets[key].pop(0)
                    if w["symmetry_digest"] in seen:
                        continue
                    seen.add(w["symmetry_digest"])
                    kept.append(w)
                    progressed = True
                    break
                if len(kept) >= harvest_limit:
                    break
            if not progressed:
                break
    result.witnesses = kept
    return result


def choose_verdict(p: dict) -> Tuple[str, str]:
    if not p.get("all_replay_ok"):
        return "SOURCE_REPLAY_FAILURE", "DEAL_NOW or PREP roots failed replay"
    if p.get("accounting_fail"):
        return "FOUNDATION_ACCOUNTING_CONTRACT_FAILURE", "engine foundation count was not exactly 2"
    if p.get("reached"):
        timings = set(p.get("witness_timings") or [])
        timings.discard("MULTIPLE")
        if "DEAL_NOW" in timings and "PREP_THEN_DEAL" in timings:
            return "FOUNDATION2_REACHED_FROM_MULTIPLE_ORIGINS", "Foundation 2 from both DEAL_NOW and PREP roots"
        if p.get("first_timing") == "PREP_THEN_DEAL" or timings == {"PREP_THEN_DEAL"}:
            return "FOUNDATION2_REACHED_FROM_PREP", "first Foundation 2 descended from a resource-aware PREP root"
        return "FOUNDATION2_REACHED_FROM_DEAL_NOW", "first Foundation 2 descended from a DEAL_NOW root"
    stop = p.get("stop_reason")
    if stop in ("unique limit", "rss abort"):
        return "RESOURCE_AWARE_SEARCH_STATE_EXPLOSION", "Foundation 2 not found before unique/RSS limit"
    if stop in ("time limit", "complete", "harvested") or p.get("search_attempted"):
        return "RESOURCE_AWARE_FOUNDATION2_NOT_FOUND", "no Foundation 2 inside MW<=110 from the condensed root union"
    return "INCONCLUSIVE", "resource-aware Foundation-2 search finished without a classified outcome"
