"""Deal-independent structural analysis of a Spider tableau.

No experiment imports, no file I/O, no search policy, no suit preference.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional, Sequence, Tuple

from spider.engine import SpiderState
from spider.metrics import Action
from spider.packed_state import pack_state
from spider.research_actions import (
    apply_action,
    capture_state,
    dump_actions,
    empty_column_indices,
    face_down_count,
    foundation_suits,
    pretty_card,
    restore_state,
    step_cost,
)

SUITS = ("s", "h", "d", "c")
INF = 99
FULL_RANKS = tuple(range(1, 14))


def empty_column_count(state: SpiderState) -> int:
    return len(empty_column_indices(state))


def foundation_count(state: SpiderState) -> int:
    return len(state.foundations)


def tableau_occupancy(state: SpiderState) -> dict:
    return {
        "face_down": face_down_count(state),
        "empty_columns": empty_column_indices(state),
        "empty_n": empty_column_count(state),
        "foundations": foundation_count(state),
        "foundation_suits": foundation_suits(state),
    }


def same_suit_components(state: SpiderState) -> List[dict]:
    """Visible same-suit runs of length >= 2. Telemetry shape, not cover math."""

    out: List[dict] = []
    for col_i, column in enumerate(state.columns):
        up = column.face_up
        i = 0
        while i < len(up):
            j = i + 1
            while (
                j < len(up)
                and up[j].suit == up[i].suit
                and up[j - 1].rank == up[j].rank + 1
            ):
                j += 1
            run = up[i:j]
            if len(run) >= 2:
                out.append(
                    {
                        "column_1": col_i + 1,
                        "suit": run[0].suit,
                        "ranks": [pretty_card(c) for c in run],
                        "length": len(run),
                        "exposed": j == len(up),
                    }
                )
            i = j
    return out


def visible_components(state: SpiderState, suit: Optional[str] = None) -> List[dict]:
    wanted = [suit] if suit else list(SUITS)
    out: List[dict] = []
    for col, column in enumerate(state.columns):
        up = column.face_up
        i = 0
        while i < len(up):
            j = i + 1
            while (
                j < len(up)
                and up[j].suit == up[i].suit
                and up[j - 1].rank == up[j].rank + 1
            ):
                j += 1
            if up[i].suit in wanted:
                run = up[i:j]
                above = up[j:]
                exposed = j == len(up)
                movable = exposed and SpiderState.is_movable_run(run)
                dests_0: List[int] = []
                if movable:
                    head = run[0]
                    for dst in range(10):
                        if dst == col:
                            continue
                        top = state.columns[dst].top()
                        if (
                            top is not None
                            and top.suit == head.suit
                            and top.rank == head.rank + 1
                            and state.can_move(col, dst, len(run))
                        ):
                            dests_0.append(dst)
                ranks = [c.rank for c in run]
                out.append(
                    {
                        "id": f"{col}:{i}:{len(run)}:{up[i].suit}",
                        "suit": up[i].suit,
                        "column_0": col,
                        "column_1": col + 1,
                        "up_index": i,
                        "cards": [pretty_card(c) for c in run],
                        "ranks": ranks,
                        "high": ranks[0],
                        "low": ranks[-1],
                        "length": len(run),
                        "exposed": exposed,
                        "movable": movable,
                        "cards_above": len(above),
                        "above": [pretty_card(c) for c in above],
                        "dests_0": dests_0,
                        "dests_1": [d + 1 for d in dests_0],
                    }
                )
            i = j
    return out


def face_down_suit_cards(state: SpiderState, suit: Optional[str] = None) -> List[dict]:
    wanted = [suit] if suit else list(SUITS)
    out = []
    for col, column in enumerate(state.columns):
        n_down = len(column.face_down)
        n_up = len(column.face_up)
        for d_i, card in enumerate(column.face_down):
            if card.suit not in wanted:
                continue
            out.append(
                {
                    "id": f"fd:{col}:{d_i}:{card.suit}{card.rank}",
                    "suit": card.suit,
                    "rank": card.rank,
                    "column_0": col,
                    "column_1": col + 1,
                    "down_index": d_i,
                    "fd_above": n_down - 1 - d_i,
                    "fu_above": n_up,
                    "cards_above": (n_down - 1 - d_i) + n_up,
                }
            )
    return out


def suit_rank_counts(state: SpiderState, suit: str) -> Dict[int, int]:
    counts = {r: 0 for r in FULL_RANKS}
    for col in state.columns:
        for card in col.face_up:
            if card.suit == suit:
                counts[card.rank] += 1
        for card in col.face_down:
            if card.suit == suit:
                counts[card.rank] += 1
    return counts


def _interval_units(comps: Sequence[dict], fd_cards: Sequence[dict], *, visible_only: bool) -> List[Tuple[int, int, int]]:
    best: Dict[Tuple[int, int], int] = {}
    for c in comps:
        key = (int(c["low"]), int(c["high"]))
        prev = best.get(key)
        if prev is None or 0 < prev:
            best[key] = 0
    if not visible_only:
        for t in fd_cards:
            key = (int(t["rank"]), int(t["rank"]))
            prev = best.get(key)
            if prev is None or 1 < prev:
                best[key] = 1
    return [(lo, hi, fd) for (lo, hi), fd in best.items()]


def min_interval_cover(units: Sequence[Tuple[int, int, int]]) -> Tuple[Optional[int], Optional[int]]:
    dp_u = [INF] * 15
    dp_f = [INF] * 15
    dp_u[1] = 0
    dp_f[1] = 0
    by_low: Dict[int, List[Tuple[int, int]]] = defaultdict(list)
    for lo, hi, fd in units:
        by_low[lo].append((hi, fd))
    for need in range(1, 14):
        if dp_u[need] >= INF:
            continue
        for hi, fd in by_low.get(need, ()):
            nxt = hi + 1
            if nxt > 14:
                continue
            nu = dp_u[need] + 1
            nf = dp_f[need] + fd
            if nu < dp_u[nxt] or (nu == dp_u[nxt] and nf < dp_f[nxt]):
                dp_u[nxt] = nu
                dp_f[nxt] = nf
    if dp_u[14] >= INF:
        return None, None
    return int(dp_u[14]), int(dp_f[14])


def component_cover(state: SpiderState, suit: str) -> dict:
    comps = visible_components(state, suit)
    fd = face_down_suit_cards(state, suit)
    vis_n, _vis_fd = min_interval_cover(_interval_units(comps, fd, visible_only=True))
    all_n, all_fd = min_interval_cover(_interval_units(comps, fd, visible_only=False))
    counts = suit_rank_counts(state, suit)
    missing = [r for r in FULL_RANKS if counts[r] == 0]
    return {
        "suit": suit,
        "visible_n": len(comps),
        "fd_n": len(fd),
        "rank_counts": counts,
        "missing_ranks": missing,
        "min_cover": all_n,
        "min_visible_cover": vis_n,
        "min_fd_cards": all_fd,
        "join_lb": None if all_n is None else all_n - 1,
        "visible_unavailable": vis_n is None,
    }


def merge_edges(state: SpiderState, suit: str, comps: Optional[Sequence[dict]] = None) -> List[Action]:
    comps = list(comps if comps is not None else visible_components(state, suit))
    by_col = {c["column_0"]: c for c in comps if c["exposed"]}
    out: List[Action] = []
    for a in comps:
        if not a["movable"]:
            continue
        for dst in a["dests_0"]:
            b = by_col.get(dst)
            if b is None or b["suit"] != suit:
                continue
            if a["high"] + 1 != b["low"]:
                continue
            if state.can_move(a["column_0"], dst, a["length"]):
                out.append((a["column_0"], dst, a["length"]))
    return out


def k_headed(comps: Sequence[dict]) -> Optional[dict]:
    headed = [c for c in comps if c["high"] == 13]
    if not headed:
        return None
    return max(headed, key=lambda c: (c["length"], -c["column_0"]))


def a_ending(comps: Sequence[dict]) -> Optional[dict]:
    ended = [c for c in comps if c["low"] == 1]
    if not ended:
        return None
    return max(ended, key=lambda c: (c["length"], -c["column_0"]))


def ka_gap(k_comp: Optional[dict], a_comp: Optional[dict]) -> Optional[int]:
    if k_comp is None or a_comp is None:
        return None
    return int(k_comp["low"]) - int(a_comp["high"]) - 1


def ka_directly_joinable(state: SpiderState, k_comp: Optional[dict], a_comp: Optional[dict]) -> bool:
    if not k_comp or not a_comp:
        return False
    if ka_gap(k_comp, a_comp) != 0:
        return False
    if not a_comp["movable"] or not k_comp["exposed"]:
        return False
    if a_comp["column_0"] == k_comp["column_0"]:
        return False
    return bool(state.can_move(a_comp["column_0"], k_comp["column_0"], a_comp["length"]))


def _metrics_from_parts(state: SpiderState, suit: str, comps: Sequence[dict], fd: Sequence[dict]) -> dict:
    vis_n, _ = min_interval_cover(_interval_units(comps, fd, visible_only=True))
    all_n, all_fd = min_interval_cover(_interval_units(comps, fd, visible_only=False))
    edges = merge_edges(state, suit, comps)
    longest = 0 if not comps else max(c["length"] for c in comps)
    cond_len = longest + (1 if edges else 0)
    kc = k_headed(comps)
    ac = a_ending(comps)
    return {
        "cover": all_n,
        "visible": vis_n,
        "edges": len(edges),
        "cond_len": cond_len,
        "gap": ka_gap(kc, ac),
        "fd": all_fd,
        "longest": longest,
        "k_len": 0 if not kc else kc["length"],
        "a_len": 0 if not ac else ac["length"],
    }


def lane_suit_metrics(state: SpiderState, suit: str) -> dict:
    comps = visible_components(state, suit)
    fd = face_down_suit_cards(state, suit)
    return _metrics_from_parts(state, suit, comps, fd)


def all_lane_metrics(state: SpiderState) -> dict:
    comps_all = visible_components(state)
    fd_all = face_down_suit_cards(state)
    by_suit_c = {s: [] for s in SUITS}
    by_suit_f = {s: [] for s in SUITS}
    for c in comps_all:
        by_suit_c[c["suit"]].append(c)
    for t in fd_all:
        by_suit_f[t["suit"]].append(t)
    return {s: _metrics_from_parts(state, s, by_suit_c[s], by_suit_f[s]) for s in SUITS}


def suit_lane_key(metrics: dict, g: int) -> tuple:
    def n(v, default=INF):
        return default if v is None else int(v)

    return (
        n(metrics.get("cover")),
        n(metrics.get("visible")),
        -int(metrics.get("edges") or 0),
        -int(metrics.get("cond_len") or 0),
        n(metrics.get("gap")),
        n(metrics.get("fd")),
        int(g),
    )


def direct_condensation(state: SpiderState, suit: str, *, g0: int = 0) -> dict:
    """Only target-suit component merges. Tiny exact graph."""

    start_comps = visible_components(state, suit)
    start_n = len(start_comps)
    start_edges = merge_edges(state, suit, start_comps)
    best = {
        "suit": suit,
        "start_n": start_n,
        "min_n": start_n,
        "merges": 0,
        "longest": 0 if not start_comps else max(c["length"] for c in start_comps),
        "k_len": 0,
        "a_len": 0,
        "k_low": None,
        "a_high": None,
        "gap": ka_gap(k_headed(start_comps), a_ending(start_comps)),
        "joinable": ka_directly_joinable(state, k_headed(start_comps), a_ending(start_comps)),
        "f2": False,
        "path": [],
        "g_add": 0,
        "start_edges": len(start_edges),
        "end_edges": len(start_edges),
    }
    kc0 = k_headed(start_comps)
    ac0 = a_ending(start_comps)
    best["k_len"] = 0 if not kc0 else kc0["length"]
    best["a_len"] = 0 if not ac0 else ac0["length"]
    best["k_low"] = None if not kc0 else kc0["low"]
    best["a_high"] = None if not ac0 else ac0["high"]
    seen = {pack_state(state): 0}

    def consider(merges: int, g_add: int, path: List[Action]) -> None:
        comps = visible_components(state, suit)
        n = len(comps)
        longest = 0 if not comps else max(c["length"] for c in comps)
        kc = k_headed(comps)
        ac = a_ending(comps)
        f2 = len(state.foundations) >= 2
        better = False
        if f2 and not best["f2"]:
            better = True
        elif not best["f2"]:
            if n < best["min_n"] or (n == best["min_n"] and longest > best["longest"]):
                better = True
        if better:
            best.update(
                min_n=n,
                longest=longest,
                merges=merges,
                g_add=g_add,
                path=dump_actions(path),
                k_len=0 if not kc else kc["length"],
                a_len=0 if not ac else ac["length"],
                k_low=None if not kc else kc["low"],
                a_high=None if not ac else ac["high"],
                gap=ka_gap(kc, ac),
                joinable=ka_directly_joinable(state, kc, ac),
                f2=f2,
                end_edges=len(merge_edges(state, suit, comps)),
            )

    def dfs(merges: int, g_add: int, path: List[Action]) -> None:
        consider(merges, g_add, path)
        if len(state.foundations) >= 2:
            best["f2"] = True
            best["merges"] = merges
            best["g_add"] = g_add
            best["path"] = dump_actions(path)
            return
        comps = visible_components(state, suit)
        for action in merge_edges(state, suit, comps):
            cost = step_cost(state, action)
            cap = capture_state(state, action)
            try:
                apply_action(state, action)
                ident = pack_state(state)
                child_g = g_add + cost
                prev = seen.get(ident)
                if prev is not None and child_g >= prev:
                    continue
                seen[ident] = child_g
                if len(state.foundations) >= 2:
                    best.update(
                        min_n=0,
                        longest=13,
                        merges=merges + 1,
                        g_add=child_g,
                        f2=True,
                        path=dump_actions(path + [action]),
                        joinable=True,
                        gap=0,
                    )
                    continue
                dfs(merges + 1, child_g, path + [action])
            finally:
                restore_state(state, cap)

    dfs(0, 0, [])
    return best
