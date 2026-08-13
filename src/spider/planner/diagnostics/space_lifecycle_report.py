#!/usr/bin/env python3
"""Sprint 1C diagnostics: workspace lifecycle, next-stock recovery, human trace.

Canonical 172 is diagnostic evidence only. No long search.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import parse_moves_file
from spider.planner.foundation_feasibility import analyze_foundation_feasibility
from spider.planner.reveal_graph import analyze_reveal_graph
from spider.planner.space_lifecycle import (
    WorkspaceEffectKind,
    analyze_space_lifecycle,
    empty_columns,
    empty_count,
    format_space_report,
    simulate_move_effect,
)
from spider.planner.strategic_analysis import analyze_strategic


@dataclass
class DealSpaceRow:
    deal_no: int
    pre_empties: Tuple[int, ...]
    incoming: Tuple[Tuple[int, Card], ...]
    # first later cmd where each pre-empty column is empty again
    same_col_recovery_cmd: Dict[int, Optional[int]]
    same_col_recovery_mw: Dict[int, Optional[int]]
    total_workspace_restored_cmd: Optional[int]
    total_workspace_restored_mw: Optional[int]


def _replay_to_pre_deal(cards, actions, deal_target: int) -> SpiderState:
    st = SpiderState.from_cards(list(cards))
    deals = 0
    for action in actions:
        if action == ("deal",):
            deals += 1
            if deals == deal_target:
                return st
            st.deal()
        else:
            src, dst, k = action
            st.move(src, dst, k)
    raise RuntimeError(f"deal {deal_target} not found")


def _replay_to_post_deal(cards, actions, deal_target: int) -> SpiderState:
    st = _replay_to_pre_deal(cards, actions, deal_target)
    st.deal()
    return st


def whole_trace_space_lifecycle(deal_path: Path, moves_path: Path) -> Tuple[
    List[str], List[DealSpaceRow], Dict[str, int]
]:
    """Replay full canonical trace; log space events and per-deal recovery."""
    cards = load_deal(deal_path)
    actions = parse_moves_file(moves_path)
    st = SpiderState.from_cards(list(cards))
    events: List[str] = []
    stats = {
        "creates": 0,
        "consumes": 0,
        "relocates": 0,
        "preserves": 0,
        "other": 0,
        "foundation_space": 0,
        "zero_cost_relocate": 0,
    }
    deal_rows: List[DealSpaceRow] = []

    # Tracking for recovery after each deal
    pending: Optional[dict] = None
    mw_total = 0
    cmd = 0

    for action in actions:
        cmd += 1
        if action == ("deal",):
            pre = empty_columns(st)
            pre_n = len(pre)
            # Apply deal
            st.deal()
            mw_total += 1
            incoming = []
            for c in pre:
                top = st.columns[c].top()
                if top is not None:
                    incoming.append((c, top))
            events.append(
                f"cmd {cmd} DEAL pre_empties={[x+1 for x in pre]} "
                f"incoming={[(c+1, str(card)) for c, card in incoming]}"
            )
            pending = {
                "deal_no": len(deal_rows) + 1,
                "pre": pre,
                "pre_n": pre_n,
                "incoming": tuple(incoming),
                "same_cmd": {c: None for c in pre},
                "same_mw": {c: None for c in pre},
                "mw_at_deal": mw_total,
                "total_cmd": None,
                "total_mw": None,
            }
            continue

        src, dst, k = action
        before_e = empty_columns(st)
        before_n = len(before_e)
        dest_was_empty = st.columns[dst].is_empty()
        cost = st.move(src, dst, k)
        mw_total += cost
        after_e = empty_columns(st)
        after_n = len(after_e)
        lm = st.last_move
        flipped = bool(lm and lm[3])
        found = bool(lm and lm[4])
        source_empty = st.columns[src].is_empty()
        if after_n > before_n:
            kind = "creates"
        elif after_n < before_n:
            kind = "consumes"
        elif dest_was_empty and source_empty and after_n == before_n:
            kind = "relocates"
        elif after_n == before_n:
            kind = "preserves"
        else:
            kind = "other"

        stats[kind] = stats.get(kind, 0) + 1
        if found:
            stats["foundation_space"] += 1
        if kind == "relocates" and cost == 0:
            stats["zero_cost_relocate"] += 1

        if kind in ("creates", "consumes", "relocates") or found:
            events.append(
                f"cmd {cmd} move {src+1}->{dst+1} k={k} cost={cost} "
                f"{kind} empties {before_n}->{after_n} "
                f"{[x+1 for x in before_e]}->{[x+1 for x in after_e]} "
                f"flip={flipped} found={found}"
            )

    deal_rows = _deal_recovery_table(cards, actions)
    return events, deal_rows, stats


def _deal_recovery_table(cards, actions) -> List[DealSpaceRow]:
    st = SpiderState.from_cards(list(cards))
    rows: List[DealSpaceRow] = []
    mw_total = 0
    cmd = 0
    active = None

    def finalize(act):
        nonlocal active
        if active is None:
            return
        rows.append(
            DealSpaceRow(
                deal_no=active["deal_no"],
                pre_empties=active["pre"],
                incoming=active["incoming"],
                same_col_recovery_cmd=dict(active["same_cmd"]),
                same_col_recovery_mw=dict(active["same_mw"]),
                total_workspace_restored_cmd=active["total_cmd"],
                total_workspace_restored_mw=active["total_mw"],
            )
        )
        active = None

    deal_no = 0
    for action in actions:
        cmd += 1
        if action == ("deal",):
            finalize(None)
            pre = empty_columns(st)
            pre_n = len(pre)
            st.deal()
            mw_total += 1
            deal_no += 1
            incoming = []
            for c in pre:
                top = st.columns[c].top()
                if top is not None:
                    incoming.append((c, top))
            active = {
                "deal_no": deal_no,
                "pre": pre,
                "pre_n": pre_n,
                "incoming": tuple(incoming),
                "same_cmd": {c: None for c in pre},
                "same_mw": {c: None for c in pre},
                "mw_at_deal": mw_total,
                "total_cmd": None,
                "total_mw": None,
            }
            continue
        src, dst, k = action
        mw_total += st.move(src, dst, k)
        if active is not None:
            for c in active["pre"]:
                if active["same_cmd"][c] is None and st.columns[c].is_empty():
                    active["same_cmd"][c] = cmd
                    active["same_mw"][c] = mw_total - active["mw_at_deal"]
            if (
                active["total_cmd"] is None
                and active["pre_n"] > 0
                and empty_count(st) >= active["pre_n"]
            ):
                active["total_cmd"] = cmd
                active["total_mw"] = mw_total - active["mw_at_deal"]
    finalize(None)
    return rows


def main(argv: Optional[Sequence[str]] = None) -> int:
    del argv
    deal_path = ROOT / "deals" / "4925153.txt"
    moves_path = ROOT / "solutions" / "4925153_canonical.moves"
    cards = load_deal(deal_path)
    actions = parse_moves_file(moves_path)

    print("=" * 88)
    print("SPRINT 1C — SPACE LIFECYCLE DIAGNOSTIC")
    print("=" * 88)

    # 1. Initial
    st0 = SpiderState.from_cards(list(cards))
    a0 = analyze_space_lifecycle(st0, cards=cards)
    print()
    print(format_space_report(a0, title="1) Benchmark INITIAL state"))

    # 2/3/4 pre-deal1, post-deal1, pre-deal2
    if moves_path.exists():
        for label, builder in [
            ("2) Canonical IMMEDIATELY BEFORE Deal 1", lambda: _replay_to_pre_deal(cards, actions, 1)),
            ("3) Canonical IMMEDIATELY AFTER Deal 1", lambda: _replay_to_post_deal(cards, actions, 1)),
            ("4) Canonical IMMEDIATELY BEFORE Deal 2", lambda: _replay_to_pre_deal(cards, actions, 2)),
        ]:
            st = builder()
            analysis = analyze_space_lifecycle(st, cards=cards)
            print()
            print("=" * 88)
            print(format_space_report(analysis, title=label))

        # Whole-trace deal table
        print()
        print("=" * 88)
        print("5) CANONICAL WHOLE-TRACE SPACE LIFECYCLE (stock deals)")
        print("-" * 88)
        events, deal_rows, stats = whole_trace_space_lifecycle(deal_path, moves_path)
        print(
            f"{'Deal':<5} {'Pre-empties':<16} {'Incoming':<40} "
            f"{'Same-col recovery':<28} {'Total WS restore'}"
        )
        for row in deal_rows:
            pre = [c + 1 for c in row.pre_empties]
            inc = ",".join(f"{c+1}:{card}" for c, card in row.incoming) or "—"
            same_parts = []
            for c in row.pre_empties:
                cmd = row.same_col_recovery_cmd.get(c)
                mw = row.same_col_recovery_mw.get(c)
                if cmd is None:
                    same_parts.append(f"{c+1}:never")
                else:
                    same_parts.append(f"{c+1}:cmd{cmd}/+{mw}mw")
            same = ";".join(same_parts) if same_parts else "—"
            if row.total_workspace_restored_cmd is None:
                tot = "never/not-before-next"
            else:
                tot = f"cmd{row.total_workspace_restored_cmd}/+{row.total_workspace_restored_mw}mw"
            print(f"{row.deal_no:<5} {str(pre):<16} {inc:<40} {same:<28} {tot}")

        print()
        print("Event-type counts (moves classified over full trace):")
        for k, v in stats.items():
            print(f"  {k}: {v}")
        print()
        print("Sample space-changing events (first 25):")
        for e in events[:25]:
            print(" ", e)

        # Sprint 1B disagreement context at pre-deal1
        print()
        print("=" * 88)
        print("6) WORKSPACE CONTEXT FOR SPRINT 1B REVEAL PRIORITIES (pre-Deal 1)")
        print("-" * 88)
        st_pre1 = _replay_to_pre_deal(cards, actions, 1)
        sa = analyze_strategic(st_pre1, cards=cards)
        print(f"empty_count={sa.space.workspace.empty_count} "
              f"empties={[c+1 for c in sa.space.workspace.empty_columns]}")
        # Top reveal opportunities with workspace burden
        top = sa.reveal.top_opportunities(6) if sa.reveal else ()
        for opp in top:
            col = opp.prefix.column
            # deepest context for column
            ctxs = [
                c
                for c in sa.space.reveal_contexts
                if c.column == col
                and c.stop_reveal_order == opp.prefix.stop_reveal_order
            ]
            ctx = ctxs[0] if ctxs else None
            seq = " -> ".join(str(c) for c in opp.prefix.cards_unlocked)
            burden = ctx.heuristic_workspace_burden if ctx else "?"
            recov = ctx.heuristic_recovery_outlook if ctx else "?"
            print(
                f"  col {col+1} interest={opp.heuristic_interest} "
                f"prefix={opp.prefix.unavoidable_reveal_count} [{seq}]"
            )
            print(f"    workspace_burden={burden} recovery_outlook={recov}")
            if ctx:
                n_moves = len(ctx.immediate_excavation_moves)
                n_consume = sum(
                    1
                    for m in ctx.immediate_excavation_moves
                    if m.effect == WorkspaceEffectKind.CONSUMES
                )
                n_reloc = sum(
                    1
                    for m in ctx.immediate_excavation_moves
                    if m.effect == WorkspaceEffectKind.RELOCATES
                )
                print(
                    f"    immediate_moves={n_moves} "
                    f"consume={n_consume} relocate={n_reloc} "
                    f"can_use_empty={ctx.can_start_with_existing_empty}"
                )

    # Synthetic unrelated
    print()
    print("=" * 88)
    print("7) UNRELATED SYNTHETIC STATE")
    print("-" * 88)
    cols = [
        Column([], [Card("s", 9), Card("s", 8)]),
        Column([], []),
        Column([Card("c", 2)], [Card("h", 4)]),
    ]
    while len(cols) < 10:
        cols.append(Column([], [Card("d", 5 if len(cols) % 2 else 4)]))
    stock = [Card("h", r) for r in range(1, 11)] * 5
    st_syn = SpiderState(cols, stock, [])
    a_syn = analyze_space_lifecycle(st_syn, include_reveal_link=True)
    print(format_space_report(a_syn, title="Synthetic: open spade column + one empty"))

    print()
    print("Done (no long search).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
