"""Generic operational foundation viability.

Current-state facts only. No route history, no suit preference, no
benchmark face-down threshold. Material completeness is necessary but
not sufficient for a strong opportunity.
"""

from __future__ import annotations

from typing import List, Optional, Sequence

from spider.engine import SpiderState
from spider.structural_analysis import (
    INF,
    SUITS,
    _n,
    current_tableau_summary,
    foundation_readiness,
    same_suit_component_spans,
)

ACCESS_RANKS = (13, 1)


def _anchor_slot(rank: int, rec: dict) -> List[dict]:
    return rec["k_anchors"] if rank == 13 else rec["a_anchors"]


def tableau_access_scan(state: SpiderState) -> dict:
    """One pass: per-suit exposure, blockers, K/A anchors, global mobility proxies."""

    by_suit = {
        s: {
            "fd_n": 0,
            "exposed_components": 0,
            "buried_components": 0,
            "relevant_blockers": 0,
            "max_blocker_depth": 0,
            "exposed_cards": 0,
            "k_anchors": [],
            "a_anchors": [],
            "movable_exposed": 0,
            "receiver_hits": 0,
        }
        for s in SUITS
    }
    global_fd = 0
    empty_n = 0
    visible_n = 0
    boundaries = 0
    merge_ops = 0
    tops = []
    for col in state.columns:
        tops.append(col.top())

    for col_i, col in enumerate(state.columns):
        if col.is_empty():
            empty_n += 1
            continue
        down = col.face_down
        up = col.face_up
        n_down = len(down)
        n_up = len(up)
        global_fd += n_down
        for d_i, card in enumerate(down):
            rec = by_suit[card.suit]
            rec["fd_n"] += 1
            vis_blockers = n_up
            fd_above = n_down - 1 - d_i
            rec["relevant_blockers"] += vis_blockers
            rec["max_blocker_depth"] = max(rec["max_blocker_depth"], vis_blockers + fd_above)
            if card.rank in ACCESS_RANKS:
                _anchor_slot(card.rank, rec).append(
                    {
                        "rank": card.rank,
                        "zone": "face_down",
                        "column_1": col_i + 1,
                        "visible": False,
                        "exposed": False,
                        "movable": False,
                        "visible_blockers": vis_blockers,
                        "face_down_blockers": fd_above,
                        "access_blockers": vis_blockers + fd_above,
                        "in_component": False,
                        "component_length": 1,
                    }
                )
        if not up:
            continue
        spans = same_suit_component_spans(up)
        visible_n += len(spans)
        boundaries += max(0, len(spans) - 1)
        for ci, (a, b) in enumerate(spans):
            suit = up[a].suit
            rec = by_suit[suit]
            length = b - a
            exposed = ci == len(spans) - 1
            if exposed:
                rec["exposed_components"] += 1
                rec["exposed_cards"] += length
                run = list(up[a:b])
                if SpiderState.is_movable_run(run):
                    rec["movable_exposed"] += 1
                    head = run[0]
                    for dst, top in enumerate(tops):
                        if dst == col_i or top is None:
                            continue
                        if top.suit == head.suit and top.rank == head.rank + 1:
                            rec["receiver_hits"] += 1
                            merge_ops += 1
            else:
                rec["buried_components"] += 1
                rec["relevant_blockers"] += n_up - b
                rec["max_blocker_depth"] = max(rec["max_blocker_depth"], n_up - b)
            for u_i in range(a, b):
                card = up[u_i]
                if card.rank not in ACCESS_RANKS:
                    continue
                vis_blockers = n_up - 1 - u_i
                is_exp = u_i == n_up - 1
                movable = bool(is_exp and SpiderState.is_movable_run(list(up[u_i:])))
                component_blockers = 0 if exposed else n_up - b
                if card.rank == 13 and u_i == a:
                    access_blockers = component_blockers
                elif card.rank == 1 and u_i == b - 1:
                    access_blockers = component_blockers
                else:
                    access_blockers = vis_blockers
                _anchor_slot(card.rank, rec).append(
                    {
                        "rank": card.rank,
                        "zone": "face_up",
                        "column_1": col_i + 1,
                        "visible": True,
                        "exposed": is_exp,
                        "movable": movable,
                        "visible_blockers": vis_blockers,
                        "face_down_blockers": 0,
                        "access_blockers": access_blockers,
                        "in_component": length >= 2,
                        "component_length": length,
                    }
                )

    for card in state.stock:
        if card.rank not in ACCESS_RANKS:
            continue
        rec = by_suit[card.suit]
        _anchor_slot(card.rank, rec).append(
            {
                "rank": card.rank,
                "zone": "stock",
                "column_1": None,
                "visible": False,
                "exposed": False,
                "movable": False,
                "visible_blockers": INF,
                "face_down_blockers": INF,
                "access_blockers": INF,
                "in_component": False,
                "component_length": 1,
            }
        )

    return {
        "global_fd": global_fd,
        "empty_n": empty_n,
        "visible_components": visible_n,
        "boundaries_total": boundaries,
        "legal_merge_ops": merge_ops,
        "by_suit": by_suit,
    }


def _anchor_contention(anchors: Sequence[dict]) -> int:
    cols = [a["column_1"] for a in anchors if a.get("column_1")]
    if len(cols) < 2:
        return 0
    return 1 if len(set(cols)) < len(cols) else 0


def _best_access(anchors: Sequence[dict]) -> dict:
    tab = [a for a in anchors if a.get("zone") in ("face_up", "face_down")]
    if not tab:
        return {
            "n": len(anchors),
            "visible": 0,
            "exposed": 0,
            "movable": 0,
            "min_blockers": INF,
            "in_stock": sum(1 for a in anchors if a.get("zone") == "stock"),
        }
    def burden(a):
        if a.get("access_blockers") is not None:
            return int(a["access_blockers"])
        return int(a["visible_blockers"]) + int(a["face_down_blockers"])

    best = min(tab, key=burden)
    return {
        "n": len(anchors),
        "visible": sum(1 for a in tab if a["visible"]),
        "exposed": sum(1 for a in tab if a["exposed"]),
        "movable": sum(1 for a in tab if a["movable"]),
        "min_blockers": burden(best),
        "in_stock": sum(1 for a in anchors if a.get("zone") == "stock"),
    }


def _dividend(state: SpiderState, suit: str) -> dict:
    would_flip = 0
    would_empty = 0
    imminent = False
    for col in state.columns:
        up = col.face_up
        if len(up) < 12:
            continue
        if up[0].suit != suit or up[0].rank != 13:
            continue
        if not SpiderState.is_movable_run(list(up)):
            continue
        if up[-1].rank != 1:
            continue
        imminent = True
        if col.face_down:
            would_flip += 1
        else:
            would_empty += 1
    return {
        "imminent": imminent,
        "removal_would_flip": would_flip,
        "removal_would_empty": would_empty,
        "cards_removed_if_complete": 13 if imminent else 0,
    }


def foundation_operational_viability(
    state: SpiderState,
    suit: str,
    *,
    readiness: Optional[dict] = None,
    scan: Optional[dict] = None,
    summary: Optional[dict] = None,
) -> dict:
    """Operational facts for the next foundation of ``suit``."""

    r = readiness if readiness is not None else foundation_readiness(state)
    scan = scan if scan is not None else tableau_access_scan(state)
    s = summary if summary is not None else current_tableau_summary(state)
    rd = (r.get("by_suit") or {}).get(suit) or {}
    acc = (scan.get("by_suit") or {}).get(suit) or {}
    k_anchors = list(acc.get("k_anchors") or [])
    a_anchors = list(acc.get("a_anchors") or [])
    k_acc = _best_access(k_anchors)
    a_acc = _best_access(a_anchors)
    contention = _anchor_contention(k_anchors) + _anchor_contention(a_anchors)
    div = _dividend(state, suit)
    material_ready = bool(rd.get("material_complete_now"))
    required_fd = rd.get("fd")
    cover = rd.get("cover")
    vis = {
        "suit": suit,
        "material_ready": material_ready,
        "global_fd": int(scan.get("global_fd") if scan.get("global_fd") is not None else s["face_down"]),
        "suit_fd": int(acc.get("fd_n") or 0),
        "required_fd": required_fd,
        "relevant_blockers": int(acc.get("relevant_blockers") or 0),
        "max_blocker_depth": int(acc.get("max_blocker_depth") or 0),
        "exposed_components": int(acc.get("exposed_components") or 0),
        "buried_components": int(acc.get("buried_components") or 0),
        "exposed_cards": int(acc.get("exposed_cards") or 0),
        "cover": cover,
        "visible_cover": rd.get("visible"),
        "visible_n": rd.get("visible_n"),
        "cond_len": rd.get("cond_len"),
        "edges": rd.get("edges"),
        "longest": rd.get("longest"),
        "k_len": rd.get("k_len") or 0,
        "a_len": rd.get("a_len") or 0,
        "gap": rd.get("gap"),
        "bonds": rd.get("bonds") or 0,
        "movable_exposed": int(acc.get("movable_exposed") or 0),
        "legal_merge_edges": int(acc.get("receiver_hits") or 0),
        "inaccessible_joins": max(
            0,
            int(rd.get("visible_n") or acc.get("exposed_components") or 0)
            - 1
            - int(acc.get("receiver_hits") or 0),
        ),
        "k_access": k_acc,
        "a_access": a_acc,
        "anchor_contention": contention,
        "empty_n": int(scan.get("empty_n") if scan.get("empty_n") is not None else s["empty_n"]),
        "visible_components_global": int(scan.get("visible_components") or s.get("visible_runs") or 0),
        "boundaries_total": int(scan.get("boundaries_total") or 0),
        "legal_merge_ops_global": int(scan.get("legal_merge_ops") or 0),
        "foundations": int(s["foundations"]),
        **div,
    }
    vis["k_min_blockers"] = k_acc["min_blockers"]
    vis["a_min_blockers"] = a_acc["min_blockers"]
    vis["receiver_contention"] = 1 if int(acc.get("receiver_hits") or 0) >= 2 and int(acc.get("movable_exposed") or 0) >= 2 else 0
    return vis


def operational_viability_key(v: dict, g: int = 0) -> tuple:
    """Lexicographic operational opportunity. Lower is better.

    1. global excavation
    2. component cover (unavailable → INF)
    3. relevant blockers / depth
    4. duplicate-anchor contention
    5. K/A access and length
    6. legal merge opportunities
    7. workspace / exposed components
    8. g
    """

    if not v.get("material_ready"):
        return (INF, INF, INF, INF, INF, INF, INF, INF, INF, INF, INF, int(g))
    return (
        int(v.get("global_fd") or 0),
        _n(v.get("cover")),
        int(v.get("relevant_blockers") or 0),
        int(v.get("max_blocker_depth") or 0),
        int(v.get("anchor_contention") or 0),
        int(v.get("k_min_blockers") or INF),
        int(v.get("a_min_blockers") or INF),
        -int(v.get("k_len") or 0),
        -int(v.get("a_len") or 0),
        -int(v.get("legal_merge_edges") or 0),
        -int(v.get("empty_n") or 0),
        -int(v.get("exposed_components") or 0),
        int(g),
    )


def compact_operational(v: dict) -> dict:
    keep = (
        "suit",
        "material_ready",
        "global_fd",
        "suit_fd",
        "required_fd",
        "relevant_blockers",
        "max_blocker_depth",
        "cover",
        "exposed_components",
        "buried_components",
        "legal_merge_edges",
        "inaccessible_joins",
        "k_len",
        "a_len",
        "gap",
        "k_min_blockers",
        "a_min_blockers",
        "anchor_contention",
        "empty_n",
        "boundaries_total",
        "imminent",
        "removal_would_flip",
        "removal_would_empty",
    )
    return {k: v.get(k) for k in keep}


def rank_ready_suits(
    state: SpiderState,
    *,
    readiness: Optional[dict] = None,
    scan: Optional[dict] = None,
    summary: Optional[dict] = None,
    g: int = 0,
) -> dict:
    r = readiness if readiness is not None else foundation_readiness(state)
    scan = scan if scan is not None else tableau_access_scan(state)
    s = summary if summary is not None else current_tableau_summary(state)
    ranked = []
    for suit in r.get("ready_suits") or []:
        v = foundation_operational_viability(
            state, suit, readiness=r, scan=scan, summary=s
        )
        v["key"] = operational_viability_key(v, g)
        ranked.append(v)
    ranked.sort(key=lambda rec: rec["key"])
    best = ranked[0] if ranked else None
    second = ranked[1] if len(ranked) > 1 else None
    return {
        "n_ready": int(r.get("n_ready") or 0),
        "ready_suits": list(r.get("ready_suits") or []),
        "ranked": ranked,
        "best": best,
        "second": second,
        "best_suit": None if best is None else best["suit"],
        "second_suit": None if second is None else second["suit"],
        "scan": scan,
    }
