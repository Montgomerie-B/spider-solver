"""Bounded tactical foundation cash-out v0.71."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.foundation_cashout import (
    CLASS_SLACK_G,
    PORTFOLIO_LIMIT,
    TACTICAL_CEILING,
    TACTICAL_LANES,
    TACTICAL_RSS_MB,
    TACTICAL_TIME_S,
    TACTICAL_UNIQUE,
    SearchFirewallError,
    choose_tactical_verdict,
    is_target_cashout,
    replay_incumbent_suffix_for_eval,
    replay_to_stock_rows,
    require_eval_phase,
    search_firewall_active,
    search_foundation_cashout,
    select_tactical_target,
    serialized_tactical_root,
    suit_foundation_count,
    tactical_lane_keys,
    tactical_search_session,
    target_access_key,
    target_assembly_key,
    trace_tactical_path,
)
from spider.metrics import parse_moves_file, replay_actions
from spider.operational_viability import rank_ready_suits
from spider.packed_state import (
    pack_post_stock_symmetry_state,
    pack_state,
    pack_whole_game_identity,
    unpack_state,
)
from spider.research_actions import as_actions, is_deal, step_cost, stock_rows, tableau_actions
from spider.search_kernel import run_search
from spider.whole_game_anytime import opening_state

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "foundation_cashout.py"
SCRIPT = ROOT / "research" / "bounded_foundation_cashout_v0_71.py"
V067 = ROOT / "solutions" / "4925153_autonomous_v0_67.moves"
CANON = ROOT / "solutions" / "4925153_canonical.moves"
V059 = ROOT / "solutions" / "4925153_autonomous_v0_59.moves"
ARTEFACT = ROOT / "docs" / "research" / "bounded_foundation_cashout_v0_71.json"
POLICY_PATHS = (
    MOD,
    ROOT / "src" / "spider" / "search_kernel.py",
    ROOT / "src" / "spider" / "operational_viability.py",
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _run(suit: str, hi: int, lo: int):
    return [Card(suit, r) for r in range(hi, lo - 1, -1)]


def _ka(suit: str):
    return _run(suit, 13, 1)


def _stock_row(suit: str = "h"):
    return [Card(suit, r) for r in range(1, 11)]


def _columns(*runs, down=None, foundations=None, stock=None) -> SpiderState:
    downs = list(down or [])
    cols = []
    for i, run in enumerate(runs):
        fd = list(downs[i]) if i < len(downs) else []
        cols.append(Column(fd, list(run)))
    while len(cols) < 10:
        cols.append(Column([], []))
    return SpiderState(cols, list(stock or []), list(foundations or []))


def test_target_suit_is_operational_rank_1():
    st = _columns(_ka("c"), _run("d", 13, 6), stock=_stock_row())
    ranked = rank_ready_suits(st, g=9)
    chosen = select_tactical_target(st, 9)
    assert ranked["n_ready"] >= 1
    assert chosen["suit"] == ranked["best"]["suit"]
    assert chosen["suit"] == ranked["ranked"][0]["suit"]
    assert chosen["operational_key"] == list(ranked["best"]["key"])


def test_no_suit_literal_in_policy():
    src = inspect.getsource(search_foundation_cashout)
    src += inspect.getsource(select_tactical_target)
    src += inspect.getsource(tactical_lane_keys)
    src += inspect.getsource(is_target_cashout)
    lower = src.lower()
    for word in ("diamonds", "hearts", "spades", "clubs"):
        assert word not in lower
    text = _text(MOD)
    assert "4925153_canonical.moves" not in text
    assert "canonical.moves" not in text
    assert "g=130" not in text
    assert "g130" not in text
    tree = ast.parse(text)
    simple = [
        n.module
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("spider.simple_")
    ]
    assert simple == []


def test_target_suit_fixed_for_tactical_probe():
    st = _columns(_ka("c"), _ka("d"), stock=_stock_row())
    ranked = rank_ready_suits(st, g=4)
    assert ranked["n_ready"] >= 2
    forced = ranked["ranked"][1]["suit"]
    assert forced != ranked["best"]["suit"]
    keys = tactical_lane_keys(st, 4, forced)
    assert set(keys) == set(TACTICAL_LANES)
    src = inspect.getsource(tactical_lane_keys)
    assert "rank_ready_suits" not in src
    src_s = inspect.getsource(search_foundation_cashout)
    assert "select_tactical_target" not in src_s


def test_target_goal_detects_correct_suit_only():
    stock = _stock_row()
    empty = _columns(stock=stock)
    assert not is_target_cashout(empty, "d", 0)
    clubs_only = _columns(foundations=[_ka("c")], stock=stock)
    assert suit_foundation_count(clubs_only, "c") == 1
    assert not is_target_cashout(clubs_only, "d", 0)
    assert is_target_cashout(clubs_only, "c", 0)
    both = _columns(foundations=[_ka("c"), _ka("d")], stock=stock)
    assert is_target_cashout(both, "d", 0)
    assert not is_target_cashout(both, "d", 1)


def test_other_suit_foundation_does_not_terminate_target_search():
    st = _columns(
        _run("d", 13, 2),
        [Card("d", 1)],
        _run("c", 13, 2),
        [Card("c", 1)],
        stock=_stock_row(),
    )
    before_d = suit_foundation_count(st, "d")
    before_c = suit_foundation_count(st, "c")
    assert before_d == before_c == 0
    club_merge = None
    for action in tableau_actions(st):
        src, dst, k = action
        run = st.columns[src].face_up[-k:]
        dest = st.columns[dst].top()
        if (
            run
            and run[-1].suit == "c"
            and run[-1].rank == 1
            and dest is not None
            and dest.suit == "c"
            and dest.rank == 2
        ):
            club_merge = action
            break
    assert club_merge is not None
    child = st.clone()
    child.move(club_merge[0], club_merge[1], club_merge[2])
    assert suit_foundation_count(child, "c") > before_c
    assert not is_target_cashout(child, "d", before_d)
    res = search_foundation_cashout(
        root_state=st,
        root_g=10,
        target_suit="d",
        max_unique=2_000,
        time_limit_s=3.0,
        rss_abort_mb=TACTICAL_RSS_MB,
        cost_ceiling=40,
    )
    assert res.found
    end = unpack_state(bytes.fromhex(res.cheapest_digest))
    assert suit_foundation_count(end, "d") > before_d


def test_deal_absent_from_tactical_actions():
    st = _columns(_run("c", 13, 2), [Card("c", 1)], stock=_stock_row())
    legal = st.enumerate_legal_actions()
    tab = tableau_actions(st)
    assert ("deal",) in legal
    assert ("deal",) not in tab
    from spider.foundation_cashout import _tactical_actions

    src = inspect.getsource(search_foundation_cashout) + inspect.getsource(_tactical_actions)
    assert "tableau_actions" in src
    assert "all_legal_actions" not in src
    assert all(not is_deal(a) for a in _tactical_actions(st))
    res = search_foundation_cashout(
        root_state=st,
        root_g=3,
        target_suit="c",
        max_unique=200,
        time_limit_s=2.0,
        cost_ceiling=20,
    )
    assert res.found
    assert all(not is_deal(a) for a in res.path)
    assert stock_rows(unpack_state(bytes.fromhex(res.cheapest_digest))) == stock_rows(st)


def test_ordered_pre_stock_identity_retained():
    st = _columns(_run("c", 13, 2), [Card("c", 1)], stock=_stock_row())
    assert st.stock
    packed = pack_state(st)
    ident = pack_whole_game_identity(st)
    assert packed == ident
    with pytest.raises(ValueError):
        pack_post_stock_symmetry_state(st)
    src = inspect.getsource(search_foundation_cashout)
    assert "pack_whole_game_identity" in src
    assert "pack_post_stock_symmetry_state" not in src


def test_corrected_mw_accumulation_and_cheapest_g_tt():
    st = _columns(_run("c", 13, 2), [Card("c", 1)], stock=_stock_row())
    res = search_foundation_cashout(
        root_state=st,
        root_g=11,
        target_suit="c",
        max_unique=200,
        time_limit_s=2.0,
        cost_ceiling=30,
    )
    assert res.found
    g = 11
    replay = st.clone()
    for action in res.path:
        g += step_cost(replay, action)
        replay.move(action[0], action[1], action[2])
    assert g == res.cheapest_g
    assert res.delta_g == res.cheapest_g - 11
    src = inspect.getsource(run_search)
    assert "best_g" in src
    assert "child_g >= prev" in src
    src_s = inspect.getsource(search_foundation_cashout)
    assert "harvest_slack=None" in src_s


def test_nonmonotonic_target_metrics_allowed():
    from spider.operational_viability import foundation_operational_viability

    src = inspect.getsource(search_foundation_cashout)
    assert "monotonic" not in src.lower()
    fillers = [[Card("s", 13)], [Card("h", 13)], [Card("d", 13)], [Card("s", 12)], [Card("h", 12)], [Card("d", 12)]]
    st = _columns(
        _run("c", 13, 10),
        [Card("h", 9)],
        _run("c", 9, 2),
        [Card("c", 1)],
        *fillers,
        stock=_stock_row(),
    )
    parent_v = foundation_operational_viability(st, "c")
    bury = None
    for action in tableau_actions(st):
        src_i, dst_i, k = action
        card = st.columns[src_i].face_up[-1]
        if card.suit == "h" and card.rank == 9 and dst_i == 0:
            bury = action
            break
    assert bury is not None
    child = st.clone()
    child.move(bury[0], bury[1], bury[2])
    child_v = foundation_operational_viability(child, "c")
    assert int(child_v.get("inaccessible_joins") or 0) >= int(parent_v.get("inaccessible_joins") or 0)
    res = search_foundation_cashout(
        root_state=st,
        root_g=8,
        target_suit="c",
        max_unique=4_000,
        time_limit_s=4.0,
        cost_ceiling=40,
    )
    assert res.found
    assert res.unique >= 2
    # A worse-assembly child was legal; the planner still completed the target.
    assert suit_foundation_count(unpack_state(bytes.fromhex(res.cheapest_digest)), "c") >= 1


def test_synthetic_cashout_examples():
    st = _columns(_run("c", 13, 2), [Card("c", 1)], stock=_stock_row())
    target = select_tactical_target(st, 5)
    assert target["suit"] == "c"
    res = search_foundation_cashout(
        root_state=st,
        root_g=5,
        target_suit=target["suit"],
        max_unique=500,
        time_limit_s=2.0,
        cost_ceiling=20,
    )
    assert res.found
    assert res.cheapest_g is not None
    assert res.cheapest_g > 5
    assert suit_foundation_count(unpack_state(bytes.fromhex(res.cheapest_digest)), "c") >= 1
    two = _columns(
        _run("d", 13, 3),
        [Card("d", 2), Card("d", 1)],
        stock=_stock_row(),
    )
    t2 = select_tactical_target(two, 6)
    res2 = search_foundation_cashout(
        root_state=two,
        root_g=6,
        target_suit=t2["suit"],
        max_unique=500,
        time_limit_s=2.0,
        cost_ceiling=20,
    )
    assert res2.found


def test_suffix_not_available_to_search_code():
    assert not search_firewall_active()
    with tactical_search_session():
        assert search_firewall_active()
        with pytest.raises(SearchFirewallError):
            require_eval_phase("incumbent suffix")
        with pytest.raises(SearchFirewallError):
            replay_incumbent_suffix_for_eval(
                opening_state(), [], prefix_n=0, root_g=0
            )
    assert not search_firewall_active()
    src = inspect.getsource(search_foundation_cashout)
    assert "replay_incumbent_suffix_for_eval" not in src
    assert "parse_moves_file" not in src
    st = _columns(_run("c", 13, 2), [Card("c", 1)], stock=_stock_row())
    digest = pack_state(st).hex()
    import spider.metrics as metrics

    orig = metrics.parse_moves_file

    def boom(*_a, **_k):
        raise AssertionError("search must not read a moves file")

    metrics.parse_moves_file = boom
    try:
        res = search_foundation_cashout(
            ordered_digest=digest,
            root_g=4,
            target_suit="c",
            max_unique=300,
            time_limit_s=2.0,
            cost_ceiling=20,
        )
    finally:
        metrics.parse_moves_file = orig
    assert res.found
    assert not search_firewall_active()


def test_autonomous_192_prefix_checkpoint_replay():
    opening = opening_state()
    actions = parse_moves_file(V067)
    root = replay_to_stock_rows(opening, actions, target_rows=1)
    assert root["g"] == 123
    assert root["foundations"] == 1
    assert root["face_down"] == 2
    assert root["stock_rows"] == 1
    assert root["deals"] == 4
    assert root["suffix_discarded"] is True
    prefix = as_actions(root["prefix_actions"])
    end = opening.clone()
    g = replay_actions(end, prefix)
    assert g == 123
    assert pack_state(end).hex() == root["ordered_digest"]
    assert pack_whole_game_identity(end).hex() == root["whole_game_identity"]
    assert stock_rows(end) == 1
    assert len(end.foundations) == 1
    assert sum(len(c.face_down) for c in end.columns) == 2
    assert root["legal_mobility"] == len(tableau_actions(end))
    ser = serialized_tactical_root(root)
    assert "prefix_actions" not in ser
    target = select_tactical_target(end, 123)
    assert target["suit"] == rank_ready_suits(end, g=123)["best"]["suit"]
    assert int(target["n_ready"]) >= 1


def test_no_canonical_reads_and_script_eval_after_search():
    for path in POLICY_PATHS + (SCRIPT,):
        text = _text(path)
        if not text:
            continue
        assert "4925153_canonical.moves" not in text
    script = _text(SCRIPT)
    if script:
        search_at = script.find("search_foundation_cashout(")
        eval_at = script.find("EVAL incumbent suffix")
        assert search_at != -1
        assert eval_at > search_at
        assert "search_integrated_optimisation(" not in script
    opening = opening_state()
    assert replay_actions(opening.clone(), parse_moves_file(V059)) == 198
    assert replay_actions(opening.clone(), parse_moves_file(CANON)) == 172
    assert replay_actions(opening.clone(), parse_moves_file(V067)) == 192
    assert TACTICAL_CEILING == 191
    assert TACTICAL_TIME_S == 300.0
    assert TACTICAL_UNIQUE == 400_000
    assert TACTICAL_RSS_MB == 2.5 * 1024.0
    assert PORTFOLIO_LIMIT == 64
    assert CLASS_SLACK_G == 10
    assert TACTICAL_LANES == ("cost", "target_assembly", "target_access")
    assert "readiness_r2" not in TACTICAL_LANES


def test_artefact_verdict_matches_cheapest_if_present():
    if not ARTEFACT.exists():
        return
    import json

    data = json.loads(ARTEFACT.read_text(encoding="utf-8"))
    verdict, _ = choose_tactical_verdict(data)
    assert data.get("verdict") == verdict
    cheapest = data.get("cheapest_g")
    if cheapest is None:
        cheapest = (data.get("search") or {}).get("cheapest_g")
    if cheapest is not None:
        assert verdict != "TACTICAL_CASHOUT_NO_FOUNDATION"


def test_verdict_uses_nested_or_top_level_cheapest_g():
    cheaper = choose_tactical_verdict(
        {
            "search": {"cheapest_g": 128, "unique": 100, "expanded": 50, "stop_reason": "time limit"},
            "incumbent_compare": {"foundation_g": 130},
        }
    )
    assert cheaper[0] == "TACTICAL_CASHOUT_FINDS_CHEAPER_F2"
    same = choose_tactical_verdict({"cheapest_g": 130, "incumbent_compare": {"foundation_g": 130}})
    assert same[0] == "TACTICAL_CASHOUT_RECOVERS_F2_CLASS"
    expensive = choose_tactical_verdict({"cheapest_g": 150, "incumbent_compare": {"foundation_g": 130}})
    assert expensive[0] == "TACTICAL_CASHOUT_FINDS_EXPENSIVE_F2"
    none = choose_tactical_verdict(
        {
            "search": {"unique": 100, "expanded": 20, "stop_reason": "complete"},
            "root_cover": 3,
            "progress": {"min_cover": 3},
        }
    )
    assert none[0] == "TACTICAL_CASHOUT_NO_FOUNDATION"


def test_assembly_and_access_lane_shapes():
    v = {
        "cover": 3,
        "inaccessible_joins": 2,
        "k_min_blockers": 1,
        "a_min_blockers": 0,
        "gap": 4,
        "legal_merge_edges": 2,
        "relevant_blockers": 5,
        "buried_components": 1,
        "exposed_components": 3,
        "movable_exposed": 2,
        "empty_n": 1,
        "legal_merge_ops_global": 4,
    }
    a = target_assembly_key(v, 12)
    b = target_access_key(v, 12)
    assert a[-1] == 12 and b[-1] == 12
    assert a[0] == 3 and a[1] == 2
    worse = dict(v, cover=4)
    assert target_assembly_key(worse, 12) > a
