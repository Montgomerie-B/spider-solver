"""Solution strategy forensics v0.61."""

from __future__ import annotations

import ast
from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.research_actions import is_deal, step_cost
from spider.solution_forensics import (
    AUTO_MOVES,
    CANON_MOVES,
    classify_tableau,
    epoch_waterfall,
    exclusive_bucket,
    extract_epochs,
    instrumented_replay,
    load_opening,
    physical_labels,
    rehandling_summary,
)

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "solution_forensics.py"
SCRIPT = ROOT / "research" / "solution_strategy_forensics_v0_61.py"
SCHED = ROOT / "src" / "spider" / "whole_game_epoch_scheduler.py"
COST = ROOT / "src" / "spider" / "autonomous_cost.py"


def test_both_replays_and_scores():
    opening, raw, labels = load_opening()
    auto_a = parse_moves_file(AUTO_MOVES)
    can_a = parse_moves_file(CANON_MOVES)
    ea = opening.clone()
    ec = opening.clone()
    assert replay_actions(ea, auto_a) == 198
    assert replay_actions(ec, can_a) == 172
    assert ea.is_solved() and ec.is_solved()
    assert sum(1 for a in auto_a if is_deal(a)) == 5
    assert sum(1 for a in can_a if is_deal(a)) == 5
    auto = instrumented_replay(opening, auto_a, labels, expected_g=198)
    canon = instrumented_replay(opening, can_a, labels, expected_g=172)
    assert auto["g"] == 198 and canon["g"] == 172
    assert auto["n_physical"] == 104 and canon["n_physical"] == 104


def test_physical_identity_distinguishes_duplicates():
    opening, raw, labels = load_opening()
    assert len(raw) == 104
    assert len(labels) == 104
    assert len(set(labels.values())) == 104
    fives = [lab for lab in labels.values() if lab.startswith("5S#")]
    assert set(fives) == {"5S#A", "5S#B"}
    opening2 = SpiderState.from_cards(list(load_deal(ROOT / "deals" / "4925153.txt")))
    labs2 = physical_labels(list(load_deal(ROOT / "deals" / "4925153.txt")))
    assert set(labs2.values()) == set(labels.values())


def test_prefix_deal_and_foundation_extraction():
    opening, raw, labels = load_opening()
    auto_a = parse_moves_file(AUTO_MOVES)
    auto = instrumented_replay(opening, auto_a, labels, expected_g=198)
    eps = extract_epochs(auto, opening, auto_a, labels)
    deals = [e for e in eps if e.get("is_deal")]
    tabs = [e for e in eps if not e.get("is_deal")]
    assert len(deals) == 5
    assert len(tabs) == 6
    assert tabs[0]["enter"]["g"] == 0
    assert tabs[-1]["exit"]["g"] == 198
    assert auto["foundations"]
    assert auto["foundations"][-1]["n"] == 8
    assert tabs[-1]["enter"]["remaining_cost"] == auto["g"] - tabs[-1]["enter"]["g"]


def test_zero_cost_and_taxonomy():
    tags = classify_tableau(
        cost=0, flipped=True, removed=False, dest_was_empty=True,
        empty_before=1, empty_after=1, bonds_before=2, bonds_after=3,
        dest_top=None, run=[Card("s", 13)], broke_same_suit=False,
        rehandle=False, mixed_release=False, near_deal=True,
    )
    assert "ZERO_COST_RELOCATION" in tags
    assert "REVEAL" in tags
    assert exclusive_bucket(tags, 0) == "ZERO_COST_RELOCATION"
    assert exclusive_bucket(["REHANDLE", "REVEAL"], 1) == "REHANDLE"
    opening, raw, labels = load_opening()
    auto = instrumented_replay(opening, parse_moves_file(AUTO_MOVES), labels, expected_g=198)
    assert auto["zero_cost_commands"] > 0
    paid = sum(r["cost"] for r in auto["actions"] if r["kind"] == "tableau")
    assert paid + 5 == 198


def test_rehandling_and_waterfall_sum():
    opening, raw, labels = load_opening()
    auto_a = parse_moves_file(AUTO_MOVES)
    can_a = parse_moves_file(CANON_MOVES)
    auto = instrumented_replay(opening, auto_a, labels, expected_g=198)
    canon = instrumented_replay(opening, can_a, labels, expected_g=172)
    rh = rehandling_summary(auto)
    assert "paid_mw_tagged_rehandle" in rh
    ae = extract_epochs(auto, opening, auto_a, labels)
    ce = extract_epochs(canon, opening, can_a, labels)
    wf = epoch_waterfall(ae, ce)
    assert wf[-1]["cumulative_gap"] == 26
    assert sum(r["delta_198_minus_172"] for r in wf) == 26
    assert ae[0]["enter"]["remaining_cost"] == 198
    assert ce[0]["enter"]["remaining_cost"] == 172
    post_a = next(ep for ep in ae if ep["label"] == "post-SD5")
    post_c = next(ep for ep in ce if ep["label"] == "post-SD5")
    assert post_a["enter"]["remaining_cost"] == 67
    assert post_c["enter"]["remaining_cost"] == 22
    assert post_a["delta_g"] == 67
    assert post_c["delta_g"] == 22
    assert post_c["tableau_n"] == 22
    assert post_c["zero_cost"] == 0
    assert sum(auto["bucket_mw"].values()) == 198
    assert sum(canon["bucket_mw"].values()) == 172
    assert auto["bucket_mw"]["REHANDLE"] - canon["bucket_mw"]["REHANDLE"] == 24
    assert canon["foundations"][0]["g"] == 90
    assert canon["foundations"][0]["stock_rows"] == 3
    assert auto["foundations"][0]["stock_rows"] == 0


def test_no_solution_mutation_and_no_policy_hook():
    auto_before = AUTO_MOVES.read_bytes()
    can_before = CANON_MOVES.read_bytes()
    opening, raw, labels = load_opening()
    instrumented_replay(opening, parse_moves_file(AUTO_MOVES), labels, expected_g=198)
    assert AUTO_MOVES.read_bytes() == auto_before
    assert CANON_MOVES.read_bytes() == can_before
    sched = SCHED.read_text(encoding="utf-8")
    cost = COST.read_text(encoding="utf-8")
    assert "4925153_canonical.moves" not in sched
    assert "4925153_canonical.moves" not in cost
    tree = ast.parse(MOD.read_text(encoding="utf-8"))
    mods = [
        n.module
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("spider.simple_")
    ]
    assert mods == []
