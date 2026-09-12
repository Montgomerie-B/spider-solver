"""Research-only v0.55 whole-suit component assembly audit.

Static + tiny direct-merge condensation over the exact v0.53 post-SD5
universe.  No UCS, no descendant search, no weighted score.
"""

from __future__ import annotations

from collections import Counter
from typing import Dict, List, Optional, Sequence, Tuple

from spider.engine import SpiderState
from spider.packed_state import unpack_state
from spider.structural_analysis import (  # noqa: F401
    FULL_RANKS,
    INF,
    SUITS,
    a_ending,
    all_lane_metrics,
    component_cover,
    direct_condensation,
    face_down_suit_cards,
    k_headed,
    ka_directly_joinable,
    ka_gap,
    lane_suit_metrics,
    merge_edges,
    min_interval_cover,
    suit_lane_key,
    visible_components,
)

__all__ = [
    "SUITS",
    "INF",
    "FULL_RANKS",
    "a_ending",
    "all_lane_metrics",
    "component_cover",
    "direct_condensation",
    "face_down_suit_cards",
    "k_headed",
    "ka_directly_joinable",
    "ka_gap",
    "lane_suit_metrics",
    "merge_edges",
    "min_interval_cover",
    "suit_lane_key",
    "visible_components",
    "audit_suit",
    "audit_state",
    "dominates",
    "pareto_prep",
    "harvest_component_portfolio",
    "choose_verdict",
]


def audit_suit(state: SpiderState, suit: str, *, g0: int = 0) -> dict:
    cover = component_cover(state, suit)
    comps = visible_components(state, suit)
    cond = direct_condensation(state, suit, g0=g0)
    kc = k_headed(comps)
    ac = a_ending(comps)
    longest = 0 if not comps else max(c["length"] for c in comps)
    return {
        **cover,
        "longest": longest,
        "k_len": 0 if not kc else kc["length"],
        "a_len": 0 if not ac else ac["length"],
        "k_low": None if not kc else kc["low"],
        "a_high": None if not ac else ac["high"],
        "gap": ka_gap(kc, ac),
        "joinable": ka_directly_joinable(state, kc, ac),
        "start_edges": cond["start_edges"],
        "end_edges": cond["end_edges"],
        "cond_min_n": cond["min_n"],
        "cond_longest": cond["longest"],
        "cond_merges": cond["merges"],
        "cond_f2": cond["f2"],
        "cond_path": cond["path"],
        "cond_g_add": cond["g_add"],
        "k_headed": kc is not None,
        "a_ending": ac is not None,
    }


def _metric_tuple(s: dict) -> tuple:
    cover = INF if s.get("min_cover") is None else int(s["min_cover"])
    fd = INF if s.get("min_fd_cards") is None else int(s["min_fd_cards"])
    lb = INF if s.get("join_lb") is None else int(s["join_lb"])
    gap = INF if s.get("gap") is None else int(s["gap"])
    return (
        1 if s.get("cond_f2") else 0,
        -cover,
        -fd,
        -lb,
        int(s.get("start_edges") or 0),
        int(s.get("cond_longest") or 0),
        -gap,
        int(s.get("longest") or 0),
    )


def audit_state(rec: dict) -> dict:
    st = unpack_state(bytes.fromhex(rec["ordered_digest"]))
    by_suit = {suit: audit_suit(st, suit, g0=int(rec["g"])) for suit in SUITS}
    best_suit = max(SUITS, key=lambda s: _metric_tuple(by_suit[s]))
    best = by_suit[best_suit]
    return {
        "g": rec["g"],
        "timing": rec["timing"],
        "prep_depth": rec.get("prep_depth"),
        "prep_cost": rec.get("prep_cost"),
        "lineages": rec.get("lineages") or [],
        "origin": rec.get("origin"),
        "ordered_digest": rec["ordered_digest"],
        "symmetry_digest": rec["symmetry_digest"],
        "full_actions": rec.get("full_actions"),
        "best_suit": best_suit,
        "min_cover": best.get("min_cover"),
        "min_visible_cover": best.get("min_visible_cover"),
        "min_fd_cards": best.get("min_fd_cards"),
        "join_lb": best.get("join_lb"),
        "visible_n": best.get("visible_n"),
        "start_edges": best.get("start_edges"),
        "cond_longest": best.get("cond_longest"),
        "cond_min_n": best.get("cond_min_n"),
        "longest": best.get("longest"),
        "k_len": best.get("k_len"),
        "a_len": best.get("a_len"),
        "gap": best.get("gap"),
        "joinable": best.get("joinable"),
        "f2": any(by_suit[s].get("cond_f2") for s in SUITS),
        "f2_suit": next((s for s in SUITS if by_suit[s].get("cond_f2")), None),
        "f2_path": next((by_suit[s].get("cond_path") for s in SUITS if by_suit[s].get("cond_f2")), []),
        "by_suit": {
            s: {
                k: by_suit[s].get(k)
                for k in (
                    "min_cover",
                    "min_visible_cover",
                    "min_fd_cards",
                    "join_lb",
                    "visible_n",
                    "longest",
                    "k_len",
                    "a_len",
                    "gap",
                    "joinable",
                    "start_edges",
                    "cond_longest",
                    "cond_min_n",
                    "cond_merges",
                    "cond_f2",
                    "k_headed",
                    "a_ending",
                )
            }
            for s in SUITS
        },
    }


def _vec(r: dict) -> tuple:
    def n(v, default=INF):
        return default if v is None else int(v)

    return (
        n(r.get("min_cover")),
        n(r.get("min_fd_cards")),
        n(r.get("join_lb")),
        -int(r.get("start_edges") or 0),
        -int(r.get("cond_longest") or 0),
        n(r.get("gap")),
    )


def dominates(a: dict, b: dict) -> bool:
    """True if a is at least as good as b on every metric and better on one."""

    va, vb = _vec(a), _vec(b)
    le = all(x <= y for x, y in zip(va, vb))
    lt = any(x < y for x, y in zip(va, vb))
    return le and lt


def pareto_prep(deal_now: Sequence[dict], prep: Sequence[dict]) -> List[dict]:
    dn = sorted(deal_now, key=lambda r: r["g"])
    out = []
    for p in prep:
        g = int(p["g"])
        cand = [d for d in dn if int(d["g"]) <= g]
        if any(dominates(d, p) or _vec(d) == _vec(p) for d in cand):
            continue
        if not cand:
            out.append(p)
            continue
        # not dominated and not equal to a cheaper-or-equal DEAL_NOW vector
        out.append(p)
    return out


def tally(rows: Sequence[dict], *, suit: Optional[str] = None) -> dict:
    def pick(r, key):
        if suit is None:
            return r.get(key)
        return ((r.get("by_suit") or {}).get(suit) or {}).get(key)

    def dist(key):
        c = Counter()
        for r in rows:
            v = pick(r, key)
            c["none" if v is None else str(v)] += 1
        return dict(c)

    covers = [pick(r, "min_cover") for r in rows]
    finite = [int(v) for v in covers if v is not None]
    return {
        "n": len(rows),
        "min_cover": dist("min_cover"),
        "min_visible_cover": dist("min_visible_cover"),
        "min_fd_cards": dist("min_fd_cards"),
        "join_lb": dist("join_lb"),
        "longest": dist("longest"),
        "start_edges": dist("start_edges"),
        "cond_longest": dist("cond_longest"),
        "k_len": dist("k_len"),
        "a_len": dist("a_len"),
        "gap": dist("gap"),
        "f2": sum(1 for r in rows if (pick(r, "cond_f2") if suit else r.get("f2"))),
        "best_cover": None if not finite else min(finite),
        "best_fd": None if not rows else min((pick(r, "min_fd_cards") for r in rows if pick(r, "min_fd_cards") is not None), default=None),
        "best_cond_len": 0 if not rows else max((int(pick(r, "cond_longest") or 0) for r in rows), default=0),
        "best_edges": 0 if not rows else max((int(pick(r, "start_edges") or 0) for r in rows), default=0),
        "best_gap": None if not rows else min((pick(r, "gap") for r in rows if pick(r, "gap") is not None), default=None),
        "max_k": 0 if not rows else max((int(pick(r, "k_len") or 0) for r in rows), default=0),
        "max_a": 0 if not rows else max((int(pick(r, "a_len") or 0) for r in rows), default=0),
    }


def new_classes(deal: dict, prep: dict) -> List[str]:
    reasons = []
    if prep.get("best_cover") is not None and (
        deal.get("best_cover") is None or prep["best_cover"] < deal["best_cover"]
    ):
        reasons.append("lower_min_component_cover")
    if prep.get("best_fd") is not None and (
        deal.get("best_fd") is None or prep["best_fd"] < deal["best_fd"]
    ):
        reasons.append("fewer_required_face_down")
    if prep.get("best_edges", 0) > deal.get("best_edges", 0):
        reasons.append("more_direct_merge_edges")
    if prep.get("best_cond_len", 0) > deal.get("best_cond_len", 0):
        reasons.append("longer_direct_condensation")
    if prep.get("best_gap") is not None and (
        deal.get("best_gap") is None or prep["best_gap"] < deal["best_gap"]
    ):
        reasons.append("smaller_ka_gap")
    if (prep.get("f2") or 0) > 0 and not (deal.get("f2") or 0):
        reasons.append("local_component_foundation2")
    return reasons


def harvest_component_portfolio(rows: Sequence[dict], *, limit: int = 512) -> List[dict]:
    picked: List[dict] = []
    seen = set()

    def take(cands, n, cat):
        ordered = sorted(
            cands,
            key=lambda r: (
                INF if r.get("min_cover") is None else r["min_cover"],
                r["g"],
                r["ordered_digest"],
            ),
        )
        got = 0
        suits = Counter()
        for w in ordered:
            if got >= n or len(picked) >= limit:
                return
            ident = w["symmetry_digest"]
            if ident in seen:
                continue
            if suits[w.get("best_suit")] >= max(2, n // 2) and n >= 8:
                continue
            seen.add(ident)
            item = dict(w)
            item["portfolio_cat"] = cat
            picked.append(item)
            suits[w.get("best_suit")] += 1
            got += 1

    finite = [r for r in rows if r.get("min_cover") is not None]
    best_c = None if not finite else min(int(r["min_cover"]) for r in finite)
    take([r for r in finite if r["min_cover"] == best_c], 80, "A_COVER")
    take(sorted(rows, key=lambda r: (-int(r.get("cond_longest") or 0), r["g"])), 64, "B_CONDENSE")
    take([r for r in rows if r.get("gap") is not None and int(r["gap"]) <= 1], 64, "C_MEET")
    take([r for r in rows if r.get("f2")], 32, "D_F2")
    take([r for r in rows if r.get("timing") == "DEAL_NOW"], 64, "E_DEAL_NOW")
    for suit in SUITS:
        take([r for r in rows if r.get("best_suit") == suit], 16, "F_SUIT")
    if len(picked) < limit:
        take(rows, limit - len(picked), "G_FILL")
    return picked[:limit]


def choose_verdict(p: dict) -> Tuple[str, str]:
    if not p.get("all_replay_ok"):
        return "SOURCE_REPLAY_FAILURE", "v0.53 post-SD5 universe failed reconstruction/replay"
    if p.get("contract_fail"):
        return "COMPONENT_MODEL_CONTRACT_FAILURE", "component cover or merge model failed a contract"
    if not p.get("static_complete"):
        return "COMPONENT_AUDIT_RESOURCE_LIMIT", "static component-cover audit did not finish"
    if p.get("f2"):
        return "PREP_CREATES_LOCAL_COMPONENT_FOUNDATION2", "direct component condensation auto-removed Foundation 2"
    reasons = p.get("new_classes") or []
    pareto_n = int(p.get("pareto_n") or 0)
    if reasons or pareto_n:
        return "PREP_CREATES_SUPERIOR_COMPONENT_TOPOLOGY", "PREP creates a whole-suit assembly class absent from DEAL_NOW"
    return (
        "WHOLE_SUIT_AUDIT_SUPPORTS_PRE_SD4_RETREAT",
        "PREP does not improve whole-suit component topology inside depth<=4/MW<=4",
    )
