#!/usr/bin/env python3
"""Sprint 1J — strategic campaign investment frontiers (no Deal 3)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.planner.campaign_realizer import (
    prefix_at_budget,
    realize_campaign,
    run_campaign_frontier,
)
from spider.planner.lower_bounds import count_face_down
from spider.planner.plan_search_v2 import (
    compute_quality,
    replay_canonical_epochs,
    search_to_stock_epoch,
    select_stratified_seeds,
)
from spider.planner.space_lifecycle import empty_count
from spider.planner.strategic_analysis import analyze_strategic
from spider.planner.strategic_campaigns import CampaignKind, generate_campaigns


def _qline(label, g, fd, e, ss, mass, extra=""):
    print(f"  {label}g={g} fd={fd} e={e} ssL={ss} mass={mass}{extra}")


def _res_line(r, label=""):
    eff = f"{r.fd_per_paid:.2f}" if r.fd_per_paid is not None else "—"
    pret = (
        f"{r.productive_return_per_move:.2f}"
        if r.productive_return_per_move is not None
        else "—"
    )
    kinds = [s.objective_kind for s in r.steps if s.status == "found"]
    print(
        f"  {label}{r.campaign.campaign_id} {r.status} +{r.paid_cost} "
        f"fd={r.start_face_down}->{r.end_face_down} (Δ{r.fd_reduction}) "
        f"e={r.start_empty}->{r.end_empty} ss={r.start_ss}->{r.end_ss} "
        f"mass={r.start_mass}->{r.end_mass} foundΔ={r.foundations_delta} "
        f"stockSS={r.start_stock_ss}->{r.end_stock_ss} "
        f"fB={r.start_foundation_build:.0f}->{r.end_foundation_build:.0f} "
        f"fR={r.start_foundation_removal:.0f}->{r.end_foundation_removal:.0f} "
        f"eff={eff} pret={pret} prod={r.productive} "
        f"sel={r.selected_foundation} steps={kinds} "
        f"try={r.realizations_attempted} nodes={r.nodes_expanded} "
        f"t={r.elapsed_seconds:.2f}s replay={r.replay_verified}"
    )
    print(f"    reason={r.campaign.reason}")


def _frontier_block(title, state, cards, budgets, **kwargs):
    print()
    print(title)
    fd0 = count_face_down(state)
    print(f"  start fd={fd0} empty={empty_count(state)} stock={len(state.stock)}")
    camps = generate_campaigns(state, cards=cards, max_campaigns=6)
    print("  generated:")
    for c in camps:
        print(
            f"    {c.kind.value} {c.campaign_id} pri={c.heuristic_priority:.1f} "
            f"suit={c.focus_suit} col={c.focus_column} :: {c.reason}"
        )
    biggest = max(budgets)
    fr = run_campaign_frontier(
        state, cards=cards, max_paid_cost=biggest, max_campaigns=4, **kwargs
    )
    print(
        f"  mix={fr.mix} elapsed={fr.elapsed_seconds:.2f}s "
        f"nodes={fr.nodes_expanded} n={len(fr.results)}"
    )
    assert all(("deal",) not in r.actions for r in fr.results)
    for r in fr.results:
        _res_line(r)
        for b in budgets:
            if b >= biggest:
                continue
            paid, fd, e, ss, mass = prefix_at_budget(r, state, b)
            print(
                f"    prefix+{b}: paid={paid} fd={fd} e={e} ssL={ss} mass={mass}"
            )
    print("  pareto:")
    for r in fr.pareto:
        _res_line(r, "P ")
    print("  stratified:")
    for r in fr.stratified:
        _res_line(r, "S ")
    best_fd = min(fr.results, key=lambda r: (r.end_face_down, r.paid_cost))
    best_eff = max(
        [r for r in fr.results if r.paid_cost > 0] or fr.results,
        key=lambda r: (r.fd_per_paid or 0.0, r.fd_reduction, -r.paid_cost),
    )
    print(
        f"  BEST_FD {best_fd.campaign.campaign_id} fd={best_fd.end_face_down} "
        f"+{best_fd.paid_cost} Δ{best_fd.fd_reduction}"
    )
    print(
        f"  BEST_EFF {best_eff.campaign.campaign_id} "
        f"eff={best_eff.fd_per_paid} +{best_eff.paid_cost} "
        f"fd={best_eff.end_face_down}"
    )
    return fr


def _foundation_selector(title, state, cards):
    print()
    print(title)
    analysis = analyze_strategic(state, cards=cards, run_shaping_probe=False)
    if analysis.foundation is None:
        print("  no foundation analysis (cards missing)")
        return None
    cands = [
        c
        for c in analysis.foundation.frontier.candidates
        if not c.already_completed
    ]
    cands.sort(
        key=lambda c: (
            -c.heuristic_removal_readiness if c.theoretically_available else 0.0,
            -c.heuristic_build_readiness,
            c.earliest_epoch if c.earliest_epoch is not None else 99,
            c.suit,
            c.copy_index,
        )
    )
    print("  frontier (generic rank):")
    for i, c in enumerate(cands[:6]):
        print(
            f"    [{i}] {c.label} theo={c.theoretically_available} "
            f"epoch={c.earliest_epoch} build={c.heuristic_build_readiness:.1f} "
            f"rem={c.heuristic_removal_readiness:.1f} "
            f"frag={c.longest_same_suit_fragment}"
        )
    camps = generate_campaigns(state, cards=cards, analysis=analysis)
    founds = [c for c in camps if c.kind == CampaignKind.FOUNDATION_BUILD]
    print("  selected FOUNDATION_BUILD campaigns:")
    for c in founds:
        print(f"    {c.campaign_id} pri={c.heuristic_priority:.1f} :: {c.reason}")
    favours_s1 = any(c.campaign_id == "foundation_s1" for c in founds[:1])
    any_s1 = any(c.campaign_id == "foundation_s1" for c in founds)
    print(f"  top_is_S#1={favours_s1} s1_in_selected={any_s1}")
    return founds[0] if founds else None


def main() -> int:
    t_all = time.time()
    cards = load_deal(ROOT / "deals" / "4925153.txt")
    start = SpiderState.from_cards(list(cards))
    actions = parse_moves_file(ROOT / "solutions" / "4925153_canonical.moves")
    snaps = replay_canonical_epochs(start, actions, up_to_deals=3, cards=cards)

    print("SPRINT 1J — STRATEGIC CAMPAIGNS / PRODUCTIVE INVESTMENT")
    print("HUMAN REFERENCE (canonical, diagnostic only)")
    for k in ("initial", "pre_deal_1", "post_deal_1", "pre_deal_2", "post_deal_2"):
        n = snaps.get(k)
        if not n:
            continue
        q = n.quality
        print(
            f"  {k}: g={n.g} fd={q.face_down} e={q.empty_count} "
            f"ssL={q.longest_same_suit} mass={q.same_suit_run_mass} "
            f"found={q.foundations_removed} "
            f"H1t={q.h1_theo} Hb={q.h1_build:.0f}/{q.h1_removal:.0f} "
            f"S1t={q.s1_theo} Sb={q.s1_build:.0f}/{q.s1_removal:.0f} "
            f"stockSS={q.predeal_same_suit_landings}"
        )
    human_pre_d1 = snaps["pre_deal_1"]
    human_d1 = snaps["post_deal_1"]
    human_d2 = snaps["post_deal_2"]
    print(
        f"  human pre-D1 investment: cost={human_pre_d1.g} "
        f"fd {snaps['initial'].quality.face_down}->{human_pre_d1.quality.face_down} "
        f"ssL={human_pre_d1.quality.longest_same_suit}"
    )
    assert len(human_d2.state.stock) >= 30  # Deal 3 not yet taken (5 rows left after D2? 50-20=30)

    kw = dict(
        max_steps=8,
        tactical_max_cost=4,
        tactical_max_nodes=350,
        tactical_time_s=0.25,
        workspace_max_cost=6,
    )

    opening = _frontier_block(
        "A. OPENING INVESTMENT FRONTIER (no deal)",
        start,
        cards,
        (5, 10, 20),
        **kw,
    )

    print()
    print("OPENING vs HUMAN PRE-D1")
    print(
        f"  human: g={human_pre_d1.g} fd={human_pre_d1.quality.face_down} "
        f"ssL={human_pre_d1.quality.longest_same_suit} "
        f"mass={human_pre_d1.quality.same_suit_run_mass}"
    )
    for r in opening.results:
        print(
            f"  machine {r.campaign.campaign_id}: +{r.paid_cost} "
            f"fd={r.end_face_down} ssL={r.end_ss} Δfd={r.fd_reduction} "
            f"vs human spend {human_pre_d1.g} / fd {human_pre_d1.quality.face_down}"
        )

    print()
    print("Collecting machine Deal-1 seeds (short 1H/1G)...")
    d1 = search_to_stock_epoch(
        start,
        cards=cards,
        target_deals=1,
        max_non_deal=3,
        beam=16,
        tactical_max_cost=3,
        workspace_max_cost=5,
        max_plan_nodes=28,
        time_limit_s=25.0,
    )
    d1_seeds = select_stratified_seeds(d1.terminals, limit=3)
    print(
        f"  d1_terminals={len(d1.terminals)} seeds={len(d1_seeds)} "
        f"time={d1.stats.elapsed_seconds:.1f}s"
    )
    for i, s in enumerate(d1_seeds):
        q = s.quality
        print(
            f"  [{i}] g={s.g} fd={q.face_down} e={q.empty_count} "
            f"ssL={q.longest_same_suit} kinds={list(s.objective_kinds)}"
        )

    d1_frontiers = []
    for i, s in enumerate(d1_seeds):
        fr = _frontier_block(
            f"B. POST-DEAL1 SEED[{i}] g={s.g} fd={s.quality.face_down}",
            s.state,
            cards,
            (5, 10, 20),
            **kw,
        )
        d1_frontiers.append(fr)

    print()
    print("Collecting machine Deal-2 seeds (short 1H)...")
    d2 = search_to_stock_epoch(
        start,
        cards=cards,
        target_deals=2,
        max_non_deal=3,
        beam=20,
        tactical_max_cost=3,
        workspace_max_cost=5,
        max_plan_nodes=36,
        time_limit_s=35.0,
    )
    d2_seeds = select_stratified_seeds(d2.terminals, limit=4)
    print(
        f"  d2_terminals={len(d2.terminals)} seeds={len(d2_seeds)} "
        f"time={d2.stats.elapsed_seconds:.1f}s"
    )
    for i, s in enumerate(d2_seeds):
        q = s.quality
        print(
            f"  [{i}] g={s.g} fd={q.face_down} e={q.empty_count} "
            f"ssL={q.longest_same_suit} Hb={q.h1_build:.0f} Sb={q.s1_build:.0f} "
            f"kinds={list(s.objective_kinds)}"
        )
        assert s.deals_done == 2
        assert len(s.state.stock) >= 30

    d2_frontiers = []
    for i, s in enumerate(d2_seeds):
        fr = _frontier_block(
            f"C. POST-DEAL2 MACHINE SEED[{i}] g={s.g} fd={s.quality.face_down}",
            s.state,
            cards,
            (5, 10, 20),
            **kw,
        )
        d2_frontiers.append(fr)
        # plateau question: did +20 beat fd≈33?
        best = min(fr.results, key=lambda r: r.end_face_down)
        print(
            f"  PLATEAU_CHECK seed[{i}] start_fd={s.quality.face_down} "
            f"best_end_fd={best.end_face_down} Δ={s.quality.face_down - best.end_face_down} "
            f"broken_below_33={best.end_face_down < 33}"
        )

    print()
    print("D. CANONICAL POST-DEAL2 (diagnostic reference)")
    hq = human_d2.quality
    print(
        f"  human post-D2 g={human_d2.g} fd={hq.face_down} e={hq.empty_count} "
        f"ssL={hq.longest_same_suit}"
    )
    _foundation_selector("FOUNDATION SELECTOR @ human post-D2", human_d2.state, cards)
    human_fr = _frontier_block(
        "HUMAN POST-D2 CAMPAIGNS",
        human_d2.state,
        cards,
        (5, 10, 20),
        **kw,
    )

    if d2_seeds:
        _foundation_selector(
            "FOUNDATION SELECTOR @ machine post-D2 seed[0]",
            d2_seeds[0].state,
            cards,
        )

    print()
    print("UNRELATED SYNTHETIC")
    stock = [Card("h", r) for r in range(1, 11)] * 3
    st_u = SpiderState(
        [
            Column([Card("c", 2), Card("c", 3)], [Card("c", 4)]),
            Column([], [Card("c", 5)]),
            Column([], [Card("s", 9), Card("s", 8)]),
            Column([], [Card("s", 7)]),
        ]
        + [Column([], [Card("d", 5 if i % 2 else 4)]) for i in range(6)],
        stock,
        [],
    )
    ufr = run_campaign_frontier(
        st_u, max_paid_cost=10, max_campaigns=3, max_steps=6, tactical_max_cost=3
    )
    print(
        f"  results={len(ufr.results)} mix={ufr.mix} "
        f"best_fdΔ={max(r.fd_reduction for r in ufr.results)} "
        f"time={ufr.elapsed_seconds:.2f}s"
    )
    for r in ufr.results:
        _res_line(r)
        assert ("deal",) not in r.actions

    print()
    print("SUMMARY")
    open_best = min(opening.results, key=lambda r: (r.end_face_down, r.paid_cost))
    print(
        f"  opening best fd={open_best.end_face_down} +{open_best.paid_cost} "
        f"Δ{open_best.fd_reduction} kind={open_best.campaign.kind.value} "
        f"vs human pre-D1 g=51 fd={human_pre_d1.quality.face_down}"
    )
    if d2_frontiers:
        bests = [
            min(fr.results, key=lambda r: r.end_face_down) for fr in d2_frontiers
        ]
        abs_best = min(bests, key=lambda r: r.end_face_down)
        print(
            f"  post-D2 machine best fd={abs_best.end_face_down} "
            f"+{abs_best.paid_cost} Δ{abs_best.fd_reduction} "
            f"plateau_broken={abs_best.end_face_down < 33}"
        )
    hbest = min(human_fr.results, key=lambda r: r.end_face_down)
    print(
        f"  human-post-D2 campaign best fd={hbest.end_face_down} "
        f"+{hbest.paid_cost} Δ{hbest.fd_reduction}"
    )
    print(f"  total_runtime={time.time() - t_all:.1f}s")
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
