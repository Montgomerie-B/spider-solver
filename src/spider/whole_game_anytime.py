"""Whole-game anytime search adapter (v0.58).

Starts from the untouched opening deal. Terminal success is
``state.is_solved()`` only. Heuristic lanes order only.

Does not import ``simple_*`` modules. Does not read the canonical
solution, historical F1 path, or suit/rank targets for policy.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from spider.engine import SpiderState
from spider.metrics import Action, export_actions_to_moves_file, replay_actions
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.research_actions import (
    all_legal_actions,
    empty_column_indices,
    face_down_count,
    is_deal,
    opening_from_deal,
    stock_rows,
)
from spider.search_kernel import KernelResult, SearchLimits, reconstruct_path, run_search
from spider.structural_analysis import current_tableau_summary

ROOT = Path(__file__).resolve().parents[2]
DEAL_PATH = ROOT / "deals" / "4925153.txt"

LANES = (
    "cost",
    "foundation",
    "reveal",
    "workspace",
    "construction",
    "prep",
    "epoch",
)

COST_CEILING = 300
SEARCH_UNIQUE = 800_000
SEARCH_TIME_S = 900.0
SEARCH_RSS_MB = 2.5 * 1024.0
EPOCH_ROWS = (5, 4, 3, 2, 1, 0)


def opening_state() -> SpiderState:
    return opening_from_deal(DEAL_PATH)


def opening_root(opening: Optional[SpiderState] = None) -> dict:
    opening = opening or opening_state()
    store = pack_state(opening)
    ident = pack_whole_game_identity(opening)
    return {
        "g": 0,
        "ordered_digest": store.hex(),
        "whole_game_identity": ident.hex(),
        "full_actions": [],
        "stock_rows": stock_rows(opening),
        "foundations": len(opening.foundations),
        "face_down": face_down_count(opening),
    }


def lane_keys(state: SpiderState, g: int, summary: Optional[dict] = None) -> Dict[str, tuple]:
    """Seven global lanes. Lower tuple is better. No suit or rank target."""

    s = summary or current_tableau_summary(state)
    fd = int(s["face_down"])
    f = int(s["foundations"])
    rows = int(s["stock_rows"])
    empty = int(s["empty_n"])
    bonds = int(s["same_suit_bonds"])
    longest = int(s["longest_run"])
    merges = int(s["merge_edges"])
    compress = int(s["run_compression"])
    return {
        "cost": (int(g),),
        "foundation": (-f, fd, rows, int(g)),
        "reveal": (fd, -f, -empty, int(g)),
        "workspace": (-empty, fd, -compress, int(g)),
        "construction": (-bonds, -longest, -merges, fd, int(g)),
        "prep": (-rows, fd, -bonds, -empty, int(g)),
        "epoch": (rows, -f, fd, int(g)),
    }


def _snapshot(state: SpiderState, g: int, node: int, kr: KernelResult, elapsed: float) -> dict:
    s = current_tableau_summary(state)
    rec = {
        "g": int(g),
        "node": int(node),
        "elapsed_s": float(elapsed),
        "unique": int(kr.unique),
        "expanded": int(kr.expanded),
        "stock_rows": int(s["stock_rows"]),
        "face_down": int(s["face_down"]),
        "empty_n": int(s["empty_n"]),
        "empty_columns": [i + 1 for i in empty_column_indices(state)],
        "foundations": int(s["foundations"]),
        "foundation_suits": list(s["foundation_suits"]),
        "same_suit_bonds": int(s["same_suit_bonds"]),
        "longest_run": int(s["longest_run"]),
        "merge_edges": int(s["merge_edges"]),
        "run_compression": int(s["run_compression"]),
        "ordered_digest": pack_state(state).hex(),
        "whole_game_identity": pack_whole_game_identity(state).hex(),
    }
    if rec["stock_rows"] == 0:
        from spider.structural_analysis import SUITS, lane_suit_metrics as _lsm

        rec["post_stock_topology"] = {suit: _lsm(state, suit) for suit in SUITS}
    return rec


def _better_construction(old: Optional[dict], new: dict) -> bool:
    if old is None:
        return True
    a = (
        -int(new.get("same_suit_bonds") or 0),
        -int(new.get("longest_run") or 0),
        -int(new.get("merge_edges") or 0),
        int(new.get("face_down") or 0),
        int(new.get("g") or 0),
    )
    b = (
        -int(old.get("same_suit_bonds") or 0),
        -int(old.get("longest_run") or 0),
        -int(old.get("merge_edges") or 0),
        int(old.get("face_down") or 0),
        int(old.get("g") or 0),
    )
    return a < b


@dataclass
class WholeGameResult:
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
    min_live_g: Optional[int] = None
    closed_g: Optional[int] = None
    incumbent: Optional[int] = None
    lane_pops: Dict[str, int] = field(default_factory=dict)
    lane_exp: Dict[str, int] = field(default_factory=dict)
    lane_stale: Dict[str, int] = field(default_factory=dict)
    solved: bool = False
    solution_g: Optional[int] = None
    solution_actions: List[Action] = field(default_factory=list)
    replay_ok: bool = False
    replay_g: Optional[int] = None
    accounting_fail: bool = False
    foundations_first: Dict[int, dict] = field(default_factory=dict)
    foundations_cheap: Dict[int, dict] = field(default_factory=dict)
    epochs: Dict[int, dict] = field(default_factory=dict)
    min_face_down: Optional[int] = None
    max_empty: Optional[int] = None
    max_foundations: int = 0
    best_construction: Optional[dict] = None
    best_state: Optional[dict] = None
    states_per_s: float = 0.0


def search_whole_game(
    *,
    opening: Optional[SpiderState] = None,
    max_unique: int = SEARCH_UNIQUE,
    time_limit_s: float = SEARCH_TIME_S,
    rss_abort_mb: float = SEARCH_RSS_MB,
    cost_ceiling: int = COST_CEILING,
) -> WholeGameResult:
    opening = opening or opening_state()
    root = opening_root(opening)
    started = time.perf_counter()
    out = WholeGameResult()

    def on_progress(kr: KernelResult, state: SpiderState, g: int, node: int) -> None:
        elapsed = time.perf_counter() - started
        rec = _snapshot(state, g, node, kr, elapsed)
        nfound = rec["foundations"]
        if nfound > out.max_foundations:
            out.max_foundations = nfound
        if nfound >= 1:
            if nfound not in out.foundations_first:
                out.foundations_first[nfound] = rec
            prev = out.foundations_cheap.get(nfound)
            if prev is None or rec["g"] < prev["g"]:
                out.foundations_cheap[nfound] = rec
        rows = rec["stock_rows"]
        if rows in EPOCH_ROWS:
            ep = out.epochs.get(rows)
            if ep is None:
                out.epochs[rows] = {
                    "first": rec,
                    "cheapest_g": rec["g"],
                    "cheapest": rec,
                    "min_face_down": rec["face_down"],
                    "min_fd": rec,
                    "max_foundations": rec["foundations"],
                    "max_f": rec,
                    "best_construction": rec,
                }
            else:
                if rec["g"] < ep["cheapest_g"]:
                    ep["cheapest_g"] = rec["g"]
                    ep["cheapest"] = rec
                if rec["face_down"] < ep["min_face_down"]:
                    ep["min_face_down"] = rec["face_down"]
                    ep["min_fd"] = rec
                if rec["foundations"] > ep["max_foundations"]:
                    ep["max_foundations"] = rec["foundations"]
                    ep["max_f"] = rec
                if _better_construction(ep.get("best_construction"), rec):
                    ep["best_construction"] = rec
        if out.min_face_down is None or rec["face_down"] < out.min_face_down:
            out.min_face_down = rec["face_down"]
        if out.max_empty is None or rec["empty_n"] > out.max_empty:
            out.max_empty = rec["empty_n"]
        if _better_construction(out.best_construction, rec):
            out.best_construction = rec
        if out.best_state is None:
            out.best_state = rec
        else:
            # Prefer more foundations, then fewer fd, then fewer stock rows, then lower g.
            a = (-nfound, rec["face_down"], rec["stock_rows"], rec["g"])
            b = (
                -int(out.best_state["foundations"]),
                int(out.best_state["face_down"]),
                int(out.best_state["stock_rows"]),
                int(out.best_state["g"]),
            )
            if a < b:
                out.best_state = rec

    def keys_fn(state: SpiderState, g: int) -> Dict[str, tuple]:
        return lane_keys(state, g)

    kr = run_search(
        [root],
        limits=SearchLimits(
            max_unique=max_unique,
            time_limit_s=time_limit_s,
            rss_abort_mb=rss_abort_mb,
            cost_ceiling=cost_ceiling,
        ),
        identity_fn=pack_whole_game_identity,
        store_fn=pack_state,
        unpack_fn=unpack_state,
        lane_names=LANES,
        lane_keys_fn=keys_fn,
        is_terminal=lambda st: st.is_solved(),
        actions_fn=all_legal_actions,
        on_progress=on_progress,
    )
    out.unique = kr.unique
    out.expanded = kr.expanded
    out.generated = kr.generated
    out.duplicate_skips = kr.duplicate_skips
    out.stale_skips = kr.stale_skips
    out.elapsed_s = kr.elapsed_s
    out.peak_rss_mb = kr.peak_rss_mb
    out.stop_reason = kr.stop_reason
    out.min_g = kr.min_g
    out.max_g = kr.max_g
    out.min_live_g = kr.min_live_g
    out.closed_g = kr.closed_g
    out.incumbent = kr.incumbent_g
    out.lane_pops = kr.lane_pops
    out.lane_exp = kr.lane_exp
    out.lane_stale = kr.lane_stale
    out.states_per_s = 0.0 if kr.elapsed_s <= 0 else kr.expanded / kr.elapsed_s
    if kr.terminals:
        best = min(kr.terminals, key=lambda t: (t["g"], t["store"]))
        path = reconstruct_path(kr.nodes, best["node"])
        out.solved = True
        out.solution_g = int(best["g"])
        out.solution_actions = path
        end = opening.clone()
        try:
            cost = replay_actions(end, path)
        except Exception:
            out.accounting_fail = True
            out.replay_ok = False
        else:
            out.replay_g = cost
            out.replay_ok = (
                cost == out.solution_g
                and end.is_solved()
                and len(end.foundations) == 8
                and stock_rows(end) == 0
                and all(col.is_empty() for col in end.columns)
            )
            if not out.replay_ok:
                out.accounting_fail = True
    return out


def choose_verdict(p: dict) -> tuple[str, str]:
    if p.get("accounting_fail") or (p.get("solved") and not p.get("replay_ok")):
        return "WHOLE_GAME_CONTRACT_FAILURE", "replay or accounting disagreed with the engine"
    if p.get("solved") and p.get("replay_ok"):
        return "WHOLE_GAME_AUTONOMOUS_SOLVE", "independently replayed complete solution"
    max_f = int(p.get("max_foundations") or 0)
    if max_f >= 2:
        return "WHOLE_GAME_REACHES_F2_OR_BEYOND", f"max foundations {max_f}, unsolved"
    if max_f == 1:
        return "WHOLE_GAME_REDISCOVERS_F1_ONLY", "exactly one foundation from the opening"
    epochs = p.get("epochs") or {}
    min_fd = p.get("min_face_down")
    if (isinstance(epochs, dict) and any(int(k) < 5 for k in epochs)) or (
        min_fd is not None and min_fd < int(p.get("opening_face_down") or min_fd + 1)
    ):
        return "WHOLE_GAME_PROGRESS_NO_FOUNDATION", "excavation or epoch progress without a foundation"
    return "WHOLE_GAME_SEARCH_STALLED", "no meaningful whole-game advancement inside the envelope"


def save_solution(actions: Sequence[Action], path: Path, *, g: int) -> None:
    deals = sum(1 for a in actions if is_deal(a))
    tableau = len(actions) - deals
    header = (
        f"Autonomous v0.58 whole-game solution. Corrected MW={g}. "
        f"tableau={tableau} deals={deals}. Not derived from the human trace."
    )
    export_actions_to_moves_file(list(actions), path, header=header)
