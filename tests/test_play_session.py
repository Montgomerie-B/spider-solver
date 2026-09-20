"""Play Lab acceptance and persistence failure tests; no production data touched."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal, stock_deal_rounds
from spider.engine import Column, SpiderState
from spider.metrics import parse_moves_file, replay_actions_detailed
from spider.play_render import column_cards, movable_count
from spider.play_session import AutosaveError, PlaySession, apply_action, state_digest
from spider.solution_archive import validate_solution
from spider.state_identity import canonical_state_key

DEAL = ROOT / "deals/4925153.txt"
SOLUTION = ROOT / "solutions/4925153_canonical.moves"


@pytest.fixture
def session(tmp_path):
    return PlaySession.from_deal(DEAL, path=tmp_path / "session.json")


def test_fresh_deal_and_snapshot_isolation(session):
    expected = SpiderState.from_cards(load_deal(DEAL))
    assert canonical_state_key(session.state) == canonical_state_key(expected)
    assert session.node.face_down == 44
    assert session.node.stock_deals == session.node.g == 0
    changed = session.state
    changed.deal()
    assert len(session.state.stock) == 50


def test_import_next_previous_exact(session):
    actions = parse_moves_file(SOLUTION)
    session.load_solution(SOLUTION)
    root = state_digest(session.state)
    session.next()
    assert session.actions() == actions[:1]
    expected = SpiderState.from_cards(load_deal(DEAL))
    cost = apply_action(expected, actions[0])
    assert session.node.g == cost
    assert session.node.state_hash == state_digest(expected)
    session.undo()
    assert state_digest(session.state) == root
    session.next()
    assert session.node.state_hash == state_digest(expected)


def test_branch_preserves_replay_parent(session, tmp_path):
    route_id = session.load_solution(SOLUTION)
    for _ in range(36):
        session.next()
    parent = session.current
    route = list(session.routes[route_id]["nodes"])
    expected = session.expected_action()
    different = next(a for a in session.state.enumerate_legal_actions() if a != expected)
    session.act(different)
    branch = session.current
    assert session.route_position()[1:] == (36, True)
    assert session.routes[route_id]["nodes"] == route
    assert session.actions() == parse_moves_file(SOLUTION)[:36] + [different]
    session.undo()
    assert session.current == parent
    assert len(session.children[parent]) >= 2
    session.next()  # Replay next explicitly follows the original route.
    assert session.current == route[37]
    session.goto(branch)
    session.export(tmp_path / "branch.moves")
    assert parse_moves_file(tmp_path / "branch.moves") == session.actions()


def test_undo_redo_different_move_and_exact_export(session, tmp_path):
    choices = session.state.enumerate_legal_actions()
    session.act(choices[0])
    old = session.current
    session.undo()
    assert session.actions() == []
    session.act(choices[1])
    new = session.current
    assert old in session.nodes and new in session.nodes
    session.undo()
    session.redo(old)
    assert session.actions() == [choices[0]]
    session.undo()
    session.redo(new)
    report = session.export(tmp_path / "line.moves")
    assert parse_moves_file(tmp_path / "line.moves") == [choices[1]]
    assert report["explicit_commands"] == 1
    assert "undo" not in (tmp_path / "line.moves").read_text()
    assert PlaySession.load(tmp_path / "line.json").actions() == [choices[1]]


def test_full_tree_reload_mw_cost_and_navigation_autosaved(session):
    session.load_solution(SOLUTION)
    for _ in range(40):
        session.next()
    session.act(("deal",))
    session.undo()
    recovered = PlaySession.load(session.path)
    assert recovered.current == session.current
    assert recovered.nodes == session.nodes
    assert recovered.routes == session.routes
    assert recovered.preferred == session.preferred
    assert recovered.node.g == session.node.g
    assert canonical_state_key(recovered.state) == canonical_state_key(session.state)
    expected_child = session.preferred[session.current]
    recovered.redo()
    assert recovered.node == session.nodes[expected_child]


def test_analysis_cards_never_unlock_hidden(session):
    for col, column in enumerate(session.state.columns):
        normal = column_cards(column, False)
        analysis = column_cards(column, True)
        assert len(normal) == len(analysis)
        for a, b in zip(normal, analysis):
            if a.locked:
                assert a.card is None and b.card is not None
                assert b.locked and b.anchor is None
                assert movable_count(session.state, col, b.anchor) == 0
        assert not session.state.can_move(col, (col+1)%10, len(column.face_up)+1)


def test_every_future_stock_round_matches_engine(session):
    original = stock_deal_rounds(session.state.stock)
    assert [str(c) for c in original[0]] == "Js 9d 4d Kh 4d 6d 9s 7d 8s 5c".split()
    for number in range(1, 6):
        future = session.future_stock()
        assert [n for n, _ in future] == list(range(number, 6))
        assert future[0][1] == original[number-1]
        session.act(("deal",))
        assert session.state.top_row() == original[number-1]
    assert session.future_stock() == []


def test_empty_column_deal_uses_mw_rules():
    state = SpiderState([Column([], []) for _ in range(10)], [Card("s", 7)]*10)
    assert apply_action(state, ("deal",)) == 1
    assert all(c.top() == Card("s", 7) for c in state.columns)


def test_engine_flip_and_removal_through_session_adapter():
    columns = [Column([], []) for _ in range(10)]
    columns[0] = Column([Card("h", 7)], [Card("s", 1)])
    columns[1] = Column([Card("d", 3)], [Card("s", r) for r in range(13, 1, -1)])
    state = SpiderState(columns, [])
    assert apply_action(state, (0, 1, 1)) == 1
    assert state.columns[0].face_up == [Card("h", 7)]
    assert state.columns[1].face_up == [Card("d", 3)]
    assert len(state.foundations) == 1
    assert len(state.foundations[0]) == 13


def test_same_suit_anchor_uses_exact_tail_length():
    columns = [Column([], []) for _ in range(10)]
    columns[0] = Column([], [Card("h", 8), Card("s", 7), Card("s", 6), Card("s", 5)])
    state = SpiderState(columns, [])
    assert movable_count(state, 0, 0) == 0
    assert movable_count(state, 0, 1) == 3
    assert movable_count(state, 0, 2) == 2
    assert movable_count(state, 0, 3) == 1


def test_known_solution_step_full_and_independent_solved_branch(session, tmp_path):
    session.load_solution(SOLUTION)
    actions = parse_moves_file(SOLUTION)
    for action in actions:
        assert session.expected_action() == action
        session.next()
    assert session.node.g == 172
    assert session.node.ordinal == 174
    assert session.state.is_solved()
    # Add a genuine divergent detour at a state with a reversible legal relocation.
    for node_id in session.routes[session.active_route]["nodes"][:-1]:
        state = session._states[node_id]
        detour = None
        for action in state.enumerate_moves():
            clone = state.clone()
            clone.move(*action)
            reverse = (action[1], action[0], action[2])
            if clone.can_move(*reverse):
                clone.move(*reverse)
                if canonical_state_key(clone) == canonical_state_key(state):
                    detour = action, reverse
                    break
        if detour:
            break
    assert detour is not None
    session.goto(node_id)
    start = session.node.ordinal
    session.act(detour[0])
    session.act(detour[1])
    for action in actions[start:]:
        session.act(action)
    assert session.state.is_solved()
    assert session.route_position()[2]
    output = tmp_path / "solved_branch.moves"
    report = session.export(output)
    assert report["solved"] and report["verified"]
    independent = validate_solution("4925153", output)
    assert independent.valid
    assert independent.mobilityware_moves == session.node.g == report["mobilityware_moves"]
    assert independent.explicit_commands == 176


def test_invalid_import_is_transactional(session, tmp_path):
    bad = tmp_path / "bad.moves"
    first = parse_moves_file(SOLUTION)[0]
    from spider.metrics import format_action
    bad.write_text(format_action(first) + "\nmove 1 1 1\n")
    before = session.path.read_bytes()
    with pytest.raises(ValueError, match="action 2"):
        session.load_solution(bad)
    assert len(session.nodes) == 1
    assert session.path.read_bytes() == before


def test_illegal_action_is_never_recorded(session):
    before = session.path.read_bytes()
    with pytest.raises(ValueError):
        session.act((0, 0, 1))
    assert len(session.nodes) == 1
    assert session.path.read_bytes() == before


def test_partial_and_empty_solution_import(session, tmp_path):
    partial = tmp_path / "partial.moves.txt"
    partial.write_text("# partial route\ndeal\n")
    session.load_solution(partial)
    session.next()
    assert session.node.stock_deals == 1
    empty = tmp_path / "empty.moves"
    empty.write_text("# root checkpoint\n")
    session.load_solution(empty)
    assert session.current == session.root


@pytest.mark.parametrize("field,value", [("g", 999), ("cost", 99), ("state_hash", "corrupt"),
                                         ("face_down", 0), ("ordinal", 5)])
def test_corruption_detected_on_replay(session, field, value):
    session.act(("deal",))
    data = json.loads(session.path.read_text())
    data["nodes"][-1][field] = value
    session.path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="integrity"):
        PlaySession.load(session.path)


def test_save_failure_keeps_memory_and_last_good_disk(session, monkeypatch, tmp_path):
    import spider.play_session as module
    original = module.atomic_write
    disk = session.path.read_bytes()
    def fail(*args):
        raise OSError("disk full")
    monkeypatch.setattr(module, "atomic_write", fail)
    with pytest.raises(AutosaveError, match="disk full"):
        session.act(("deal",))
    assert session.node.ordinal == 1 and session.dirty
    assert session.path.read_bytes() == disk
    with pytest.raises(AutosaveError):
        session.undo()
    monkeypatch.setattr(module, "atomic_write", original)
    session.save(tmp_path / "recovery.json")
    assert PlaySession.load(session.path).node.ordinal == 1
    assert not session.dirty


def test_concurrent_window_cannot_overwrite_newer_work(session, tmp_path):
    other = PlaySession.load(session.path)
    session.act(("deal",))
    with pytest.raises(AutosaveError, match="another window"):
        other.act(other.state.enumerate_moves()[0])
    assert PlaySession.load(session.path).actions() == [("deal",)]
    other.save(tmp_path / "other-recovery.json")
    assert PlaySession.load(other.path).actions() == other.actions()


def test_backup_is_valid_previous_state(session):
    session.act(("deal",))
    backup = PlaySession.load(session.path.with_suffix(".json.bak"))
    assert backup.node.ordinal == 0


def test_export_failure_detects_mw_tamper(session, tmp_path):
    from dataclasses import replace
    session.act(("deal",))
    session.nodes[session.current] = replace(session.node, g=99)
    with pytest.raises(ValueError, match="FAILED"):
        session.export(tmp_path / "bad.moves")
    assert not (tmp_path / "bad.moves").exists()


def test_export_cannot_clobber_session(session):
    with pytest.raises(ValueError, match="different"):
        session.export(session.path.with_suffix(".moves"))


def test_multiple_routes_preserved_after_reload(session, tmp_path):
    first = session.load_solution(SOLUTION)
    partial = tmp_path / "stock.moves"
    partial.write_text("deal\n")
    second = session.load_solution(partial)
    recovered = PlaySession.load(session.path)
    assert set(recovered.routes) == {first, second}
    assert recovered.active_route == second
    recovered.last()
    assert recovered.actions() == [("deal",)]


def test_export_rejects_non_moves_extension(session, tmp_path):
    with pytest.raises(ValueError, match="filename"):
        session.export(tmp_path / "output.json")
    assert not (tmp_path / "output.json").exists()


def test_writer_lock_preserves_unsaved_action(session):
    from spider.play_session import writer_lock
    with writer_lock(session.path):
        with pytest.raises(AutosaveError):
            session.act(("deal",))
    assert session.dirty and session.node.ordinal == 1
    session.save()
    assert PlaySession.load(session.path).node.ordinal == 1
