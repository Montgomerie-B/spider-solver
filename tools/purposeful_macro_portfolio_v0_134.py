"""One purposeful macro portfolio and, if it qualifies, one multi-root bridge.

Discovery is capped at 8 tableau actions, 4 paid moves, 4,000 identities,
and 6 seconds. The continuation, when the landing demonstration succeeds,
is one 20,000-state, 45-second, 512 MB search. The canonical post-SD5
search is not repeated and its budgets are not raised. Solution files are
not rewritten.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, "src")

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.human_strategy.anchored import build_checkpoints
from spider.metrics import format_action, parse_moves_file, replay_actions_detailed
from spider.purposeful_macro import (
    CEILING,
    CHECKPOINT_PREP,
    CONTINUATION_RSS_MB,
    CONTINUATION_TIME_S,
    CONTINUATION_UNIQUE,
    DISCOVERY_DEPTH,
    DISCOVERY_PAID,
    DISCOVERY_RSS_MB,
    DISCOVERY_TIME_S,
    DISCOVERY_UNIQUE,
    GATE_B_G_POST,
    GATE_B_LANDINGS,
    HISTORICAL_SINGLE_ROOT,
    PROVENANCE,
    SCHEMA,
    accept_improved_route,
    compose_discovered_route,
    discover_macros,
    roots_from_portfolio,
    search_bridge_roots,
)
from spider.stock_boundary_bridge import EARLY_PREP, load_verified_bridge_inputs

ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
CANONICAL = ROOT / "solutions" / "4925153_canonical.moves"
AUTONOMOUS = ROOT / "solutions" / "4925153_autonomous_185.moves"
OUT = ROOT / "artifacts" / "purposeful_macro_v0_134" / "results.json"

EXPECTED_HASHES = {
    "solutions/4925153_canonical.moves": "18338A08576AD24E9AF1F4BA2E7DB3E28768788DD511E823193B1937F3FEEF33",
    "solutions/4925153_autonomous_185.moves": "B19C56E957AC2666298A80118D54FF7FCA6C8114ED7D27590E2E98A017D4FB73",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def hashes() -> dict:
    return {name: sha256(ROOT / name) for name in EXPECTED_HASHES}


def replay_label(path: Path, opening: SpiderState) -> dict:
    actions = parse_moves_file(path)
    state = opening.clone()
    detailed = replay_actions_detailed(state, actions)
    return {
        "path": path.name,
        "actions": len(actions),
        "mobilityware_moves": detailed["mobilityware_moves"],
        "solved": bool(state.is_solved() and len(state.foundations) == 8 and not state.stock),
        "foundations": len(state.foundations),
        "sha256": sha256(path),
    }


def named_preparation() -> list:
    return [format_action(action) for action in EARLY_PREP if action != ("deal",)]


def main() -> None:
    before = hashes()
    if before != EXPECTED_HASHES:
        raise SystemExit(f"solution hash mismatch before the macro probe: {before}")
    opening = SpiderState.from_cards(list(load_deal(DEAL)))
    canonical = parse_moves_file(CANONICAL)
    canonical_label = replay_label(CANONICAL, opening)
    autonomous = replay_label(AUTONOMOUS, opening)
    if not canonical_label["solved"] or canonical_label["mobilityware_moves"] != 172:
        raise SystemExit("canonical 172 route did not replay")
    if not autonomous["solved"] or autonomous["mobilityware_moves"] != 185:
        raise SystemExit("autonomous 185 route did not replay")
    _early, table, targets, checkpoints = load_verified_bridge_inputs(opening, canonical)
    source = checkpoints[CHECKPOINT_PREP]
    print(
        f"CHECKPOINT {source.index} g={source.g} stock={source.stock_cards} "
        f"empty={source.empty_columns} foundations={source.foundations}",
        flush=True,
    )
    discovery = discover_macros(
        source.state,
        g0=source.g,
        max_depth=DISCOVERY_DEPTH,
        paid_moves=DISCOVERY_PAID,
        max_unique=DISCOVERY_UNIQUE,
        time_limit_s=DISCOVERY_TIME_S,
        rss_abort_mb=DISCOVERY_RSS_MB,
    )
    witness = discovery.witness
    named = named_preparation()
    witness_actions = [] if witness is None else witness.public()["actions"]
    print(
        f"DISCOVERY gate_b={discovery.gate_b} candidates={len(discovery.candidates)} "
        f"unique={discovery.unique} expanded={discovery.expanded} "
        f"zero_cost={discovery.zero_cost_actions} stop={discovery.stop_reason} "
        f"elapsed={discovery.elapsed_s:.3f}s witness={witness_actions}",
        flush=True,
    )
    continuation = None
    verification = None
    full_actions = []
    outcome = "discovery_miss"
    if discovery.gate_b and witness is not None:
        if not discovery.portfolio:
            outcome = "no_admissible_root"
        else:
            roots = roots_from_portfolio(discovery.portfolio)
            continuation = search_bridge_roots(
                roots,
                references=table,
                ordering_targets=targets,
                ceiling=CEILING,
                max_unique=CONTINUATION_UNIQUE,
                time_limit_s=CONTINUATION_TIME_S,
                rss_abort_mb=CONTINUATION_RSS_MB,
                progress=True,
            )
            if continuation.accepted:
                full_actions = compose_discovered_route(
                    canonical,
                    continuation.macro,
                    continuation.continuation,
                    continuation.remapped_suffix,
                )
                verified = accept_improved_route(
                    opening,
                    full_actions,
                    expected_cost=continuation.projected_cost,
                    ceiling=CEILING,
                )
                if verified is None:
                    outcome = "replay_rejected"
                    verification = {"ok": False, "projected_cost": continuation.projected_cost}
                else:
                    outcome = "improvement"
                    verification = {
                        "ok": True,
                        "cost": verified.cost,
                        "foundations": verified.foundations,
                        "actions": len(verified.actions),
                        "source": verified.source,
                    }
            elif continuation.inconclusive:
                outcome = "inconclusive"
            elif continuation.negative_within_cap:
                outcome = "negative_within_cap"
            elif continuation.stop_reason == "replay rejected":
                outcome = "replay_rejected"
            else:
                outcome = continuation.stop_reason or "inconclusive"
    after = hashes()
    if after != EXPECTED_HASHES:
        raise SystemExit(f"solution hash mismatch after the macro probe: {after}")
    payload = {
        "schema": SCHEMA,
        "deal": "4925153",
        "branch_intent": "local/purposeful-macro-portfolio-v0-134",
        "outcome": outcome,
        "provenance": PROVENANCE if outcome == "improvement" else "no complete route established",
        "independent_cold_complete": False,
        "canonical_post_sd5_search_repeated": False,
        "post_sd5_budgets_increased": False,
        "continuation_caps_raised": False,
        "macro_actions_implemented": True,
        "empty_count_is_objective": False,
        "historical_single_root": HISTORICAL_SINGLE_ROOT,
        "historical_comparison_limit": (
            "The v0.133 figure is one root at g=142. This portfolio starts "
            "from other pre-deal tableaux. The numbers are not a paired control."
        ),
        "gate_b_landings": GATE_B_LANDINGS,
        "gate_b_g_post": GATE_B_G_POST,
        "named_preparation_was_seeded": False,
        "named_preparation_matched": witness_actions == named,
        "named_preparation_observed": named,
        "ceiling": CEILING,
        "discovery_limits": {
            "depth": DISCOVERY_DEPTH,
            "paid_moves": DISCOVERY_PAID,
            "max_unique": DISCOVERY_UNIQUE,
            "time_limit_s": DISCOVERY_TIME_S,
            "rss_abort_mb": DISCOVERY_RSS_MB,
        },
        "continuation_limits": {
            "max_unique": CONTINUATION_UNIQUE,
            "time_limit_s": CONTINUATION_TIME_S,
            "rss_abort_mb": CONTINUATION_RSS_MB,
            "ran": continuation is not None,
        },
        "checkpoint": source.public(),
        "discovery": discovery.public(),
        "continuation": None if continuation is None else continuation.public(),
        "verification": verification,
        "full_route": [],
        "canonical_replay": canonical_label,
        "autonomous_replay": autonomous,
        "hashes_before": before,
        "hashes_after": after,
        "solution_files_unchanged": before == after,
        "f_166_is_not_a_route_judgement": True,
        "prefix_checkpoint": CHECKPOINT_PREP,
        "v0_135_started": False,
    }
    if outcome == "improvement":
        payload["full_route"] = [format_action(action) for action in full_actions]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"OUTCOME {outcome}", flush=True)
    if continuation is not None:
        print(
            f"CONTINUATION stop={continuation.stop_reason} accepted={continuation.accepted} "
            f"unique={continuation.unique} expanded={continuation.expanded} "
            f"generated={continuation.generated} proof_prunes={continuation.lower_bound_prunes} "
            f"min_f={continuation.min_f} max_foundations={continuation.max_foundations} "
            f"matches={continuation.reference_checkpoint_matches} "
            f"elapsed={continuation.elapsed_s:.3f}s expansions={list(continuation.expansions_by_origin)}",
            flush=True,
        )
    print(f"WROTE {OUT}", flush=True)


if __name__ == "__main__":
    main()
