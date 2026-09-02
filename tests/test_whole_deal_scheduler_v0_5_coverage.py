"""v0.5 cleanup: conversion-child coverage is gone; class-E handoff remains."""

from __future__ import annotations

import inspect

import spider.planner.anytime_controller as controller
import spider.planner.whole_deal_scheduler as scheduler
from spider.planner.anytime_controller import (
    ControllerTelemetry,
    StrategicSearchNode,
)

from test_whole_deal_scheduler_v0_5 import (
    test_01_lead_converted_lane_emits_legal_bridge_successor,
    test_02_terminal_ready_converted_lane_emits_existing_terminal_successor,
    test_04_non_lead_converted_lane_is_not_forced,
)


def test_01_no_conversion_child_coverage_api_remains():
    assert "arrival_conversion_coverage" not in StrategicSearchNode.__dataclass_fields__
    assert not hasattr(scheduler, "ArrivalConversionCoverage")
    assert not hasattr(scheduler, "qualify_arrival_conversion_coverage")
    assert not hasattr(controller, "_reserve_arrival_conversion_coverage")
    source = inspect.getsource(controller)
    assert "_reserve_arrival_conversion_coverage" not in source
    assert "qualify_arrival_conversion_coverage" not in source


def test_02_no_conversion_child_reservation_counters_are_used():
    telemetry = ControllerTelemetry()
    assert telemetry.arrival_conversion_representatives_required == 0
    assert telemetry.arrival_conversion_representatives_reserved == 0
    assert telemetry.arrival_conversion_representatives_expanded == 0
    assert not hasattr(telemetry, "arrival_conversion_coverage_traces")


def test_03_non_lead_converted_lanes_are_not_forced():
    test_04_non_lead_converted_lane_is_not_forced()


def test_04_lead_converted_lane_still_emits_legal_maturation_successor():
    test_01_lead_converted_lane_emits_legal_bridge_successor()


def test_05_terminal_ready_lead_handoff_remains_supported():
    test_02_terminal_ready_converted_lane_emits_existing_terminal_successor()
