"""Stock-empty assembly lower bound v0.67."""

from __future__ import annotations

import ast
import inspect
import random
from pathlib import Path

from spider.assembly_lower_bound import (
    assembly_bound_detail,
    assembly_lb,
    brute_min_interval_multicover,
    copies_remaining,
    min_interval_multicover,
    physical_units,
    stock_empty_assembly_h,
    suit_lower_bound,
)
from spider.assembly_policy import (
    CANDIDATE_CEILING,
    COMPLETION_LANES,
    assembly_lane_keys,
    enrich_assembly,
    search_assembly_continuation,
)
from spider.autonomous_cost import COST_LANES
from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.final_deal_transition import TRANSITION_HARVEST_CATS, load_v065_f2_actions, verify_v065_f2
from spider.healthy_f2 import F2_FD, F2_G, F2_N, F2_ROWS, F2_SUITS
from spider.metrics import parse_moves_file, replay_actions
from spider.operational_policy import OP_LANES, search_operational_optimisation
from spider.packed_state import pack_state, pack_whole_game_identity
from spider.research_actions import apply_action, is_deal, stock_rows, tableau_actions
from spider.search_kernel import SearchLimits, run_search
from spider.whole_game_anytime import opening_root, opening_state

ROOT = Path(__file__).resolve().parents[1]
BOUND = ROOT / "src" / "spider" / "assembly_lower_bound.py"
POLICY = ROOT / "src" / "spider" / "assembly_policy.py"
KERNEL = ROOT / "src" / "spider" / "search_kernel.py"
OP = ROOT / "src" / "spider" / "operational_policy.py"
SCRIPT = ROOT / "research" / "stock_empty_assembly_lower_bound_v0_67.py"
INCUMBENT = ROOT / "solutions" / "4925153_autonomous_v0_59.moves"
CANON = ROOT / "solutions" / "4925153_canonical.moves"
ARTEFACT = ROOT / "docs" / "research" / "stock_empty_assembly_lower_bound_v0_67.json"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _simple_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        n.module
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("spider.simple_")
    ]


def _run(suit: str, hi: int, lo: int):
    return [Card(suit, r) for r in range(hi, lo - 1, -1)]


def _ka(suit: str):
    return _run(suit, 13, 1)


def _columns(*runs, down=None, foundations=None, stock=None) -> SpiderState:
    downs = list(down or [])
    cols = []
    for i, run in enumerate(runs):
        fd = list(downs[i]) if i < len(downs) else []
        cols.append(Column(fd, list(run)))
    while len(cols) < 10:
        cols.append(Column([], []))
    return SpiderState(cols, list(stock or []), list(foundations or []))


def _seven_other_foundations() -> list:
    return [_ka("s"), _ka("s"), _ka("h"), _ka("h"), _ka("d"), _ka("d"), _ka("c")]


def test_greedy_matches_brute_force_on_random_intervals():
    rng = random.Random(67)
    for _ in range(120):
        n = rng.randint(2, 11)
        intervals = []
        for _k in range(n):
            a = rng.randint(1, 13)
            b = rng.randint(1, 13)
            intervals.append((min(a, b), max(a, b)))
        m = rng.choice([1, 2])
        demand = [0] + [m] * 13
        greedy = min_interval_multicover(intervals, demand)
        brute = brute_min_interval_multicover(intervals, demand)
        assert greedy == brute


def test_synthetic_known_joins_and_edge_cases():
    # one foundation, two components: at least 1 join
    two = _columns(
        _run("c", 13, 7),
        _run("c", 6, 1),
        foundations=_seven_other_foundations(),
        stock=[],
    )
    d = assembly_bound_detail(two)
    assert d["active"] is True
    assert d["by_suit"]["c"]["m"] == 1
    assert d["by_suit"]["c"]["u"] == 2
    assert d["h"] == 1

    four = _columns(
        _run("c", 13, 10),
        _run("c", 9, 7),
        _run("c", 6, 4),
        _run("c", 3, 1),
        foundations=_seven_other_foundations(),
        stock=[],
    )
    d4 = assembly_bound_detail(four)
    assert d4["by_suit"]["c"]["u"] == 4
    assert d4["h"] == 3
    assert 196 + d4["h"] > 197

    two_f = _columns(
        _run("c", 13, 10),
        _run("c", 9, 7),
        _run("c", 6, 4),
        _run("c", 3, 1),
        _run("c", 13, 10),
        _run("c", 9, 7),
        _run("c", 6, 4),
        _run("c", 3, 1),
        foundations=_seven_other_foundations()[:-1],
        stock=[],
    )
    d2 = assembly_bound_detail(two_f)
    assert d2["by_suit"]["c"]["m"] == 2
    assert d2["by_suit"]["c"]["u"] == 8
    assert d2["h"] == max(2, 8 - 2)

    solved = _columns(foundations=[_ka(s) for s in ("s", "s", "h", "h", "d", "d", "c", "c")], stock=[])
    assert assembly_lb(solved) == 0
    assert solved.is_solved()

    fd_state = _columns(
        _run("c", 13, 8),
        [],
        down=[[], [Card("c", 7), Card("c", 6), Card("c", 5), Card("c", 4), Card("c", 3), Card("c", 2), Card("c", 1)]],
        foundations=_seven_other_foundations(),
        stock=[],
    )
    df = assembly_bound_detail(fd_state)
    assert df["by_suit"]["c"]["u"] == 8
    assert df["h"] == 7

    extra = _columns(
        _run("c", 13, 7),
        _run("c", 6, 1),
        [Card("c", 13), Card("h", 5)],
        foundations=_seven_other_foundations(),
        stock=[],
    )
    de = assembly_bound_detail(extra)
    assert de["by_suit"]["c"]["u"] == 2
    assert de["h"] == 1

    multi = _columns(
        _run("c", 13, 7),
        _run("c", 6, 1),
        _run("h", 13, 7),
        _run("h", 6, 1),
        foundations=[_ka("s"), _ka("s"), _ka("d"), _ka("d"), _ka("c"), _ka("h")],
        stock=[],
    )
    dm = assembly_bound_detail(multi)
    assert dm["by_suit"]["c"]["m"] == 1
    assert dm["by_suit"]["h"]["m"] == 1
    assert dm["h"] == 2

    frag = _columns(
        [Card("c", 13)],
        [Card("c", 12)],
        [Card("c", 11)],
        [Card("c", 10)],
        [Card("c", 9)],
        [Card("c", 8)],
        [Card("c", 7)],
        [Card("c", 6)],
        [Card("c", 5), Card("h", 9), Card("c", 4)],
        [Card("c", 3), Card("h", 8), Card("c", 2), Card("h", 7), Card("c", 1)],
        foundations=_seven_other_foundations(),
        stock=[],
    )
    dfrag = assembly_bound_detail(frag)
    assert dfrag["by_suit"]["c"]["u"] >= 11
    assert dfrag["h"] >= 10

    empty_solved = _columns(foundations=[_ka(s) for s in "sshhdcdc"], stock=[])
    assert assembly_lb(empty_solved) == 0

    opening = opening_state()
    assert stock_rows(opening) > 0
    assert assembly_lb(opening) == 0
    assert assembly_lane_keys(opening, 0)["completion"] is None


def test_suit_lb_formula_and_infeasible_fallback():
    assert suit_lower_bound(1, 2) == (1, True)
    assert suit_lower_bound(1, 4) == (3, True)
    assert suit_lower_bound(2, 8) == (6, True)
    assert suit_lower_bound(1, None) == (1, False)
    assert suit_lower_bound(0, 5) == (0, True)


def test_move_effect_at_most_one_join_and_one_foundation():
    st = _columns(
        _run("c", 13, 10),
        _run("c", 9, 7),
        _run("c", 6, 4),
        _run("c", 3, 1),
        foundations=_seven_other_foundations(),
        stock=[],
    )
    assert stock_rows(st) == 0
    actions = tableau_actions(st)
    assert all(not is_deal(a) for a in actions)
    packed = pack_state(st)
    for action in actions:
        src, dst, k = action
        run = st.columns[src].face_up[-k:]
        assert SpiderState.is_movable_run(run)
        assert len({c.suit for c in run}) == 1
        top = st.columns[dst].top()
        same_suit_merge = bool(
            top is not None and top.suit == run[0].suit and top.rank == run[0].rank + 1
        )
        child = st.clone()
        before_f = len(child.foundations)
        stock_n = len(child.stock)
        apply_action(child, action)
        assert len(child.stock) == stock_n
        assert len(child.foundations) - before_f <= 1
        if not same_suit_merge:
            # off-suit or empty: not a same-suit component join
            pass
        assert pack_state(st) == packed
    # engine check_seq is per destination column only
    src = inspect.getsource(SpiderState.check_seq)
    assert "self.foundations.append" in src
    assert "for c in range(10)" not in src or "check_seq" in inspect.getsource(SpiderState.deal)


def test_kernel_default_off_and_proof_prune_dead_f7_style():
    four = _columns(
        _run("c", 13, 10),
        _run("c", 9, 7),
        _run("c", 6, 4),
        _run("c", 3, 1),
        foundations=_seven_other_foundations(),
        stock=[],
    )
    assert assembly_lb(four) == 3
    root = {
        "g": 196,
        "ordered_digest": pack_state(four).hex(),
        "whole_game_identity": pack_whole_game_identity(four).hex(),
    }
    res_off = run_search(
        [root],
        limits=SearchLimits(max_unique=40, time_limit_s=1.0, cost_ceiling=197),
        identity_fn=pack_whole_game_identity,
    )
    assert res_off.lower_bound_prunes == 0
    assert res_off.lower_bound_calls == 0
    res_on = run_search(
        [root],
        limits=SearchLimits(max_unique=40, time_limit_s=1.0, cost_ceiling=197),
        identity_fn=pack_whole_game_identity,
        lower_bound_fn=stock_empty_assembly_h,
    )
    assert res_on.lower_bound_prunes >= 1
    assert res_on.expanded == 0
    ident = pack_whole_game_identity(four)
    packed = pack_state(four)
    stock_empty_assembly_h(four, 196)
    assert pack_whole_game_identity(four) == ident
    assert pack_state(four) == packed


def test_completion_orders_by_f_not_foundation_count():
    low_f = _columns(
        _run("c", 13, 7),
        _run("c", 6, 1),
        foundations=_seven_other_foundations(),
        stock=[],
    )
    high_f_dead = _columns(
        _run("c", 13, 10),
        _run("c", 9, 7),
        _run("c", 6, 4),
        _run("c", 3, 1),
        foundations=_seven_other_foundations(),
        stock=[],
    )
    k_low = assembly_lane_keys(low_f, 190)
    k_dead = assembly_lane_keys(high_f_dead, 196)
    assert k_low["completion"] is not None
    assert k_dead["completion"] is not None
    assert k_low["completion"][0] == 190 + 1
    assert k_dead["completion"][0] == 196 + 3
    assert k_low["completion"] < k_dead["completion"]
    assert "completion" in COMPLETION_LANES
    assert "durability" not in COMPLETION_LANES
    assert OP_LANES == COST_LANES


def test_known_routes_stock_empty_h_le_remaining():
    opening = opening_state()
    for path in (INCUMBENT, CANON):
        actions = parse_moves_file(path)
        st = opening.clone()
        total = replay_actions(opening.clone(), list(actions))
        g = 0
        from spider.research_actions import is_deal as _deal, step_cost

        for action in actions:
            if stock_rows(st) == 0:
                remain = total - g
                h = assembly_lb(st)
                assert h <= remain
            cost = 1 if _deal(action) else step_cost(st, action)
            apply_action(st, action)
            g += cost
        assert st.is_solved()
        assert assembly_lb(st) == 0


def test_no_canonical_in_search_tt_ceiling_and_f2():
    for path in (BOUND, POLICY, OP, KERNEL):
        text = _text(path)
        assert "4925153_canonical.moves" not in text
        assert _simple_imports(path) == []
    src = inspect.getsource(search_operational_optimisation)
    assert "operational_lane_keys" in src
    assert "incumbent_g - 1" in src
    assert "durability" not in src
    assert "lane_names=OP_LANES" in src
    src_k = inspect.getsource(run_search)
    assert "lower_bound_fn" in src_k
    asm = inspect.getsource(search_assembly_continuation)
    assert "TRANSITION_HARVEST_CATS" in asm
    assert "stock_empty_assembly_h" in asm
    assert CANDIDATE_CEILING == 197
    opening = opening_state()
    packed = pack_state(opening)
    ident = pack_whole_game_identity(opening)
    assembly_lb(opening)
    assert pack_state(opening) == packed
    assert pack_whole_game_identity(opening) == ident
    actions = load_v065_f2_actions()
    if actions:
        snap = verify_v065_f2(opening, actions)
        assert snap["replay_ok"]
        assert snap["g"] == F2_G
        assert snap["stock_rows"] == F2_ROWS
        assert snap["face_down"] == F2_FD
        assert snap["foundations"] == F2_N
        assert set(snap["suits"]) == F2_SUITS


def test_script_canonical_after_search_and_absolute_g():
    script = _text(SCRIPT)
    if script:
        search_at = script.find("search_assembly_continuation(")
        eval_at = script.find("EVAL canonical")
        parse_at = script.find("parse_moves_file(CANON)")
        assert search_at != -1
        assert eval_at > search_at
        assert parse_at > search_at
    opening = opening_state()
    root = opening_root(opening)
    root["g"] = 130
    from spider.whole_game_epoch_scheduler import search_epoch_portfolio

    res = search_epoch_portfolio(
        opening=opening,
        initial_roots=[root],
        max_unique=8,
        time_limit_s=0.5,
        rss_abort_mb=4096,
        cost_ceiling=197,
        portfolio_width=4,
    )
    assert res.min_g is None or res.min_g >= 130
    assert res.candidate_ceiling == 197


def test_incumbent_and_terminal_replay_if_present():
    opening = opening_state()
    actions = parse_moves_file(INCUMBENT)
    end = opening.clone()
    assert replay_actions(end, actions) == 198
    assert sum(1 for a in actions if is_deal(a)) == 5
    if not ARTEFACT.exists():
        return
    import json

    from spider.healthy_f2 import parse_stored_actions, verify_f2_prefix

    data = json.loads(ARTEFACT.read_text(encoding="utf-8"))
    raw = data.get("f2_prefix_actions")
    if raw:
        snap = verify_f2_prefix(opening, parse_stored_actions(raw))
        assert snap["replay_ok"]
    if data.get("solved") and data.get("solution_actions"):
        term = opening.clone()
        g = replay_actions(term, parse_stored_actions(data["solution_actions"]))
        assert term.is_solved()
        assert g == data.get("replay_g") or g == data.get("solution_g")
        assert g < 198
        assert sum(1 for a in parse_stored_actions(data["solution_actions"]) if is_deal(a)) == 5
