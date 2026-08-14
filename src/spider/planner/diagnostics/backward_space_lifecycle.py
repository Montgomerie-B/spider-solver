#!/usr/bin/env python3
"""One-off diagnostic: backward strategic dependency / space lifecycle.

Canonical solution is used only as a validation tape. Analysis at each
checkpoint never sees future moves.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.planner.backward_strategy import (
    Urgency,
    analyze_backward,
)
from spider.planner.space_lifecycle import empty_columns, empty_count
from spider.planner.workspace_obstruction import open_column_facts


def _walk_checkpoints(start: SpiderState, actions):
    """HARD walk. Returns named snapshots just before the labelled event."""
    st = start.clone()
    g = 0
    deals = 0
    snaps: Dict[str, Tuple[SpiderState, int, int]] = {}
    snaps["A_opening"] = (st.clone(), 0, 0)
    first_create_at = None
    first_use_at = None
    prev_e = empty_count(st)

    for i, a in enumerate(actions):
        e_before = empty_count(st)
        if a == ("deal",):
            deals += 1
            if deals == 1:
                snaps["C_pre_deal1"] = (st.clone(), g, i)
            elif deals == 2:
                snaps["D_pre_deal2"] = (st.clone(), g, i)
            elif deals == 5:
                snaps["E_pre_deal5"] = (st.clone(), g, i)
            g += replay_actions(st, [a])
            if deals == 2:
                snaps["D_post_deal2"] = (st.clone(), g, i + 1)
            elif deals == 5:
                snaps["F_post_deal5"] = (st.clone(), g, i + 1)
        else:
            g += replay_actions(st, [a])
        e_after = empty_count(st)
        if first_create_at is None and e_after > prev_e:
            first_create_at = i
            snaps["B_first_space_create"] = (st.clone(), g, i + 1)
        if (
            first_create_at is not None
            and first_use_at is None
            and e_after < e_before
        ):
            first_use_at = i
            snaps["B_first_space_use"] = (st.clone(), g, i + 1)
        prev_e = e_after
    return snaps, first_create_at, first_use_at


def _human_next_columns(actions, start_i: int, n: int = 8) -> List[int]:
    cols = []
    for a in actions[start_i : start_i + n]:
        if a == ("deal",):
            break
        src, dst, _k = a
        cols.append(src)
    return cols


def _human_prev_columns(actions, end_i: int, n: int = 8) -> List[int]:
    cols = []
    for a in actions[max(0, end_i - n) : end_i]:
        if a == ("deal",):
            cols = []
            continue
        src, dst, _k = a
        cols.append(src)
    return cols


def _print_buried(an, n=8):
    print("  buried cards (top value):")
    print(
        f"    {'card':<5} {'col':>3} {'d':>2} {'rev':>3} {'urg':<26} "
        f"{'prereq':<14} {'ep':>3} {'val':>5} notes"
    )
    for b in an.buried[:n]:
        print(
            f"    {str(b.card):<5} {b.column + 1:3d} {b.reveal_order:2d} "
            f"{b.min_reveals:3d} {b.urgency.value:<26} {b.prereq_status.value:<14} "
            f"{b.earliest_useful_epoch:3d} {b.value_score:5.1f} "
            f"{'; '.join(b.notes[:2])}"
        )
    urg = {}
    for b in an.buried:
        urg[b.urgency.value] = urg.get(b.urgency.value, 0) + 1
    print(f"    urgency counts: {urg}")


def _print_projects(an, n=8):
    print("  excavation projects / meet-in-the-middle rank:")
    print(
        f"    {'rk':>2} {'col':>3} {'fd':>3} {'comb':>5} {'fwd':>4} {'bwd':>4} "
        f"{'stk':>4} {'unl':>5} {'open~':>5} start latent"
    )
    for i, r in enumerate(an.ranked[:n], 1):
        p = next(x for x in an.projects if x.column == r.column)
        print(
            f"    {i:2d} {r.column + 1:3d} {p.face_down:3d} {r.combined:5.2f} "
            f"{r.forward:4.2f} {r.backward:4.2f} {r.stock:4.2f} "
            f"{p.unlock_value:5.0f} {p.approx_open_cost:5d} "
            f"{'Y' if p.can_start_now else '.'}     "
            f"{'Y' if p.latent_workspace else '.'}"
        )
        if p.important:
            print(f"       important: {', '.join(p.important[:3])}")


def _print_liquidity(an):
    liq = an.liquidity
    print(
        f"  space: now={liq.spaces_now} empties={[c+1 for c in liq.empty_columns]} "
        f"open={liq.fully_open} nk={liq.fully_open_nonking} minfd={liq.min_column_fd} "
        f"1-create={liq.one_move_creates} cheapest={liq.cheapest_create} "
        f"({liq.create_status})"
    )
    print(
        f"    regain_if_consumed={liq.regain_if_consumed} "
        f"recoverability={liq.recoverability} "
        f"consume_plausible={liq.consume_is_plausible}"
    )
    for n in liq.notes:
        print(f"    note: {n}")
    print("  if one space existed, we would:")
    if not an.top_uses:
        print("    (no candidate uses)")
    for u in an.top_uses[:5]:
        print(
            f"    {u.kind:<22} col {u.column + 1:<2} cost~{u.approx_cost} "
            f"val={u.value:.0f}  {u.benefit}"
        )


def _print_stock(an):
    s = an.stock
    print(
        f"  stock pass: rec={s.recommendation} post_e={s.post_deal_empty} "
        f"post_ws={s.post_deal_ws_cost} post_nk={s.post_deal_open_nk}"
    )
    print(f"    carry: {s.carry_empty_assessment}")
    print(f"    fill : {s.fill_then_recreate_assessment}")
    if s.incoming:
        row = " ".join(f"{c+1}:{card}" for c, card in s.incoming)
        print(f"    incoming: {row}")
        print(f"    landings: {list(s.landings)}")
    if s.receiver_wishes:
        print("    receiver wishes:")
        for w in s.receiver_wishes[:5]:
            print(
                f"      col {w.column + 1} {w.incoming} now={w.landing_now} "
                f"want {w.desired_top} ({w.importance:.0f}) {w.reason}"
            )
    if s.cards_wanted_before:
        print("    wanted before deal:")
        for w in s.cards_wanted_before[:5]:
            print(f"      {w}")
    if s.projects_unlocked:
        print("    unlocked by incoming row:")
        for p in s.projects_unlocked[:5]:
            print(f"      {p}")
    for n in s.notes:
        print(f"    note: {n}")


def _compare_human(an, human_cols: List[int], label: str, hits: List[str]):
    top_cols = [r.column for r in an.ranked[:3] if an.projects]
    human_src = [c for c in human_cols if c >= 0]
    overlap = [c for c in human_src if c in top_cols]
    print(f"  human next src cols (1-based): {[c+1 for c in human_src]}")
    print(f"  analyser top-3 cols: {[c+1 for c in top_cols]}")
    print(f"  overlap: {[c+1 for c in overlap] or '—'}")
    # Did analysis surface a useful-now card the human then exposed?
    now_cols = {
        b.column
        for b in an.buried
        if b.urgency == Urgency.USEFUL_NOW and b.value_score >= 16
    }
    now_hit = [c for c in human_src if c in now_cols]
    if overlap:
        hits.append(f"{label}: top-3 overlap { [c+1 for c in overlap] }")
    elif now_hit:
        hits.append(f"{label}: useful_now col touched { [c+1 for c in now_hit] }")
    else:
        hits.append(f"{label}: no top-3 overlap with next human sources")


def main() -> int:
    t0 = time.time()
    cards = load_deal(ROOT / "deals" / "4925153.txt")
    start = SpiderState.from_cards(list(cards))
    actions = parse_moves_file(ROOT / "solutions" / "4925153_canonical.moves")

    snaps, i_create, i_use = _walk_checkpoints(start, actions)
    print("BACKWARD STRATEGIC DEPENDENCY / SPACE-LIFECYCLE")
    print("Canonical tape used only for checkpoints + post-hoc comparison.")
    print(f"  first_space_create action_index={i_create}")
    print(f"  first_space_use    action_index={i_use}")
    print(f"  checkpoints: {sorted(snaps)}")

    order = [
        "A_opening",
        "B_first_space_create",
        "B_first_space_use",
        "C_pre_deal1",
        "D_pre_deal2",
        "D_post_deal2",
        "E_pre_deal5",
        "F_post_deal5",
    ]
    hits: List[str] = []
    analyses = {}
    for key in order:
        if key not in snaps:
            print(f"\n=== {key} MISSING ===")
            continue
        st, g, idx = snaps[key]
        fd = sum(len(c.face_down) for c in st.columns)
        n_open, n_nk, min_fd = open_column_facts(st)
        print()
        print("=" * 92)
        print(
            f"{key}  g={g} fd={fd} e={empty_count(st)} "
            f"open={n_open} nk={n_nk} minfd={min_fd} stock={len(st.stock)} "
            f"action_idx={idx}"
        )
        an = analyze_backward(st, cards=cards)
        analyses[key] = (an, st, g, idx)
        _print_buried(an)
        _print_projects(an)
        _print_liquidity(an)
        _print_stock(an)
        if key.startswith("C_pre") or key.startswith("D_pre") or key.startswith("E_pre"):
            human_cols = _human_prev_columns(actions, idx, 10)
            print("  (comparing against human sources in the run-up to this deal)")
        else:
            human_cols = _human_next_columns(actions, idx, 10)
        _compare_human(an, human_cols, key, hits)

    # Extra: first-space create seen prospectively from opening / from prior?
    print()
    print("=" * 92)
    print("CANONICAL BEHAVIOUR CHECKS (post-hoc vs prospective)")
    print()
    print("  1. First spaces created then USED, not preserved.")
    if i_create is not None and i_use is not None:
        print(f"     create@{i_create} use@{i_use} gap={i_use - i_create} actions")
        an_b, *_ = analyses.get("B_first_space_create", (None,))
        if an_b:
            print(
                f"     at create: consume_plausible={an_b.liquidity.consume_is_plausible} "
                f"top use={an_b.top_uses[0].kind if an_b.top_uses else '—'}"
            )
            if an_b.liquidity.consume_is_plausible or (
                an_b.top_uses and an_b.top_uses[0].kind in (
                    "reveal_buried", "continue_excavation", "park_king"
                )
            ):
                hits.append("first-space: analyser treats the new empty as spendable")
            else:
                hits.append("first-space: analyser did not clearly recommend spending it")
    print("  2. Space migrates (create/use, not hoard). See create→use gap above.")
    print("  3. Spaces gone before stock deals.")
    for key in ("C_pre_deal1", "D_pre_deal2", "E_pre_deal5"):
        if key in snaps:
            print(f"     {key} empty={empty_count(snaps[key][0])}")
    print("  4. After Deal5 a space is regained almost immediately.")
    if "F_post_deal5" in analyses:
        an_f, st_f, _, idx_f = analyses["F_post_deal5"]
        print(
            f"     post-D5: empty={an_f.liquidity.spaces_now} "
            f"cheapest={an_f.liquidity.cheapest_create} "
            f"1-create={an_f.liquidity.one_move_creates} "
            f"nk={an_f.liquidity.fully_open_nonking}"
        )
        # Did human recreate quickly?
        regained = None
        stx = st_f.clone()
        for j, a in enumerate(actions[idx_f: idx_f + 12]):
            if a == ("deal",):
                break
            replay_actions(stx, [a])
            if empty_count(stx) > 0:
                regained = j + 1
                break
        print(f"     human next empty within {regained} post-D5 moves" if regained else
              "     human did not empty in next 12 post-D5 moves")
        if an_f.liquidity.cheapest_create is not None and an_f.liquidity.cheapest_create <= 2:
            hits.append("post-D5: analyser saw cheap workspace regain before the human move")
        elif an_f.liquidity.one_move_creates:
            hits.append("post-D5: analyser saw a one-move create")
        else:
            hits.append("post-D5: analyser missed cheap regain")
    print("  5. Known stock contributes to club / late structure.")
    if "E_pre_deal5" in analyses:
        an_e = analyses["E_pre_deal5"][0]
        clubbish = [
            w
            for w in an_e.stock.receiver_wishes
            if w.incoming.suit == "c" or "foundation" in w.reason
        ]
        print(f"     pre-D5 foundation/club-ish wishes={len(clubbish)}")
        for w in clubbish[:4]:
            print(f"       col {w.column + 1} {w.incoming} {w.reason}")
        if an_e.stock.projects_unlocked or clubbish:
            hits.append("pre-D5: stock pass tagged incoming foundation/unlock roles")

    # Opening vs machine-style cheap-spread
    print()
    print("OPENING RANK vs CHEAP-SPREAD")
    if "A_opening" in analyses:
        an0 = analyses["A_opening"][0]
        shallow = [p for p in an0.projects if 0 < p.face_down <= 2]
        print("  shallow columns by raw fd (machine-like ACCESS bait):")
        for p in sorted(shallow, key=lambda x: (x.face_down, -x.unlock_value)):
            r = next((x for x in an0.ranked if x.column == p.column), None)
            print(
                f"    col {p.column + 1} fd={p.face_down} unlock={p.unlock_value:.0f} "
                f"rank={r.combined if r else 0:.2f} start={p.can_start_now} "
                f"{p.important[:2]}"
            )
        print("  meet-in-middle top:")
        for r in an0.ranked[:5]:
            print(f"    {r.label} comb={r.combined:.2f}")

    print()
    print("COMPARISON HITS")
    for h in hits:
        print(f"  - {h}")

    # Classification
    prospective = sum(
        1
        for h in hits
        if "overlap" in h or "saw cheap" in h or "spendable" in h or "tagged incoming" in h
    )
    misses = sum(1 for h in hits if "no top-3" in h or "missed" in h)
    print()
    print("CLASSIFICATION")
    opening_tied = False
    now_n = 0
    if "A_opening" in analyses:
        scores = [r.combined for r in analyses["A_opening"][0].ranked[:6]]
        opening_tied = len(scores) >= 4 and (max(scores) - min(scores) < 0.05)
        now_n = sum(
            1
            for b in analyses["A_opening"][0].buried
            if b.urgency.value == "useful_now"
        )
    if prospective >= 4 and misses <= 1 and not opening_tied and now_n <= 12:
        verdict = "A"
        note = "STRONG SIGNAL — several canonical choices visible with lead time"
    elif prospective >= 2:
        verdict = "B"
        note = (
            "PARTIAL SIGNAL — space-lifecycle / late-game cards are visible; "
            "opening column identity is still too flat to stop cheap-spread excavation"
        )
    else:
        verdict = "C"
        note = "NO SIGNAL — mostly retrospective; cannot distinguish prospectively"
    print(f"  {verdict}: {note}")
    print(f"  prospective_hits={prospective} opaque={misses}")
    print(f"  total_runtime={time.time() - t0:.1f}s")
    print("Done.")
    return 0 if verdict != "C" else 1


if __name__ == "__main__":
    raise SystemExit(main())
