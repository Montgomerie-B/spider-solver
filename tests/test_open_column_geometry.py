"""Focused tests for latent workspace / open-column geometry A/B."""

from __future__ import annotations

import inspect
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
from spider.planner import campaign_realizer as cr_mod
from spider.planner import plan_search_v2 as ps
from spider.planner import strategic_campaigns as sc_mod
from spider.planner.campaign_realizer import realize_campaign
from spider.planner.objective_realizer import (
    RealizationMode,
    RealizationResult,
    RealizationStatus,
)
from spider.planner.plan_search_v2 import (
    PlanNode,
    QualityVector,
    compute_quality,
    search_to_stock_epoch,
    stratify_nodes,
)
from spider.planner.strategic_campaigns import (
    CampaignKind,
    StrategicCampaign,
    campaign_subobjectives,
)
from spider.planner.strategic_objectives import ObjectiveKind
from spider.planner.workspace_obstruction import open_column_facts
from spider.planner.workspace_tactics import WorkspaceBackend
from spider.state_identity import canonical_state_key


def _buried_pad(cols, stock=None):
    """Pad with buried (not fully-open) columns so metrics stay honest."""
    while len(cols) < 10:
        i = len(cols)
        cols.append(Column([Card("d", 3 if i % 2 else 2)], [Card("d", 5 if i % 2 else 4)]))
    if stock is None:
        stock = [Card("h", r) for r in range(1, 11)] * 5
    return SpiderState(cols, list(stock), [])


def _open_pad(cols, stock=None):
    """Pad with inert open 4/5s — same helper the ACCESS campaign tests use."""
    while len(cols) < 10:
        cols.append(Column([], [Card("d", 5 if len(cols) % 2 else 4)]))
    if stock is None:
        stock = [Card("h", r) for r in range(1, 11)] * 5
    return SpiderState(cols, list(stock), [])


def _access_camp():
    return StrategicCampaign(
        kind=CampaignKind.ACCESS,
        campaign_id="access",
        description="test access",
        focus_column=None,
        focus_suit=None,
        reason="test",
        heuristic_priority=1.0,
    )


def _node(state: SpiderState, g: int) -> PlanNode:
    q = compute_quality(state, g)
    return PlanNode(
        state=state,
        g=g,
        actions=(),
        objective_ids=(),
        objective_kinds=(),
        key=canonical_state_key(state),
        deals_done=0,
        epoch_depth=0,
        quality=q,
    )


def _qv(**kw) -> QualityVector:
    base = dict(
        g=5,
        face_down=30,
        empty_count=0,
        longest_same_suit=2,
        same_suit_run_mass=4,
        foundation_build_max=10.0,
        predeal_same_suit_landings=0,
        predeal_immediate_outs=0,
        predeal_non_connecting=3,
    )
    base.update(kw)
    return QualityVector(**base)


def test_fully_open_and_nonking_metrics():
    st = _buried_pad(
        [
            Column([], [Card("s", 12), Card("s", 11), Card("s", 10)]),  # open non-king
            Column([], [Card("h", 13), Card("h", 12)]),  # open king
            Column([Card("c", 2), Card("c", 3)], [Card("c", 5)]),  # buried
            Column([], []),  # empty: ignored
        ]
    )
    n_open, n_nonking, min_fd = open_column_facts(st)
    assert n_open == 2
    assert n_nonking == 1
    assert min_fd == 0
    q = compute_quality(st, 0)
    assert q.fully_open_columns == 2
    assert q.fully_open_nonking_columns == 1
    assert q.min_column_fd == 0

    buried = _buried_pad(
        [
            Column([Card("s", 2)], [Card("s", 7)]),
            Column([Card("h", 4), Card("h", 3)], [Card("h", 9)]),
        ]
    )
    bo, bn, bmin = open_column_facts(buried)
    assert bo == 0
    assert bn == 0
    assert bmin == 1
    qb = compute_quality(buried, 0)
    assert qb.fully_open_columns == 0
    assert qb.fully_open_nonking_columns == 0
    assert qb.min_column_fd == 1

    mixed = _buried_pad(
        [Column([], [Card("s", 12), Card("h", 11), Card("h", 10)])]
    )
    mo, mn, _ = open_column_facts(mixed)
    assert mo == 1
    assert mn == 0


def test_open_facts_are_heuristic_not_dominance():
    a = _qv(fully_open_nonking_columns=0, min_column_fd=4, workspace_potential=0.0)
    b = replace(a, fully_open_nonking_columns=3, min_column_fd=0, workspace_potential=40.0)
    assert not b.dominates(a)
    assert not a.dominates(b)
    # Existing cost/structure dominance is unchanged.
    cheaper = replace(a, g=3, face_down=20)
    assert cheaper.dominates(a)


def test_beam_retains_latent_workspace_branch():
    cheap_buried = _buried_pad(
        [Column([Card("s", 2), Card("s", 3)], [Card("s", 7)]) for _ in range(10)]
    )
    latent = _buried_pad(
        [
            Column([], [Card("s", 12), Card("s", 11)]),
            Column([], [Card("h", 8), Card("h", 7), Card("h", 6)]),
            Column([Card("c", 2)], [Card("c", 5)]),
        ]
    )
    n_cheap = _node(cheap_buried, g=2)
    n_latent = _node(latent, g=8)
    assert n_cheap.quality.fully_open_nonking_columns == 0
    assert n_latent.quality.fully_open_nonking_columns >= 2
    # Extra filler: same cheap geometry, different keys/g so cost strata fill.
    fillers = []
    for i in range(4):
        st = cheap_buried.clone()
        # Touch a face-up rank so the canonical key differs.
        st.columns[i].face_up[0] = Card("s", 6 + i)
        fillers.append(_node(st, g=2 + i))

    pool = [n_cheap, n_latent, *fillers]
    off = stratify_nodes(pool, limit=5, use_open_column_geometry=False)
    on = stratify_nodes(pool, limit=5, use_open_column_geometry=True)
    off_keys = {n.key for n in off}
    on_keys = {n.key for n in on}
    assert n_latent.key in on_keys
    # Geometry slot is the only dedicated keeper; OFF may drop it.
    if n_latent.key not in off_keys:
        assert n_latent.key in on_keys
    # Existing cheapest stratum still present.
    assert n_cheap.key in on_keys
    assert n_cheap.key in off_keys


def test_access_completion_does_not_override_blocked_fallback(monkeypatch):
    # Equal interest: completion would rank the fd=1 column first, but it is
    # forced blocked. ACCESS must still take the realizable second column.
    st = _open_pad(
        [
            Column([Card("s", 1)], [Card("s", 13)]),  # fd=1, closer, blocked
            Column([Card("c", 2), Card("c", 3)], [Card("c", 4)]),  # fd=2, realizable
            Column([], [Card("c", 5)]),
        ]
    )
    monkeypatch.setattr(sc_mod, "_column_interest", lambda analysis, col: 10.0)
    camp = _access_camp()
    subs = campaign_subobjectives(st, camp, prefer_open_completion=True)
    expose_cols = [
        o.target_params.get("column")
        for o in subs
        if o.kind == ObjectiveKind.EXPOSE_REVEAL_PREFIX
    ]
    assert 0 in expose_cols and 1 in expose_cols
    # Completion ranks remaining fd after interest/required_reveals.
    first_expose = next(
        o.target_params.get("column")
        for o in subs
        if o.kind == ObjectiveKind.EXPOSE_REVEAL_PREFIX
    )
    assert first_expose == 0

    orig = cr_mod.realize_objective

    def wrapped(state, obj, **kwargs):
        if (
            obj.kind == ObjectiveKind.EXPOSE_REVEAL_PREFIX
            and obj.target_params.get("column") == 0
        ):
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
        st,
        camp,
        max_paid_cost=8,
        max_steps=6,
        tactical_max_cost=3,
        prefer_open_completion=True,
    )
    assert r.replay_verified
    found = [s for s in r.steps if s.status == "found"]
    assert found
    cols = [s.focus_column for s in found if s.focus_column is not None]
    assert 1 in cols
    assert 0 not in cols
    assert r.fallbacks_tried >= 1 or any(s.fallback for s in r.steps)
    assert r.fd_reduction >= 1


def test_access_completion_is_secondary_to_interest():
    # High-interest deeper column must still beat a near-open low-interest king.
    st = _open_pad(
        [
            Column([Card("s", 1)], [Card("s", 13)]),  # fd=1, usually low interest
            Column(
                [Card("c", 2), Card("c", 3), Card("c", 4)],
                [Card("c", 5)],
            ),  # fd=3, 5c→6c
            Column([], [Card("c", 6)]),
        ]
    )
    camp = _access_camp()
    off = campaign_subobjectives(st, camp, prefer_open_completion=False)
    on = campaign_subobjectives(st, camp, prefer_open_completion=True)
    def first_col(subs):
        for o in subs:
            if o.kind == ObjectiveKind.EXPOSE_REVEAL_PREFIX:
                return o.target_params.get("column")
        return None

    # Interest (col 1) stays primary under both flags.
    assert first_col(off) == 1
    assert first_col(on) == 1


def test_improved_workspace_backend_used(monkeypatch):
    src = inspect.getsource(ps.search_to_stock_epoch)
    assert "use_improved_workspace" in src
    assert "WorkspaceBackend.IMPROVED" in src
    assert "realize_workspace" in src
    seen = {}
    orig = __import__(
        "spider.planner.workspace_tactics", fromlist=["realize_workspace"]
    ).realize_workspace

    def spy(*args, **kwargs):
        seen["backend"] = kwargs.get("backend")
        seen["max_nodes"] = kwargs.get("max_nodes")
        return orig(*args, **kwargs)

    monkeypatch.setattr("spider.planner.workspace_tactics.realize_workspace", spy)
    st = _open_pad(
        [
            Column([], [Card("s", 9), Card("s", 8)]),
            Column([], [Card("s", 7)]),
        ]
    )
    res = search_to_stock_epoch(
        st,
        target_deals=1,
        max_non_deal=1,
        beam=6,
        max_plan_nodes=10,
        time_limit_s=6.0,
        use_access_campaigns=True,
        use_improved_workspace=True,
        workspace_max_nodes=800,
        workspace_time_s=0.7,
    )
    assert res.config["use_improved_workspace"] is True
    if seen:
        assert seen["backend"] == WorkspaceBackend.IMPROVED
        assert seen["max_nodes"] == 800


def test_geometry_replay_and_cost_unchanged():
    st = _open_pad(
        [
            Column([], [Card("s", 8)]),
            Column([], [Card("s", 9)]),
        ]
    )
    kwargs = dict(
        target_deals=1,
        max_non_deal=1,
        beam=6,
        max_plan_nodes=12,
        time_limit_s=8.0,
        use_access_campaigns=True,
        use_improved_workspace=True,
        workspace_max_nodes=200,
        workspace_time_s=0.2,
    )
    off = search_to_stock_epoch(st, use_open_column_geometry=False, **kwargs)
    on = search_to_stock_epoch(st, use_open_column_geometry=True, **kwargs)
    assert off.terminals and on.terminals
    for res in (off, on):
        for t in res.terminals:
            chk = st.clone()
            assert replay_actions(chk, list(t.actions)) == t.g
            assert ("deal",) in t.actions
    assert off.config["use_open_column_geometry"] is False
    assert on.config["use_open_column_geometry"] is True
