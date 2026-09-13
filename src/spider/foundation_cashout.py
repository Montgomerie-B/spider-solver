"""v0.71 bounded tactical foundation cash-out planner.

READINESS answers: which currently-ready suit looks best in this state?
TACTICAL CASH-OUT answers: given that suit as a fixed short-term objective,
which sequence of legal tableau actions reaches its foundation?

The planner may traverse intermediate states whose instantaneous operational
key becomes temporarily worse. Monotonic improvement is not required.

Search-side code uses only a serialized root, its absolute g, and a target
suit already chosen from rank_ready_suits(state)["best"]. It does not read
canonical 172, the autonomous 192 suffix, or any named-suit policy.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from spider.deal_preview import compact_preview, preview_next_deal
from spider.engine import SpiderState
from spider.metrics import Action
from spider.operational_viability import (
    compact_operational,
    foundation_operational_viability,
    operational_viability_key,
    rank_ready_suits,
)
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.research_actions import (
    apply_action,
    dump_actions,
    face_down_count,
    foundation_suits,
    is_deal,
    step_cost,
    stock_rows,
    tableau_actions,
)
from spider.search_kernel import KernelResult, SearchLimits, run_search
from spider.structural_analysis import INF, SUITS, _n, current_tableau_summary

TACTICAL_LANES = ("cost", "target_assembly", "target_access")
TACTICAL_TIME_S = 300.0
TACTICAL_UNIQUE = 400_000
TACTICAL_RSS_MB = 2.5 * 1024.0
TACTICAL_CEILING = 191
PORTFOLIO_LIMIT = 64
CLASS_SLACK_G = 10

_FIREWALL = False


class SearchFirewallError(RuntimeError):
    """Raised when evaluation-only suffix access runs during tactical search."""


def search_firewall_active() -> bool:
    return _FIREWALL


def require_eval_phase(reason: str = "incumbent suffix") -> None:
    if _FIREWALL:
        raise SearchFirewallError(
            f"{reason} is forbidden while tactical search is active"
        )


@contextmanager
def tactical_search_session():
    """Arm the search firewall for the duration of a tactical probe."""

    global _FIREWALL
    nested = _FIREWALL
    _FIREWALL = True
    try:
        yield
    finally:
        if not nested:
            _FIREWALL = False


def suit_foundation_count(state: SpiderState, suit: str) -> int:
    return sum(1 for run in state.foundations if run and run[0].suit == suit)


def is_target_cashout(
    state: SpiderState, target_suit: str, foundations_before: int
) -> bool:
    """True only when the fixed target suit gained a completed foundation."""

    return suit_foundation_count(state, target_suit) > int(foundations_before)


def select_tactical_target(state: SpiderState, g: int = 0) -> dict:
    """The only target-selection rule: operational rank 1 at this state."""

    ranked = rank_ready_suits(state, g=g)
    if int(ranked.get("n_ready") or 0) < 1 or ranked.get("best") is None:
        raise ValueError("tactical cash-out requires a materially-ready suit")
    best = ranked["best"]
    return {
        "suit": best["suit"],
        "n_ready": ranked["n_ready"],
        "ready_suits": list(ranked.get("ready_suits") or []),
        "operational_key": list(best.get("key") or operational_viability_key(best, g)),
        "cover": best.get("cover"),
        "blockers": best.get("relevant_blockers"),
        "k_access": best.get("k_min_blockers"),
        "a_access": best.get("a_min_blockers"),
        "gap": best.get("gap"),
        "merge_edges": best.get("legal_merge_edges"),
        "compact": compact_operational(best),
        "ranked": ranked,
    }


def target_assembly_key(v: dict, g: int) -> tuple:
    """Fixed-target assembly order. Lower is better. No global suit ranking."""

    return (
        _n(v.get("cover")),
        int(v.get("inaccessible_joins") or 0),
        int(v.get("k_min_blockers") or INF),
        int(v.get("a_min_blockers") or INF),
        _n(v.get("gap")),
        -int(v.get("legal_merge_edges") or 0),
        int(v.get("relevant_blockers") or 0),
        int(g),
    )


def target_access_key(v: dict, g: int) -> tuple:
    """Fixed-target access/workspace order. Lower is better."""

    return (
        int(v.get("k_min_blockers") or INF),
        int(v.get("a_min_blockers") or INF),
        int(v.get("buried_components") or 0),
        -int(v.get("exposed_components") or 0),
        -int(v.get("movable_exposed") or 0),
        -int(v.get("empty_n") or 0),
        -int(v.get("legal_merge_ops_global") or 0),
        int(g),
    )


def tactical_lane_keys(state: SpiderState, g: int, target_suit: str) -> Dict[str, tuple]:
    v = foundation_operational_viability(state, target_suit)
    return {
        "cost": (int(g),),
        "target_assembly": target_assembly_key(v, int(g)),
        "target_access": target_access_key(v, int(g)),
    }


def target_metric_snapshot(state: SpiderState, target_suit: str, g: int) -> dict:
    s = current_tableau_summary(state)
    v = foundation_operational_viability(state, target_suit, summary=s)
    key = operational_viability_key(v, g)
    return {
        "g": int(g),
        "fd": int(s["face_down"]),
        "empties": int(s["empty_n"]),
        "legal_mobility": len(tableau_actions(state)),
        "foundations": int(s["foundations"]),
        "foundation_suits": list(s["foundation_suits"]),
        "stock_rows": stock_rows(state),
        "boundaries": int(v.get("boundaries_total") or 0),
        "visible_components": int(s["visible_runs"]),
        "cover": v.get("cover"),
        "blockers": int(v.get("relevant_blockers") or 0),
        "k_access": v.get("k_min_blockers"),
        "a_access": v.get("a_min_blockers"),
        "gap": v.get("gap"),
        "merge_edges": int(v.get("legal_merge_edges") or 0),
        "inaccessible_joins": int(v.get("inaccessible_joins") or 0),
        "buried_components": int(v.get("buried_components") or 0),
        "exposed_components": int(v.get("exposed_components") or 0),
        "operational_key": list(key),
        "compact": compact_operational(v),
        "ordered_digest": pack_state(state).hex(),
        "whole_game_identity": pack_whole_game_identity(state).hex(),
    }


def _worsened_fields(prev: dict, cur: dict) -> List[str]:
    """Fields that became worse. Lower is better except merge_edges."""

    out: List[str] = []
    for name in (
        "cover",
        "blockers",
        "k_access",
        "a_access",
        "gap",
        "inaccessible_joins",
        "buried_components",
    ):
        a, b = prev.get(name), cur.get(name)
        if a is None or b is None:
            continue
        if int(b) > int(a):
            out.append(name)
    if int(cur.get("merge_edges") or 0) < int(prev.get("merge_edges") or 0):
        out.append("merge_edges")
    if int(cur.get("exposed_components") or 0) < int(prev.get("exposed_components") or 0):
        out.append("exposed_components")
    pk = list(prev.get("operational_key") or [])
    ck = list(cur.get("operational_key") or [])
    if pk and ck:
        # Drop trailing g so a uniform +g step is not itself a valley.
        p_body = tuple(pk[:-1]) if len(pk) > 1 else tuple(pk)
        c_body = tuple(ck[:-1]) if len(ck) > 1 else tuple(ck)
        if c_body > p_body:
            out.append("operational_key")
    return out


def replay_to_stock_rows(
    opening: SpiderState,
    actions: Sequence[Action],
    *,
    target_rows: int = 1,
) -> dict:
    """Replay until the first state with ``target_rows`` stock rows, then stop.

    Remaining actions are not stored. Search-side callers must drop the input
    list after this returns.
    """

    state = opening.clone()
    g = 0
    deals = 0
    prefix: List[Action] = []
    for action in actions:
        if stock_rows(state) == int(target_rows):
            break
        cost = 1 if is_deal(action) else step_cost(state, action)
        apply_action(state, action)
        g += int(cost)
        prefix.append(action)
        if is_deal(action):
            deals += 1
    if stock_rows(state) != int(target_rows):
        raise ValueError(
            f"prefix never reached stock_rows={target_rows} (at {stock_rows(state)})"
        )
    s = current_tableau_summary(state)
    packed = pack_state(state)
    ident = pack_whole_game_identity(state)
    return {
        "g": int(g),
        "deals": int(deals),
        "prefix_actions": dump_actions(prefix),
        "n_prefix": len(prefix),
        "stock_rows": stock_rows(state),
        "foundations": int(s["foundations"]),
        "foundation_suits": list(s["foundation_suits"]),
        "face_down": int(s["face_down"]),
        "empty_n": int(s["empty_n"]),
        "legal_mobility": len(tableau_actions(state)),
        "visible_components": int(s["visible_runs"]),
        "boundaries": int(s.get("visible_runs") or 0),
        "ordered_digest": packed.hex(),
        "whole_game_identity": ident.hex(),
        "suffix_discarded": True,
        "identity_is_ordered": packed == ident,
    }


def serialized_tactical_root(root: dict) -> dict:
    """JSON-safe root with no suffix and no live SpiderState."""

    keep = (
        "g",
        "deals",
        "n_prefix",
        "stock_rows",
        "foundations",
        "foundation_suits",
        "face_down",
        "empty_n",
        "legal_mobility",
        "visible_components",
        "ordered_digest",
        "whole_game_identity",
        "suffix_discarded",
        "identity_is_ordered",
    )
    return {k: root.get(k) for k in keep}


def _tactical_actions(state: SpiderState) -> List[Action]:
    actions = tableau_actions(state)
    if any(is_deal(a) for a in actions):
        raise SearchFirewallError("Deal leaked into tactical actions")
    return actions


@dataclass
class TacticalProgress:
    min_cover: Optional[int] = None
    min_blockers: Optional[int] = None
    best_k_access: Optional[int] = None
    best_a_access: Optional[int] = None
    min_g_at_min_cover: Optional[int] = None
    min_g_at_min_blockers: Optional[int] = None
    n_children: int = 0
    n_target_terminals: int = 0
    first_terminal_s: Optional[float] = None
    first_terminal_g: Optional[int] = None
    started: float = field(default_factory=time.perf_counter)

    def observe(self, snap: dict, *, is_terminal: bool) -> None:
        self.n_children += 1
        g = int(snap["g"])
        cover = snap.get("cover")
        blockers = snap.get("blockers")
        k_acc = snap.get("k_access")
        a_acc = snap.get("a_access")
        if cover is not None:
            c = int(cover)
            if self.min_cover is None or c < self.min_cover:
                self.min_cover = c
                self.min_g_at_min_cover = g
        if blockers is not None:
            b = int(blockers)
            if self.min_blockers is None or b < self.min_blockers:
                self.min_blockers = b
                self.min_g_at_min_blockers = g
        if k_acc is not None:
            k = int(k_acc)
            if self.best_k_access is None or k < self.best_k_access:
                self.best_k_access = k
        if a_acc is not None:
            a = int(a_acc)
            if self.best_a_access is None or a < self.best_a_access:
                self.best_a_access = a
        if is_terminal:
            self.n_target_terminals += 1
            if self.first_terminal_s is None:
                self.first_terminal_s = time.perf_counter() - self.started
                self.first_terminal_g = g

    def as_dict(self) -> dict:
        return {
            "min_cover": self.min_cover,
            "min_blockers": self.min_blockers,
            "best_k_access": self.best_k_access,
            "best_a_access": self.best_a_access,
            "min_g_at_min_cover": self.min_g_at_min_cover,
            "min_g_at_min_blockers": self.min_g_at_min_blockers,
            "n_children": self.n_children,
            "n_target_terminals": self.n_target_terminals,
            "first_terminal_s": self.first_terminal_s,
            "first_terminal_g": self.first_terminal_g,
        }


def enrich_terminal_state(
    state: SpiderState, g: int, target_suit: str, *, with_preview: bool = False
) -> dict:
    snap = target_metric_snapshot(state, target_suit, g)
    rec = {
        "g": g,
        "delta_g": None,
        "fd": snap["fd"],
        "empties": snap["empties"],
        "legal_mobility": snap["legal_mobility"],
        "foundations": snap["foundations"],
        "foundation_suits": snap["foundation_suits"],
        "stock_rows": snap["stock_rows"],
        "boundaries": snap["boundaries"],
        "visible_components": snap["visible_components"],
        "cover": snap["cover"],
        "blockers": snap["blockers"],
        "k_access": snap["k_access"],
        "a_access": snap["a_access"],
        "gap": snap["gap"],
        "merge_edges": snap["merge_edges"],
        "ordered_digest": snap["ordered_digest"],
        "whole_game_identity": snap["whole_game_identity"],
        "target_suit": target_suit,
        "target_foundations": suit_foundation_count(state, target_suit),
    }
    if with_preview:
        rec["deal_preview"] = compact_preview(preview_next_deal(state, pre_g=g))
    return rec


def select_terminal_portfolio(rows: Sequence[dict], *, limit: int = PORTFOLIO_LIMIT) -> List[dict]:
    ordered = sorted(
        rows,
        key=lambda r: (
            int(r.get("g") or 10**9),
            int(r.get("fd") or 99),
            str(r.get("ordered_digest") or r.get("ident") or ""),
        ),
    )
    kept: List[dict] = []
    seen_ident = set()
    seen_sig = set()
    for rec in ordered:
        ident = rec.get("ordered_digest") or rec.get("ident")
        if ident in seen_ident:
            continue
        sig = (
            rec.get("g"),
            rec.get("fd"),
            rec.get("empties"),
            rec.get("legal_mobility"),
            rec.get("boundaries"),
            rec.get("visible_components"),
        )
        if kept and sig in seen_sig and len(kept) >= 8:
            continue
        seen_ident.add(ident)
        seen_sig.add(sig)
        kept.append(rec)
        if len(kept) >= int(limit):
            break
    return kept


def trace_tactical_path(
    root_state: SpiderState,
    root_g: int,
    actions: Sequence[Action],
    target_suit: str,
) -> dict:
    state = root_state.clone()
    g = int(root_g)
    before = suit_foundation_count(state, target_suit)
    start = target_metric_snapshot(state, target_suit, g)
    steps = []
    nonmonotonic = []
    prev = start
    for i, action in enumerate(actions):
        if is_deal(action):
            raise SearchFirewallError("Deal is not a tactical cash-out action")
        cost = step_cost(state, action)
        apply_action(state, action)
        g += int(cost)
        snap = target_metric_snapshot(state, target_suit, g)
        cashed = is_target_cashout(state, target_suit, before)
        worsened = [] if cashed else _worsened_fields(prev, snap)
        rec = {
            "i": i,
            "action": dump_actions([action])[0],
            "step_mw": int(cost),
            "absolute_g": g,
            "fd": snap["fd"],
            "empties": snap["empties"],
            "legal_mobility": snap["legal_mobility"],
            "target_cover": snap["cover"],
            "target_blockers": snap["blockers"],
            "target_k_access": snap["k_access"],
            "target_a_access": snap["a_access"],
            "target_gap": snap["gap"],
            "target_merge_edges": snap["merge_edges"],
            "operational_key": snap["operational_key"],
            "worsened": worsened,
        }
        steps.append(rec)
        if worsened:
            nonmonotonic.append(rec)
        prev = snap
    return {
        "root": start,
        "terminal": prev,
        "steps": steps,
        "n_steps": len(steps),
        "n_nonmonotonic": len(nonmonotonic),
        "nonmonotonic_steps": nonmonotonic,
        "delta_g": g - int(root_g),
        "terminal_g": g,
        "terminal_digest": prev["ordered_digest"],
    }


def replay_incumbent_suffix_for_eval(
    opening: SpiderState,
    actions: Sequence[Action],
    *,
    prefix_n: int,
    root_g: int,
) -> dict:
    """Evaluation only. Must not run while the tactical firewall is armed."""

    require_eval_phase("incumbent suffix replay")
    state = opening.clone()
    g = 0
    deals = 0
    for action in actions[: int(prefix_n)]:
        cost = 1 if is_deal(action) else step_cost(state, action)
        apply_action(state, action)
        g += int(cost)
        if is_deal(action):
            deals += 1
    if g != int(root_g):
        raise ValueError(f"suffix replay root g {g} != {root_g}")
    if stock_rows(state) != 1:
        raise ValueError("suffix replay is not at rows=1 entry")
    before = {s: 0 for s in SUITS}
    for suit in foundation_suits(state):
        before[suit] = before.get(suit, 0) + 1
    suffix: List[Action] = []
    cashed = None
    for action in actions[int(prefix_n) :]:
        if is_deal(action):
            break
        cost = step_cost(state, action)
        apply_action(state, action)
        g += int(cost)
        suffix.append(action)
        after = {s: 0 for s in SUITS}
        for suit in foundation_suits(state):
            after[suit] = after.get(suit, 0) + 1
        added = [s for s in after if after[s] > before.get(s, 0)]
        if added:
            cashed = added[0]
            break
    s = current_tableau_summary(state)
    preview = compact_preview(preview_next_deal(state, pre_g=g)) if cashed else None
    return {
        "cashed_suit": cashed,
        "foundation_g": None if cashed is None else int(g),
        "delta_g": None if cashed is None else int(g) - int(root_g),
        "n_actions": len(suffix),
        "actions": dump_actions(suffix),
        "fd": int(s["face_down"]),
        "empties": int(s["empty_n"]),
        "legal_mobility": len(tableau_actions(state)),
        "foundations": int(s["foundations"]),
        "foundation_suits": list(s["foundation_suits"]),
        "stock_rows": stock_rows(state),
        "visible_components": int(s["visible_runs"]),
        "ordered_digest": pack_state(state).hex(),
        "whole_game_identity": pack_whole_game_identity(state).hex(),
        "deal_preview": preview,
        "hit_deal_before_foundation": cashed is None,
    }


def classify_vs_incumbent(planner: dict, incumbent: dict) -> str:
    pg = planner.get("cheapest_g")
    ig = incumbent.get("foundation_g")
    if pg is None:
        return "failed"
    pd = planner.get("cheapest_digest")
    idn = incumbent.get("ordered_digest")
    if pd and idn and pd == idn:
        return "same_state"
    if ig is None:
        return "planner_only"
    if int(pg) < int(ig):
        return "cheaper_different" if pd != idn else "cheaper_same"
    if int(pg) == int(ig):
        return "same_cost_same" if pd == idn else "same_cost_different"
    return "more_expensive"


def choose_tactical_verdict(payload: dict) -> Tuple[str, str]:
    if payload.get("contract_fail"):
        return "TACTICAL_CASHOUT_CONTRACT_FAILURE", payload.get("contract_reason") or "contract"
    search = payload.get("search") or {}
    cheapest = payload.get("cheapest_g")
    if cheapest is None:
        cheapest = search.get("cheapest_g")
    inc_g = ((payload.get("incumbent_compare") or {}).get("foundation_g"))
    stop = payload.get("stop_reason") or search.get("stop_reason") or ""
    unique = payload.get("unique")
    if unique is None:
        unique = search.get("unique")
    expanded = payload.get("expanded")
    if expanded is None:
        expanded = search.get("expanded")
    if cheapest is None:
        prog = payload.get("progress") or {}
        strong = (
            (prog.get("min_cover") is not None and payload.get("root_cover") is not None
             and int(prog["min_cover"]) < int(payload["root_cover"]))
            or int(unique or 0) >= 10_000
            or int(expanded or 0) >= 1_000
        )
        live = stop in ("time limit", "unique limit", "rss abort")
        if strong and live:
            return (
                "TACTICAL_CASHOUT_SEARCH_LIMITED",
                "bounded search still making structural progress at expiry",
            )
        return "TACTICAL_CASHOUT_NO_FOUNDATION", "no target foundation inside the envelope"
    if inc_g is None:
        return "TACTICAL_CASHOUT_RECOVERS_F2_CLASS", f"target foundation at g={cheapest}"
    if int(cheapest) < int(inc_g):
        return "TACTICAL_CASHOUT_FINDS_CHEAPER_F2", f"g={cheapest} < incumbent {inc_g}"
    if int(cheapest) <= int(inc_g) + CLASS_SLACK_G:
        return "TACTICAL_CASHOUT_RECOVERS_F2_CLASS", f"g={cheapest} vs incumbent {inc_g}"
    return "TACTICAL_CASHOUT_FINDS_EXPENSIVE_F2", f"g={cheapest} vs incumbent {inc_g}"


@dataclass
class TacticalCashoutResult:
    found: bool
    target_suit: str
    root_g: int
    target_foundations_before: int
    cheapest_g: Optional[int]
    first_g: Optional[int]
    first_s: Optional[float]
    delta_g: Optional[int]
    path: List[Action] = field(default_factory=list)
    path_trace: dict = field(default_factory=dict)
    terminals: List[dict] = field(default_factory=list)
    portfolio: List[dict] = field(default_factory=list)
    kernel: Optional[KernelResult] = None
    progress: dict = field(default_factory=dict)
    lane_exp: Dict[str, int] = field(default_factory=dict)
    unique: int = 0
    expanded: int = 0
    generated: int = 0
    duplicate_skips: int = 0
    stale_skips: int = 0
    elapsed_s: float = 0.0
    stop_reason: str = ""
    cheapest_digest: Optional[str] = None


def search_foundation_cashout(
    *,
    root_state: Optional[SpiderState] = None,
    ordered_digest: Optional[str] = None,
    root_g: int,
    target_suit: str,
    max_unique: int = TACTICAL_UNIQUE,
    time_limit_s: float = TACTICAL_TIME_S,
    rss_abort_mb: float = TACTICAL_RSS_MB,
    cost_ceiling: int = TACTICAL_CEILING,
    portfolio_limit: int = PORTFOLIO_LIMIT,
    on_progress: Optional[Callable] = None,
    skip_preview: bool = False,
) -> TacticalCashoutResult:
    """Bounded tableau-only search for one additional target-suit foundation.

    Inputs are a serialized/current root, absolute g, and an already-chosen
    target. The autonomous suffix must not be supplied.
    """

    with tactical_search_session():
        if root_state is None:
            if not ordered_digest:
                raise ValueError("root_state or ordered_digest is required")
            state0 = unpack_state(bytes.fromhex(ordered_digest))
        else:
            state0 = root_state.clone()
        packed = pack_state(state0)
        ident = pack_whole_game_identity(state0)
        if state0.stock and packed != ident:
            raise SearchFirewallError("pre-stock identity must stay ordered")
        before = suit_foundation_count(state0, target_suit)
        root = {
            "g": int(root_g),
            "ordered_digest": packed.hex(),
            "symmetry_digest": packed.hex(),
        }
        progress = TacticalProgress()

        def keys_fn(st: SpiderState, g: int) -> Dict[str, tuple]:
            return tactical_lane_keys(st, g, target_suit)

        def terminal_fn(st: SpiderState) -> bool:
            return is_target_cashout(st, target_suit, before)

        def child_cb(st: SpiderState, g: int, node_i: int) -> None:
            hit = is_target_cashout(st, target_suit, before)
            snap = {
                "g": g,
                "cover": None,
                "blockers": None,
                "k_access": None,
                "a_access": None,
            }
            if hit or (progress.n_children & 15) == 0:
                full = target_metric_snapshot(st, target_suit, g)
                snap = full
            else:
                v = foundation_operational_viability(st, target_suit)
                snap["cover"] = v.get("cover")
                snap["blockers"] = v.get("relevant_blockers")
                snap["k_access"] = v.get("k_min_blockers")
                snap["a_access"] = v.get("a_min_blockers")
            progress.observe(snap, is_terminal=hit)
            if on_progress is not None:
                on_progress(progress, st, g, node_i)

        limits = SearchLimits(
            max_unique=int(max_unique),
            time_limit_s=float(time_limit_s),
            rss_abort_mb=float(rss_abort_mb),
            cost_ceiling=int(cost_ceiling),
            harvest_slack=None,
        )
        kernel = run_search(
            [root],
            limits=limits,
            identity_fn=pack_whole_game_identity,
            store_fn=pack_state,
            unpack_fn=unpack_state,
            lane_names=TACTICAL_LANES,
            lane_keys_fn=keys_fn,
            is_terminal=terminal_fn,
            actions_fn=_tactical_actions,
            on_child=child_cb,
        )
        unique_terms: Dict[str, dict] = {}
        for rec in kernel.terminals:
            ident_h = rec.get("ident") or rec.get("store")
            prev = unique_terms.get(ident_h)
            if prev is not None and int(prev["g"]) <= int(rec["g"]):
                continue
            st = unpack_state(bytes.fromhex(rec["store"]))
            enriched = enrich_terminal_state(st, int(rec["g"]), target_suit)
            enriched["ident"] = ident_h
            enriched["node"] = rec.get("node")
            enriched["delta_g"] = int(rec["g"]) - int(root_g)
            unique_terms[ident_h] = enriched
        terminals = sorted(unique_terms.values(), key=lambda r: (r["g"], r["ordered_digest"]))
        portfolio = select_terminal_portfolio(terminals, limit=portfolio_limit)
        for rec in portfolio:
            if rec.get("node") is not None and kernel.nodes:
                rec["actions"] = dump_actions(kernel.reconstruct(int(rec["node"])))
            if skip_preview:
                continue
            st = unpack_state(bytes.fromhex(rec["ordered_digest"]))
            rec["deal_preview"] = compact_preview(preview_next_deal(st, pre_g=int(rec["g"])))
        cheapest = terminals[0] if terminals else None
        path: List[Action] = []
        path_trace: dict = {}
        if cheapest is not None and kernel.nodes:
            path = kernel.reconstruct(int(cheapest["node"]))
            path_trace = trace_tactical_path(state0, int(root_g), path, target_suit)
        first_s = kernel.first_s
        if first_s is None:
            first_s = progress.first_terminal_s
        return TacticalCashoutResult(
            found=cheapest is not None,
            target_suit=target_suit,
            root_g=int(root_g),
            target_foundations_before=before,
            cheapest_g=None if cheapest is None else int(cheapest["g"]),
            first_g=kernel.first_g if kernel.first_g is not None else progress.first_terminal_g,
            first_s=first_s,
            delta_g=None if cheapest is None else int(cheapest["g"]) - int(root_g),
            path=path,
            path_trace=path_trace,
            terminals=terminals,
            portfolio=portfolio,
            kernel=kernel,
            progress=progress.as_dict(),
            lane_exp=dict(kernel.lane_exp),
            unique=kernel.unique,
            expanded=kernel.expanded,
            generated=kernel.generated,
            duplicate_skips=kernel.duplicate_skips,
            stale_skips=kernel.stale_skips,
            elapsed_s=kernel.elapsed_s,
            stop_reason=kernel.stop_reason,
            cheapest_digest=None if cheapest is None else cheapest["ordered_digest"],
        )
