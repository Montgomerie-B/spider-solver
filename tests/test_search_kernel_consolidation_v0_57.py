"""v0.57 search-kernel consolidation contracts.

Architectural tests. Does not run a Foundation-2 campaign.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.packed_state import pack_post_stock_symmetry_state, pack_state
from spider.research_actions import (
    apply_action,
    as_actions,
    dump_actions,
    step_cost,
    tableau_actions,
)
from spider.research_roots import dedup_roots, replay_root
from spider.rules import mw_move_cost
from spider.search_kernel import SearchLimits, run_search
from spider.simple_component_aware_f2 import search_component_aware_f2
from spider.simple_resource_aware_f2 import search_foundation2, would_remove_foundation
from spider.structural_analysis import (
    SUITS,
    all_lane_metrics,
    component_cover,
    ka_gap,
    lane_suit_metrics,
    merge_edges,
    tableau_occupancy,
    visible_components,
)

ROOT = Path(__file__).resolve().parents[1]
GENERIC = (
    ROOT / "src" / "spider" / "research_actions.py",
    ROOT / "src" / "spider" / "research_roots.py",
    ROOT / "src" / "spider" / "search_kernel.py",
    ROOT / "src" / "spider" / "structural_analysis.py",
)
ADAPTERS = (
    ROOT / "src" / "spider" / "simple_resource_aware_f2.py",
    ROOT / "src" / "spider" / "simple_sd5_component_audit.py",
    ROOT / "src" / "spider" / "simple_component_aware_f2.py",
)


def _columns(*runs, foundations=None, stock=None, blocked: int = 0) -> SpiderState:
    cols = [Column([], list(run)) for run in runs]
    cols.extend(Column([Card("s", 12)], []) for _ in range(blocked))
    while len(cols) < 10:
        cols.append(Column([], []))
    return SpiderState(cols, list(stock or []), list(foundations or []))


def _kings(n: int):
    return [[Card("s", 13)] for _ in range(n)]


def _root(state: SpiderState, g: int = 0, **meta) -> dict:
    rec = {
        "g": g,
        "ordered_digest": pack_state(state).hex(),
        "symmetry_digest": pack_post_stock_symmetry_state(state).hex(),
        "full_actions": [],
        "timing": meta.get("timing", "TEST"),
    }
    rec.update(meta)
    return rec


def _generic_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("spider.simple_"):
            names.append(node.module)
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("spider.simple_"):
                    names.append(alias.name)
    return names


def test_generic_modules_never_import_simple_experiments():
    for path in GENERIC:
        assert _generic_imports(path) == [], f"{path.name} imports {_generic_imports(path)}"


def test_recent_adapters_do_not_import_simple_experiments():
    for path in ADAPTERS:
        leftover = _generic_imports(path)
        assert leftover == [], f"{path.name} still imports {leftover}"


def test_step_cost_is_authoritative_mw():
    st = _columns([Card("c", 6), Card("c", 5)], [Card("c", 4)], *_kings(8))
    action = (1, 0, 1)
    expected = mw_move_cost(
        cards_moved=1,
        source_face_up_count=1,
        dest_was_empty=False,
        source_face_down_count=0,
    )
    assert step_cost(st, action) == expected
    assert apply_action(st.clone(), action) == expected


def test_as_actions_roundtrip_without_suit_experiment():
    raw = [["deal"], [0, 1, 3], ["deal"]]
    acts = as_actions(raw)
    assert acts[0] == ("deal",)
    assert acts[1] == (0, 1, 3)
    assert dump_actions(acts) == raw


def test_structural_metrics_all_four_suits_synthetic():
    st = _columns(
        [Card("c", r) for r in range(13, 6, -1)],  # K-7 clubs
        [Card("c", 6)],
        [Card("c", 5)],
        [Card("c", r) for r in range(4, 0, -1)],  # 4-A
        [Card("h", 13)],
        [Card("d", 13), Card("d", 12), Card("d", 11)],
        [Card("s", 5), Card("s", 4), Card("s", 3)],
        [Card("s", 13)],
        [Card("h", 1)],
        [Card("d", 1)],
    )
    by = all_lane_metrics(st)
    assert set(by) == set(SUITS)
    club = by["c"]
    assert club["cover"] == 4
    assert club["k_len"] == 7
    assert club["a_len"] == 4
    assert club["gap"] == 2
    assert club["longest"] == 7
    assert club["edges"] >= 2
    assert club["cond_len"] == club["longest"] + (1 if club["edges"] else 0)
    assert by["h"]["k_len"] == 1
    occ = tableau_occupancy(st)
    assert occ["foundations"] == 0
    assert occ["empty_n"] == 0


def test_v056_club_best_class_metrics():
    """Frozen representative of the v0.56 Club descendant class: cover 4, edges 2, gap 2."""

    st = _columns(
        [Card("c", r) for r in range(13, 6, -1)],
        [Card("c", 6)],
        [Card("c", 5)],
        [Card("c", r) for r in range(4, 0, -1)] + [Card("h", 13)],
        *_kings(6),
    )
    m = lane_suit_metrics(st, "c")
    assert m["cover"] == 4
    assert m["edges"] == 2
    assert m["gap"] == 2
    assert m["k_len"] == 7
    assert m["a_len"] == 4
    assert m["cond_len"] == 8
    comps = visible_components(st, "c")
    assert ka_gap(max([c for c in comps if c["high"] == 13], key=lambda c: c["length"]),
                  max([c for c in comps if c["low"] == 1], key=lambda c: c["length"])) == 2
    assert not any(e[0] == 3 for e in merge_edges(st, "c"))


def test_hearts_diamonds_spades_cover_on_frozen_layout():
    st = _columns(
        [Card("h", 13)],
        [Card("h", r) for r in range(12, 7, -1)],
        [Card("h", 7), Card("h", 6)],
        [Card("h", 5), Card("h", 4)],
        [Card("h", 3), Card("h", 2), Card("c", 13)],
        [Card("h", 1)],
        [Card("d", 13), Card("d", 12), Card("d", 11)],
        [Card("d", 10)],
        [Card("d", 5), Card("d", 4), Card("d", 3), Card("d", 2), Card("d", 1)],
        [Card("s", 4), Card("s", 3), Card("s", 2), Card("s", 1)],
    )
    h = component_cover(st, "h")
    d = component_cover(st, "d")
    s = component_cover(st, "s")
    assert h["min_cover"] == 6
    assert d["min_cover"] is None
    assert s["min_cover"] is None
    hm = lane_suit_metrics(st, "h")
    dm = lane_suit_metrics(st, "d")
    sm = lane_suit_metrics(st, "s")
    assert hm["k_len"] == 1
    assert hm["a_len"] == 1
    assert hm["gap"] == 11
    assert hm["edges"] == 3
    assert hm["longest"] == 5
    assert hm["cond_len"] == 6
    assert dm["k_len"] == 3
    assert dm["a_len"] == 5
    assert sm["a_len"] == 4


def test_kernel_cheapest_g_dominance_and_stale():
    st = _columns([Card("h", 13)], [], blocked=8)
    roots = [_root(st, 0)]
    kr = run_search(
        roots,
        limits=SearchLimits(max_unique=40, time_limit_s=2.0, rss_abort_mb=4096, cost_ceiling=5),
        identity_fn=pack_state,
        lane_names=("cost",),
        lane_key_fns=[lambda _st, g: (g,)],
        is_terminal=lambda _st: False,
    )
    assert kr.unique >= 2
    assert kr.duplicate_skips >= 1
    assert kr.stop_reason in {"complete", "unique limit", "time limit"}
    assert kr.min_g == 0


def test_kernel_reopen_on_better_g():
    filler = (
        [Card("s", 7)],
        [Card("h", 7)],
        [Card("d", 7)],
        [Card("s", 9)],
        [Card("h", 9)],
        [Card("d", 9)],
        [Card("s", 2)],
        [Card("h", 2)],
    )
    cheap = _columns([Card("c", 6)], [Card("h", 13), Card("c", 5)], *filler)
    expensive = _columns([Card("c", 6), Card("c", 5)], [Card("h", 13)], *filler)
    kr = run_search(
        [_root(expensive, 3, timing="HI"), _root(cheap, 0, timing="LO")],
        limits=SearchLimits(max_unique=20, time_limit_s=2.0, rss_abort_mb=4096, cost_ceiling=4),
        identity_fn=pack_state,
        lane_names=("cost",),
        lane_key_fns=[lambda _st, g: (g,)],
        is_terminal=lambda _st: False,
    )
    ident_expensive = pack_state(expensive)
    nodes = [n for n in kr.nodes if n.ident == ident_expensive]
    assert any(n.parent < 0 and n.g == 3 for n in nodes)
    assert any(n.parent >= 0 and n.g == 1 for n in nodes)


def test_kernel_stale_heap_suppression_across_lanes():
    st = _columns(
        [Card("h", 13)],
        [Card("s", 7)],
        [Card("d", 2)],
        [Card("c", 9)],
        [Card("h", 9)],
        [Card("s", 9)],
        [Card("c", 2)],
        [Card("h", 2)],
        [Card("s", 2)],
        [Card("c", 7)],
    )
    kr = run_search(
        [_root(st, 0)],
        limits=SearchLimits(max_unique=20, time_limit_s=2.0, rss_abort_mb=4096, cost_ceiling=3),
        identity_fn=pack_state,
        lane_names=("a", "b"),
        lane_keys_fn=lambda _s, g: {"a": (g,), "b": (g,)},
        is_terminal=lambda _s: False,
    )
    assert kr.stop_reason == "complete"
    assert kr.stale_skips >= 1
    assert sum(kr.lane_stale.values()) == kr.stale_skips


def test_kernel_single_lane_deterministic_and_path():
    st = _columns([Card("c", 5), Card("c", 4)], [Card("c", 6)], *_kings(8))
    kr = run_search(
        [_root(st, 0)],
        limits=SearchLimits(max_unique=30, time_limit_s=2.0, rss_abort_mb=4096, cost_ceiling=4),
        identity_fn=pack_state,
        lane_names=("cost",),
        lane_key_fns=[lambda _st, g: (g,)],
        is_terminal=lambda s: False,
    )
    assert kr.lane_pops == {"cost": kr.lane_pops["cost"]}
    assert list(kr.lane_pops) == ["cost"]
    child_nodes = [i for i, n in enumerate(kr.nodes) if n.parent >= 0]
    assert child_nodes
    path = kr.reconstruct(child_nodes[0])
    assert path
    replay = st.clone()
    cost = 0
    for action in path:
        cost += apply_action(replay, action)
    assert pack_state(replay) == kr.nodes[child_nodes[0]].store
    assert cost == kr.nodes[child_nodes[0]].g


def test_kernel_multi_lane_shared_tt_round_robin():
    st = _columns([Card("c", 5)], [Card("c", 6)], [Card("h", 5)], [Card("h", 6)], *_kings(6))
    kr = run_search(
        [_root(st, 0)],
        limits=SearchLimits(max_unique=25, time_limit_s=2.0, rss_abort_mb=4096, cost_ceiling=3),
        identity_fn=pack_post_stock_symmetry_state,
        lane_names=("cost", "c", "h"),
        lane_keys_fn=lambda s, g: {
            "cost": (g,),
            "c": (g, 0),
            "h": (g, 1),
        },
        is_terminal=lambda _s: False,
    )
    assert set(kr.lane_pops) == {"cost", "c", "h"}
    pops = [kr.lane_pops[n] for n in ("cost", "c", "h")]
    assert max(pops) - min(pops) <= 1
    assert kr.unique == len({n.ident for n in kr.nodes})


def test_kernel_root_provenance_and_terminal_predicate():
    base = _columns(
        [Card("d", 3), Card("d", 2), Card("d", 1)],
        [Card("d", r) for r in range(13, 3, -1)],
        *_kings(8),
        foundations=[[Card("s", r) for r in range(13, 0, -1)]],
    )
    kr = run_search(
        [_root(base, 7, timing="DEAL_NOW")],
        limits=SearchLimits(max_unique=20, time_limit_s=2.0, rss_abort_mb=4096, cost_ceiling=20),
        identity_fn=pack_state,
        lane_names=("cost",),
        lane_key_fns=[lambda _st, g: (g,)],
        is_terminal=lambda s: len(s.foundations) >= 2,
    )
    assert kr.terminals
    term = kr.terminals[0]
    assert term["origin"] == 0
    assert term["g"] >= 7
    end = base.clone()
    for action in kr.reconstruct(term["node"]):
        apply_action(end, action)
    assert len(end.foundations) == 2
    assert kr.stop_reason in {"complete", "harvested", "unique limit"}
    assert kr.first_g == term["g"] or kr.incumbent_g is not None


def test_kernel_stop_reasons_unique_and_time_and_cost():
    st = _columns([Card("h", 13)], [Card("h", 12)], [Card("h", 11)], *_kings(7))
    unique = run_search(
        [_root(st, 0)],
        limits=SearchLimits(max_unique=2, time_limit_s=30.0, rss_abort_mb=4096, cost_ceiling=20),
        identity_fn=pack_state,
        lane_names=("cost",),
        lane_key_fns=[lambda _st, g: (g,)],
        is_terminal=lambda _s: False,
    )
    assert unique.stop_reason == "unique limit"
    timed = run_search(
        [_root(st, 0)],
        limits=SearchLimits(max_unique=50_000, time_limit_s=0.0, rss_abort_mb=4096, cost_ceiling=20),
        identity_fn=pack_state,
        lane_names=("cost",),
        lane_key_fns=[lambda _st, g: (g,)],
        is_terminal=lambda _s: False,
    )
    assert timed.stop_reason == "time limit"
    capped = run_search(
        [_root(st, 0)],
        limits=SearchLimits(max_unique=50, time_limit_s=2.0, rss_abort_mb=4096, cost_ceiling=0),
        identity_fn=pack_state,
        lane_names=("cost",),
        lane_key_fns=[lambda _st, g: (g,)],
        is_terminal=lambda _s: False,
    )
    assert capped.max_g == 0
    assert capped.stop_reason == "complete"


def test_root_dedup_keeps_cheapest_and_merges_provenance():
    st = _columns([Card("c", 13)], *_kings(9))
    a = _root(st, 9, timing="DEAL_NOW")
    b = _root(st, 7, timing="PREP_THEN_DEAL")
    b["symmetry_digest"] = a["symmetry_digest"]
    out = dedup_roots([a, b])
    assert out["symmetry_unique"] == 1
    assert out["states"][0]["g"] == 7
    assert set(out["states"][0]["timings"]) >= {"DEAL_NOW", "PREP_THEN_DEAL"}


def test_replay_root_validates_g_and_digest():
    opening = _columns([Card("c", 6)], [Card("c", 5)], *_kings(8))
    end = opening.clone()
    action = (1, 0, 1)
    cost = apply_action(end, action)
    rec = {
        "g": cost,
        "full_actions": dump_actions([action]),
        "ordered_digest": pack_state(end).hex(),
        "timing": "TEST",
    }
    got = replay_root(opening, rec, require_stock_zero=True, require_foundation_count=0)
    assert got is not None
    assert got["g"] == cost
    bad = dict(rec)
    bad["g"] = cost + 1
    assert replay_root(opening, bad, require_stock_zero=True) is None


def test_v054_adapter_finds_synthetic_f2():
    st = _columns(
        [Card("d", 3), Card("d", 2), Card("d", 1)],
        [Card("d", r) for r in range(13, 3, -1)],
        *_kings(8),
        foundations=[[Card("s", r) for r in range(13, 0, -1)]],
    )
    assert any(would_remove_foundation(st, a) for a in tableau_actions(st))
    res = search_foundation2(
        [_root(st, 80, timing="DEAL_NOW")],
        max_unique=40,
        time_limit_s=2.0,
        rss_abort_mb=4096,
        cost_ceiling=90,
        harvest_slack=3,
        harvest_limit=8,
    )
    assert res.witnesses
    assert res.incumbent is not None
    assert res.accounting_fail is False
    assert set(res.witnesses[0]["foundation_suits"]) == {"s", "d"}
    replay = st.clone()
    for action in as_actions(res.witnesses[0]["actions"]):
        apply_action(replay, action)
    assert len(replay.foundations) == 2


def test_v056_adapter_matches_kernel_on_tiny_envelope():
    st = _columns(
        [Card("c", 5), Card("c", 4)],
        [Card("c", 6)],
        [Card("h", 5)],
        [Card("h", 6)],
        *_kings(6),
    )
    roots = [_root(st, 90, timing="DEAL_NOW", category="E_DEAL_NOW")]
    kwargs = dict(max_unique=20, time_limit_s=2.0, rss_abort_mb=4096, cost_ceiling=95, harvest_slack=3, harvest_limit=8)
    adapter = search_component_aware_f2(roots, **kwargs)
    again = search_component_aware_f2(roots, **kwargs)
    assert adapter.unique == again.unique
    assert adapter.expanded == again.expanded
    assert adapter.generated == again.generated
    assert adapter.duplicate_skips == again.duplicate_skips
    assert adapter.stop_reason == again.stop_reason
    assert set(adapter.lane_pops) == {"cost", "s", "h", "d", "c", "work"}
    assert adapter.stop_reason == "unique limit"


def test_symmetry_identity_unchanged_under_column_permutation():
    a = _columns([Card("s", 13)], [Card("h", 12)], *_kings(8))
    b = _columns([Card("h", 12)], [Card("s", 13)], *_kings(8))
    assert pack_state(a) != pack_state(b)
    assert pack_post_stock_symmetry_state(a) == pack_post_stock_symmetry_state(b)
    c = _columns([Card("s", 13)], [Card("h", 11)], *_kings(8))
    assert pack_post_stock_symmetry_state(a) != pack_post_stock_symmetry_state(c)


def test_kernel_has_no_deal_or_suit_policy():
    src = inspect.getsource(run_search)
    assert "Clubs" not in src
    assert "Hearts" not in src
    assert "Diamonds" not in src
    assert "Spades" not in src
    assert "4925153" not in src
    assert "Foundation 2" not in src
    assert "component cover" not in src.lower()
    assert "tableau_actions" in src
