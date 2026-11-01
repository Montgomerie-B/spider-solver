"""Retained-memory accounting. These tests do not run a long search."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.global_search_experiment import search_suit_ordered, suit_lane_keys
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.research_actions import all_legal_actions, opening_from_deal
from spider.search_kernel import SearchLimits, reconstruct_path, run_search
from spider.search_memory_profile import account_retained
from spider.whole_game_anytime import LANES

DEAL = ROOT / "deals" / "4925153.txt"


def test_diagnostics_hook_preserves_fixed_work_order_and_accounts_packs():
    opening = opening_from_deal(DEAL)
    kwargs = dict(
        time_limit_s=10.0,
        max_unique=20,
        rss_abort_mb=512,
        mode="cold",
        cost_ceiling=8,
        advice_fn=None,
    )
    plain = search_suit_ordered(opening, **kwargs)
    diagnostics = {}
    hooked = search_suit_ordered(opening.clone(), kernel_diagnostics=diagnostics, **kwargs)
    assert plain.actions == hooked.actions
    assert plain.unique == hooked.unique
    assert plain.expanded == hooked.expanded
    assert plain.stale_skips == hooked.stale_skips
    report = account_retained(diagnostics, ceiling=hooked.cost_ceiling)
    assert report["node_count"] == plain.unique
    assert (
        report["ident_same_object_as_store"]
        + report["ident_equal_payload_distinct_object"]
        + report["ident_different_payload"]
        == report["node_count"]
    )
    assert report["ident_equal_payload_distinct_object"] + report["ident_different_payload"] > 0 or report[
        "ident_same_object_as_store"
    ] == report["node_count"]
    assert report["best_g_keys"] == report["node_count"]
    assert report["best_g_keys_shared_with_node"] + report["best_g_keys_exclusive"] == report["best_g_keys"]
    assert report["heap_entries"] >= report["live_heap_entries"]
    assert report["accounted_bytes"] > report["store_payload_bytes"]
    assert set(report["lanes"]) == {
        "cost",
        "foundation",
        "reveal",
        "workspace",
        "construction",
        "prep",
        "epoch",
    }


def _expansion_trace():
    trace = []

    def hook(state, g, node_i):
        trace.append((int(g), pack_whole_game_identity(state), int(node_i)))

    return trace, hook


def test_compact_representation_matches_reference_order_and_uses_less_heap():
    opening = opening_from_deal(DEAL)
    kwargs = dict(
        time_limit_s=30.0,
        max_unique=250,
        rss_abort_mb=1024,
        mode="optimise",
        incumbent_cost=158,
        cost_ceiling=157,
        advice_fn=None,
        prefix_actions=(),
    )
    plain_trace, plain_hook = _expansion_trace()
    plain_diag = {}
    plain = search_suit_ordered(opening, kernel_diagnostics=plain_diag, expand_hook=plain_hook, **kwargs)
    compact_trace, compact_hook = _expansion_trace()
    compact_diag = {}
    compact = search_suit_ordered(
        opening.clone(),
        kernel_diagnostics=compact_diag,
        expand_hook=compact_hook,
        representation="compact",
        **kwargs,
    )
    assert plain_trace == compact_trace
    assert plain.unique == compact.unique == 250
    assert plain.expanded == compact.expanded
    assert plain.generated == compact.generated
    assert plain.duplicate_skips == compact.duplicate_skips
    assert plain.stale_skips == compact.stale_skips
    assert plain.lower_bound_prunes == compact.lower_bound_prunes
    assert plain_diag["proof_prune_identities"] == compact_diag["proof_prune_identities"]
    assert plain_diag["ceiling_prunes"] == compact_diag["ceiling_prunes"]
    plain_report = account_retained(plain_diag, ceiling=plain.cost_ceiling)
    compact_report = account_retained(compact_diag, ceiling=compact.cost_ceiling)
    assert plain_report["heap_entries"] == compact_report["heap_entries"]
    assert plain_report["live_heap_entries"] == compact_report["live_heap_entries"]
    assert compact_report["buckets"]["heap_entry"] < plain_report["buckets"]["heap_entry"]
    assert plain_report["ident_same_object_as_store"] == 0
    assert compact_report["ident_same_object_as_store"] > 0
    assert "node_dict" not in compact_report["buckets"]
    node_i = plain_trace[-1][2]
    assert reconstruct_path(plain_diag["nodes"], node_i) == reconstruct_path(compact_diag["nodes"], node_i)


def _bounded(representation, *, ceiling, roots, bound):
    return run_search(
        roots,
        limits=SearchLimits(max_unique=8, time_limit_s=10.0, rss_abort_mb=1024, cost_ceiling=ceiling),
        identity_fn=pack_whole_game_identity,
        store_fn=pack_state,
        unpack_fn=unpack_state,
        lane_names=LANES,
        lane_keys_fn=suit_lane_keys,
        actions_fn=all_legal_actions,
        lower_bound_fn=bound,
        is_terminal=lambda _board: False,
        representation=representation,
    )


def test_compact_keeps_lower_g_reopening_and_proof_equality():
    opening = opening_from_deal(DEAL)
    store = pack_state(opening).hex()
    roots = [
        {"g": 9, "ordered_digest": store},
        {"g": 4, "ordered_digest": store},
    ]
    plain_roots = _bounded("reference", ceiling=20, roots=roots, bound=None)
    compact_roots = _bounded("compact", ceiling=20, roots=roots, bound=None)
    assert [node.g for node in plain_roots.nodes if node.parent < 0] == [4]
    assert [node.g for node in compact_roots.nodes if node.parent < 0] == [4]
    assert plain_roots.unique == compact_roots.unique
    assert plain_roots.zero_cost_actions == compact_roots.zero_cost_actions
    assert reconstruct_path(plain_roots.nodes, len(plain_roots.nodes) - 1) == reconstruct_path(
        compact_roots.nodes, len(compact_roots.nodes) - 1
    )

    proof_root = [{"g": 0, "ordered_digest": store}]

    def bound(_state, _g):
        return 1

    plain = _bounded("reference", ceiling=1, roots=proof_root, bound=bound)
    compact = _bounded("compact", ceiling=1, roots=proof_root, bound=bound)
    assert plain.lower_bound_prunes == compact.lower_bound_prunes > 0
    assert plain.proof_prune_identities == compact.proof_prune_identities
    assert plain.unique == compact.unique
    assert all(node.g + 1 <= 1 for node in plain.nodes)
    assert all(node.g + 1 <= 1 for node in compact.nodes)
    assert plain.nodes[0].g == 0
