"""Research-only v0.45 SD5 Spade receiving planner.

Pre-SD5 column-8 suffix ending in 2S is the receiver for the known AS landing.
Canonical identity is ordered pack_state before SD5 and post-stock symmetry
after.  Target progress is not identity.  Tableau only after the single Deal.
"""

from __future__ import annotations

import heapq
import json
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.metrics import Action, replay_actions
from spider.packed_state import pack_post_stock_symmetry_state, pack_state, unpack_state
from spider.simple_current_horizon import occurrence_counts
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_c_bridge import as_actions, dump_actions, opening_state
from spider.simple_final_deal_timing import (
    PREP_COST,
    PREP_DEPTH,
    PREP_TIME_S,
    PREP_UNIQUE,
    deal_is_legal,
    enumerate_preparation,
    foundation_suits,
    verify_sd5_row,
)
from spider.simple_foundation_horizon import pretty_card, stock_deal_rows
from spider.simple_foundation_race import suit_foundation_count
from spider.simple_progressive_solver import (
    _capture,
    _restore,
    _rss_mb,
    apply_action,
    step_cost,
)
from spider.simple_workspace_reachability import empty_column_indices, engine_tableau_actions, face_down_count

ROOT = Path(__file__).resolve().parents[2]
V043_SOURCES = ROOT / "docs" / "research" / "final_deal_sources_v0_43.json"
EXPECTED_SOURCES = 720
RECEIVE_COL = 7  # column 8
TAIL4_RANKS = (4, 3, 2, 1)
TAIL5_RANKS = (5, 4, 3, 2, 1)
PORTFOLIO_CAP = 512
TAIL4_UNIQUE = 250_000
TAIL4_TIME_S = 300.0
TAIL4_DEPTH = 6
HARVEST_SLACK = 3
HARVEST_LIMIT = 256
RSS_ABORT_MB = 2.5 * 1024.0
V044_BEST_TAIL3 = 85
V044_TAIL3_N = 64


def load_pre_sd5_sources(opening: Optional[SpiderState] = None) -> dict:
    opening = opening or opening_state()
    payload = json.loads(V043_SOURCES.read_text(encoding="utf-8"))
    seen: Dict[bytes, dict] = {}
    replay_failures = 0
    chain_ok = True
    discrepancies = []
    sd5_audit = None
    for rec in payload.get("states") or []:
        full = as_actions(rec.get("full_actions") or [])
        end = opening.clone()
        try:
            cost = replay_actions(end, full)
        except Exception:
            replay_failures += 1
            continue
        ident = pack_state(end)
        ok = (
            cost == rec.get("full_cost")
            and ident.hex() == rec.get("ordered_digest")
            and stock_rows(end) == 1
            and len(end.foundations) == 1
            and end.foundations[0][0].suit == "s"
            and deal_is_legal(end)
        )
        if not ok:
            replay_failures += 1
            continue
        if sd5_audit is None:
            sd5_audit = verify_sd5_row(end)
            row = stock_deal_rows(end.stock)[0]
            sd5_audit["as_column_8"] = pretty_card(row[RECEIVE_COL]) == "AS"
        chk = verify_unique_spade_chain(end)
        if not chk["ok"]:
            chain_ok = False
            discrepancies.append(chk)
        item = {
            "ordered_digest": ident.hex(),
            "full_cost": cost,
            "full_actions": dump_actions(full),
            "lineages": rec.get("lineages") or [],
        }
        prev = seen.get(ident)
        if prev is None or cost < prev["full_cost"]:
            if prev is not None:
                item["lineages"] = sorted(set(prev["lineages"]) | set(item["lineages"]))
            seen[ident] = item
        else:
            prev["lineages"] = sorted(set(prev["lineages"]) | set(item["lineages"]))
    kept = sorted(seen.values(), key=lambda r: (r["full_cost"], r["ordered_digest"]))
    return {
        "n": len(kept),
        "expected": EXPECTED_SOURCES,
        "replay_failures": replay_failures,
        "all_replay_ok": replay_failures == 0 and len(kept) == EXPECTED_SOURCES,
        "spade_chain_ok": chain_ok and not discrepancies,
        "discrepancies": discrepancies[:8],
        "sd5_audit": sd5_audit,
        "cost_counts": {str(k): int(v) for k, v in sorted(Counter(r["full_cost"] for r in kept).items())},
        "lineage_counts": dict(Counter(lin for r in kept for lin in r["lineages"])),
        "states": kept,
    }


def verify_unique_spade_chain(state: SpiderState) -> dict:
    ranks = {}
    ok = True
    for rank in range(2, 14):
        rec = occurrence_counts(state, "s", rank)
        ranks[rank] = rec["tableau_count"]
        if rec["tableau_count"] != 1:
            ok = False
    ace = occurrence_counts(state, "s", 1)
    row = stock_deal_rows(state.stock)[0] if stock_rows(state) == 1 else []
    as_in_sd5 = bool(row) and pretty_card(row[RECEIVE_COL]) == "AS"
    as_tableau = ace["tableau_count"]
    if as_tableau != 0 or ace["future_stock_count"] != 1 or not as_in_sd5:
        ok = False
    return {
        "ok": ok,
        "tableau_ranks_2_13": ranks,
        "as_tableau": as_tableau,
        "as_in_sd5_c8": as_in_sd5,
        "as_future_stock": ace["future_stock_count"],
    }


def spade_receiver_length(state: SpiderState) -> int:
    """Contiguous same-suit descending Spade suffix ending in 2S at top of column 8."""

    up = state.columns[RECEIVE_COL].face_up
    if not up or up[-1].suit != "s" or up[-1].rank != 2:
        return 0
    i = len(up) - 1
    lo = i
    while lo > 0 and up[lo - 1].suit == "s" and up[lo - 1].rank == up[lo].rank + 1:
        lo -= 1
    return i - lo + 1


def column8_top(state: SpiderState) -> List[str]:
    up = state.columns[RECEIVE_COL].face_up
    return [pretty_card(c) for c in up[-6:]]


def spade_low_tail_length(state: SpiderState) -> int:
    """Length of the unique remaining AS-containing Spade suffix (tableau only)."""

    if suit_foundation_count(state, "s") >= 2:
        return 13
    best = 0
    for column in state.columns:
        up = column.face_up
        for i, card in enumerate(up):
            if card.suit != "s" or card.rank != 1:
                continue
            lo = i
            while lo > 0 and up[lo - 1].suit == "s" and up[lo - 1].rank == up[lo].rank + 1:
                lo -= 1
            best = max(best, i - lo + 1)
    return best


def spade_tail_present(state: SpiderState, length: int) -> bool:
    """True if a contiguous Spade packet of ranks length..1 exists (engine bottom-to-top)."""

    if length <= 0:
        return True
    if suit_foundation_count(state, "s") >= 2:
        return True
    want = list(range(length, 0, -1))
    for column in state.columns:
        up = column.face_up
        for i in range(0, len(up) - length + 1):
            run = up[i : i + length]
            if all(c.suit == "s" for c in run) and [c.rank for c in run] == want:
                return True
    return False


def tail4_is_mandatory() -> str:
    return (
        "The remaining Spade chain is physically unique, so any second Spade "
        "foundation's K-A run contains 4S-3S-2S-AS.  TAIL4 is a proof-safe "
        "trajectory obligation once Spades are the target."
    )


def locate_spade_rank(state: SpiderState, rank: int) -> dict:
    rec = occurrence_counts(state, "s", rank)
    tab = rec["tableau"]
    if not tab:
        nxt = rec["next_stock"]
        return {"zone": "SD5" if nxt else "absent", "tableau": tab, "next_stock": nxt}
    o = tab[0]
    return {
        "zone": "tableau",
        "column_1": o.get("column_1"),
        "face_up": o.get("face_up"),
        "top": o.get("top"),
        "cards_above": o.get("cards_above"),
    }


def receiver_labels(pre: SpiderState, post: SpiderState, prep_actions) -> List[str]:
    labels = []
    r = spade_receiver_length(pre)
    if r == 1:
        labels.append("AS_RECEIVED_ON_2S")
    elif r == 2:
        labels.append("AS_RECEIVED_ON_3S_2S")
    elif r >= 3:
        labels.append("AS_RECEIVED_ON_LONGER_SPADE_TAIL")
    if prep_actions:
        pre0_2 = locate_spade_rank(pre, 2)
        # cannot see original without source; use prep non-empty as relocated signal if 2S now on c8
        if r >= 1:
            labels.append("PREP_RELOCATED_2S")
        if r >= 2:
            labels.append("PREP_RELOCATED_3S")
        if r >= 1 and spade_receiver_length(pre) >= 1:
            labels.append("PREP_CLEARED_C8")
    tail = spade_low_tail_length(post)
    if tail >= 2:
        labels.append("POSTDEAL_SAME_SUIT_BUILD")
    return labels


def measure_and_deal(opening: SpiderState, candidates: Sequence[dict]) -> dict:
    classes: Dict[bytes, dict] = {}
    pred_ok = 0
    pred_fail = 0
    dist_pre = Counter()
    dist_post = Counter()
    by_len_cost = defaultdict(list)
    for rec in candidates:
        pre = opening.clone()
        replay_actions(pre, as_actions(rec["full_actions_pre"]))
        r = spade_receiver_length(pre)
        dist_pre[r] += 1
        before_f = len(pre.foundations)
        apply_action(pre, ("deal",))
        post = pre
        g = rec["g"] + 1
        tail = spade_low_tail_length(post)
        dist_post[tail] += 1
        predicted = r + 1 if r >= 1 else (1 if post.columns[RECEIVE_COL].top() and pretty_card(post.columns[RECEIVE_COL].top()) == "AS" else tail)
        if r >= 1 and tail == r + 1:
            pred_ok += 1
        elif r >= 1:
            pred_fail += 1
        ident_ord = pack_state(post)
        ident_sym = pack_post_stock_symmetry_state(post)
        item = {
            "g": g,
            "prep_depth": rec["prep_depth"],
            "prep_cost": rec["prep_cost"],
            "timing": rec["timing"],
            "lineages": rec["lineages"],
            "receiver_length": r,
            "low_tail": tail,
            "predicted_tail": r + 1 if r >= 1 else None,
            "ordered_digest": ident_ord.hex(),
            "symmetry_digest": ident_sym.hex(),
            "full_actions": dump_actions(as_actions(rec["full_actions_pre"]) + [("deal",)]),
            "prep_actions": rec["prep_actions"],
            "auto_removed": len(post.foundations) - before_f,
            "labels": receiver_labels_from_r(r, rec["prep_depth"]),
            "origin": rec["origin"],
        }
        # capture pre column-8 from a clone
        pre2 = opening.clone()
        replay_actions(pre2, as_actions(rec["full_actions_pre"]))
        item["column8_pre"] = column8_top(pre2)
        item["loc_2s_pre"] = locate_spade_rank(pre2, 2)
        item["loc_3s_pre"] = locate_spade_rank(pre2, 3)
        item["loc_4s_pre"] = locate_spade_rank(pre2, 4)
        item["loc_5s_pre"] = locate_spade_rank(pre2, 5)
        prev = classes.get(ident_sym)
        if prev is None or g < prev["g"]:
            classes[ident_sym] = item
        by_len_cost[tail].append(g)
    kept = sorted(classes.values(), key=lambda r: (-r["low_tail"], r["g"], r["ordered_digest"]))
    cheapest = {}
    for rec in kept:
        L = rec["low_tail"]
        if L not in cheapest or rec["g"] < cheapest[L]["g"]:
            cheapest[L] = {"g": rec["g"], "timing": rec["timing"], "lineages": rec["lineages"], "prep_depth": rec["prep_depth"]}
    return {
        "n_candidates": len(candidates),
        "symmetry_classes": len(kept),
        "pred_ok": pred_ok,
        "pred_fail": pred_fail,
        "pre_receiver": {str(k): int(v) for k, v in sorted(dist_pre.items())},
        "post_tail": {str(k): int(v) for k, v in sorted(dist_post.items())},
        "cheapest_by_tail": {str(k): v for k, v in sorted(cheapest.items())},
        "states": kept,
    }


def receiver_labels_from_r(r: int, prep_depth: int) -> List[str]:
    labels = []
    if r == 1:
        labels.append("AS_RECEIVED_ON_2S")
    elif r == 2:
        labels.append("AS_RECEIVED_ON_3S_2S")
    elif r >= 3:
        labels.append("AS_RECEIVED_ON_LONGER_SPADE_TAIL")
    if prep_depth > 0:
        if r >= 1:
            labels.append("PREP_RELOCATED_2S")
        if r >= 2:
            labels.append("PREP_RELOCATED_3S")
        labels.append("PREP_CLEARED_C8")
        labels.append("POSTDEAL_SAME_SUIT_BUILD")
    return labels


def build_targeted_portfolio(measured: Sequence[dict], *, cap: int = PORTFOLIO_CAP) -> List[dict]:
    """Deterministic diversity: per tail length cheapest_g .. +2, round-robin, always include controls."""

    by_len: Dict[int, List[dict]] = defaultdict(list)
    for rec in measured:
        by_len[rec["low_tail"]].append(rec)
    for L in by_len:
        by_len[L].sort(key=lambda r: (r["g"], r["prep_depth"], r["ordered_digest"]))
    forced = []
    seen = set()

    def take(rec):
        d = rec["symmetry_digest"]
        if d in seen:
            return
        seen.add(d)
        forced.append(rec)

    # best DEAL_NOW Spade controls: DEAL_NOW with tail>=3 cheapest
    deal_now_t3 = [r for r in measured if r["timing"] == "DEAL_NOW" and r["low_tail"] >= 3]
    deal_now_t3.sort(key=lambda r: (r["g"], r["ordered_digest"]))
    for rec in deal_now_t3[:64]:
        take(rec)
    # cheapest prepared tail>=3
    prep_t3 = [r for r in measured if r["timing"] == "PREP_THEN_DEAL" and r["low_tail"] >= 3]
    prep_t3.sort(key=lambda r: (r["g"], -r["low_tail"], r["ordered_digest"]))
    for rec in prep_t3[:64]:
        take(rec)
    # longest-tail prepared even if slightly more expensive
    if by_len:
        Lmax = max(by_len)
        for rec in by_len[Lmax][:32]:
            take(rec)
    # per length cheapest_g .. +2
    buckets: Dict[tuple, List[dict]] = defaultdict(list)
    for L, rows in by_len.items():
        if not rows:
            continue
        g0 = rows[0]["g"]
        slack = [r for r in rows if r["g"] <= g0 + 2]
        for rec in slack:
            key = (L, rec["timing"], tuple(rec["lineages"]), rec["prep_depth"])
            buckets[key].append(rec)
    out = list(forced)
    while len(out) < cap:
        progressed = False
        for key in sorted(buckets, key=lambda k: ( -k[0], str(k[1:]))):
            bucket = buckets[key]
            while bucket:
                rec = bucket.pop(0)
                if rec["symmetry_digest"] in seen:
                    continue
                seen.add(rec["symmetry_digest"])
                out.append(rec)
                progressed = True
                break
            if len(out) >= cap:
                break
        if not progressed:
            break
    out.sort(key=lambda r: (-r["low_tail"], r["g"], r["ordered_digest"]))
    return out[:cap]


@dataclass
class TailSearchResult:
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
    first_timing: Optional[str] = None
    sd5_expanded: bool = False
    foundation_surprise: bool = False
    already_at_source: int = 0
    witnesses: List[dict] = field(default_factory=list)


def search_tail4(
    portfolio: Sequence[dict],
    opening: SpiderState,
    *,
    max_unique: int = TAIL4_UNIQUE,
    time_limit_s: float = TAIL4_TIME_S,
    rss_abort_mb: float = RSS_ABORT_MB,
    max_depth: int = TAIL4_DEPTH,
) -> TailSearchResult:
    started = time.perf_counter()
    deadline = started + time_limit_s
    result = TailSearchResult()
    peak = _rss_mb()
    baseline = 1
    best_g: Dict[bytes, int] = {}
    parent: List[int] = []
    action_of: List[Optional[Action]] = []
    depth_of: List[int] = []
    origin_of: List[int] = []
    g_of: List[int] = []
    ident_ord_of: List[bytes] = []
    ident_sym_of: List[bytes] = []
    witnesses: Dict[bytes, dict] = {}
    current_incumbent: Optional[int] = None

    def reconstruct(node: int) -> List[Action]:
        path: List[Action] = []
        while node >= 0 and parent[node] >= 0:
            act = action_of[node]
            if act is not None:
                path.append(act)
            node = parent[node]
        path.reverse()
        return path

    def note_rss() -> bool:
        nonlocal peak
        rss = _rss_mb()
        if rss is not None and (peak is None or rss > peak):
            peak = rss
        return rss is not None and rss >= rss_abort_mb

    order = sorted(range(len(portfolio)), key=lambda i: (int(portfolio[i]["g"]), portfolio[i]["ordered_digest"]))
    for origin in order:
        rec = portfolio[origin]
        ident_ord = bytes.fromhex(rec["ordered_digest"])
        ident_sym = bytes.fromhex(rec["symmetry_digest"])
        g0 = int(rec["g"])
        if ident_sym in best_g:
            if g0 < best_g[ident_sym]:
                best_g[ident_sym] = g0
                idx = ident_sym_of.index(ident_sym)
                g_of[idx] = g0
                origin_of[idx] = origin
                ident_ord_of[idx] = ident_ord
            continue
        best_g[ident_sym] = g0
        ident_sym_of.append(ident_sym)
        ident_ord_of.append(ident_ord)
        parent.append(-1)
        action_of.append(None)
        depth_of.append(0)
        origin_of.append(origin)
        g_of.append(g0)
        st0 = unpack_state(ident_ord)
        if spade_tail_present(st0, 4) or suit_foundation_count(st0, "s") > baseline:
            result.already_at_source += 1
            witnesses[ident_sym] = {
                "origin": origin,
                "g": g0,
                "depth": 0,
                "actions": [],
                "already": True,
                "foundation": suit_foundation_count(st0, "s") > baseline,
                "ordered_digest": ident_ord.hex(),
                "symmetry_digest": ident_sym.hex(),
                "timing": rec["timing"],
                "lineages": rec["lineages"],
                "low_tail": spade_low_tail_length(st0),
            }
            if current_incumbent is None or g0 < current_incumbent:
                current_incumbent = g0
                result.incumbent = g0
                result.first_s = 0.0
                result.first_unique = 1
                result.first_g = g0
                result.first_timing = rec["timing"]
    result.unique = len(best_g)
    heap: List[tuple] = []
    seq = 0
    best_node: Dict[bytes, int] = {}
    for i, ident in enumerate(ident_sym_of):
        if best_g.get(ident) == g_of[i]:
            best_node[ident] = i
    for ident, node in best_node.items():
        st = unpack_state(ident_ord_of[node])
        if (spade_tail_present(st, 4) or suit_foundation_count(st, "s") > baseline) and depth_of[node] > 0:
            continue
        heapq.heappush(heap, (g_of[node], depth_of[node], seq, node))
        seq += 1
    seen_expand: Dict[bytes, int] = {}
    print(f"TAIL4 start unique={result.unique} already={result.already_at_source} inc={current_incumbent}", flush=True)
    while heap:
        now = time.perf_counter()
        if now >= deadline:
            result.stop_reason = "time limit"
            break
        if (result.expanded & 2047) == 0 and note_rss():
            result.stop_reason = "rss abort"
            break
        if (result.expanded & 8191) == 0 and result.expanded:
            print(
                f"TAIL4 exp={result.expanded} unique={result.unique} inc={current_incumbent} "
                f"wit={len(witnesses)} heap={len(heap)}",
                flush=True,
            )
        g, depth, _, node = heapq.heappop(heap)
        ident_sym = ident_sym_of[node]
        if g != best_g.get(ident_sym):
            continue
        if seen_expand.get(ident_sym, 10**9) <= g:
            continue
        seen_expand[ident_sym] = g
        state = unpack_state(ident_ord_of[node])
        parent_hit = spade_tail_present(state, 4) or suit_foundation_count(state, "s") > baseline
        if parent_hit and depth > 0:
            continue
        if depth >= max_depth:
            continue
        if state.stock:
            result.sd5_expanded = True
        actions, _ = engine_tableau_actions(state)
        result.expanded += 1
        for action in actions:
            if action == ("deal",):
                result.sd5_expanded = True
                continue
            cost = step_cost(state, action)
            child_g = g + cost
            cap = _capture(state, action)
            try:
                apply_action(state, action)
                result.generated += 1
                if state.stock:
                    result.sd5_expanded = True
                child_ord = pack_state(state)
                child_sym = pack_post_stock_symmetry_state(state)
                prev = best_g.get(child_sym)
                if prev is not None and child_g >= prev:
                    result.duplicate_skips += 1
                    continue
                if prev is None:
                    result.unique += 1
                if result.unique >= max_unique:
                    result.stop_reason = "unique limit"
                    break
                best_g[child_sym] = child_g
                child_node = len(ident_sym_of)
                ident_sym_of.append(child_sym)
                ident_ord_of.append(child_ord)
                parent.append(node)
                action_of.append(action)
                depth_of.append(depth + 1)
                origin_of.append(origin_of[node])
                g_of.append(child_g)
                foundation = suit_foundation_count(state, "s") > baseline
                hit = (spade_tail_present(state, 4) and not parent_hit) or foundation
                if hit:
                    src = portfolio[origin_of[node]]
                    rec = {
                        "origin": origin_of[node],
                        "g": child_g,
                        "depth": depth + 1,
                        "actions": dump_actions(reconstruct(child_node)),
                        "ordered_digest": child_ord.hex(),
                        "symmetry_digest": child_sym.hex(),
                        "already": False,
                        "foundation": foundation,
                        "timing": src["timing"],
                        "lineages": src["lineages"],
                        "prep_depth": src["prep_depth"],
                        "low_tail": spade_low_tail_length(state),
                        "fd": face_down_count(state),
                        "empties": list(empty_column_indices(state)),
                    }
                    if child_sym not in witnesses or child_g < witnesses[child_sym]["g"]:
                        witnesses[child_sym] = rec
                    if foundation:
                        result.foundation_surprise = True
                    if result.first_s is None:
                        result.first_s = time.perf_counter() - started
                        result.first_unique = result.unique
                        result.first_g = child_g
                        result.first_timing = src["timing"]
                        print(
                            f"FIRST_TAIL4 g={child_g} unique={result.unique} t={result.first_s:.2f}s "
                            f"timing={src['timing']} found={foundation}",
                            flush=True,
                        )
                    if current_incumbent is None or child_g < current_incumbent:
                        current_incumbent = child_g
                        result.incumbent = child_g
                    continue
                heapq.heappush(heap, (child_g, depth + 1, seq, child_node))
                seq += 1
            finally:
                _restore(state, cap)
        if result.stop_reason in ("unique limit", "time limit", "rss abort"):
            break
    if not result.stop_reason:
        result.stop_reason = "complete"
    f4 = current_incumbent
    kept = []
    if f4 is not None:
        eligible = [w for w in witnesses.values() if w["g"] <= f4 + HARVEST_SLACK]
        eligible.sort(key=lambda w: (w["g"], w.get("depth", 0), w.get("origin", 0), w.get("ordered_digest", "")))
        kept = eligible[:HARVEST_LIMIT]
    result.witnesses = kept
    result.elapsed_s = time.perf_counter() - started
    result.peak_rss_mb = peak
    return result


def preview_tail5(
    state: SpiderState,
    g0: int,
    *,
    max_depth: int = 5,
    deadline: float,
    rss_abort_mb: float = RSS_ABORT_MB,
) -> dict:
    if spade_tail_present(state, 5):
        return {
            "status": "TAIL5_IMMEDIATE",
            "dead": False,
            "live": False,
            "unique": 1,
            "low_tail": spade_low_tail_length(state),
            "foundation": False,
        }
    ident0 = pack_post_stock_symmetry_state(state)
    ord0 = pack_state(state)
    best = {ident0: g0}
    heap = [(g0, 0, 0, ident0, ord0)]
    seq = 0
    seen: Dict[bytes, int] = {}
    unique = 1
    live = False
    found = None
    foundation = None
    best_tail = spade_low_tail_length(state)
    while heap:
        if time.perf_counter() >= deadline:
            live = True
            break
        rss = _rss_mb()
        if rss is not None and rss >= rss_abort_mb:
            live = True
            break
        g, depth, _, ident, ident_ord = heapq.heappop(heap)
        if g != best.get(ident):
            continue
        if seen.get(ident, 10**9) <= g:
            continue
        if depth >= max_depth:
            live = True
            continue
        seen[ident] = g
        st = unpack_state(ident_ord)
        actions, _ = engine_tableau_actions(st)
        for action in actions:
            if action == ("deal",):
                continue
            cost = step_cost(st, action)
            cap = _capture(st, action)
            try:
                apply_action(st, action)
                child_ord = pack_state(st)
                child_sym = pack_post_stock_symmetry_state(st)
                child_g = g + cost
                prev = best.get(child_sym)
                if prev is not None and child_g >= prev:
                    continue
                best[child_sym] = child_g
                if prev is None:
                    unique += 1
                best_tail = max(best_tail, spade_low_tail_length(st))
                if suit_foundation_count(st, "s") > 1:
                    foundation = {"g": child_g, "depth": depth + 1}
                    break
                if spade_tail_present(st, 5):
                    found = {"g": child_g, "depth": depth + 1, "low_tail": spade_low_tail_length(st)}
                    break
                seq += 1
                heapq.heappush(heap, (child_g, depth + 1, seq, child_sym, child_ord))
            finally:
                _restore(st, cap)
        if foundation or found:
            break
    if foundation:
        status = "FOUNDATION_2"
        dead = False
        live_flag = False
    elif found:
        status = "TAIL5_IMMEDIATE" if found["depth"] <= 1 else "TAIL5_WITHIN_5"
        dead = False
        live_flag = False
    elif live or heap:
        status = "LIVE_BEYOND_5"
        dead = False
        live_flag = True
    else:
        status = "EXACT_DEAD_TO_TAIL5"
        dead = True
        live_flag = False
    if live and status == "EXACT_DEAD_TO_TAIL5":
        status = "LIVE_BEYOND_5"
        dead = False
    return {
        "status": status,
        "dead": dead,
        "live": live_flag,
        "unique": unique,
        "hit": found,
        "foundation": foundation,
        "low_tail": best_tail,
    }


def synthetic_columns(face_up_runs: Sequence[Sequence[Card]], *, stock_n: int = 10, foundations=None) -> SpiderState:
    cols = [Column([], list(run)) for run in face_up_runs]
    while len(cols) < 10:
        cols.append(Column([], []))
    stock = [Card("s", 1)] + [Card("h", 3) for _ in range(max(0, stock_n - 1))]
    # put AS as 8th of last 10 for SD5-like stock if stock_n>=10
    if stock_n >= 10:
        stock = [Card("h", 3) for _ in range(stock_n)]
        stock[-10 + RECEIVE_COL] = Card("s", 1)
    return SpiderState(cols, stock, foundations or [])
