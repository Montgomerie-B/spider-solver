#!/usr/bin/env python3
"""Whole-deal scheduler v0.7 architecture note and natural-gate acceptance.

v0.7 graduates the bounded lead-source excavation macro from c893ef2.
It does not widen that recogniser, raise mixed-park caps, change TT/Deal
policy, or increase resource envelopes.
"""

from __future__ import annotations

import pprint
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.planner.diagnostics.lead_source_excavation_v0_7_report import (
    main as excavation_gates,
)

ARCHITECTURE = {
    "version": "v0.7",
    "graduates": (
        "v0.6 current-successor canonical economics",
        "v0.6 authorised Deal accounting",
        "v0.6 bounded receiver-uncover",
        "bounded post-stock lead-source excavation macro from c893ef2",
    ),
    "v0_6_retained": {
        "standing_key": "schedule.lane_sequence_priority.lead.ordering_key()",
        "authorised_deal_ids": "RESERVED/SPENT only",
        "receiver_uncover": "one-ply same-suit follow-up, bounded_payoff != exit",
        "tt_proof_identity_unchanged": True,
    },
    "v0_7_excavation": {
        "kind": "LEAD_SOURCE_EXCAVATION",
        "stock": 0,
        "shape": "two MIXED_SUIT_PARK peels + stable consume",
        "payoff": "consume exposes current-lead first-missing-edge source",
        "canonical": "lead.ordering_key after the complete macro is non-worse",
        "emit": "one replay-verified three-action successor, g += 3",
        "no_independent_peel_admission": True,
    },
    "non_features": (
        "no generic depth-3 search",
        "no empty-column planner",
        "no general excavation campaign",
        "no mixed-park cap increase",
        "no receiver-uncover widening",
        "no benchmark-specific route",
        "no TT/proof change",
        "no local-champion / CF / OPT-assignment change",
        "no _node_priority reorder",
        "no resource increase",
    ),
}


def _section(n, title, value):
    print(f"\n{n}. {title}")
    print(pprint.pformat(value, width=140, sort_dicts=False))
    sys.stdout.flush()


def main() -> int:
    print("WHOLE-DEAL SCHEDULER v0.7")
    sys.stdout.flush()
    _section(0, "architecture", ARCHITECTURE)
    print("\n== excavation + AA/Z gates ==")
    sys.stdout.flush()
    rc = excavation_gates()
    if rc != 0:
        print("STOP: v0.7 excavation gates failed", rc)
        return rc
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
