"""Human-research workflow and deterministic visual input-gate acceptance tests."""
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from spider.play_session import PlaySession, state_digest
from spider.play_controller import PlayController, SPEEDS
from spider.play_render import SpiderBoard, future_cards
from spider.metrics import format_action, parse_moves_file
from spider.solution_archive import validate_solution

DEAL = ROOT / "deals/4925153.txt"
ROUTE = ROOT / "solutions/4925153_canonical.moves"


@pytest.fixture
def session(tmp_path):
    return PlaySession.from_deal(DEAL, path=tmp_path / "lab.json")


def test_campaign_origin_recovery_and_parent_preserved(session):
    route_id = session.load_solution(ROUTE)
    origin = session.routes[route_id]["nodes"][36]
    session.goto(origin)
    route = list(session.routes[route_id]["nodes"])
    before, g = session.actions(), session.node.g
    cid = session.start_campaign("After SD1 experiment")
    assert session.campaign == {
        "name": "After SD1 experiment", "origin_node": origin, "origin_action": 36,
        "origin_g": g, "parent_route": route_id, "parent_solution": ROUTE.name,
        "parent_path": str(ROUTE), "parent_campaign": None,
        "created": session.campaign["created"], "current_node": origin,
    }
    assert session.actions() == before
    assert session.routes[route_id]["nodes"] == route
    assert session.expected_action() is None
    recovered = PlaySession.load(session.path)
    assert recovered.active_campaign == cid
    assert recovered.campaigns == session.campaigns
    assert recovered.clean_record() == session.clean_record()
    assert recovered.node.state_hash == session.node.state_hash


@pytest.mark.parametrize("position", [0, 1, 34, 174])
def test_campaign_can_start_at_any_replay_state(session, position):
    rid = session.load_solution(ROUTE)
    session.goto(session.routes[rid]["nodes"][position])
    session.start_campaign()
    assert session.campaign["origin_action"] == position
    assert session.campaign["origin_g"] == session.node.g


def test_manual_and_child_campaign_switching(session):
    parent = session.start_campaign("Opening")
    session.act(("deal",))
    parent_tip = session.current
    child = session.start_campaign("Child")
    assert session.campaign["parent_campaign"] == parent
    assert session.campaign["origin_action"] == 1
    assert session.campaign["parent_solution"] is None
    session.act(session.state.enumerate_moves()[0])
    child_tip = session.current
    session.select_campaign(parent)
    assert session.current == parent_tip
    session.select_campaign(child)
    assert session.current == child_tip
    restored = PlaySession.load(session.path)
    assert restored.current == child_tip and restored.active_campaign == child


def test_clean_record_undo_alternatives_redo_export_recovery(session, tmp_path):
    session.start_campaign("Manual exploration")
    choices = session.state.enumerate_moves()
    a, c = choices[:2]
    session.act(a)
    aid = session.current
    b = session.state.enumerate_legal_actions()[-1]
    session.act(b)
    bid = session.current
    session.undo()
    assert [n.action for n in session.clean_record()] == [format_action(a)]
    assert bid in session.nodes
    session.undo()
    assert session.clean_record() == []
    session.act(c)
    cid = session.current
    assert aid in session.children[session.root] and cid in session.children[session.root]
    session.goto(bid)
    assert [n.action for n in session.clean_record()] == [format_action(a), format_action(b)]
    session.undo()
    session.redo(bid)
    assert session.current == bid
    session.goto(cid)
    output = tmp_path / "clean.moves"
    session.export(output)
    assert [format_action(a) for a in parse_moves_file(output)] == [n.action for n in session.clean_record()]
    assert PlaySession.load(session.path).clean_record() == session.clean_record()
    assert PlaySession.load(output.with_suffix(".json")).campaigns == session.campaigns


def test_campaign_next_follows_selected_human_child_not_parent_replay(session):
    rid = session.load_solution(ROUTE)
    session.goto(session.routes[rid]["nodes"][1])
    expected = session.expected_action()
    session.start_campaign("Try another move")
    different = next(a for a in session.state.enumerate_legal_actions() if a != expected)
    session.act(different)
    tip = session.current
    session.undo()
    session.next()
    assert session.current == tip
    cid = session.active_campaign
    session.select_route(rid)
    assert session.active_campaign is None
    session.select_campaign(cid)
    assert session.current == tip


def test_old_v103_sessions_migrate_without_changing_history(session):
    session.act(("deal",))
    data = json.loads(session.path.read_text())
    data["version"] = 1
    del data["campaigns"], data["active_campaign"]
    session.path.write_text(json.dumps(data))
    recovered = PlaySession.load(session.path)
    assert recovered.campaigns == {} and recovered.active_campaign is None
    assert recovered.nodes == session.nodes
    recovered.start_campaign("Upgraded session")
    assert json.loads(recovered.path.read_text())["version"] == 2


@pytest.mark.parametrize("field,value", [("origin_g", 999), ("origin_action", 42),
                                         ("origin_node", "missing"), ("parent_path", "bad")])
def test_campaign_metadata_is_replay_checked(session, field, value):
    cid = session.start_campaign("Checked")
    data = json.loads(session.path.read_text())
    data["campaigns"][cid][field] = value
    session.path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="campaign"):
        PlaySession.load(session.path)


class FakeView:
    def __init__(self):
        self.transitions = []
        self.refreshes = []

    def animate(self, before, after, action, duration, done):
        self.transitions.append((state_digest(before), state_digest(after), action, duration))
        self.done = done

    def refresh(self, **kwargs):
        self.refreshes.append(kwargs)


@pytest.mark.parametrize("speed", list(SPEEDS))
def test_replay_speed_applies_one_authoritative_action_before_visuals(session, speed):
    session.load_solution(ROUTE)
    view = FakeView()
    controller = PlayController(session, view.animate, view.refresh)
    controller.speed = speed
    assert controller.run(session.next)
    assert session.node.ordinal == 1
    assert session.actions() == parse_moves_file(ROUTE)[:1]
    assert PlaySession.load(session.path).node == session.node  # durable before visuals finish
    if speed == "Instant":
        assert not controller.busy and not view.transitions
    else:
        assert controller.busy
        assert view.transitions[0][3] == SPEEDS[speed]
        view.done()
    assert not controller.busy


def test_rapid_next_and_conflicting_inputs_are_ignored_not_queued(session):
    session.load_solution(ROUTE)
    view = FakeView()
    controller = PlayController(session, view.animate, view.refresh)
    controller.run(session.next)
    node = session.current
    for _ in range(20):
        assert not controller.run(session.next)
        assert not controller.run(session.undo)
        assert not controller.run(lambda: session.act(("deal",)))
    assert session.current == node and session.node.ordinal == 1
    view.done()
    controller.run(session.undo)
    assert session.node.ordinal == 0 and not controller.busy
    controller.run(session.redo)
    assert session.current == node
    view.done()


def test_last_is_instant_and_illegal_action_releases_gate(session):
    session.load_solution(ROUTE)
    view = FakeView()
    controller = PlayController(session, view.animate, view.refresh)
    with pytest.raises(ValueError):
        controller.run(lambda: session.act((0, 0, 1)))
    assert not controller.busy
    controller.run(session.last, animated=False)
    assert session.state.is_solved() and session.node.g == 172
    assert not view.transitions and not controller.busy


def test_future_card_views_exact_order_and_unavailable(session):
    for number in range(1, 6):
        shown = future_cards(session.state, True)
        concealed = future_cards(session.state, False)
        assert [n for n, _ in shown] == list(range(number, 6))
        assert [n for n, _ in concealed] == list(range(number, 6))
        assert [[d.card for d in row] for _, row in shown] == [cards for _, cards in session.future_stock()]
        assert all(d.card is None and d.locked and d.anchor is None for _, row in concealed for d in row)
        assert all(d.card is not None and d.locked and d.anchor is None for _, row in shown for d in row)
        session.act(("deal",))
    assert future_cards(session.state, True) == []


def test_completed_named_branch_verifies_and_preserves_origin(session, tmp_path):
    rid = session.load_solution(ROUTE)
    ids = session.routes[rid]["nodes"]
    session.goto(ids[-2])
    session.start_campaign("Finish experiment")
    session.act(parse_moves_file(ROUTE)[-1])
    output = tmp_path / "named-solved.moves"
    result = session.export(output)
    assert result["solved"] and result["mobilityware_moves"] == 172
    assert validate_solution("4925153", output).valid
    recovered = PlaySession.load(output.with_suffix(".json"))
    assert recovered.campaign["origin_action"] == 173
    assert recovered.clean_record() == session.clean_record()


@pytest.fixture(scope="module")
def tk_app(tmp_path_factory):
    # One Tk interpreter per process, just like the real desktop application.
    from play_lab import PlayLab
    initial = PlaySession.from_deal(DEAL, path=tmp_path_factory.mktemp("tk") / "initial.json")
    app = PlayLab(initial)
    app.withdraw()
    yield app
    app.board.cancel_transition()
    app.destroy()


@pytest.fixture
def board(session, tk_app):
    root = tk_app
    board = SpiderBoard(root, lambda *a: None, lambda: None, lambda text: None,
                        width=1100, height=700)
    board.pack()
    root.update_idletasks()
    board.update_session(session, True)
    yield root, board
    board.cancel_transition()
    board.destroy()


def test_canvas_transition_moves_sprites_and_resize_cancels_safely(session, board):
    root, canvas = board
    session.load_solution(ROUTE)
    controller = PlayController(session, canvas.animate, lambda **kw: None)
    canvas.input_blocked = lambda: controller.busy
    controller.run(session.next)
    assert controller.busy and canvas.find_withtag("transition")
    initial = canvas.bbox("transition")
    time.sleep(.14)
    root.update()
    assert canvas.bbox("transition") != initial
    current = session.current
    canvas.resized()
    assert not controller.busy and not canvas.find_withtag("transition")
    assert canvas._display_state is None and session.current == current
    assert session.node.ordinal == 1


def test_canvas_stock_animation_and_future_hit_testing(session, board):
    root, canvas = board
    calls = []
    canvas.on_move = lambda *args: calls.append(args)
    canvas.selected = (0, 1)
    assert canvas.destination(canvas.left + canvas.cw/2, canvas.tableau_bottom+60) is None
    assert canvas.hit(canvas.left + canvas.cw/2, canvas.tableau_bottom+60) is None
    controller = PlayController(session, canvas.animate, lambda **kw: None)
    controller.speed = "Fast"
    canvas.input_blocked = lambda: controller.busy
    controller.run(lambda: session.act(("deal",)))
    assert len([tag for tag in range(10) if canvas.find_withtag(f"sprite_{tag}")]) == 10
    from types import SimpleNamespace
    canvas.down(SimpleNamespace(x=canvas.left+10, y=canvas.top+10))
    assert calls == []
    deadline = time.monotonic()+2
    while controller.busy and time.monotonic()<deadline:
        root.update()
        time.sleep(.01)
    assert not controller.busy and session.node.stock_deals == 1
    assert canvas._display_state is None


def test_live_recorder_refreshes_from_lineage(session, tk_app):
    app = tk_app
    app.session = session
    app.refresh()
    app.speed.set("Instant")
    app.change_speed()
    try:
        actions = session.state.enumerate_moves()
        app.perform(actions[0])
        first = session.current
        assert app.recorder.item(first, "values")[2] == format_action(actions[0])
        app.navigate("undo")
        assert not app.recorder.get_children()
        assert app.history.exists(first)
        app.perform(actions[1])
        assert len(app.recorder.get_children()) == 1
        assert not app.recorder.exists(first) and app.history.exists(first)
        session.start_campaign("Recorder origin")
        app.refresh()
        assert app.recorder.exists("origin")
        assert "BRANCH CAMPAIGN" in app.replay.get()
    finally:
        app.board.cancel_transition()
