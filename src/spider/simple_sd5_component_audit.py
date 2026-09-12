"""Research-only v0.55 whole-suit component assembly audit.

Static + tiny direct-merge condensation over the exact v0.53 post-SD5
universe.  No UCS, no descendant search, no weighted score.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Dict, List, Optional, Sequence, Tuple

from spider.engine import SpiderState
from spider.metrics import Action
from spider.packed_state import pack_state, unpack_state
from spider.simple_diamond_c_bridge import dump_actions
from spider.simple_foundation_horizon import pretty_card
from spider.simple_progressive_solver import _capture, _restore, apply_action, step_cost
from spider.simple_sd5_resource_runway import SUITS

__all__ = ["SUITS"]
from spider.simple_workspace_reachability import engine_tableau_actions

INF = 99
FULL_RANKS = tuple(range(1, 14))


def visible_components(state: SpiderState, suit: Optional[str] = None) -> List[dict]:
    """Maximal contiguous face-up same-suit descending components."""

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
    """Unique (low, high, min_fd) intervals. Visible components cannot be split."""

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
    """Exact K-A interval tiling. Returns (min_units, min_fd) or (None, None)."""

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
    vis_u = _interval_units(comps, fd, visible_only=True)
    all_u = _interval_units(comps, fd, visible_only=False)
    vis_n, vis_fd = min_interval_cover(vis_u)
    all_n, all_fd = min_interval_cover(all_u)
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


def _metrics_from_parts(state: SpiderState, suit: str, comps: Sequence[dict], fd: Sequence[dict]) -> dict:
    vis_n, _ = min_interval_cover(_interval_units(comps, fd, visible_only=True))
    all_n, all_fd = min_interval_cover(_interval_units(comps, fd, visible_only=False))
    edges = merge_edges(state, suit, comps)
    longest = 0 if not comps else max(c["length"] for c in comps)
    # Ordering only: condensation length is longest visible, plus one if a legal merge exists.
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
    """Fast v0.55 topology for search ordering. Condensation is an ordering proxy."""

    comps = visible_components(state, suit)
    fd = face_down_suit_cards(state, suit)
    return _metrics_from_parts(state, suit, comps, fd)


def all_lane_metrics(state: SpiderState) -> dict:
    """One tableau pass, all four suits. Used on the search hot path."""

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
    """Lower is better. Ordering only."""

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
    if not a_comp["movable"]:
        return False
    if a_comp["column_0"] == k_comp["column_0"]:
        return False
    if not k_comp["exposed"]:
        return False
    return bool(state.can_move(a_comp["column_0"], k_comp["column_0"], a_comp["length"]))


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
            cap = _capture(state, action)
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
                _restore(state, cap)

    dfs(0, 0, [])
    if best["merges"] == 0 and best["path"] == []:
        # keep start_n merges 0; min_n already from consider/dfs
        pass
    return best


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
