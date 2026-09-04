#!/usr/bin/env python3
"""Whole-deal scheduler v0.8 architecture note and natural-gate acceptance.

v0.8 graduates the bounded face-down lead-edge excavation macro from a2fa330.
It does not widen that recogniser, raise mixed-park caps, change TT/Deal
policy, or increase resource envelopes.
"""

from __future__ import annotations

import pprint
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.planner.diagnostics.face_down_lead_edge_excavation_v0_8_report import (
    main as excavation_gates,
)

ARCHITECTURE = {
    "version": "v0.8",
    "graduates": (
        "v0.6 current-successor canonical economics",
        "v0.6 authorised Deal accounting",
        "v0.6 bounded receiver-uncover",
        "v0.7 bounded post-stock lead-source excavation",
        "bounded post-stock face-down lead-edge excavation macro from a2fa330",
    ),
    "v0_6_retained": {
        "standing_key": "schedule.lane_sequence_priority.lead.ordering_key()",
        "authorised_deal_ids": "RESERVED/SPENT only",
        "receiver_uncover": "one-ply same-suit follow-up, bounded_payoff != exit",
        "tt_proof_identity_unchanged": True,
    },
    "v0_7_retained": {
        "kind": "LEAD_SOURCE_EXCAVATION",
        "stock": 0,
        "shape": "two MIXED_SUIT_PARK peels + stable consume",
        "payoff": "consume exposes current-lead first-missing-edge source",
        "canonical": "global lead.ordering_key after the complete macro is non-worse",
    },
    "v0_8_excavation": {
        "kind": "FACE_DOWN_LEAD_EDGE_EXCAVATION",
        "stock": 0,
        "shape": "two MIXED_SUIT_PARK peels + stable consume of flipped X",
        "payoff": "consume exposes a scheduled-lane face-down missing-edge rank",
        "canonical": "owning lane.ordering_key after the complete macro is non-worse",
        "emit": "one replay-verified three-action successor, g += 3",
        "no_independent_peel_admission": True,
        "not_global_lead_override": True,
    },
    "common_architecture": (
        "strategic dependency",
        "short bounded tactical valley",
        "replay-verified macro",
        "ordinary production resumes",
    ),
    "non_features": (
        "no generic 3-ply search",
        "no generic excavation planning",
        "no arbitrary face-down-card targeting",
        "no empty-column planner",
        "no mixed-park cap increase",
        "no v0.7 widening",
        "no global-lead override",
        "no forced foundation-lane persistence",
        "no benchmark-specific route",
        "no Td/c10 excavation",
        "no local-champion / CF / OPT-assignment change",
        "no TT/proof change",
        "no _node_priority reorder",
        "no resource increase",
    ),
}


def _section(n, title, value):
    print(f"\n{n}. {title}")
    print(pprint.pformat(value, width=140, sort_dicts=False))
    sys.stdout.flush()


def main() -> int:
    print("WHOLE-DEAL SCHEDULER v0.8")
    sys.stdout.flush()
    _section(0, "architecture", ARCHITECTURE)
    print("\n== excavation + targeted continuation + AA/Z gates ==")
    sys.stdout.flush()
    rc = excavation_gates()
    if rc != 0:
        print("STOP: v0.8 excavation gates failed", rc)
        return rc
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
