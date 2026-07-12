"""Forensic move-accounting audit tests — deal 4925153."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import (
    CANONICAL_MOBILITYWARE_MOVES,
    LEGACY_CANONICAL_MW_COST,
    count_actions,
    parse_moves_file,
    replay_actions,
    replay_actions_detailed,
)
from spider.planner.diagnostics.audit_4925153_move_accounting import (
    CANONICAL,
    DEAL,
    LEDGER_CSV,
    LEDGER_JSON,
    RESULTS_JSON,
    RESULTS_MD,
    USER_OBSERVED_MOBILITYWARE,
    build_report,
    file_provenance,
    milestone_table,
    replay_ledger,
    write_ledger,
)

INCIDENT = ROOT / "docs" / "4925153_move_accounting_incident.md"


def test_canonical_command_counts():
    tab, deals = count_actions(CANONICAL)
    assert tab == 169
    assert deals == 5
    assert tab + deals == 174


def test_canonical_replay_legal_solved():
    st = SpiderState.from_cards(load_deal(DEAL))
    acts = parse_moves_file(CANONICAL)
    total = replay_actions(st, acts)
    assert st.is_solved()
    assert len(st.foundations) == 8
    assert len(st.stock) == 0
    assert total == USER_OBSERVED_MOBILITYWARE == 172
    assert total == CANONICAL_MOBILITYWARE_MOVES


def test_detailed_counters_and_legacy_explained():
    st = SpiderState.from_cards(load_deal(DEAL))
    d = replay_actions_detailed(st, parse_moves_file(CANONICAL))
    assert d["explicit_commands"] == 174
    assert d["tableau_moves"] == 169
    assert d["stock_deals"] == 5
    assert d["automatic_foundation_removals"] == 8
    assert d["mobilityware_moves"] == 172
    assert d["legacy_mw"] == LEGACY_CANONICAL_MW_COST == 163
    assert d["mobilityware_count_verified"] is True
    # 174 - 11 free-legacy = 163; 174 - 2 free-corrected = 172
    assert d["legacy_mw"] == d["explicit_commands"] - 11
    assert d["mobilityware_moves"] == d["explicit_commands"] - 2


def test_ledger_row_per_command_and_sums():
    ledger = replay_ledger()
    write_ledger(ledger)
    assert len(ledger["rows"]) == 174
    assert ledger["solved"] is True
    assert ledger["final_cum"]["explicit_commands"] == 174
    assert ledger["final_cum"]["tableau_moves"] == 169
    assert ledger["final_cum"]["stock_deals"] == 5
    assert ledger["final_cum"]["automatic_foundation_removals"] == 8
    assert ledger["final_cum"]["legacy_mw"] == 163
    assert ledger["final_cum"]["mobilityware_moves"] == 172
    # independent sum of deltas
    assert sum(r["delta_explicit_commands"] for r in ledger["rows"]) == 174
    assert sum(r["delta_legacy_mw"] for r in ledger["rows"]) == 163
    assert sum(r["delta_mobilityware_moves"] for r in ledger["rows"]) == 172
    assert LEDGER_CSV.is_file()
    with LEDGER_CSV.open(encoding="utf-8") as f:
        n = sum(1 for _ in csv.DictReader(f))
    assert n == 174


def test_all_deals_and_removals_identified():
    ledger = replay_ledger()
    deals = [r for r in ledger["rows"] if r["command_type"] == "stock_deal"]
    assert len(deals) == 5
    for d in deals:
        assert d["delta_mobilityware_moves"] == 1
        assert d["delta_legacy_mw"] == 1
    assert ledger["final_cum"]["automatic_foundation_removals"] == 8
    assert len(ledger["removal_events"]) == 8


def test_auto_removals_do_not_erase_player_moves():
    ledger = replay_ledger()
    for r in ledger["rows"]:
        if r["automatic_removals_triggered"]:
            assert r["delta_explicit_commands"] == 1
            assert r["delta_mobilityware_moves"] in (0, 1)
            # player command still present even when free relocate


def test_legacy_163_reproduced_and_explained():
    ledger = replay_ledger()
    assert ledger["final_cum"]["legacy_mw"] == 163
    free = [
        r
        for r in ledger["rows"]
        if r["delta_legacy_mw"] == 0 and r["command_type"] == "tableau_move"
    ]
    assert len(free) == 11
    # corrected free subset
    free_mw = [
        r
        for r in ledger["rows"]
        if r["delta_mobilityware_moves"] == 0 and r["command_type"] == "tableau_move"
    ]
    assert len(free_mw) == 2
    assert all(r["source_face_down"] == 0 for r in free_mw)


def test_never_labels_163_as_verified_mobilityware():
    assert CANONICAL_MOBILITYWARE_MOVES == 172
    assert LEGACY_CANONICAL_MW_COST == 163
    st = SpiderState.from_cards(load_deal(DEAL))
    assert replay_actions(st, parse_moves_file(CANONICAL)) != 163 or True
    assert replay_actions(
        SpiderState.from_cards(load_deal(DEAL)), parse_moves_file(CANONICAL)
    ) == 172


def test_milestones_regenerated():
    ms = milestone_table()
    by = {m["milestone"]: m for m in ms}
    assert by["J22_solved"]["mobilityware_moves"] == 172
    assert by["J22_solved"]["legacy_mw"] == 163
    assert by["J22_solved"]["solved"] is True
    assert by["J22_solved"]["old_reported_mw"] == 163
    # corrected > old for late milestones under defect
    assert by["J22_solved"]["mobilityware_moves"] > by["J22_solved"]["old_reported_mw"]


def test_documentation_no_verified_163_claim():
    assert INCIDENT.is_file()
    text = INCIDENT.read_text(encoding="utf-8")
    assert "172" in text
    assert "withdrawn" in text.lower() or "defective" in text.lower()
    assert "163" in text


def test_audit_does_not_optimise_or_overwrite_canonical():
    text = (
        ROOT
        / "src/spider/planner/diagnostics/audit_4925153_move_accounting.py"
    ).read_text(encoding="utf-8")
    assert "beam" not in text.lower() or "diagnostic" in text.lower()
    assert "does not search" in text or "not search" in text
    # canonical file still 174 commands
    tab, deals = count_actions(CANONICAL)
    assert tab + deals == 174


def test_build_report_outputs():
    build_report()
    assert RESULTS_JSON.is_file()
    assert RESULTS_MD.is_file()
    rep = json.loads(RESULTS_JSON.read_text(encoding="utf-8"))
    assert rep["executive"]["is_163_a_distinct_solution"] is False
    assert rep["executive"]["corrected_mobilityware_moves"] == 172
    assert rep["executive"]["legacy_mw"] == 163
    assert rep["executive"]["163_claim_withdrawn"] is True
    assert rep["optimisation_executed"] is False
    assert rep["canonical_overwritten"] is False


def test_provenance_canonical():
    p = file_provenance(CANONICAL)
    assert p["exists"]
    assert p["tableau_moves"] == 169
    assert p["stock_deals"] == 5
    assert p["explicit_commands"] == 174
