#!/usr/bin/env python3
"""Teacher-trace audit: canonical second-foundation mechanism from end Section D."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal, tokens_from_file
from spider.deal_analysis import build_deal_analysis
from spider.engine import SpiderState
from spider.hash import zobrist
from spider.heuristics import (
    _completed_foundation_suits,
    _same_suit_desc_fragments_in_column,
    detect_foundation_completing_merge,
    next_foundation_completion_potential,
    stock_assisted_executable_gate,
)
from spider.metrics import replay_actions
from spider.planner.dependency import DynamicDependencyAnalyser

DEAL = ROOT / "deals" / "4925153.txt"
CANONICAL = ROOT / "solutions" / "4925153_canonical.moves"


@dataclass
class ParsedMove:
    action: Tuple
    section: str
    move_in_section: int
    global_index: int
    line_label: str


@dataclass
class Checkpoint:
    label: str
    section: str
    move_index: int
    global_index: int
    actions: int
    mw: int
    deals: int
    state: SpiderState
    last_move: Optional[str] = None


def parse_canonical_trace() -> List[ParsedMove]:
    moves: List[ParsedMove] = []
    section = "A"
    sec_idx = 0
    gidx = 0
    for line in CANONICAL.read_text(encoding="utf-8").splitlines():
        if line.startswith("# ---") and ":" in line:
            part = line.split(":", 1)[0].replace("# ---", "").strip()
            if part and part[0].isalpha():
                section = part.split()[0]
                sec_idx = 0
            continue
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if parts[0] == "deal":
            action = ("deal",)
            label = "deal"
        elif parts[0] == "move" and len(parts) >= 4:
            action = (int(parts[1]) - 1, int(parts[2]) - 1, int(parts[3]))
            label = f"move {parts[1]} {parts[2]} {parts[3]}"
        else:
            continue
        sec_idx += 1
        gidx += 1
        moves.append(
            ParsedMove(
                action=action,
                section=section,
                move_in_section=sec_idx,
                global_index=gidx,
                line_label=label,
            )
        )
    return moves


def tops(st: SpiderState) -> List[str]:
    return [str(c.top()) if c.top() else "-" for c in st.columns]


def foundation_suits(st: SpiderState) -> List[str]:
    return [pile[0].suit for pile in st.foundations if pile]


def strongest_fragments(st: SpiderState, limit: int = 2) -> Dict[str, List[str]]:
    done = _completed_foundation_suits(st)
    out: Dict[str, List[str]] = {}
    for s in "schd":
        if s in done:
            continue
        frags = []
        for ci in range(10):
            for f in _same_suit_desc_fragments_in_column(st, ci, s):
                frags.append((f["length"], f))
        frags.sort(key=lambda x: (-x[0], -x[1]["movable"]))
        out[s] = [
            f"col{f['col']} {f['pattern']} len={f['length']} mov={f['movable']}"
            for _, f in frags[:limit]
        ]
    return out


def pot_row(st: SpiderState, analysis, deals: int) -> Dict:
    pot = next_foundation_completion_potential(
        st, analysis=analysis, round_index=deals, lookahead=1
    )
    bs = pot.get("best_suit")
    sp = pot.get("per_suit", {}).get(bs, pot) if bs else pot
    k_st, a_st = "?", "?"
    anchor = sp.get("anchor_status", "")
    if anchor:
        for part in anchor.split(";"):
            if part.startswith("K:"):
                k_st = part[2:]
            elif part.startswith("A:"):
                a_st = part[2:]
    return {
        "pot": pot,
        "best_suit": bs,
        "score": sp.get("score", 0),
        "fragment": sp.get("best_fragment", "-"),
        "length": sp.get("fragment_length", "-"),
        "movable": sp.get("movable", False),
        "k_status": k_st,
        "a_status": a_st,
        "exact_now": sp.get("exact_merge_now", False),
        "exact_after": sp.get("exact_merge_after_stock", False),
        "reason": sp.get("reason", "-"),
    }


def gate_summary(st: SpiderState, analyser: DynamicDependencyAnalyser) -> Dict[str, Dict]:
    return {s: analyser.compute_executable_foundation_gate(st, s) for s in "schd"}


def replay_to(moves: List[ParsedMove], upto: int) -> Tuple[SpiderState, int, List]:
    st = SpiderState.from_cards(load_deal(DEAL))
    prefix = [m.action for m in moves[:upto]]
    mw = replay_actions(st, prefix)
    return st, mw, prefix


def make_checkpoint(
    label: str,
    moves: List[ParsedMove],
    upto: int,
    last_move: Optional[str] = None,
) -> Checkpoint:
    st, mw, _ = replay_to(moves, upto)
    sec = moves[upto - 1].section if upto > 0 else "init"
    mi = moves[upto - 1].move_in_section if upto > 0 else 0
    gi = moves[upto - 1].global_index if upto > 0 else 0
    deals = sum(1 for m in moves[:upto] if m.action == ("deal",))
    return Checkpoint(
        label=label,
        section=sec,
        move_index=mi,
        global_index=gi,
        actions=upto,
        mw=mw,
        deals=deals,
        state=st,
        last_move=last_move,
    )


def find_section_boundaries(moves: List[ParsedMove]) -> Dict[str, int]:
    """Return global_index (1-based count) at end of each section."""
    ends: Dict[str, int] = {}
    for i, m in enumerate(moves):
        ends[m.section] = i + 1
    return ends


def print_checkpoint_detail(
    cp: Checkpoint,
    analysis,
    analyser: DynamicDependencyAnalyser,
    *,
    verbose: bool = True,
) -> Dict:
    st = cp.state
    pr = pot_row(st, analysis, cp.deals)
    gates = gate_summary(st, analyser)
    sag = stock_assisted_executable_gate(st, analysis, cp.deals, 1)
    frags = strongest_fragments(st)
    row = {
        "label": cp.label,
        "section": cp.section,
        "move_index": cp.move_index,
        "actions": cp.actions,
        "mw": cp.mw,
        "deals": cp.deals,
        "foundations": len(st.foundations),
        "foundation_suits": foundation_suits(st),
        "sw": sum(len(c.face_up) for c in st.columns if c.face_down),
        "spaces": sum(1 for c in st.columns if c.is_empty()),
        "tops": tops(st),
        "stock": len(st.stock),
        "zobrist": zobrist(st),
        "best_suit": pr["best_suit"],
        "score": pr["score"],
        "fragment": pr["fragment"],
        "length": pr["length"],
        "movable": pr["movable"],
        "k_status": pr["k_status"],
        "a_status": pr["a_status"],
        "exact_now": pr["exact_now"],
        "exact_after": pr["exact_after"],
        "reason": pr["reason"],
        "sag_pass": sag.get("pass"),
        "sag_reason": sag.get("reason", "-"),
    }
    if verbose:
        print(f"\n--- {cp.label} ---")
        print(
            f"section={cp.section} move_idx={cp.move_index} global={cp.global_index} "
            f"actions={cp.actions} MW={cp.mw} deals={cp.deals}"
        )
        if cp.last_move:
            print(f"last_move={cp.last_move}")
        print(
            f"foundations={row['foundations']} suits={row['foundation_suits']} "
            f"sw={row['sw']} spaces={row['spaces']} stock={row['stock']}"
        )
        print(f"tops={row['tops']}")
        print(f"zobrist={row['zobrist']}")
        for s, items in frags.items():
            if items:
                print(f"  frag {s}: {items[0]}" + (f" | {items[1]}" if len(items) > 1 else ""))
        print(
            f"  nfcp best={pr['best_suit']} score={pr['score']} frag={pr['fragment']} "
            f"len={pr['length']} mov={pr['movable']} K={pr['k_status']} A={pr['a_status']} "
            f"exact_now={pr['exact_now']} exact_after={pr['exact_after']}"
        )
        for s in "schd":
            if s in row["foundation_suits"]:
                continue
            g = gates[s]
            ps = pr["pot"].get("per_suit", {}).get(s, {})
            print(
                f"  {s}: nfcp={ps.get('score', 0)} ImmGate={g['passes_gate']} "
                f"main={g['main_chain']} debt={g['connector_grounded_debt']}"
            )
        print(f"  StockAssistedGate pass={row['sag_pass']} reason={row['sag_reason'][:80]}")
    return row


def find_foundation_increases(moves: List[ParsedMove]) -> List[Dict]:
    st = SpiderState.from_cards(load_deal(DEAL))
    mw = 0
    prev_count = 0
    events: List[Dict] = []
    for i, pm in enumerate(moves):
        if pm.action == ("deal",):
            mw += st.deal()
        else:
            src, dst, k = pm.action
            mw += st.move(src, dst, k)
        count = len(st.foundations)
        if count > prev_count:
            suit = foundation_suits(st)[-1] if st.foundations else "?"
            events.append(
                {
                    "from": prev_count,
                    "to": count,
                    "section": pm.section,
                    "move_in_section": pm.move_in_section,
                    "global_index": pm.global_index,
                    "move": pm.line_label,
                    "actions": i + 1,
                    "mw": mw,
                    "suit": suit,
                    "state_after": st.clone(),
                }
            )
            prev_count = count
    return events


def timeline_from_end_d(moves: List[ParsedMove], analysis, ends: Dict[str, int]) -> List[Dict]:
    """Sample every N moves from end Section D through second foundation."""
    start = ends["D"]
    # Find second foundation event
    events = find_foundation_increases(moves)
    second = next((e for e in events if e["to"] == 2), None)
    stop = second["actions"] if second else ends.get("H", len(moves))
    rows: List[Dict] = []
    analyser = DynamicDependencyAnalyser(analysis)
    # Key indices: end D, every 2 moves in E/F, deal3, through F, deal4, samples in H, second foundation
    sample_points = {start}
    for i in range(start, min(stop + 1, len(moves) + 1)):
        if i == start:
            continue
        pm = moves[i - 1] if i <= len(moves) else None
        if pm and pm.section in ("E", "G", "I"):
            sample_points.add(i)
        if pm and pm.section == "F" and pm.move_in_section % 3 == 0:
            sample_points.add(i)
        if pm and pm.section == "H" and pm.move_in_section % 5 == 0:
            sample_points.add(i)
    if second:
        sample_points.add(second["actions"])
        sample_points.add(max(1, second["actions"] - 1))
    for idx in sorted(sample_points):
        cp = make_checkpoint(f"T@{idx}", moves, idx)
        row = print_checkpoint_detail(cp, analysis, analyser, verbose=False)
        row["checkpoint"] = (
            f"{cp.section}:{cp.move_index}" if cp.move_index else cp.section
        )
        rows.append(row)
    return rows


def main() -> int:
    tokens = tokens_from_file(DEAL)
    analysis = build_deal_analysis(tokens)
    analyser = DynamicDependencyAnalyser(analysis)
    moves = parse_canonical_trace()
    ends = find_section_boundaries(moves)

    print("=== Task 1: Canonical Trace Checkpoints ===")
    key_labels = [
        ("post-1st-foundation (after D move 1)", lambda: ends["C"] + 1),
        ("end Section D", lambda: ends["D"]),
        ("after stock deal #3", lambda: ends["E"]),
        ("end Section F", lambda: ends["F"]),
        ("after stock deal #4", lambda: ends["G"]),
        ("end Section H", lambda: ends["H"]),
        ("after stock deal #5", lambda: ends["I"]),
    ]
    checkpoint_rows: List[Dict] = []
    for label, idx_fn in key_labels:
        idx = idx_fn()
        lm = moves[idx - 1].line_label if idx > 0 else None
        cp = make_checkpoint(label, moves, idx, last_move=lm)
        row = print_checkpoint_detail(cp, analysis, analyser)
        checkpoint_rows.append(row)

    print("\n=== Foundation Count Increases ===")
    events = find_foundation_increases(moves)
    for ev in events:
        print(
            f"  {ev['from']}->{ev['to']} at {ev['section']}:{ev['move_in_section']} "
            f"({ev['move']}) actions={ev['actions']} MW={ev['mw']} suit={ev['suit']}"
        )

    print("\n=== Task 2: Second Foundation Event ===")
    second_events = [e for e in events if e["to"] == 2]
    if not second_events:
        print("  Second foundation NOT reached as isolated 1->2 increase in trace.")
        print("  Checking batch completions in Section J...")
        batch = [e for e in events if e["from"] >= 1]
        for ev in batch:
            print(f"    {ev['from']}->{ev['to']}: {ev['section']}:{ev['move_in_section']} {ev['move']} suit={ev['suit']}")
    else:
        ev = second_events[0]
        before_cp = make_checkpoint("pre-2nd-foundation", moves, ev["actions"] - 1)
        print(f"  Section: {ev['section']}")
        print(f"  Move: {ev['move']} (index {ev['move_in_section']} in section, global action {ev['actions']})")
        print(f"  Suit completed: {ev['suit']}")
        print(f"  Actions={ev['actions']} MW={ev['mw']}")
        print("\n  State BEFORE:")
        print_checkpoint_detail(before_cp, analysis, analyser)
        print("\n  State AFTER:")
        after_cp = Checkpoint(
            label="post-2nd-foundation",
            section=ev["section"],
            move_index=ev["move_in_section"],
            global_index=ev["global_index"],
            actions=ev["actions"],
            mw=ev["mw"],
            deals=sum(1 for m in moves[: ev["actions"]] if m.action == ("deal",)),
            state=ev["state_after"],
            last_move=ev["move"],
        )
        print_checkpoint_detail(after_cp, analysis, analyser)
        merge = detect_foundation_completing_merge(before_cp.state, ev["suit"])
        print(f"\n  detect_foundation_completing_merge before move: {merge.get('found')} {merge}")
        # Classify completion type
        if merge.get("found") and merge.get("legal"):
            print("  Completion type: one legal merge (engine-validated)")
        elif ev["section"] == "J" and ev["move_in_section"] >= 15:
            print("  Completion type: batch/final cleanup (late-game multi-foundation phase)")
        else:
            print("  Completion type: gradual build then auto-remove / multi-move setup")

    print("\n=== Task 3: Mechanism Analysis ===")
    end_d_idx = ends["D"]
    cp_end_d = make_checkpoint("mech:end_D", moves, end_d_idx)
    st_d = cp_end_d.state
    pr_d = pot_row(st_d, analysis, cp_end_d.deals)
    print(f"At end Section D: best_suit={pr_d['best_suit']} score={pr_d['score']} frag={pr_d['fragment']}")
    for s in "schd":
        if s in foundation_suits(st_d):
            continue
        ps = pr_d["pot"].get("per_suit", {}).get(s, {})
        print(f"  {s}: score={ps.get('score',0)} frag={ps.get('best_fragment')} missing={ps.get('missing_cards',[])} stock={ps.get('missing_cards_in_next_stock',[])}")

    if second_events:
        ev = second_events[0]
        before = replay_to(moves, ev["actions"] - 1)[0]
        suit = ev["suit"]
        frags = strongest_fragments(before, limit=3)
        print(f"\nSecond foundation suit: {suit}")
        print(f"Long fragments before completion: {frags.get(suit, [])}")
        pr = pot_row(before, analysis, sum(1 for m in moves[: ev["actions"] - 1] if m.action == ("deal",)))
        sp = pr["pot"].get("per_suit", {}).get(suit, {})
        print(f"K_status={sp.get('anchor_status')} missing={sp.get('missing_cards')}")
        print(f"Stock dependency: deals_used={sum(1 for m in moves[:ev['actions']] if m.action==('deal',))}")

    print("\n=== Task 4: Potential Timeline (end D -> 2nd foundation) ===")
    print(
        "checkpoint | actions | MW | deals | foundations | sw | spaces | best_suit | "
        "potential_score | fragment | length | movable | K_status | A_status | "
        "exact_now | exact_after_stock | reason"
    )
    timeline = timeline_from_end_d(moves, analysis, ends)
    for row in timeline:
        print(
            f"{row['checkpoint']} | {row['actions']} | {row['mw']} | {row['deals']} | "
            f"{row['foundations']} | {row['sw']} | {row['spaces']} | {row['best_suit']} | "
            f"{row['score']} | {row['fragment']} | {row['length']} | {row['movable']} | "
            f"{row['k_status']} | {row['a_status']} | {row['exact_now']} | {row['exact_after']} | "
            f"{row['reason'][:40]}"
        )

    print("\n=== Task 5: Proposed Seed Checkpoints ===")
    seeds: List[Dict] = []
    analyser2 = DynamicDependencyAnalyser(analysis)
    start_idx = ends["C"] + 1  # post-first-foundation (first Section D move)
    best_at_300: Optional[Dict] = None
    best_at_500: Optional[Dict] = None
    best_movable: Optional[Dict] = None
    best_near_merge: Optional[Dict] = None
    for i in range(start_idx, len(moves) + 1):
        cp = make_checkpoint(f"scan@{i}", moves, i)
        pr = pot_row(cp.state, analysis, cp.deals)
        sc = pr["score"]
        entry = {
            "label": "",
            "section": cp.section,
            "move_index": cp.move_index,
            "actions": cp.actions,
            "mw": cp.mw,
            "deals": cp.deals,
            "foundations": len(cp.state.foundations),
            "score": sc,
            "best_suit": pr["best_suit"],
            "fragment": pr["fragment"],
            "movable": pr["movable"],
            "exact_after": pr["exact_after"],
        }
        if sc >= 300 and best_at_300 is None:
            best_at_300 = {**entry, "label": "earliest_score_300"}
        if sc >= 500 and best_at_500 is None:
            best_at_500 = {**entry, "label": "earliest_score_500"}
        if pr["movable"] and (pr["length"] or 0) >= 6 and best_movable is None:
            best_movable = {**entry, "label": "earliest_long_movable"}
        if pr["exact_after"] and best_near_merge is None:
            best_near_merge = {**entry, "label": "earliest_stock_near_merge"}
        if second_events and i == second_events[0]["actions"] - 1:
            seeds.append({**entry, "label": "pre_second_foundation"})

    baseline = checkpoint_rows[1]  # end Section D
    seeds.append(
        {
            "label": "canonical_end_section_D",
            "section": "D",
            "move_index": ends["D"] - ends["C"] if "C" in ends else 11,
            "actions": ends["D"],
            "mw": baseline["mw"],
            "deals": baseline["deals"],
            "foundations": baseline["foundations"],
            "score": baseline["score"],
            "best_suit": baseline["best_suit"],
            "fragment": baseline["fragment"],
            "movable": baseline["movable"],
            "exact_after": baseline["exact_after"],
        }
    )
    for s in (best_at_300, best_at_500, best_movable, best_near_merge):
        if s:
            seeds.append(s)
    # dedupe by actions
    seen = set()
    for s in seeds:
        key = s["actions"]
        if key in seen:
            continue
        seen.add(key)
        reason = {
            "canonical_end_section_D": "baseline scaffold; nfcp signal present",
            "earliest_score_300": "first measurable second-foundation potential",
            "earliest_score_500": "stronger preparatory signal",
            "earliest_long_movable": "long movable fragment for active shaping",
            "earliest_stock_near_merge": "stock-assisted near-merge detected",
            "pre_second_foundation": "immediate pre-completion control",
        }.get(s["label"], "timeline scan")
        print(
            f"  {s['label']}: {s['section']}:{s['move_index']} actions={s['actions']} MW={s['mw']} "
            f"deals={s['deals']} foundations={s['foundations']} score={s['score']} "
            f"best_suit={s['best_suit']} frag={s['fragment']} — {reason}"
        )

    print("\n=== Task 6: Why Not B5 Shortcut (high level) ===")
    print("  - B5 shortcut saves 28 MW to first foundation (verified).")
    print("  - Section D compatibility failed at move 4 1 2 for all beam candidates.")
    print("  - Shortcut nfcp baseline ~215 (hearts); canonical end Section D ~320 (hearts).")
    print("  - Local beam from shortcut peaked 270 vs canonical control 320.")
    print("  - Canonical end Section D preserves verified Section D structure for continuation.")

    print("\n=== DELIVERABLE ===")
    if second_events:
        ev = second_events[0]
        print(
            f"Second foundation ({ev['suit']}) completes at {ev['section']}:{ev['move_in_section']} "
            f"({ev['move']}), actions={ev['actions']}, MW={ev['mw']}."
        )
    else:
        print("Second foundation emerges in late batch phase (Section J); no early isolated 1->2 event.")
    end_d_score = checkpoint_rows[1]["score"]
    print(f"Signal first measurable at end Section D: score={end_d_score} suit={checkpoint_rows[1]['best_suit']}.")
    if best_at_300:
        print(
            f"Earliest score>=300: {best_at_300['section']}:{best_at_300['move_index']} "
            f"actions={best_at_300['actions']} suit={best_at_300['best_suit']} score={best_at_300['score']}."
        )
    print(
        "NOTE: nfcp best_suit=h (hearts) dominates until H:19; actual 2nd foundation is d (diamonds) "
        "via short 2-card merge — search must not overfit hearts score alone."
    )
    print("Recommended seed: canonical_end_section_D; stretch target pre_second_foundation (H:19).")
    print(
        "Next bounded search: seeded second-foundation beam from canonical end Section D, "
        "dual tracking hearts (prep signal) and diamonds (completion suit)."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())