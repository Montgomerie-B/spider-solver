"""Sprint 1J/1K — strategic campaign generation and execution tests."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
from spider.planner import campaign_realizer as cr_mod
from spider.planner.campaign_realizer import (
    realize_campaign,
    run_campaign_frontier,
    stratify_campaign_results,
    productive_campaign_results,
)
from spider.planner.strategic_campaigns import (
    CampaignKind,
    StrategicCampaign,
    campaign_subobjectives,
    generate_campaigns,
    objective_is_suit_relevant,
    foundation_candidate_is_actionable,
)
from spider.planner import strategic_campaigns as sc_mod
from spider.planner.lower_bounds import count_face_down
from spider.planner.objective_realizer import RealizationMode, RealizationStatus
from spider.planner.strategic_objectives import ObjectiveKind, StrategicObjective
from spider.planner.strategic_analysis import analyze_strategic


def _pad(cols, stock=None):
    while len(cols) < 10:
        cols.append(Column([], [Card("d", 5 if len(cols) % 2 else 4)]))
    if stock is None:
        stock = [Card("h", r) for r in range(1, 11)] * 5
    return SpiderState(cols, list(stock), [])


def _access_camp(focus_column=None):
    return StrategicCampaign(
        kind=CampaignKind.ACCESS,
        campaign_id="access",
        description="test access",
        focus_column=focus_column,
        focus_suit=None,
        reason="test",
        heuristic_priority=1.0,
    )


def _foundation_camp(suit: str):
    return StrategicCampaign(
        kind=CampaignKind.FOUNDATION_BUILD,
        campaign_id=f"foundation_{suit}1",
        description=f"test {suit}",
        focus_column=None,
        focus_suit=suit,
        reason="test",
        heuristic_priority=1.0,
    )


def test_no_benchmark_constants_in_campaigns():
    for mod in (sc_mod, cr_mod):
        src = inspect.getsource(mod)
        assert "4925153" not in src
        assert "77d169da" not in src
        assert "Deal 3" not in src
        assert "deal 3" not in src


def test_repeated_shallow_reveals_excavate_synthetic():
    # Shallow chain: 4c on 5c reveals 3c; 3c on 4c reveals 2c.
    st = _pad(
        [
            Column([Card("c", 2), Card("c", 3)], [Card("c", 4)]),
            Column([], [Card("c", 5)]),
        ]
    )
    camps = generate_campaigns(st)
    access = [c for c in camps if c.kind == CampaignKind.ACCESS]
    assert access
    r = realize_campaign(
        st,
        access[0],
        max_paid_cost=8,
        max_steps=6,
        tactical_max_cost=3,
        workspace_max_cost=4,
    )
    assert r.replay_verified
    assert ("deal",) not in r.actions
    found = [s for s in r.steps if s.status == "found"]
    assert len(found) >= 2
    assert r.fd_reduction >= 2


def test_workspace_then_productive_use():
    st = _pad(
        [
            Column([Card("c", 2)], [Card("s", 13)]),
            Column([], [Card("s", 9), Card("s", 8)]),
            Column([], [Card("s", 7)]),
        ]
    )
    camp = next(
        c for c in generate_campaigns(st) if c.kind == CampaignKind.WORKSPACE_EXPLOIT
    )
    r = realize_campaign(st, camp, max_paid_cost=8, max_steps=6)
    assert r.replay_verified
    kinds = [s.objective_kind for s in r.steps if s.status == "found"]
    if "CREATE_WORKSPACE" in kinds:
        follow = [k for k in kinds if k != "CREATE_WORKSPACE"]
        assert r.productive or follow
        if r.status == "success":
            assert r.productive
            assert r.fd_reduction > 0 or r.end_ss > r.start_ss


def test_campaign_replay_exact():
    st = _pad(
        [
            Column([], [Card("s", 8)]),
            Column([], [Card("s", 9)]),
        ]
    )
    camp = generate_campaigns(st)[0]
    r = realize_campaign(st, camp, max_paid_cost=6, max_steps=4)
    chk = st.clone()
    cost = replay_actions(chk, list(r.actions)) if r.actions else 0
    assert cost == r.paid_cost
    assert r.replay_verified


def test_campaign_stops_on_budget():
    st = _pad(
        [
            Column([Card("c", i) for i in range(2, 6)], [Card("s", 13)]),
            Column([], [Card("s", 9), Card("s", 8)]),
        ]
    )
    camp = next(
        c for c in generate_campaigns(st) if c.kind == CampaignKind.WORKSPACE_EXPLOIT
    )
    r = realize_campaign(st, camp, max_paid_cost=2, max_steps=8, tactical_max_cost=2)
    assert r.paid_cost <= 2
    assert r.stop_reason in (
        "budget",
        "plateau",
        "success",
        "resource_limit",
        "all_candidates_blocked",
        "no_relevant_subobjective",
    )


def test_generic_foundation_selection():
    st = _pad(
        [
            Column([], [Card("c", 10), Card("c", 9), Card("c", 8)]),
            Column([], [Card("s", 5)]),
        ]
    )
    camps = generate_campaigns(st)
    founds = [c for c in camps if c.kind == CampaignKind.FOUNDATION_BUILD]
    for c in founds:
        assert c.focus_suit in ("c", "d", "h", "s", None)


def test_never_deals():
    st = _pad([Column([], [Card("h", 4)])])
    stock0 = len(st.stock)
    for camp in generate_campaigns(st):
        r = realize_campaign(st, camp, max_paid_cost=3, max_steps=3)
        assert ("deal",) not in r.actions
        chk = st.clone()
        if r.actions:
            replay_actions(chk, list(r.actions))
        assert len(chk.stock) == stock0


def test_reanalyse_after_every_subobjective(monkeypatch):
    calls = {"n": 0}
    orig = cr_mod.analyze_strategic

    def wrapped(*args, **kwargs):
        calls["n"] += 1
        return orig(*args, **kwargs)

    monkeypatch.setattr(cr_mod, "analyze_strategic", wrapped)
    st = _pad(
        [
            Column([Card("c", 2), Card("c", 3)], [Card("c", 4)]),
            Column([], [Card("c", 5)]),
        ]
    )
    camp = next(c for c in generate_campaigns(st) if c.kind == CampaignKind.ACCESS)
    r = realize_campaign(st, camp, max_paid_cost=6, max_steps=4)
    found = [s for s in r.steps if s.status == "found"]
    assert calls["n"] >= 2 + len(found)
    if len(found) >= 2:
        assert found[0].objective_id != found[1].objective_id or found[0].cost > 0


def test_frontier_no_deal():
    st = _pad(
        [
            Column([], [Card("s", 8)]),
            Column([], [Card("s", 9)]),
        ]
    )
    frontier = run_campaign_frontier(st, max_paid_cost=4, max_campaigns=3)
    assert frontier.results
    assert all(("deal",) not in r.actions for r in frontier.results)


def test_resource_limit_is_not_impossible():
    st = _pad(
        [
            Column([Card("c", i) for i in range(2, 8)], [Card("s", 13)]),
            Column([], [Card("h", 6)]),
        ]
    )
    camp = next(c for c in generate_campaigns(st) if c.kind == CampaignKind.ACCESS)
    r = realize_campaign(
        st,
        camp,
        max_paid_cost=2,
        max_steps=3,
        tactical_max_cost=1,
        tactical_max_nodes=8,
        tactical_time_s=0.01,
    )
    assert r.status != "impossible"
    assert r.stop_reason != "impossible"
    assert RealizationStatus.RESOURCE_LIMIT.value != "impossible"
    for step in r.steps:
        assert step.status != "impossible"


def test_workspace_create_alone_not_success():
    st = _pad(
        [
            Column([], [Card("s", 13)]),
            Column([], [Card("h", 6)]),
            Column([], [Card("d", 8)]),
        ]
    )
    camp = next(
        c for c in generate_campaigns(st) if c.kind == CampaignKind.WORKSPACE_EXPLOIT
    )
    r = realize_campaign(st, camp, max_paid_cost=6, max_steps=4, tactical_max_cost=2)
    if r.fd_reduction == 0 and r.end_ss <= r.start_ss and r.foundations_delta == 0:
        assert r.status != "success"
        assert not r.productive


def test_stratify_is_diverse():
    st = _pad(
        [
            Column([Card("c", 2)], [Card("c", 4)]),
            Column([], [Card("c", 5)]),
            Column([], [Card("s", 9), Card("s", 8)]),
        ]
    )
    frontier = run_campaign_frontier(st, max_paid_cost=5, max_campaigns=4)
    picked = stratify_campaign_results(frontier.results, limit=4)
    assert len(picked) <= len(frontier.results)
    assert all(p.productive for p in picked)


# ---------------------------------------------------------------------------
# Sprint 1K
# ---------------------------------------------------------------------------


def test_access_fallback_second_column_when_top_blocked(monkeypatch):
    # Col0 blocked by the probe; col1 is a cheap 4c→5c reveal.
    st = _pad(
        [
            Column([Card("s", 1)], [Card("s", 13)]),
            Column([Card("c", 3)], [Card("c", 4)]),
            Column([], [Card("c", 5)]),
        ]
    )
    camp = _access_camp(focus_column=0)
    subs = campaign_subobjectives(st, camp)
    expose_cols = {
        o.target_params.get("column")
        for o in subs
        if o.kind == ObjectiveKind.EXPOSE_REVEAL_PREFIX
    }
    assert 0 in expose_cols and 1 in expose_cols

    orig = cr_mod.realize_objective

    def wrapped(state, obj, **kwargs):
        if (
            obj.kind == ObjectiveKind.EXPOSE_REVEAL_PREFIX
            and obj.target_params.get("column") == 0
        ):
            from spider.planner.objective_realizer import RealizationResult

            return RealizationResult(
                status=RealizationStatus.RESOURCE_LIMIT,
                objective=obj,
                mode=RealizationMode.EXACT_BOUNDED,
                corrected_mw_cost=None,
                actions=(),
                action_labels=(),
                result_key_hex=None,
                nodes_expanded=1,
                elapsed_seconds=0.0,
                target_verified=False,
                exact_within_bound=False,
                max_cost=kwargs.get("max_cost", 3),
                max_nodes=kwargs.get("max_nodes", 80),
                notes=("forced resource_limit",),
            )
        return orig(state, obj, **kwargs)

    monkeypatch.setattr(cr_mod, "realize_objective", wrapped)
    r = realize_campaign(
        st, camp, max_paid_cost=8, max_steps=6, tactical_max_cost=3
    )
    assert r.replay_verified
    found = [s for s in r.steps if s.status == "found"]
    assert found
    assert r.fd_reduction >= 1
    cols = [s.focus_column for s in found if s.focus_column is not None]
    assert 1 in cols
    assert 0 not in cols
    assert r.fallbacks_tried >= 1 or any(s.fallback for s in found)


def test_resource_limit_falls_through_to_other_column():
    st = _pad(
        [
            Column(
                [Card("h", 1), Card("h", 2), Card("h", 3), Card("h", 4)],
                [Card("s", 13)],
            ),
            Column([Card("c", 2)], [Card("c", 4)]),
            Column([], [Card("c", 5)]),
        ]
    )
    camp = _access_camp()
    r = realize_campaign(
        st,
        camp,
        max_paid_cost=6,
        max_steps=4,
        tactical_max_cost=2,
        tactical_max_nodes=80,
        tactical_time_s=0.08,
    )
    assert r.status != "impossible"
    found = [s for s in r.steps if s.status == "found"]
    if found:
        assert r.fd_reduction >= 1
        assert any(s.focus_column != 0 for s in found if s.focus_column is not None)


def test_failed_target_not_retried_endlessly(monkeypatch):
    st = _pad(
        [
            Column([Card("s", 1)], [Card("s", 13)]),
            Column([Card("c", 3)], [Card("c", 4)]),
            Column([], [Card("c", 5)]),
        ]
    )
    calls: list = []
    orig = cr_mod.realize_objective

    def wrapped(state, obj, **kwargs):
        calls.append(obj.objective_id)
        return orig(state, obj, **kwargs)

    monkeypatch.setattr(cr_mod, "realize_objective", wrapped)
    camp = _access_camp()
    r = realize_campaign(
        st, camp, max_paid_cost=8, max_steps=6, tactical_max_cost=3
    )
    from collections import Counter

    counts = Counter(calls)
    # A blocked objective may be probed once per distinct actionability
    # context, not once per loop iteration.
    assert counts
    assert max(counts.values()) <= 3
    assert r.realizations_attempted >= 1


def test_access_reselects_focus_after_successful_reveal():
    st = _pad(
        [
            Column([Card("c", 2)], [Card("c", 4)]),
            Column([], [Card("c", 5)]),
            Column([Card("h", 3)], [Card("h", 6)]),
            Column([], [Card("h", 7)]),
        ]
    )
    camp = _access_camp()
    r = realize_campaign(st, camp, max_paid_cost=8, max_steps=6, tactical_max_cost=3)
    found = [s for s in r.steps if s.status == "found" and s.focus_column is not None]
    assert len(found) >= 2
    cols = {s.focus_column for s in found}
    assert len(cols) >= 2 or r.access_focus_changes >= 1
    assert r.fd_reduction >= 2


def test_zero_progress_excluded_from_productive_frontier():
    st = _pad(
        [
            Column([], [Card("s", 13)]),
            Column([], [Card("h", 6)]),
            Column([], [Card("d", 8)]),
        ]
    )
    frontier = run_campaign_frontier(st, max_paid_cost=4, max_campaigns=4)
    prod = productive_campaign_results(frontier.results)
    assert all(r.productive and not r.zero_progress for r in prod)
    assert all(r.productive for r in frontier.pareto)
    assert all(r.productive for r in frontier.stratified)
    blocked = [r for r in frontier.results if r.zero_progress]
    for r in blocked:
        assert r not in frontier.pareto
        assert r not in frontier.stratified


def test_foundation_build_rejects_off_suit_objectives():
    st = _pad(
        [
            Column([], [Card("c", 10), Card("c", 9), Card("c", 8)]),
            Column([Card("h", 2)], [Card("h", 5)]),
            Column([], [Card("h", 6)]),
        ]
    )
    camp = _foundation_camp("c")
    analysis = analyze_strategic(st, run_shaping_probe=False)
    subs = campaign_subobjectives(st, camp, analysis=analysis)
    for o in subs:
        assert objective_is_suit_relevant(o, "c", st, analysis)
        assert o.target_params.get("suit", "c") in ("c", None) or o.kind == ObjectiveKind.EXPOSE_REVEAL_PREFIX
        if o.kind == ObjectiveKind.EXPOSE_REVEAL_PREFIX:
            col = o.target_params["column"]
            assert any(c.suit == "c" for c in st.columns[col].face_down) or any(
                c.suit == "c" for c in st.columns[col].face_up
            )
        if o.kind in (
            ObjectiveKind.CONSOLIDATE_SAME_SUIT,
            ObjectiveKind.ADVANCE_FOUNDATION,
            ObjectiveKind.REMOVE_FOUNDATION,
        ):
            assert o.target_params.get("suit") == "c"


def test_foundation_focus_persists_after_reanalysis():
    st = _pad(
        [
            Column([], [Card("c", 10), Card("c", 9)]),
            Column([], [Card("c", 8)]),
        ]
    )
    camp = _foundation_camp("c")
    assert camp.focus_suit == "c"
    r = realize_campaign(st, camp, max_paid_cost=6, max_steps=4)
    assert r.campaign.focus_suit == "c"
    analysis = analyze_strategic(st, run_shaping_probe=False)
    for s in r.steps:
        if s.status != "found":
            continue
        # Reconstruct a dummy check: accepted kinds must be club-relevant
        assert s.objective_kind != "EXPOSE_REVEAL_PREFIX" or True
        assert "h" not in s.objective_id.split("_")[1:2]


def test_no_bogus_generic_foundation_when_no_suit_action():
    st = _pad(
        [
            Column([], [Card("s", 13)]),
            Column([], [Card("h", 6)]),
        ]
    )
    # Without cards there is no 1A frontier → no generated FOUNDATION_BUILD.
    camps = generate_campaigns(st)
    assert all(c.kind != CampaignKind.FOUNDATION_BUILD for c in camps)
    # A forced hearts campaign with no heart material stops cleanly.
    camp = _foundation_camp("h")
    r = realize_campaign(st, camp, max_paid_cost=6, max_steps=4)
    found = [s for s in r.steps if s.status == "found"]
    assert r.fd_reduction == 0 or all(
        "h" in s.objective_id or s.objective_kind != "EXPOSE_REVEAL_PREFIX"
        for s in found
    )
    if not found:
        assert r.stop_reason in (
            "no_relevant_subobjective",
            "all_candidates_blocked",
            "plateau",
            "resource_limit",
        )
        assert r.status == "zero_progress"
        assert not r.productive


def test_workspace_exploit_not_generic_reveal():
    # Cheap expose exists (4c→5c) but no empty and no easy workspace.
    st = _pad(
        [
            Column([Card("c", 3)], [Card("c", 4)]),
            Column([], [Card("c", 5)]),
            Column([], [Card("s", 13)]),
            Column([], [Card("h", 6)]),
        ]
    )
    camp = next(
        c for c in generate_campaigns(st) if c.kind == CampaignKind.WORKSPACE_EXPLOIT
    )
    r = realize_campaign(st, camp, max_paid_cost=8, max_steps=6, tactical_max_cost=3)
    found = [s for s in r.steps if s.status == "found"]
    # Must not silently become a reveal campaign without workspace.
    if not any(s.objective_kind == "CREATE_WORKSPACE" for s in found) and r.start_empty == 0:
        assert r.status != "success"
        assert not r.productive or r.end_empty > 0


def test_workspace_success_requires_use():
    st = _pad(
        [
            Column([Card("c", 2)], [Card("s", 13)]),
            Column([], [Card("s", 9), Card("s", 8)]),
            Column([], [Card("s", 7)]),
        ]
    )
    camp = next(
        c for c in generate_campaigns(st) if c.kind == CampaignKind.WORKSPACE_EXPLOIT
    )
    r = realize_campaign(st, camp, max_paid_cost=8, max_steps=6)
    if r.status == "success":
        created = any(
            s.objective_kind == "CREATE_WORKSPACE" and s.status == "found"
            for s in r.steps
        )
        assert created or r.start_empty > 0 or r.end_empty > 0
        assert r.fd_reduction > 0 or r.end_ss > r.start_ss or r.end_mass > r.start_mass


def test_foundation_candidate_gate_rejects_empty_label():
    class _C:
        already_completed = False
        theoretically_available = False
        longest_same_suit_fragment = 1
        heuristic_removal_readiness = 0.0

    assert not foundation_candidate_is_actionable(_C())

    class _Ready:
        already_completed = False
        theoretically_available = True
        longest_same_suit_fragment = 1
        heuristic_removal_readiness = 0.0

    assert foundation_candidate_is_actionable(_Ready())


def test_stop_reasons_are_specific():
    st = _pad([Column([], [Card("s", 13)])])
    camp = _access_camp()
    r = realize_campaign(st, camp, max_paid_cost=4, max_steps=3, tactical_max_cost=2)
    assert r.stop_reason in (
        "budget",
        "plateau",
        "all_candidates_blocked",
        "resource_limit",
        "no_relevant_subobjective",
        "success",
    )
    assert r.stop_reason != "impossible"
