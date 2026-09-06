"""Narrow gates for the common Stage-0 queue representation experiment."""

from dataclasses import replace
from types import SimpleNamespace

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.planner.anytime_controller import (
    ControllerTelemetry,
    FoundationCheckpointPortfolio,
    FrontierPrioritySchema,
    StrategicCreditLevel,
    StrategicSearchNode,
    StrategicTranspositionTable,
    _node_priority,
    _raw_move_successors,
    _reserve_epoch_transition_representative,
    _trim_frontier_with_checkpoint_diversity,
    analyze_stage0_state,
)


def _state(*, buried: int = 0) -> SpiderState:
    columns = []
    for index in range(10):
        down = [Card("c", 13)] * buried if index == 0 else []
        columns.append(Column(down, [Card("s" if index == 0 else "h", 5 + index % 2)]))
    return SpiderState(columns, [])


def _analysis():
    progress = SimpleNamespace(ordering_key=lambda: (1,) + (0,) * 21)
    return SimpleNamespace(progress=progress)


def _node(
    node_id: int,
    *,
    state: SpiderState | None = None,
    analysis=None,
    schema: FrontierPrioritySchema = FrontierPrioritySchema.LEGACY,
    credit: StrategicCreditLevel = StrategicCreditLevel.CLEAN,
) -> StrategicSearchNode:
    state = state or _state()
    return StrategicSearchNode(
        node_id,
        state,
        0,
        (),
        None,
        None,
        0,
        credit,
        analysis,
        analyze_stage0_state(state, spent_cost=0, incumbent_cost=None),
        frontier_priority_schema=schema,
    )


def test_control_retains_legacy_lazy_vs_analysed_priority_layouts():
    lazy = _node(7)
    analysed = replace(lazy, analysis=_analysis())
    assert _node_priority(lazy) != _node_priority(analysed)
    assert _node_priority(lazy)[0] == 0
    assert _node_priority(analysed)[0] == 1


def test_common_stage0_analysis_attachment_does_not_change_queue_key():
    lazy = _node(7, schema=FrontierPrioritySchema.COMMON_STAGE0)
    analysed = replace(lazy, analysis=_analysis())
    assert _node_priority(lazy) == _node_priority(analysed)


def test_common_stage0_is_preserved_by_widening_replace():
    lazy = _node(7, schema=FrontierPrioritySchema.COMMON_STAGE0)
    widened = replace(
        lazy,
        node_id=8,
        credit_level=StrategicCreditLevel.POSITIVE_INVESTMENT,
        analysis=_analysis(),
    )
    widened_lazy = replace(widened, analysis=None)
    assert widened.frontier_priority_schema is FrontierPrioritySchema.COMMON_STAGE0
    assert _node_priority(widened) == _node_priority(widened_lazy)


def test_common_stage0_rekey_and_trim_paths_use_common_keys():
    common = _node(2, analysis=_analysis(), schema=FrontierPrioritySchema.COMMON_STAGE0)
    other = _node(
        3,
        state=_state(buried=1),
        analysis=_analysis(),
        schema=FrontierPrioritySchema.COMMON_STAGE0,
    )
    rebuilt = _reserve_epoch_transition_representative(
        (((999,), 2, common),),
        tt=StrategicTranspositionTable(),
        spent_opportunity_ids=(),
        telemetry=ControllerTelemetry(),
    )
    assert rebuilt[0][0] == _node_priority(common)

    frontier = [
        (_node_priority(common), common.node_id, common),
        (_node_priority(other), other.node_id, other),
    ]
    portfolio = FoundationCheckpointPortfolio((), (), 0, 0, 1)
    kept = _trim_frontier_with_checkpoint_diversity(
        frontier,
        maximum=1,
        portfolio=portfolio,
    )
    assert kept[0] == min(frontier)


def test_priority_schema_switch_does_not_change_raw_successor_generation():
    legacy = _node(1)
    common = replace(legacy, frontier_priority_schema=FrontierPrioritySchema.COMMON_STAGE0)

    def signature(node):
        return [
            (item.kind, item.actions, item.corrected_cost, item.category)
            for item in _raw_move_successors(node)
        ]

    assert signature(legacy) == signature(common)
