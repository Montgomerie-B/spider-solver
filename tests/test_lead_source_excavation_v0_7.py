"""Focused regressions for scheduler v0.7 bounded lead-source excavation."""

from __future__ import annotations

import inspect
import time
from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
from spider.move_lifecycle import PlacementClass, assess_tableau_move
from spider.planner.anytime_controller import (
    AnytimeControllerConfig,
    ControllerTelemetry,
    StrategicActionKind,
    StrategicCreditLevel,
    StrategicSearchNode,
    StrategicTranspositionTable,
    allowed_frontier_tiers,
    analyze_strategic_state,
    generate_strategic_successors,
    solve_anytime,
    _node_priority,
)
from spider.planner.diagnostics.anytime_whole_game_controller_v0_6_report import (
    _node,
    _opening_anchor_config,
)
from spider.planner.diagnostics.anytime_whole_game_controller_v0_8_report import (
    _gate_f_config as _gate_z_base_config,
)
from spider.planner.diagnostics.whole_deal_backward_forward_scheduler_v0_4_report import (
    _gate_envelope,
)
from spider.planner.economic_projects import (
    EconomicFrontierTier,
    EconomicProjectKind,
    analyze_economic_projects,
)
from spider.planner.lead_source_excavation import (
    LeadSourceExcavationReject,
    already_covered_by_successors,
    lead_source_excavation_reject_reason,
    recognise_lead_source_excavation,
)
from spider.planner.receiver_uncover import assess_receiver_uncover
from spider.rules import MW_RULES
from spider.state_identity import canonical_state_key, states_structurally_equal
import spider.planner.anytime_controller as controller
import heapq


ROOT = Path(__file__).resolve().parents[1]
DEAL_PATH = ROOT / "deals" / "4925153.txt"
MACRO78_DIAGNOSTIC = ((3, 0, 1), (3, 8, 1), (2, 3, 1))
MACRO78 = ((3, 0, 1), (3, 9, 1), (2, 3, 1))


def _card(suit: str, rank: int) -> Card:
    return Card(suit, rank)


def _state(*face_up, stock=()) -> SpiderState:
    columns = [Column([], list(cards)) for cards in face_up]
    columns.extend(Column([], []) for _ in range(10 - len(columns)))
    return SpiderState(columns, list(stock))


def _cards() -> list[Card]:
    return [Card(suit, rank) for suit in "cdhs" for rank in range(1, 14) for _ in range(2)]


def _clean_config() -> AnytimeControllerConfig:
    return AnytimeControllerConfig(
        wall_clock_limit_s=8,
        max_strategic_expansions=2,
        max_tactical_nodes=1_000,
        max_frontier_size=50,
        max_credit_level=StrategicCreditLevel.CLEAN,
        campaign_source_combination_limit=4,
        enable_campaign_edges=False,
        enable_removal_edges=False,
        max_trace_entries=2,
        max_timeline_entries=2,
    )


def known_pattern_state() -> SpiderState:
    """Lead queen under one blocker; king-receiver under two mixed k=1 cards.

    Diamonds keep 2-A after the peels so the canonical key is non-worse.
    """
    return _state(
        [_card("d", 2)],
        [_card("c", 2)],
        [_card("d", 12), _card("h", 12)],
        [_card("h", 13), _card("h", 9), _card("s", 1)],
        [_card("d", 1)],
        [_card("s", 8)],
        [_card("c", 7)],
        [_card("h", 5)],
        [_card("c", 10)],
        [_card("c", 4)],
    )


def canonical_worse_state() -> SpiderState:
    """Same valley, but the first peel buries the only exposed 2d and worsens lead."""
    return _state(
        [_card("d", 2)],
        [_card("s", 9)],
        [_card("d", 12), _card("h", 12)],
        [_card("h", 13), _card("h", 9), _card("s", 1)],
        [_card("d", 1)],
        [_card("s", 8)],
        [_card("c", 7)],
        [_card("h", 5)],
        [_card("c", 10)],
        [_card("c", 4)],
    )


def join_broken_state() -> SpiderState:
    return _state(
        [_card("d", 2)],
        [_card("c", 2)],
        [_card("d", 12), _card("h", 12)],
        [_card("h", 13), _card("s", 6), _card("s", 5)],
        [_card("d", 1)],
        [_card("s", 8)],
        [_card("c", 7)],
        [_card("h", 5)],
        [_card("c", 10)],
        [_card("c", 4)],
    )


def three_peel_state() -> SpiderState:
    """Kh buried under three mixed cards."""
    return _state(
        [_card("d", 2)],
        [_card("c", 2)],
        [_card("d", 12), _card("h", 12)],
        [_card("h", 13), _card("c", 8), _card("h", 9), _card("s", 1)],
        [_card("d", 1)],
        [_card("s", 8)],
        [_card("c", 7)],
        [_card("h", 5)],
        [_card("c", 10)],
        [_card("c", 4)],
    )


def no_source_state() -> SpiderState:
    return _state(
        [_card("d", 2)],
        [_card("c", 2)],
        [_card("h", 12)],
        [_card("h", 13), _card("h", 9), _card("s", 1)],
        [_card("d", 1)],
        [_card("s", 8)],
        [_card("c", 7)],
        [_card("h", 5)],
        [_card("c", 10)],
        [_card("c", 4)],
    )


def uncover_pattern_state() -> SpiderState:
    return _state(
        [_card("s", 13)],
        [_card("d", 2)],
        [_card("c", 5)],
        [_card("s", 7)],
        [_card("h", 2)],
        [_card("d", 9)],
        [_card("c", 9)],
        [_card("h", 9)],
        [_card("s", 8), _card("h", 12)],
        [_card("d", 4)],
    )


def unrelated_speculative_park_state() -> SpiderState:
    return _state(
        [_card("c", 13)],
        [_card("s", 8), _card("h", 12)],
        [_card("d", 5)],
        [_card("c", 5)],
        [_card("h", 5)],
        [_card("s", 5)],
        [_card("d", 4)],
        [_card("c", 4)],
        [_card("h", 4)],
        [_card("s", 4)],
    )


def _successors(state: SpiderState, *, g: int = 0):
    config = _clean_config()
    cards = _cards()
    analysis = analyze_strategic_state(
        state, cards, spent_cost=g, incumbent_cost=None, config=config
    )
    node = StrategicSearchNode(
        0,
        state,
        g,
        (),
        None,
        None,
        0,
        StrategicCreditLevel.CLEAN,
        analysis,
    )
    telemetry = ControllerTelemetry()
    successors = generate_strategic_successors(
        node,
        cards,
        incumbent_cost=None,
        config=config,
        telemetry=telemetry,
        actionability_cache={},
        started=time.perf_counter(),
    )
    return successors, telemetry, analysis


def _fd(state: SpiderState) -> int:
    return sum(len(col.face_down) for col in state.columns)


def _empty(state: SpiderState) -> int:
    return sum(col.is_empty() for col in state.columns)


def _broken_across(state: SpiderState, actions) -> int:
    cur = state.clone()
    broken = 0
    for action in actions:
        life = assess_tableau_move(cur, action, discover_exit=False)
        broken += len(life.same_suit_joins_broken)
        cur.move(*action, rules=MW_RULES)
    return broken


def test_known_pattern_recognises_three_action_macro():
    state = known_pattern_state()
    macros = recognise_lead_source_excavation(state)
    assert macros
    evidence = macros[0]
    assert evidence.qualified
    assert evidence.actions is not None
    assert len(evidence.actions) == 3
    assert evidence.cost == 3
    assert evidence.source == _card("d", 12)
    assert evidence.blocker == _card("h", 12)
    assert evidence.receiver == _card("h", 13)
    park1, park2, consume = evidence.actions
    assert assess_tableau_move(state, park1, discover_exit=False).placement_class == (
        PlacementClass.MIXED_SUIT_PARK
    )
    mid = state.clone()
    mid.move(*park1, rules=MW_RULES)
    assert assess_tableau_move(mid, park2, discover_exit=False).placement_class == (
        PlacementClass.MIXED_SUIT_PARK
    )
    mid.move(*park2, rules=MW_RULES)
    life3 = assess_tableau_move(mid, consume, discover_exit=False)
    assert life3.placement_class == PlacementClass.STABLE_SAME_SUIT_JOIN
    end = state.clone()
    assert replay_actions(end, list(evidence.actions)) == 3
    assert end.columns[2].top() == _card("d", 12)
    assert _broken_across(state, evidence.actions) == 0
    assert evidence.post_key is not None and evidence.pre_key is not None
    assert evidence.post_key <= evidence.pre_key


def test_known_pattern_emitted_as_one_clean_successor():
    successors, telemetry, _analysis = _successors(known_pattern_state())
    excav = [
        item
        for item in successors
        if item.kind == StrategicActionKind.LEAD_SOURCE_EXCAVATION
    ]
    assert excav, [item.actions for item in successors]
    assert len(excav[0].actions) == 3
    assert excav[0].corrected_cost == 3
    assert excav[0].category == "lead_source_excavation"
    assert telemetry.lead_source_excavation_qualified >= 1
    assert telemetry.lead_source_excavation_generated >= 1
    assert telemetry.lead_source_excavation_admitted_clean >= 1
    assert allowed_frontier_tiers(StrategicCreditLevel.CLEAN) == (
        EconomicFrontierTier.STRUCTURALLY_DOMINANT,
    )


def test_mixed_park_cap_is_unchanged():
    state = known_pattern_state()
    analysis = analyze_economic_projects(state, cards=_cards())
    mixed = [
        project
        for project in analysis.projects
        if project.kind == EconomicProjectKind.TEMPORARY_REWORK
        and project.action is not None
        and (
            project.rework_investment is None
            or project.rework_investment.payoff_followup is None
        )
    ]
    assert len(mixed) <= 3


def test_stock_nonempty_is_rejected():
    state = known_pattern_state()
    state.stock.append(_card("c", 13))
    assert recognise_lead_source_excavation(state) == ()
    assert (
        lead_source_excavation_reject_reason(state)
        == LeadSourceExcavationReject.STOCK_NONEMPTY
    )


def test_three_peels_are_rejected():
    state = three_peel_state()
    assert recognise_lead_source_excavation(state) == ()
    assert lead_source_excavation_reject_reason(state) in {
        LeadSourceExcavationReject.RECEIVER_NEEDS_OTHER_THAN_TWO_PEELS,
        LeadSourceExcavationReject.NO_SINGLE_BLOCKER_SOURCE,
    }


def test_breaking_a_stable_join_is_rejected():
    state = join_broken_state()
    assert recognise_lead_source_excavation(state) == ()
    assert lead_source_excavation_reject_reason(state) in {
        LeadSourceExcavationReject.PARK_JOIN_BROKEN,
        LeadSourceExcavationReject.RECEIVER_NEEDS_OTHER_THAN_TWO_PEELS,
        LeadSourceExcavationReject.NO_SINGLE_BLOCKER_SOURCE,
    }


def test_consume_without_lead_source_is_rejected():
    state = no_source_state()
    assert recognise_lead_source_excavation(state) == ()
    assert (
        lead_source_excavation_reject_reason(state)
        == LeadSourceExcavationReject.NO_SINGLE_BLOCKER_SOURCE
    )


def test_uncover_pattern_is_not_stolen():
    state = uncover_pattern_state()
    park = (8, 0, 1)
    assert assess_receiver_uncover(state, park).qualified
    assert recognise_lead_source_excavation(state) == ()
    successors, telemetry, _ = _successors(state)
    excav = [
        item
        for item in successors
        if item.kind == StrategicActionKind.LEAD_SOURCE_EXCAVATION
    ]
    uncover = [item for item in successors if item.receiver_uncover_followup is not None]
    assert uncover
    assert not excav
    assert telemetry.receiver_uncover_generated >= 1


def test_already_covered_macro_is_not_reemitted():
    state = known_pattern_state()
    macros = recognise_lead_source_excavation(state)
    assert macros
    assert already_covered_by_successors(macros[0].actions, (macros[0].actions,))
    successors, _telemetry, _ = _successors(state)
    existing = tuple(item.actions for item in successors)
    from spider.planner.anytime_controller import _lead_source_excavation_successors

    node_successors, _, analysis = _successors(state)
    node = StrategicSearchNode(
        0,
        state,
        0,
        (),
        None,
        None,
        0,
        StrategicCreditLevel.CLEAN,
        analysis,
    )
    extras = _lead_source_excavation_successors(
        node, ControllerTelemetry(), existing
    )
    assert extras == []


def test_unrelated_parks_stay_speculative():
    state = unrelated_speculative_park_state()
    action = (1, 0, 1)
    assert recognise_lead_source_excavation(state) == ()
    successors, _telemetry, analysis = _successors(state)
    assert (action,) not in {item.actions for item in successors}
    excav = [
        item
        for item in successors
        if item.kind == StrategicActionKind.LEAD_SOURCE_EXCAVATION
    ]
    assert not excav
    projects = [item for item in analysis.economic.projects if item.action == action]
    if projects:
        assert projects[0].assessment.frontier_tier == (
            EconomicFrontierTier.SPECULATIVE_DEFERRABLE
        )


def test_canonical_worse_is_rejected():
    state = canonical_worse_state()
    assert recognise_lead_source_excavation(state) == ()
    assert (
        lead_source_excavation_reject_reason(state)
        == LeadSourceExcavationReject.CANONICAL_WORSE
    )


def test_after_macro_both_ends_generate_stable_join():
    """After the macro, if both ends of the required edge are tops, CLEAN emits the join."""
    start = known_pattern_state()
    macros = recognise_lead_source_excavation(start)
    assert macros
    evidence = macros[0]
    assert evidence.source is not None
    mid = start.clone()
    assert replay_actions(mid, list(evidence.actions)) == 3
    source = evidence.source
    high = source.rank + 1
    src_col = next(
        ci
        for ci, col in enumerate(mid.columns)
        if col.top() is not None
        and col.top().suit == source.suit
        and col.top().rank == source.rank
    )
    dst_col = next(
        ci
        for ci, col in enumerate(mid.columns)
        if ci != src_col and (not col.face_up or col.top().suit != source.suit)
    )
    mid.columns[dst_col].face_up[:] = [_card(source.suit, high)]
    join = (src_col, dst_col, 1)
    assert mid.can_move(*join)
    life = assess_tableau_move(mid, join, discover_exit=False)
    assert life.placement_class == PlacementClass.STABLE_SAME_SUIT_JOIN
    assert not life.same_suit_joins_broken
    successors, _telemetry, analysis = _successors(mid, g=3)
    generated = [
        item for item in successors if item.actions == (join,) or join in item.actions
    ]
    assert generated, [item.actions for item in successors]
    project = next((p for p in analysis.economic.projects if p.action == join), None)
    if project is not None:
        assert project.assessment.frontier_tier == EconomicFrontierTier.STRUCTURALLY_DOMINANT
    end = mid.clone()
    assert replay_actions(end, [join]) == 1


def test_tt_and_frontier_policy_unchanged():
    state = known_pattern_state()
    before = canonical_state_key(state)
    recognise_lead_source_excavation(state)
    assert canonical_state_key(state) == before
    tt = StrategicTranspositionTable()
    assert tt.admit(state, 4)
    assert not tt.admit(state, 4)
    assert not tt.admit(state, 5)
    assert tt.admit(state, 3)
    source = inspect.getsource(allowed_frontier_tiers)
    assert source.index("return (EconomicFrontierTier.STRUCTURALLY_DOMINANT,)") < source.index(
        "POSITIVE_INVESTMENT"
    )


def _reconstruct_node78():
    cards = tuple(load_deal(DEAL_PATH))
    opening = SpiderState.from_cards(list(cards))
    anchor = _node(solve_anytime(opening, cards, None, _opening_anchor_config()))
    assert (anchor.g, len(anchor.state.foundations), len(anchor.state.stock)) == (
        21,
        1,
        30,
    )
    pops = []
    nodes = {}
    original_pop = heapq.heappop
    original_record = controller._record_transition

    def wrapped_pop(heap):
        item = original_pop(heap)
        try:
            node = item[2]
        except (IndexError, TypeError):
            return item
        if isinstance(node, StrategicSearchNode):
            nodes[node.node_id] = node
            pops.append(node.node_id)
        return item

    def wrapped_record(parent, successor, child, telemetry, config, *, elapsed_seconds):
        nodes[child.node_id] = child
        return original_record(
            parent, successor, child, telemetry, config, elapsed_seconds=elapsed_seconds
        )

    controller._record_transition = wrapped_record
    heapq.heappop = wrapped_pop
    try:
        solve_anytime(
            anchor.state,
            cards,
            None,
            _gate_envelope(_gate_z_base_config, 90.0, 25, 300_000),
        )
    finally:
        controller._record_transition = original_record
        heapq.heappop = original_pop
    seen = {}
    for nid in pops:
        node = nodes.get(nid)
        if node is None or len(node.state.foundations) != 1 or len(node.state.stock) != 0:
            continue
        key = canonical_state_key(node.state)
        prev = seen.get(key)
        if prev is None or _node_priority(node) < _node_priority(prev):
            seen[key] = node
    stock0 = sorted(seen.values(), key=_node_priority)
    node78 = next((n for n in stock0 if n.node_id == 78), None)
    assert node78 is not None
    return node78, cards, stock0


def test_node_78_emits_exact_known_macro():
    node78, _cards_deal, stock0 = _reconstruct_node78()
    state = node78.state
    assert len(state.stock) == 0
    assert _fd(state) == 32
    assert _empty(state) == 0
    macros = recognise_lead_source_excavation(state)
    actions = tuple(item.actions for item in macros)
    assert MACRO78 in actions
    # The diagnostic (3,8,1) peel is legal and exposes Qd, but it raises
    # lead blocker_work 7->8 so the canonical gate keeps (3,9,1) instead.
    diag = state.clone()
    assert replay_actions(diag, list(MACRO78_DIAGNOSTIC)) == 3
    assert diag.columns[2].top() == _card("d", 12)
    assert MACRO78_DIAGNOSTIC not in actions
    evidence = next(item for item in macros if item.actions == MACRO78)
    assert evidence.cost == 3
    assert evidence.post_key is not None and evidence.pre_key is not None
    assert evidence.post_key <= evidence.pre_key
    end = state.clone()
    assert replay_actions(end, list(MACRO78)) == 3
    assert end.columns[2].top() == _card("d", 12)
    assert _fd(end) == 32
    assert _empty(end) == 0
    assert _broken_across(state, MACRO78) == 0
    after2 = state.clone()
    after2.move(*MACRO78[0], rules=MW_RULES)
    after2.move(*MACRO78[1], rules=MW_RULES)
    consume_life = assess_tableau_move(after2, MACRO78[2], discover_exit=False)
    assert consume_life.placement_class == PlacementClass.STABLE_SAME_SUIT_JOIN
    assert any("Kh" in label and "Qh" in label for label in consume_life.same_suit_joins_created)
    successors, telemetry, _ = _successors(state, g=node78.g)
    excav = [
        item
        for item in successors
        if item.kind == StrategicActionKind.LEAD_SOURCE_EXCAVATION
        and item.actions == MACRO78
    ]
    assert excav, [item.actions for item in successors]
    assert excav[0].corrected_cost == 3
    assert telemetry.lead_source_excavation_generated >= 1
    analysis = analyze_economic_projects(state, cards=_cards())
    mixed = [
        project
        for project in analysis.projects
        if project.kind == EconomicProjectKind.TEMPORARY_REWORK
        and project.action is not None
        and (
            project.rework_investment is None
            or project.rework_investment.payoff_followup is None
        )
    ]
    assert len(mixed) <= 3
    similar = sum(1 for node in stock0 if recognise_lead_source_excavation(node.state))
    assert similar >= 1
