"""Generic research action helpers.

No experiment imports. Corrected MobilityWare costing is ``rules.mw_move_cost``
via ``step_cost`` / ``apply_action``.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Sequence, Tuple, Union

from spider.cards import rank_str
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import Action
from spider.rules import MW_RULES, MobilityWareRules, deal_cost, mw_move_cost

SolverAction = Union[Action, str]


def is_deal(action: SolverAction) -> bool:
    return action == ("deal",) or action == "deal"


def stock_rows(state: SpiderState) -> int:
    return len(state.stock) // 10


def face_down_count(state: SpiderState) -> int:
    return sum(len(col.face_down) for col in state.columns)


def empty_column_indices(state: SpiderState) -> Tuple[int, ...]:
    return tuple(index for index, col in enumerate(state.columns) if col.is_empty())


def pretty_card(card) -> str:
    return f"{rank_str(card.rank)}{card.suit.upper()}"


def as_actions(raw) -> List[Action]:
    out: List[Action] = []
    for item in raw:
        if item == "deal" or item == ["deal"] or item == ("deal",):
            out.append(("deal",))
        else:
            out.append((int(item[0]), int(item[1]), int(item[2])))
    return out


def dump_actions(actions: Sequence[Action]):
    return [list(a) if a != ("deal",) else ["deal"] for a in actions]


def format_moves_text(actions: Sequence[Action], *, header: str = "") -> str:
    lines = []
    if header:
        lines.append(header.rstrip())
        if not header.endswith("\n"):
            lines.append("")
    for action in actions:
        if action == ("deal",):
            lines.append("deal")
        else:
            src, dst, k = action  # type: ignore[misc]
            lines.append(f"move {src + 1} {dst + 1} {k}")
    lines.append("")
    return "\n".join(lines)


def opening_from_deal(path: Path) -> SpiderState:
    return SpiderState.from_cards(list(load_deal(path)))


def step_cost(
    state: SpiderState,
    action: SolverAction,
    *,
    rules: MobilityWareRules = MW_RULES,
) -> int:
    if is_deal(action):
        return deal_cost()
    src, dst, k = action  # type: ignore[misc]
    src_col = state.columns[src]
    dst_col = state.columns[dst]
    return mw_move_cost(
        cards_moved=k,
        source_face_up_count=len(src_col.face_up),
        dest_was_empty=dst_col.is_empty(),
        source_face_down_count=len(src_col.face_down),
        rules=rules,
    )


def apply_action(
    state: SpiderState,
    action: SolverAction,
    *,
    rules: MobilityWareRules = MW_RULES,
) -> int:
    if is_deal(action):
        return state.deal(rules=rules)
    src, dst, k = action  # type: ignore[misc]
    return state.move(src, dst, k, rules=rules)


def capture_state(state: SpiderState, action: SolverAction) -> tuple:
    if is_deal(action):
        cols = tuple((col.face_down[:], col.face_up[:]) for col in state.columns)
        return ("d", cols, state.stock[:], state.foundations[:], state.last_move)
    src, dst, _k = action  # type: ignore[misc]
    sc = state.columns[src]
    dc = state.columns[dst]
    return (
        "m",
        src,
        dst,
        sc.face_down[:],
        sc.face_up[:],
        dc.face_down[:],
        dc.face_up[:],
        state.foundations[:],
        state.last_move,
    )


def restore_state(state: SpiderState, snap: tuple) -> None:
    if snap[0] == "d":
        _kind, cols, stock, found, last = snap
        for col, (face_down, face_up) in zip(state.columns, cols):
            col.face_down[:] = face_down
            col.face_up[:] = face_up
        state.stock[:] = stock
        state.foundations[:] = found
        state.last_move = last
        return
    _kind, src, dst, sfd, sfu, dfd, dfu, found, last = snap
    sc = state.columns[src]
    dc = state.columns[dst]
    sc.face_down[:] = sfd
    sc.face_up[:] = sfu
    dc.face_down[:] = dfd
    dc.face_up[:] = dfu
    state.foundations[:] = found
    state.last_move = last


def tableau_actions(state: SpiderState, *, rules: MobilityWareRules = MW_RULES) -> List[Action]:
    """Engine-legal tableau primitives. Deal is omitted."""

    return [action for action in state.enumerate_legal_actions(rules=rules) if action != ("deal",)]


def all_legal_actions(state: SpiderState, *, rules: MobilityWareRules = MW_RULES) -> List[Action]:
    """Engine-legal primitives including Deal when the engine says Deal is legal.

    Does not invent Deal legality. Unrestricted Deal is whatever ``rules``
    and ``SpiderState.enumerate_legal_actions`` already allow.
    """

    return list(state.enumerate_legal_actions(rules=rules))


def engine_tableau_actions(
    state: SpiderState, *, rules: MobilityWareRules = MW_RULES
) -> Tuple[List[Action], List[dict]]:
    """Compatible (actions, surprises) pair. Surprises unused; all tableau moves kept."""

    return tableau_actions(state, rules=rules), []


def rss_mb() -> Optional[float]:
    try:
        import ctypes
        from ctypes import wintypes

        class _PMC(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = _PMC()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_PMC),
            wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        handle = kernel32.GetCurrentProcess()
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return None
        return counters.PeakWorkingSetSize / (1024.0 * 1024.0)
    except Exception:
        return None


def foundation_suits(state: SpiderState) -> List[str]:
    return [run[0].suit for run in state.foundations if run]
