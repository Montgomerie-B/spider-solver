"""Retained-memory accounting. These tests do not run a long search."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.global_search_experiment import search_suit_ordered
from spider.research_actions import opening_from_deal
from spider.search_memory_profile import account_retained

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
