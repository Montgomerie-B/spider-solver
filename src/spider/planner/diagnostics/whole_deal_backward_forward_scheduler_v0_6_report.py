#!/usr/bin/env python3
"""Whole-deal scheduler v0.6 architecture note and natural-gate acceptance.

v0.6 graduates two already-validated behaviours from e094efa.  It does not
add later forensic-audit ideas (CF-A/B/C/D, OPT assignment, MERGE_READY
capacity counting, local-champion override, TT-covered maturation demotion,
TT identity changes, new representatives, resource increases, new successor
families, or _node_priority reordering).

A. Current-state frontier economics
   Standing maturation priority uses the successor's already-attached
   FoundationLaneMaturationAssessment.ordering_key().  Incoming-edge
   maturation history is telemetry only.  Anonymous Deal debt discharges
   one unit only for RESERVED/SPENT epoch-transition opportunity ids.
   QUALIFIED-only and unauthorised RAW_DEAL remain penalised.  Exact TT
   identity and proof pruning are unchanged.

B. Receiver-uncover
   CLEAN may admit a MIXED_SUIT_PARK only when one-ply evidence shows:
   an existing same-suit receiver, an exact immediate legal follow-up,
   fragment reduction >= 1, no stable join broken, and non-regressing
   successor canonical lead economics.  bounded_payoff is a PAYOFF fact
   and is not a parked-card EXIT.  There is no generic two-ply search and
   no global speculative-park widening.

NON-CHANGES (later audits; unimplemented):
   - duplicate-lane assignment remains imperfect and unmodified
   - MERGE_READY remains lane-local descriptive evidence, not independent
     suit-capacity counting
   - TT-covered empty maturation exists but has no safe cheap production gate
   - no local-champion suppression
   - no current _node_priority reorder beyond the v0.6 current-lead key
"""

from __future__ import annotations

import pprint
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.planner.anytime_controller import solve_anytime
from spider.planner.diagnostics.anytime_whole_game_controller_v0_6_report import (
    _node,
    _opening_anchor_config,
)
from spider.planner.diagnostics.anytime_whole_game_controller_v0_8_report import (
    _gate_f_config as _gate_z_base_config,
    _gate_g_config as _gate_aa_base_config,
)
from spider.planner.diagnostics.whole_deal_backward_forward_scheduler_v0_4_report import (
    _gate_envelope,
)
from spider.planner.diagnostics.receiver_uncover_v0_6_report import (
    _run,
    _summarize_gate,
    _z_safety,
)


DEAL_PATH = ROOT / "deals" / "4925153.txt"

ARCHITECTURE = {
    "version": "v0.6",
    "graduates": (
        "current-successor canonical economics in frontier ordering",
        "bounded receiver-uncover tactical compensation",
    ),
    "current_state_frontier": {
        "standing_key": "schedule.lane_sequence_priority.lead.ordering_key()",
        "no_stale_incoming_maturation_privilege": True,
        "authorised_deal_ids": "RESERVED/SPENT only",
        "tt_proof_identity_unchanged": True,
    },
    "receiver_uncover": {
        "park_class": "MIXED_SUIT_PARK",
        "requires_existing_same_suit_receiver": True,
        "exact_immediate_followup": True,
        "fragment_reduction_min": 1,
        "no_stable_join_broken": True,
        "canonical_economics_non_regressing": True,
        "bounded_payoff_distinct_from_exit": True,
        "no_generic_two_ply": True,
        "no_speculative_park_widening": True,
    },
    "non_changes": (
        "duplicate-lane assignment unmodified",
        "MERGE_READY is lane-local descriptive evidence, not suit-capacity counting",
        "TT-covered empty maturation has no production gate",
        "no local-champion suppression",
        "no further _node_priority reorder",
        "no CF-A/B/C/D",
        "no OPT assignment",
        "no TT policy change",
        "no resource increase",
        "no new successor family",
    ),
}


def _section(n, title, value):
    print(f"\n{n}. {title}")
    print(pprint.pformat(value, width=140, sort_dicts=False))
    sys.stdout.flush()


def main() -> int:
    cards = tuple(load_deal(DEAL_PATH))
    opening = SpiderState.from_cards(list(cards))
    print("WHOLE-DEAL SCHEDULER v0.6")
    sys.stdout.flush()
    _section(0, "architecture", ARCHITECTURE)

    anchor = _node(solve_anytime(opening, cards, None, _opening_anchor_config()))
    if (anchor.g, len(anchor.state.foundations), len(anchor.state.stock)) != (21, 1, 30):
        print("STOP: cost-21 regression")
        return 1

    print("\n== Gate AA ==")
    sys.stdout.flush()
    aa_config = _gate_envelope(_gate_aa_base_config, 180.0, 50, 500_000)
    aa_result = _run(opening, cards, aa_config)
    aa = _summarize_gate("AA", aa_result, opening)
    _section(1, "Gate AA", aa)
    uncover = aa["receiver_uncover"]
    if uncover["generated"] <= 0 or uncover["tt_admitted"] <= 0:
        print("STOP: receiver-uncover did not naturally occur")
        return 2
    if not aa["replay_ok"]:
        print("STOP: AA replay failed")
        return 2
    follow = uncover["followup_realised_on_expansion"]
    print(
        f" AA uncover generated={uncover['generated']} tt_admitted={uncover['tt_admitted']} "
        f"followup_realised={follow} replay_ok={aa['replay_ok']}",
        flush=True,
    )

    print("\n== Gate Z ==")
    sys.stdout.flush()
    z_config = _gate_envelope(_gate_z_base_config, 90.0, 25, 300_000)
    z_result = _run(anchor.state, cards, z_config)
    z = _summarize_gate("Z", z_result, anchor.state)
    z_safety = _z_safety(z_result, cards, z_config)
    z_safety["replay_ok"] = z["replay_ok"]
    z_f1 = z["best_F"] is not None and z["best_F"][1] >= 1
    _section(2, "Gate Z", z)
    _section(3, "Gate Z safety", z_safety)
    if not z_f1:
        print("STOP: F1 not retained")
        return 3
    z_fail = bool(
        not z["replay_ok"]
        or z_safety["uncover_before_join"]
        or z_safety["speculative_uncover_fallback"]
        or z_safety["must_starved"]
        or z_safety["unauth_zero_debt_deals"]
    )
    if z_fail:
        print("STOP: Z safety failed")
        return 4
    print(
        f" Z F1={z_f1} replay_ok={z['replay_ok']} must_starved={z_safety['must_starved']} "
        f"unauth_zero_debt={z_safety['unauth_zero_debt_deals']} "
        f"speculative_fallback={z_safety['speculative_uncover_fallback']}",
        flush=True,
    )
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
