"""Whole-game anytime baseline v0.58."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
from spider.packed_state import (
    PACKED_MAGIC,
    PACKED_SYMMETRY_MAGIC,
    pack_post_stock_symmetry_state,
    pack_state,
    pack_whole_game_identity,
    permute_tableau_columns,
)
from spider.research_actions import (
    all_legal_actions,
    apply_action,
    capture_state,
    restore_state,
    step_cost,
    stock_rows,
    tableau_actions,
)
from spider.rules import MW_RULES, deal_cost
from spider.search_kernel import SearchLimits, run_search
from spider.structural_analysis import current_tableau_summary
from spider.whole_game_anytime import (
    LANES,
    choose_verdict,
    lane_keys,
    opening_root,
    opening_state,
    search_whole_game,
)

ROOT = Path(__file__).resolve().parents[1]
GENERIC = (
    ROOT / "src" / "spider" / "research_actions.py",
    ROOT / "src" / "spider" / "research_roots.py",
    ROOT / "src" / "spider" / "search_kernel.py",
    ROOT / "src" / "spider" / "structural_analysis.py",
    ROOT / "src" / "spider" / "packed_state.py",
    ROOT / "src" / "spider" / "whole_game_anytime.py",
)
ADAPTER = ROOT / "src" / "spider" / "whole_game_anytime.py"
SCRIPT = ROOT / "research" / "whole_game_anytime_v0_58.py"


def _simple_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("spider.simple_"):
            names.append(node.module)
    return names


def _columns(*runs, foundations=None, stock=None) -> SpiderState:
    cols = [Column([], list(run)) for run in runs]
    while len(cols) < 10:
        cols.append(Column([], []))
    return SpiderState(cols, list(stock or []), list(foundations or []))


def _ka(suit: str) -> list[Card]:
    return [Card(suit, r) for r in range(13, 0, -1)]


def test_generic_and_adapter_never_import_simple():
    for path in GENERIC:
        assert _simple_imports(path) == [], path.name


def test_all_legal_actions_includes_engine_deal():
    opening = opening_state()
    all_acts = all_legal_actions(opening)
    tab = tableau_actions(opening)
    assert ("deal",) in all_acts
    assert ("deal",) not in tab
    assert opening.can_deal(rules=MW_RULES) is True
    assert MW_RULES.can_deal_into_empty is True
    empty = _columns([Card("s", 13)], stock=[])
    assert ("deal",) not in all_legal_actions(empty)
    assert empty.can_deal() is False


def test_deal_cost_apply_restore():
    opening = opening_state()
    before = pack_state(opening)
    assert step_cost(opening, ("deal",)) == deal_cost() == 1
    cap = capture_state(opening, ("deal",))
    cost = apply_action(opening, ("deal",))
    assert cost == 1
    assert stock_rows(opening) == 4
    assert pack_state(opening) != before
    restore_state(opening, cap)
    assert pack_state(opening) == before


def test_pre_stock_permutation_is_not_identity():
    opening = opening_state()
    assert opening.stock
    perm = list(range(10))
    perm[0], perm[1] = perm[1], perm[0]
    swapped = permute_tableau_columns(opening, perm)
    assert pack_state(opening) != pack_state(swapped)
    assert pack_whole_game_identity(opening) != pack_whole_game_identity(swapped)
    assert pack_whole_game_identity(opening).startswith(PACKED_MAGIC)


def test_post_stock_permutation_collides_and_domains_do_not():
    a = _columns([Card("s", 13)], [Card("h", 12)], stock=[])
    b = _columns([Card("h", 12)], [Card("s", 13)], stock=[])
    assert pack_state(a) != pack_state(b)
    assert pack_whole_game_identity(a) == pack_whole_game_identity(b)
    assert pack_whole_game_identity(a) == pack_post_stock_symmetry_state(a)
    assert pack_whole_game_identity(a).startswith(PACKED_SYMMETRY_MAGIC)
    with_stock = _columns([Card("s", 13)], [Card("h", 12)], stock=[Card("d", 5)] * 10)
    assert pack_whole_game_identity(with_stock).startswith(PACKED_MAGIC)
    assert pack_whole_game_identity(with_stock) != pack_whole_game_identity(a)
    extra_f = _columns([Card("s", 13)], [Card("h", 12)], stock=[], foundations=[_ka("c")])
    assert pack_whole_game_identity(a) != pack_whole_game_identity(extra_f)


def test_opening_root_is_g0_unsolved():
    opening = opening_state()
    root = opening_root(opening)
    assert root["g"] == 0
    assert len(opening.foundations) == 0
    assert opening.is_solved() is False
    assert stock_rows(opening) == 5
    assert root["ordered_digest"] == pack_state(opening).hex()


def test_seven_lanes_no_suit_preference():
    assert LANES == (
        "cost",
        "foundation",
        "reveal",
        "workspace",
        "construction",
        "prep",
        "epoch",
    )
    src = ADAPTER.read_text(encoding="utf-8") + SCRIPT.read_text(encoding="utf-8")
    assert "canonical.moves" not in src
    assert "simple_" not in inspect.getsource(search_whole_game)
    opening = opening_state()
    keys = lane_keys(opening, 0)
    assert set(keys) == set(LANES)
    assert "s" not in LANES and "h" not in LANES and "d" not in LANES and "c" not in LANES


def test_prep_and_epoch_compete_on_deal_timing():
    opening = opening_state()
    dealt = opening.clone()
    apply_action(dealt, ("deal",))
    a = lane_keys(opening, 10)
    b = lane_keys(dealt, 10)
    assert a["prep"] < b["prep"]
    assert a["epoch"] > b["epoch"]
    assert a["cost"] == b["cost"] == (10,)


def test_solved_is_only_terminal_predicate():
    src = inspect.getsource(search_whole_game)
    assert "is_solved()" in src
    assert "len(st.foundations) == 2" not in src
    assert "len(st.foundations) >= 2" not in src


def test_current_tableau_summary_has_no_cover_requirement():
    opening = opening_state()
    s = current_tableau_summary(opening)
    assert "min_cover" not in s
    assert s["stock_rows"] == 5
    assert s["foundations"] == 0
    assert "same_suit_bonds" in s
    assert "longest_run" in s


def test_kernel_path_across_deal():
    opening = opening_state()
    root = opening_root(opening)
    kr = run_search(
        [root],
        limits=SearchLimits(max_unique=40, time_limit_s=2.0, rss_abort_mb=4096, cost_ceiling=5),
        identity_fn=pack_whole_game_identity,
        actions_fn=all_legal_actions,
        action_order=lambda _st, acts: sorted(acts, key=lambda a: 0 if a == ("deal",) else 1),
        is_terminal=lambda st: stock_rows(st) <= 4,
        lane_names=("cost",),
        lane_key_fns=[lambda _st, g: (g,)],
    )
    assert kr.terminals
    path = kr.reconstruct(kr.terminals[0]["node"])
    assert path[0] == ("deal",)
    end = opening.clone()
    cost = replay_actions(end, path)
    assert cost == 1
    assert stock_rows(end) == 4


def test_synthetic_solve_replays():
    foundations = [
        _ka("s"),
        _ka("h"),
        _ka("d"),
        _ka("c"),
        _ka("s"),
        _ka("h"),
        _ka("d"),
    ]
    left = _ka("c")
    st = _columns(left[:10], left[10:], foundations=foundations, stock=[])
    assert len(st.foundations) == 7
    assert not st.is_solved()
    res = search_whole_game(
        opening=st,
        max_unique=40,
        time_limit_s=2.0,
        rss_abort_mb=4096,
        cost_ceiling=20,
    )
    assert res.solved is True
    assert res.replay_ok is True
    assert res.solution_g == res.replay_g
    end = st.clone()
    replay_actions(end, res.solution_actions)
    assert end.is_solved()
    assert len(end.foundations) == 8
    assert stock_rows(end) == 0


def test_milestones_and_verdict_space():
    opening = opening_state()
    res = search_whole_game(
        opening=opening,
        max_unique=20,
        time_limit_s=2.0,
        rss_abort_mb=4096,
        cost_ceiling=10,
    )
    assert 5 in res.epochs
    assert res.epochs[5]["first"]["g"] == 0
    assert res.max_foundations >= 0
    v, _ = choose_verdict({"solved": True, "replay_ok": True})
    assert v == "WHOLE_GAME_AUTONOMOUS_SOLVE"
    v, _ = choose_verdict({"max_foundations": 2})
    assert v == "WHOLE_GAME_REACHES_F2_OR_BEYOND"
    v, _ = choose_verdict({"max_foundations": 1})
    assert v == "WHOLE_GAME_REDISCOVERS_F1_ONLY"
    v, _ = choose_verdict({"max_foundations": 0, "epochs": {"4": {}}, "min_face_down": 40, "opening_face_down": 50})
    assert v == "WHOLE_GAME_PROGRESS_NO_FOUNDATION"


def test_policy_firewall_source():
    text = ADAPTER.read_text(encoding="utf-8")
    assert "4925153_canonical" not in text
    assert "canonical.moves" not in text
    assert "g=21" not in text
    assert "TARGET" not in inspect.getsource(lane_keys)
