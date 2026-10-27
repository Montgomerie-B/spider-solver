"""One bounded bridge from the verified early fifth deal onto the 172 route.

The search starts at corrected cost 142. It does not start from the
canonical post-SD5 checkpoint and it does not use that search's
80,000-state or 90-second budgets. A cap without a remapped continuation
is inconclusive. Solution files are not rewritten.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, "src")

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.human_strategy.incumbent import IncumbentRejected, verify_complete_solution
from spider.metrics import parse_moves_file, replay_actions_detailed
from spider.stock_boundary_bridge import (
    CANONICAL_TOTAL,
    CEILING,
    CHECKPOINT_PREP,
    MAX_UNIQUE,
    PROVENANCE,
    RSS_ABORT_MB,
    SCHEMA,
    TIME_LIMIT_S,
    BridgeContractError,
    compose_full_route,
    load_verified_bridge_inputs,
    search_route_bridge,
)

ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
CANONICAL = ROOT / "solutions" / "4925153_canonical.moves"
AUTONOMOUS = ROOT / "solutions" / "4925153_autonomous_185.moves"
OUT = ROOT / "artifacts" / "stock_boundary_v0_133" / "results.json"

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


def main() -> None:
    before = hashes()
    if before != EXPECTED_HASHES:
        raise SystemExit(f"solution hash mismatch before the bridge: {before}")
    opening = SpiderState.from_cards(list(load_deal(DEAL)))
    canonical = parse_moves_file(CANONICAL)
    autonomous = replay_label(AUTONOMOUS, opening)
    canonical_label = replay_label(CANONICAL, opening)
    if not canonical_label["solved"] or canonical_label["mobilityware_moves"] != CANONICAL_TOTAL:
        raise SystemExit("canonical 172 route did not replay")
    if not autonomous["solved"] or autonomous["mobilityware_moves"] != 185:
        raise SystemExit("autonomous 185 route did not replay")
    try:
        early, table, targets, _checkpoints = load_verified_bridge_inputs(opening, canonical)
    except BridgeContractError as exc:
        raise SystemExit(f"early route did not replay; search not started: {exc}") from exc
    print(
        f"EARLY g={early.g} h={early.h} f={early.f} landings={early.same_suit_landings} "
        f"already_on_reference={early.already_on_reference} targets={ [stop.index for stop in targets] }",
        flush=True,
    )
    found = search_route_bridge(
        early.state,
        g0=early.g,
        references=table,
        ordering_targets=targets,
        ceiling=CEILING,
        max_unique=MAX_UNIQUE,
        time_limit_s=TIME_LIMIT_S,
        rss_abort_mb=RSS_ABORT_MB,
        progress=True,
    )
    verification = None
    outcome = "inconclusive" if found.inconclusive else "negative_within_cap" if found.negative_within_cap else found.stop_reason
    full_actions = []
    if found.accepted:
        full_actions = compose_full_route(canonical, found.bridge, found.remapped_suffix)
        try:
            verified = verify_complete_solution(
                opening,
                full_actions,
                expected_cost=found.projected_cost,
                source=PROVENANCE,
                source_id="4925153-early-sd5-bridge",
            )
        except IncumbentRejected as exc:
            outcome = "replay_rejected"
            verification = {"ok": False, "error": str(exc)}
        else:
            if verified.cost <= CEILING and verified.foundations == 8 and verified.solved:
                outcome = "improvement"
                verification = {
                    "ok": True,
                    "cost": verified.cost,
                    "foundations": verified.foundations,
                    "actions": len(verified.actions),
                    "source": verified.source,
                }
            else:
                outcome = "replay_rejected"
                verification = {"ok": False, "cost": verified.cost}
    after = hashes()
    if after != EXPECTED_HASHES:
        raise SystemExit(f"solution hash mismatch after the bridge: {after}")
    payload = {
        "schema": SCHEMA,
        "deal": "4925153",
        "branch_intent": "local/stock-boundary-route-bridge-v0-133",
        "outcome": outcome,
        "provenance": PROVENANCE if outcome == "improvement" else "no complete route established",
        "independent_cold_complete": False,
        "canonical_post_sd5_search_repeated": False,
        "post_sd5_budgets_increased": False,
        "macro_actions_implemented": False,
        "ceiling": CEILING,
        "max_unique": MAX_UNIQUE,
        "time_limit_s": TIME_LIMIT_S,
        "rss_abort_mb": RSS_ABORT_MB,
        "early": early.public(),
        "reference_stops": len(table.stops),
        "ordering_targets": [stop.index for stop in targets],
        "search": found.to_dict(),
        "verification": verification,
        "full_route": [],
        "canonical_replay": canonical_label,
        "autonomous_replay": autonomous,
        "hashes_before": before,
        "hashes_after": after,
        "solution_files_unchanged": before == after,
        "f_166_is_not_a_route_judgement": True,
        "prefix_checkpoint": CHECKPOINT_PREP,
    }
    if outcome == "improvement":
        payload["full_route"] = [
            "deal" if action == ("deal",) else f"move {action[0] + 1} {action[1] + 1} {action[2]}"
            for action in full_actions
        ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        f"OUTCOME {outcome} stop={found.stop_reason} accepted={found.accepted} "
        f"unique={found.unique} expanded={found.expanded} generated={found.generated} "
        f"proof_prunes={found.lower_bound_prunes} min_f={found.min_f} "
        f"max_foundations={found.max_foundations} matches={found.reference_checkpoint_matches} "
        f"elapsed={found.elapsed_s:.3f}s affinity={found.affinity_s:.3f}s "
        f"rss={found.peak_rss_mb}",
        flush=True,
    )
    print(f"WROTE {OUT}", flush=True)


if __name__ == "__main__":
    main()
