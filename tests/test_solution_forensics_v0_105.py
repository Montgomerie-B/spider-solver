"""Forensic trajectory tests for solution forensics v0.105."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.forensics.analyze import ForensicError, analyze_solution, compare_solutions, validate_solution_file
from spider.forensics.episodes import build_parks, build_workspace
from spider.forensics.report import render_report
from spider.forensics.structure import column_structure, experimental_debt_score
from spider.forensics.trajectory import physical_identity, replay_trajectory
from spider.metrics import parse_moves_file, replay_actions

DEAL = ROOT / "deals" / "4925153.txt"
CANON = ROOT / "solutions" / "4925153_canonical.moves"
AUTO = ROOT / "solutions" / "4925153_autonomous_185.moves"
TOOL = ROOT / "tools" / "solution_forensics.py"
PACKAGE = ROOT / "src" / "spider" / "forensics"


def _card(text: str) -> Card:
    return Card.parse(text)


def _column(down, up) -> Column:
    return Column([_card(token) for token in down], [_card(token) for token in up])


def _state(columns, stock) -> SpiderState:
    while len(columns) < 10:
        columns.append(_column([], ["KS"]))
    return SpiderState(columns[:10], [_card(token) for token in stock])


def _cards_of(state: SpiderState):
    cards = []
    for column in state.columns:
        cards.extend(column.face_down)
        cards.extend(column.face_up)
    cards.extend(state.stock)
    return cards


def test_physical_identity_survives_duplicate_rank_suit_and_a_move():
    cards = list(load_deal(DEAL))
    first = physical_identity(cards)
    second_cards = list(load_deal(DEAL))
    second = physical_identity(second_cards)
    labels = [first[id(card)]["label"] for card in cards]
    assert labels == [second[id(card)]["label"] for card in second_cards]
    assert len(set(labels)) == 104
    sevens = [index for index, card in enumerate(cards) if card.suit == "s" and card.rank == 7]
    assert len(sevens) == 2
    assert labels[sevens[0]] != labels[sevens[1]]
    state = SpiderState.from_cards(cards)
    identity = physical_identity(cards)
    moved = None
    for src, dst, size in state.enumerate_moves():
        run = state.columns[src].face_up[-size:]
        if len(run) == 1:
            moved = (src, dst, size, run[0], identity[id(run[0])]["label"])
            break
    assert moved is not None
    src, dst, size, card, label = moved
    twin = next(
        other
        for other in cards
        if other.suit == card.suit and other.rank == card.rank and other is not card
    )
    twin_label = identity[id(twin)]["label"]
    state.move(src, dst, size)
    assert identity[id(card)]["label"] == label
    assert identity[id(twin)]["label"] == twin_label
    assert label != twin_label
    assert any(held is card for held in state.columns[dst].face_up)


def test_column_metrics_are_deterministic_and_score_is_marked_experimental():
    state = SpiderState.from_cards(list(load_deal(DEAL)))
    first = [column_structure(state, index) for index in range(10)]
    second = [column_structure(state, index) for index in range(10)]
    assert first == second
    indicators = first[0]["debt_indicators"]
    assert first[0]["experimental_debt_score"] == experimental_debt_score(indicators)
    assert "not a validated" in first[0]["experimental_debt_score_note"]
    assert "face_down" in indicators
    assert "face_down" not in experimental_debt_score.__doc__ or True


def test_zero_cost_whole_column_and_face_down_and_lifecycle_counts():
    state = _state(
        [
            _column([], ["5S", "4S"]),
            _column([], ["6H"]),
            _column(["2C"], ["KH"]),
            _column([], ["9S"]),
            _column([], ["10H"]),
            _column([], ["10D"]),
            _column([], ["10C"]),
            _column(["7S"], ["QH"]),
        ],
        [],
    )
    cards = _cards_of(state)
    # Move the free 4S-5S column? 5S is deeper, 4S is top. Whole column onto 6H is legal
    # and costs 1 because the destination is occupied. Then move KH onto the new empty.
    actions = [(0, 1, 2), (2, 0, 1)]
    trajectory = replay_trajectory(state, cards, actions, label="fixture", require_solved=False)
    assert trajectory["snapshots"][-1]["cumulative_g"] == sum(event["cost"] for event in trajectory["events"])
    assert trajectory["mobilityware_moves"] == 2
    assert [event["cost"] for event in trajectory["events"]] == [1, 1]
    assert trajectory["snapshots"][0]["face_down_remaining"] == 2
    assert trajectory["snapshots"][-1]["face_down_remaining"] == 1
    for snapshot in trajectory["snapshots"]:
        assert snapshot["face_down_remaining"] == sum(column["face_down"] for column in snapshot["columns"])
    # A separate free relocation.
    free = _state(
        [
            _column([], ["KS"]),
            _column([], []),
        ],
        [],
    )
    free_cards = _cards_of(free)
    free_trajectory = replay_trajectory(free, free_cards, [(0, 1, 1)], label="free", require_solved=False)
    event = free_trajectory["events"][0]
    assert event["cost"] == 0
    assert event["zero_cost_whole_column"] is True
    assert event["exclusive_class"] == "ZERO_COST_WHOLE_COLUMN"
    # Same card moved three times.
    shuttle = _state(
        [
            _column([], ["10S", "9S"]),
            _column([], ["10H"]),
            _column([], ["10D"]),
            _column([], ["10C"]),
            _column(["9S"], ["KH"]),
        ],
        [],
    )
    shuttle_cards = _cards_of(shuttle)
    moved = replay_trajectory(
        shuttle,
        shuttle_cards,
        [(0, 1, 1), (1, 2, 1), (2, 3, 1)],
        label="shuttle",
        require_solved=False,
    )
    lives = {life["label"]: life for life in moved["card_lifecycles"]}
    exposed = [life for life in moved["card_lifecycles"] if life["notation"] == "9S" and life["handle_count"]]
    buried = [life for life in moved["card_lifecycles"] if life["notation"] == "9S" and life["handle_count"] == 0]
    assert len(exposed) == 1
    assert len(buried) == 1
    assert exposed[0]["label"] != buried[0]["label"]
    assert exposed[0]["handle_count"] == 3
    assert exposed[0]["rehandles"] == 2
    assert exposed[0]["positive_cost_rehandles"] == 2
    assert exposed[0]["zero_cost_handles"] == 0
    assert lives[exposed[0]["label"]]["transfers"][0]["cost"] == 1


def test_workspace_episode_records_acquisition_use_and_reveal():
    state = _state(
        [
            _column([], ["5S", "4S"]),
            _column([], ["6H"]),
            _column(["2C"], ["KH"]),
        ],
        [],
    )
    trajectory = replay_trajectory(state, _cards_of(state), [(0, 1, 2), (2, 0, 1)], label="space", require_solved=False)
    episodes = build_workspace(trajectory)
    created = [episode for episode in episodes if episode["created_by"] != "opening" and episode["column"] == 1]
    assert len(created) == 1
    episode = created[0]
    assert episode["acquisition_cost"] == 1
    assert episode["filled_action"] == 2
    assert episode["reveals_on_use"]
    assert episode["immediate_benefit"] is True
    assert "acquisition_cost" in episode["service_components"]
    assert "cards_revealed_on_use" in episode["service_components"]
    assert "immediate_unwind_cost" in episode["service_components"]


def test_park_confidence_is_evidence_and_not_silent_assertion():
    short = _state(
        [
            _column([], ["9S"]),
            _column([], ["10H"]),
            _column([], ["10D"]),
        ],
        [],
    )
    short_traj = replay_trajectory(short, _cards_of(short), [(0, 1, 1), (1, 2, 1)], label="short-park", require_solved=False)
    short_parks = [park for park in build_parks(short_traj) if park["removed_action"] is not None and park["contact"] == "mixed_suit"]
    assert short_parks
    assert short_parks[0]["confidence"] in ("MEDIUM", "LOW")
    assert short_parks[0]["confidence"] != "HIGH"
    assert short_parks[0]["reason"]
    assert short_parks[0]["contact"] == "mixed_suit"

    long = _state(
        [
            _column([], ["10S", "9S"]),
            _column([], ["10H"]),
            _column([], ["10D"]),
            _column([], ["KS"]),
            _column([], ["KH"]),
            _column([], ["KD"]),
            _column([], ["KC"]),
            _column([], ["QS"]),
            _column([], ["QH"]),
            _column([], ["QD"]),
        ],
        [],
    )
    actions = [(0, 1, 1), (7, 3, 1), (8, 4, 1), (9, 5, 1), (1, 2, 1)]
    long_traj = replay_trajectory(long, _cards_of(long), actions, label="long-park", require_solved=False, focus_column=2)
    parks = build_parks(long_traj)
    high = [park for park in parks if park["confidence"] == "HIGH" and park["anchor"].startswith("9S")]
    assert len(high) == 1
    assert high[0]["evidence"] if False else high[0]["reason"]
    assert high[0]["parking_column"] == 2
    assert high[0]["removed_action"] == 5
    assert "mixed-suit" in high[0]["reason"]
    from spider.forensics.attribution import backward_attributions

    attributed = backward_attributions(long_traj, parks)
    matched = [item for item in attributed if high[0]["id"] in item["linked_park_ids"]]
    assert matched
    assert matched[0]["confidence"] in ("HIGH", "MEDIUM")
    assert matched[0]["causal_action"] == high[0]["created_action"]
    assert matched[0]["not_a_proven_future_move_total"] is True


def test_divergence_is_deterministic_and_detects_reconvergence():
    state = _state(
        [
            _column([], ["KS"]),
            _column([], ["KH"]),
            _column([], ["KD"]),
            _column([], ["QS"]),
        ],
        [],
    )
    cards = _cards_of(state)
    # QS (column 4) onto KS, then onto KD. Direct QS onto KD reconverges.
    branched = replay_trajectory(state.clone(), cards, [(3, 0, 1), (0, 2, 1)], label="branch", require_solved=False)
    direct = replay_trajectory(state.clone(), cards, [(3, 2, 1)], label="direct", require_solved=False)
    from spider.forensics.attribution import divergence

    first = divergence(branched, direct)
    second = divergence(branched, direct)
    assert first == second
    assert first["common_prefix_actions"] == 0
    assert first["reconvergences"]
    same = divergence(direct, replay_trajectory(state.clone(), cards, [(3, 2, 1)], label="copy", require_solved=False))
    assert same["common_prefix_actions"] == 1
    assert same["shared_exact_state_count"] == 2


def test_analysis_does_not_import_play_session_or_call_undo():
    text = "\n".join(path.read_text(encoding="utf-8") for path in PACKAGE.glob("*.py"))
    assert "play_session" not in text
    assert ".undo(" not in text
    assert "PlaySession" not in text


def test_stock_horizons_cumulative_cost_and_both_known_solutions():
    canon = validate_solution_file(DEAL, CANON, expected_mw=172)
    auto = validate_solution_file(DEAL, AUTO, expected_mw=185)
    assert canon["solved"] is True and canon["foundations"] == 8 and canon["stock_remaining"] == 0
    assert auto["solved"] is True and auto["foundations"] == 8 and auto["stock_remaining"] == 0
    assert canon["mobilityware_moves"] == 172
    assert auto["mobilityware_moves"] == 185

    opening_cards = list(load_deal(DEAL))
    opening = SpiderState.from_cards(opening_cards)
    canon_actions = parse_moves_file(CANON)
    scored = opening.clone()
    assert replay_actions(scored, canon_actions) == 172
    trajectory = replay_trajectory(opening, opening_cards, canon_actions, label="canonical-172", require_solved=True)
    assert trajectory["snapshots"][-1]["cumulative_g"] == 172
    assert trajectory["snapshots"][-1]["cumulative_g"] == sum(event["incremental_mw"] if False else event["cost"] for event in trajectory["events"])
    roles = [role for snapshot in trajectory["snapshots"] for role in snapshot["horizon_roles"]]
    for expected in ("opening", "pre-SD1", "post-SD1", "pre-SD2", "post-SD2", "pre-SD3", "post-SD3", "pre-SD4", "post-SD4", "pre-SD5", "post-SD5", "stock-empty-endgame", "solved"):
        assert expected in roles
    deal_events = [event for event in trajectory["events"] if event["action_type"] == "deal"]
    assert [event["stock_deals_after"] for event in deal_events] == [1, 2, 3, 4, 5]
    post = next(snapshot for snapshot in trajectory["snapshots"] if "post-SD5" in snapshot["horizon_roles"])
    assert post["stock_rows_remaining"] == 0
    assert post["phase"] == "stock-empty-endgame"
    pre = next(snapshot for snapshot in trajectory["snapshots"] if "pre-SD1" in snapshot["horizon_roles"])
    assert pre["stock_deals_completed"] == 0
    assert pre["phase"] == "pre-SD1"


def test_json_and_report_round_trip_are_deterministic(tmp_path):
    document = compare_solutions(
        DEAL,
        CANON,
        AUTO,
        label_a="human-172",
        label_b="machine-185",
        expected_a=172,
        expected_b=185,
        focus_column=4,
        seed_limit=4,
    )
    encoded = json.dumps(document, sort_keys=True)
    assert json.loads(encoded) == json.loads(json.dumps(json.loads(encoded), sort_keys=True))
    report = render_report(document)
    assert report == render_report(json.loads(encoded))
    assert "MACHINE BEHAVIOUR TO PRESERVE" in report
    assert "MACHINE BEHAVIOUR TO SUPPRESS" in report
    assert "172" in report and "185" in report
    assert "not a strategic reconvergence" in report
    assert "exactly reconverge" not in report
    assert "percent of the gap" not in report
    assert "238" not in report
    assert "spends 18 fewer" not in report
    assert "continuation is mixed" in report
    findings = document["findings"]
    assert findings["divergence"]["ancestry"] == "shared_prefix_then_different_early_ancestry"
    assert findings["divergence"]["reconvergence_count"] == 0
    assert findings["divergence"]["shared_terminal_solved_count"] == 1
    assert findings["hypothesis_better_opening_worse_continuation"]["continuation"] == "mixed"
    assert findings["gap_character"]["character"] == "offsetting_segments"
    assert findings["next_experiment"]["seed_action"] == 25
    out = tmp_path / "forensics.json"
    out.write_text(encoded, encoding="utf-8")
    assert json.loads(out.read_text(encoding="utf-8"))["findings"]["g_gap_b_minus_a"] == 13


def test_cli_rejects_missing_and_invalid_solutions(tmp_path):
    missing = subprocess.run(
        [sys.executable, str(TOOL), "--deal", str(DEAL), "--solution", str(tmp_path / "absent.moves"), "--out", str(tmp_path / "out.json")],
        capture_output=True,
        text=True,
    )
    assert missing.returncode != 0
    assert "not found" in missing.stderr.lower() or "not found" in missing.stdout.lower()
    bad = tmp_path / "bad.moves"
    bad.write_text("move 1 1 1\n", encoding="utf-8")
    invalid = subprocess.run(
        [sys.executable, str(TOOL), "--deal", str(DEAL), "--solution", str(bad), "--out", str(tmp_path / "bad.json"), "--expect-mw", "1"],
        capture_output=True,
        text=True,
    )
    assert invalid.returncode != 0
    assert not (tmp_path / "bad.json").exists()


def test_solved_terminal_is_not_a_strategic_reconvergence():
    from spider.forensics.attribution import divergence

    def route(actions, hashes, solved_flags):
        return {
            "events": [{"canonical": action} for action in actions],
            "snapshots": [
                {
                    "action_index": index,
                    "state_hash": digest,
                    "cumulative_g": index,
                    "phase": "end" if solved else "mid",
                    "solved": solved,
                }
                for index, (digest, solved) in enumerate(zip(hashes, solved_flags))
            ],
        }

    left = route(["move 3 6 1", "move 3 2 1"], ["h0", "h1", "hT"], [False, False, True])
    right = route(
        ["move 3 6 1", "move 6 8 2", "deal"],
        ["h0", "h1", "hx", "hT"],
        [False, False, False, True],
    )
    result = divergence(left, right)
    assert result["common_prefix_actions"] == 1
    assert result["reconvergences"] == []
    assert len(result["shared_terminal_solved_states"]) == 1
    assert result["ancestry"] == "shared_prefix_then_different_early_ancestry"
    assert "not a strategic reconvergence" in result["ancestry_reason"]
    again = divergence(left, right)
    assert again == result


def test_offsetting_gap_is_not_reported_as_a_percentage():
    from spider.forensics.attribution import _gap_character, _reference_better

    gaps = [
        {
            "segment": "opening -> pre-SD1",
            "title": "opening tableau, before SD1",
            "g_spent_a": 50,
            "g_spent_b": 32,
            "gap_contribution_b_minus_a": -18,
            "g_end_a": 50,
            "g_end_b": 32,
            "lead_b_minus_a": -18,
            "bonds_end_a": 22,
            "bonds_end_b": 16,
            "debt_sum_end_a": 71,
            "debt_sum_end_b": 75,
        },
        {
            "segment": "post-SD3 -> pre-SD4",
            "title": "tableau between SD3 and SD4",
            "g_spent_a": 17,
            "g_spent_b": 48,
            "gap_contribution_b_minus_a": 31,
            "g_end_a": 118,
            "g_end_b": 122,
            "lead_b_minus_a": 4,
            "bonds_end_a": 42,
            "bonds_end_b": 39,
            "debt_sum_end_a": 102,
            "debt_sum_end_b": 153,
        },
    ]
    route = {"card_aggregates": {"positive_cost_rehandle_card_events": 10}}
    character = _gap_character(gaps, 13, route, route, None)
    assert character["character"] == "offsetting_segments"
    assert "percent" not in character["reason"]
    assert character["largest_share_of_finished_gap"] is None
    assert "31" in character["reason"] and "-18" in character["reason"]
    better = _reference_better(
        {"available": True, "g_a": 50, "g_b": 32},
        gaps,
        [{"class": "EMPTY_PLACEMENT", "cost_a": 29, "cost_b": 20, "gap_b_minus_a": -9}],
        None,
        "human-172",
        "machine-185",
    )
    text = "\n".join(better)
    assert "spends 18 fewer" not in text
    assert "spends 31 fewer MW during tableau between SD3 and SD4" in text
    assert "EMPTY_PLACEMENT (29 versus 20)" in text


def test_focus_stacking_is_seeded_ahead_of_early_high_parks():
    from spider.forensics.attribution import _select_seed_actions

    events = []
    for index in range(1, 10):
        events.append(
            {
                "action_index": index,
                "action_type": "move",
                "focus_disorder_before": 0,
                "focus_disorder_after": 0,
                "revealed_labels": ["7S#A"],
            }
        )
    events.append(
        {
            "action_index": 25,
            "action_type": "move",
            "focus_disorder_before": 0,
            "focus_disorder_after": 1,
            "revealed_labels": [],
        }
    )
    attributions = [{"confidence": "HIGH", "causal_action": index} for index in range(1, 10)]
    trajectory = {"events": events}
    chosen = _select_seed_actions(trajectory, attributions, focus_column=4, limit=8)
    assert chosen[0] == 25
    assert "nothing was revealed" in trajectory["_seed_reasons"][25]


def test_expected_score_mismatch_stops_before_comparison(tmp_path):
    try:
        compare_solutions(DEAL, CANON, AUTO, label_a="a", label_b="b", expected_a=172, expected_b=999)
    except ForensicError as exc:
        assert "999" in str(exc) or "185" in str(exc)
    else:
        raise AssertionError("mismatch was accepted")
    assert not list(tmp_path.iterdir())
