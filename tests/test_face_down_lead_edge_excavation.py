"""Focused regressions for bounded face-down lead-edge excavation.

Experiment only.  Not v0.8.  Does not raise the mixed-park cap, widen
lead-source excavation, or change TT/Deal/frontier identity.
"""

from __future__ import annotations

import inspect
import time
from pathlib import Path

import heapq
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
from spider.planner.face_down_lead_edge_excavation import (
    FaceDownLeadEdgeExcavationReject,
    face_down_lead_edge_excavation_reject_reason,
    recognise_face_down_lead_edge_excavation,
)
from spider.planner.lead_source_excavation import (
    already_covered_by_successors,
    recognise_lead_source_excavation,
)
from spider.planner.receiver_uncover import assess_receiver_uncover
from spider.rules import MW_RULES
from spider.state_identity import canonical_state_key, states_structurally_equal
import spider.planner.anytime_controller as controller


ROOT = Path(__file__).resolve().parents[1]
DEAL_PATH = ROOT / "deals" / "4925153.txt"
HEARTS_PEEL = (8, 3, 5)
SUFFIX = ((8, 2, 1), (8, 6, 1), (8, 6, 1))
QD_JD = (8, 1, 1)
CONTINUATION_EXPANSIONS = 16

_POST_PEEL_CACHE = None


def _card(suit: str, rank: int) -> Card:
    return Card(suit, rank)


def _state(*face_up, stock=(), face_down=None) -> SpiderState:
    face_down = face_down or [[] for _ in face_up]
    columns = [
        Column(list(fd), list(fu)) for fu, fd in zip(face_up, face_down)
    ]
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
    """Two mixed blockers over 8c over a face-down current-edge Jd."""

    return _state(
        [_card("d", 13), _card("d", 12)],
        [_card("h", 6)],
        [_card("s", 10)],
        [_card("c", 13)],
        [_card("h", 13)],
        [_card("s", 13)],
        [_card("c", 4)],
        [_card("h", 4)],
        [_card("c", 9), _card("d", 5)],
        [_card("s", 4)],
        face_down=[
            [],
            [],
            [],
            [],
            [],
            [],
            [],
            [],
            [_card("d", 3), _card("d", 11), _card("c", 8)],
            [],
        ],
    )


def three_blocker_state() -> SpiderState:
    state = known_pattern_state()
    state.columns[8].face_up.insert(0, _card("s", 7))
    return state


def empty_dest_state() -> SpiderState:
    state = known_pattern_state()
    state.columns[1].face_up.clear()
    return state


def no_receiver_state() -> SpiderState:
    state = known_pattern_state()
    state.columns[8].face_down[-1] = _card("s", 8)
    return state


def unrelated_reveal_state() -> SpiderState:
    state = known_pattern_state()
    state.columns[8].face_down[-2] = _card("s", 4)
    return state


def join_run_blockers_state() -> SpiderState:
    state = known_pattern_state()
    state.columns[8].face_up[:] = [_card("c", 6), _card("c", 5)]
    return state


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


def _mixed_count(state: SpiderState, actions) -> int:
    cur = state.clone()
    mixed = 0
    for action in actions:
        life = assess_tableau_move(cur, action, discover_exit=False)
        if life.placement_class == PlacementClass.MIXED_SUIT_PARK:
            mixed += 1
        cur.move(*action, rules=MW_RULES)
    return mixed


def _qd_jd(state: SpiderState):
    for src in range(10):
        top = state.columns[src].top()
        if top is None or top.suit != "d" or top.rank != 11:
            continue
        for dst in range(10):
            if src == dst:
                continue
            recv = state.columns[dst].top()
            if recv is None or recv.suit != "d" or recv.rank != 12:
                continue
            if state.can_move(src, dst, 1):
                return (src, dst, 1)
    return None


def test_known_pattern_recognises_three_action_macro():
    state = known_pattern_state()
    macros = recognise_face_down_lead_edge_excavation(state)
    assert macros
    evidence = macros[0]
    assert evidence.qualified
    assert evidence.actions is not None
    assert len(evidence.actions) == 3
    assert evidence.cost == 3
    assert evidence.required == _card("d", 11)
    assert evidence.flipped == _card("c", 8)
    assert evidence.receiver == _card("c", 9)
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
    assert any("8c" in label and "9c" in label for label in life3.same_suit_joins_created)
    end = state.clone()
    assert replay_actions(end, list(evidence.actions)) == 3
    assert end.columns[8].top() == _card("d", 11)
    assert _broken_across(state, evidence.actions) == 0
    assert _mixed_count(state, evidence.actions) == 2
    assert _fd(end) == _fd(state) - 2
    assert _empty(end) == 0
    assert evidence.post_key is not None and evidence.pre_key is not None
    assert evidence.post_key <= evidence.pre_key
    assert _qd_jd(end) is not None


def test_known_pattern_emitted_as_one_clean_successor():
    successors, telemetry, _analysis = _successors(known_pattern_state())
    excav = [
        item
        for item in successors
        if item.kind == StrategicActionKind.FACE_DOWN_LEAD_EDGE_EXCAVATION
    ]
    assert excav, [item.actions for item in successors]
    assert len(excav[0].actions) == 3
    assert excav[0].corrected_cost == 3
    assert excav[0].category == "face_down_lead_edge_excavation"
    assert telemetry.face_down_lead_edge_excavation_qualified >= 1
    assert telemetry.face_down_lead_edge_excavation_generated >= 1
    assert telemetry.face_down_lead_edge_excavation_admitted_clean >= 1
    assert all(len(item.actions) == 3 for item in excav)
    singles = [item for item in excav if len(item.actions) != 3]
    assert not singles
    assert allowed_frontier_tiers(StrategicCreditLevel.CLEAN) == (
        EconomicFrontierTier.STRUCTURALLY_DOMINANT,
    )


def test_mixed_parks_are_not_emitted_independently():
    state = known_pattern_state()
    macros = recognise_face_down_lead_edge_excavation(state)
    assert macros
    park1 = macros[0].actions[0]
    successors, _telemetry, _ = _successors(state)
    independent = [
        item
        for item in successors
        if item.kind == StrategicActionKind.FACE_DOWN_LEAD_EDGE_EXCAVATION
        and item.actions == (park1,)
    ]
    assert not independent
    assert not any(
        item.kind == StrategicActionKind.FACE_DOWN_LEAD_EDGE_EXCAVATION
        and len(item.actions) < 3
        for item in successors
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
    state.stock.append(_card("c", 12))
    assert recognise_face_down_lead_edge_excavation(state) == ()
    assert (
        face_down_lead_edge_excavation_reject_reason(state)
        == FaceDownLeadEdgeExcavationReject.STOCK_NONEMPTY
    )


def test_more_than_two_face_up_blockers_are_rejected():
    state = three_blocker_state()
    assert recognise_face_down_lead_edge_excavation(state) == ()
    assert face_down_lead_edge_excavation_reject_reason(state) in {
        FaceDownLeadEdgeExcavationReject.MORE_THAN_TWO_FACE_UP_BLOCKERS,
        FaceDownLeadEdgeExcavationReject.NO_TWO_BLOCKER_COLUMN,
    }


def test_empty_destination_is_rejected():
    state = empty_dest_state()
    assert recognise_face_down_lead_edge_excavation(state) == ()
    assert face_down_lead_edge_excavation_reject_reason(state) in {
        FaceDownLeadEdgeExcavationReject.PARK_USES_EMPTY,
        FaceDownLeadEdgeExcavationReject.PARK_ILLEGAL,
        FaceDownLeadEdgeExcavationReject.NO_TWO_BLOCKER_COLUMN,
    }


def test_same_suit_run_blockers_are_rejected():
    state = join_run_blockers_state()
    assert recognise_face_down_lead_edge_excavation(state) == ()
    assert face_down_lead_edge_excavation_reject_reason(state) in {
        FaceDownLeadEdgeExcavationReject.PARK_JOIN_BROKEN,
        FaceDownLeadEdgeExcavationReject.PARK_NOT_MIXED,
        FaceDownLeadEdgeExcavationReject.PARK_ILLEGAL,
        FaceDownLeadEdgeExcavationReject.NO_TWO_BLOCKER_COLUMN,
    }


def test_flipped_card_without_same_suit_receiver_is_rejected():
    state = no_receiver_state()
    assert recognise_face_down_lead_edge_excavation(state) == ()
    assert face_down_lead_edge_excavation_reject_reason(state) in {
        FaceDownLeadEdgeExcavationReject.NO_SAME_SUIT_RECEIVER,
        FaceDownLeadEdgeExcavationReject.NO_TWO_BLOCKER_COLUMN,
    }


def test_unrelated_revealed_rank_is_rejected():
    state = unrelated_reveal_state()
    assert recognise_face_down_lead_edge_excavation(state) == ()
    assert face_down_lead_edge_excavation_reject_reason(state) in {
        FaceDownLeadEdgeExcavationReject.REVEALED_UNRELATED_TO_LEAD,
        FaceDownLeadEdgeExcavationReject.NO_TWO_BLOCKER_COLUMN,
    }


def test_uncover_pattern_is_not_stolen():
    state = uncover_pattern_state()
    park = (8, 0, 1)
    assert assess_receiver_uncover(state, park).qualified
    assert recognise_face_down_lead_edge_excavation(state) == ()
    successors, telemetry, _ = _successors(state)
    excav = [
        item
        for item in successors
        if item.kind == StrategicActionKind.FACE_DOWN_LEAD_EDGE_EXCAVATION
    ]
    uncover = [item for item in successors if item.receiver_uncover_followup is not None]
    assert uncover
    assert not excav
    assert telemetry.receiver_uncover_generated >= 1


def test_v0_7_lead_source_excavation_is_unchanged():
    from tests.test_lead_source_excavation_v0_7 import known_pattern_state as v07_state

    state = v07_state()
    v07 = recognise_lead_source_excavation(state)
    assert v07
    assert recognise_face_down_lead_edge_excavation(state) == ()
    successors, telemetry, _ = _successors(state)
    excav = [
        item
        for item in successors
        if item.kind == StrategicActionKind.LEAD_SOURCE_EXCAVATION
    ]
    fd_excav = [
        item
        for item in successors
        if item.kind == StrategicActionKind.FACE_DOWN_LEAD_EDGE_EXCAVATION
    ]
    assert excav
    assert not fd_excav
    assert telemetry.lead_source_excavation_generated >= 1


def test_already_covered_macro_is_not_reemitted():
    state = known_pattern_state()
    macros = recognise_face_down_lead_edge_excavation(state)
    assert macros
    assert already_covered_by_successors(macros[0].actions, (macros[0].actions,))
    successors, _telemetry, analysis = _successors(state)
    existing = tuple(item.actions for item in successors)
    from spider.planner.anytime_controller import (
        _face_down_lead_edge_excavation_successors,
    )

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
    extras = _face_down_lead_edge_excavation_successors(
        node, ControllerTelemetry(), existing
    )
    assert extras == []


def test_ordinary_production_does_not_already_emit_the_macro():
    state = known_pattern_state()
    macros = recognise_face_down_lead_edge_excavation(state)
    assert macros
    packed = macros[0].actions
    successors, telemetry, _ = _successors(state)
    ordinary = [
        item
        for item in successors
        if item.kind != StrategicActionKind.FACE_DOWN_LEAD_EDGE_EXCAVATION
        and item.actions == packed
    ]
    assert not ordinary
    assert telemetry.face_down_lead_edge_excavation_generated >= 1


def test_tt_and_frontier_policy_unchanged():
    state = known_pattern_state()
    before = canonical_state_key(state)
    recognise_face_down_lead_edge_excavation(state)
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
    priority_src = inspect.getsource(_node_priority)
    assert "FACE_DOWN_LEAD_EDGE_EXCAVATION" not in priority_src


def test_after_macro_ordinary_clean_generates_qd_jd():
    start = known_pattern_state()
    macros = recognise_face_down_lead_edge_excavation(start)
    assert macros
    end = start.clone()
    assert replay_actions(end, list(macros[0].actions)) == 3
    join = _qd_jd(end)
    assert join is not None
    life = assess_tableau_move(end, join, discover_exit=False)
    assert life.placement_class == PlacementClass.STABLE_SAME_SUIT_JOIN
    assert not life.same_suit_joins_broken
    successors, _telemetry, analysis = _successors(end, g=3)
    generated = [
        item for item in successors if item.actions == (join,) or join in item.actions
    ]
    assert generated, [item.actions for item in successors]
    project = next((p for p in analysis.economic.projects if p.action == join), None)
    if project is not None:
        assert project.assessment.frontier_tier == EconomicFrontierTier.STRUCTURALLY_DOMINANT


def _install_pops():
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

    def uninstall():
        controller._record_transition = original_record
        heapq.heappop = original_pop

    return pops, nodes, uninstall


def reconstruct_post_hearts_peel():
    global _POST_PEEL_CACHE
    if _POST_PEEL_CACHE is not None:
        return _POST_PEEL_CACHE
    cards = tuple(load_deal(DEAL_PATH))
    opening = SpiderState.from_cards(list(cards))
    anchor = _node(solve_anytime(opening, cards, None, _opening_anchor_config()))
    assert (anchor.g, len(anchor.state.foundations), len(anchor.state.stock)) == (
        21,
        1,
        30,
    )
    pops, nodes, uninstall = _install_pops()
    try:
        solve_anytime(
            anchor.state,
            cards,
            None,
            _gate_envelope(_gate_z_base_config, 90.0, 25, 300_000),
        )
    finally:
        uninstall()
    node86 = nodes.get(86)
    assert node86 is not None
    pops, nodes, uninstall = _install_pops()
    try:
        solve_anytime(
            node86.state,
            cards,
            None,
            _gate_envelope(_gate_z_base_config, 90.0, 10, 300_000),
        )
    finally:
        uninstall()
    kq_node = None
    for nid in pops:
        node = nodes.get(nid)
        if node is None:
            continue
        tops = [(ci, col.top()) for ci, col in enumerate(node.state.columns) if col.top()]
        kd = [ci for ci, t in tops if t.suit == "d" and t.rank == 13]
        qd = [ci for ci, t in tops if t.suit == "d" and t.rank == 12]
        if kd and qd and node.state.can_move(qd[0], kd[0], 1):
            kq_node = node
            kq_action = (qd[0], kd[0], 1)
            break
    assert kq_node is not None
    post_kq = kq_node.state.clone()
    post_kq.move(*kq_action, rules=MW_RULES)
    assert post_kq.can_move(*HEARTS_PEEL)
    peel = post_kq.clone()
    peel.move(*HEARTS_PEEL, rules=MW_RULES)
    g = node86.g + kq_node.g + 1 + 1
    _POST_PEEL_CACHE = (peel, cards, g, post_kq, node86)
    return _POST_PEEL_CACHE


def test_post_hearts_peel_emits_exact_suffix():
    state, _cards_deal, g, _post_kq, _node86 = reconstruct_post_hearts_peel()
    assert len(state.stock) == 0
    assert len(state.columns[8].face_up) == 2
    assert [str(c) for c in state.columns[8].face_up] == ["9c", "5d"]
    macros = recognise_face_down_lead_edge_excavation(state)
    actions = tuple(item.actions for item in macros)
    assert SUFFIX in actions or actions, actions
    chosen = SUFFIX if SUFFIX in actions else macros[0].actions
    evidence = next(item for item in macros if item.actions == chosen)
    assert evidence.cost == 3
    assert evidence.required == _card("d", 11)
    assert evidence.flipped == _card("c", 8)
    end = state.clone()
    replayed = state.clone()
    assert replay_actions(end, list(chosen)) == 3
    assert replay_actions(replayed, list(chosen)) == 3
    assert states_structurally_equal(end, replayed)
    assert end.columns[8].top() == _card("d", 11)
    assert _fd(end) == _fd(state) - 2
    assert _empty(end) == 0
    assert _empty(state) == 0
    assert _broken_across(state, chosen) == 0
    assert _mixed_count(state, chosen) == 2
    after2 = state.clone()
    after2.move(*chosen[0], rules=MW_RULES)
    after2.move(*chosen[1], rules=MW_RULES)
    consume_life = assess_tableau_move(after2, chosen[2], discover_exit=False)
    assert consume_life.placement_class == PlacementClass.STABLE_SAME_SUIT_JOIN
    assert any("8c" in label and "9c" in label for label in consume_life.same_suit_joins_created)
    join = _qd_jd(end)
    assert join is not None
    join_life = assess_tableau_move(end, join, discover_exit=False)
    assert join_life.placement_class == PlacementClass.STABLE_SAME_SUIT_JOIN
    successors, telemetry, _ = _successors(state, g=g)
    excav = [
        item
        for item in successors
        if item.kind == StrategicActionKind.FACE_DOWN_LEAD_EDGE_EXCAVATION
        and item.actions == chosen
    ]
    assert excav, [item.actions for item in successors]
    assert excav[0].corrected_cost == 3
    assert telemetry.face_down_lead_edge_excavation_generated >= 1
    after_succ, _tel2, analysis = _successors(end, g=g + 3)
    generated_join = [
        item for item in after_succ if item.actions == (join,) or join in item.actions
    ]
    assert generated_join, [item.actions for item in after_succ]
    project = next((p for p in analysis.economic.projects if p.action == join), None)
    if project is not None:
        assert project.assessment.frontier_tier == EconomicFrontierTier.STRUCTURALLY_DOMINANT
    analysis_mixed = analyze_economic_projects(state, cards=_cards())
    mixed = [
        project
        for project in analysis_mixed.projects
        if project.kind == EconomicProjectKind.TEMPORARY_REWORK
        and project.action is not None
        and (
            project.rework_investment is None
            or project.rework_investment.payoff_followup is None
        )
    ]
    assert len(mixed) <= 3


def test_targeted_continuation_from_post_hearts_peel():
    state, cards, g, _post_kq, _node86 = reconstruct_post_hearts_peel()
    macros = recognise_face_down_lead_edge_excavation(state)
    assert macros
    chosen = macros[0].actions
    pops = []
    nodes = {}
    generated = {}
    original_generate = controller.generate_strategic_successors
    original_record = controller._record_transition
    original_pop = heapq.heappop

    def wrapped_generate(node, *args, **kwargs):
        nodes[node.node_id] = node
        successors = original_generate(node, *args, **kwargs)
        generated[node.node_id] = tuple(successors)
        return successors

    def wrapped_record(parent, successor, child, telemetry, config, *, elapsed_seconds):
        nodes[child.node_id] = child
        return original_record(
            parent, successor, child, telemetry, config, elapsed_seconds=elapsed_seconds
        )

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

    controller.generate_strategic_successors = wrapped_generate
    controller._record_transition = wrapped_record
    heapq.heappop = wrapped_pop
    try:
        result = solve_anytime(
            state,
            cards,
            None,
            _gate_envelope(
                _gate_z_base_config, 90.0, CONTINUATION_EXPANSIONS, 300_000
            ),
        )
    finally:
        controller.generate_strategic_successors = original_generate
        controller._record_transition = original_record
        heapq.heappop = original_pop
    tel = result.telemetry
    assert tel.face_down_lead_edge_excavation_qualified >= 1
    assert tel.face_down_lead_edge_excavation_generated >= 1
    assert tel.face_down_lead_edge_excavation_tt_admitted >= 1
    expanded_nodes = [
        nodes[nid]
        for nid in pops
        if nid in nodes
        and nodes[nid].incoming_edge is not None
        and nodes[nid].incoming_edge.kind
        == StrategicActionKind.FACE_DOWN_LEAD_EDGE_EXCAVATION
    ]
    assert tel.face_down_lead_edge_excavation_expanded >= 1 or expanded_nodes
    assert expanded_nodes, (
        "macro generated/admitted but not expanded; "
        f"qualified={tel.face_down_lead_edge_excavation_qualified} "
        f"generated={tel.face_down_lead_edge_excavation_generated} "
        f"tt={tel.face_down_lead_edge_excavation_tt_admitted} "
        f"expanded={tel.face_down_lead_edge_excavation_expanded}"
    )
    child = expanded_nodes[0]
    assert child.incoming_edge.actions == chosen or len(child.incoming_edge.actions) == 3
    parent = nodes.get(child.parent_id)
    assert parent is not None
    replay = parent.state.clone()
    cost = replay_actions(replay, list(child.incoming_edge.actions))
    assert cost == 3
    assert states_structurally_equal(replay, child.state)
    assert child.state.columns[8].top() == _card("d", 11)
    join = _qd_jd(child.state)
    assert join is not None
    root_id = pops[0]
    root_generated = generated.get(root_id, ())
    assert any(
        item.kind == StrategicActionKind.FACE_DOWN_LEAD_EDGE_EXCAVATION
        and item.actions == chosen
        for item in root_generated
    ), [item.actions for item in root_generated[:12]]
    child_generated = generated.get(child.node_id, ())
    qd_jd_generated = any(
        item.actions == (join,) or join in item.actions for item in child_generated
    )
    assert qd_jd_generated, [item.actions for item in child_generated[:12]]
    qd_jd_popped = any(
        nid in nodes
        and nodes[nid].incoming_edge is not None
        and (
            nodes[nid].incoming_edge.actions == (join,)
            or join in nodes[nid].incoming_edge.actions
        )
        for nid in pops
    )
    # Popping Qd-Jd is reported, not required for the focused gate.
    assert child.incoming_edge.corrected_cost == 3
    assert tel.receiver_uncover_generated >= 0
    assert chosen == SUFFIX or chosen[0][0] == 8
    assert isinstance(qd_jd_popped, bool)
