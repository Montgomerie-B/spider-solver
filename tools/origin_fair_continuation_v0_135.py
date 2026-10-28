"""One origin-fair continuation from the unchanged v0.134 macro portfolio.

Discovery stays at 8 tableau actions, 4 paid moves, 4,000 identities, and
6 seconds. The continuation is one shared 20,000-state, 45-second, 512 MB
search. Each admitted root has its own goal lane and cost lane. The v0.134
continuation is not rerun. Solution files are not rewritten.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, "src")

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import format_action, parse_moves_file, replay_actions_detailed
from spider.origin_fair_continuation import (
    CONTINUATION_RSS_MB,
    CONTINUATION_TIME_S,
    CONTINUATION_UNIQUE,
    HISTORICAL_V0134,
    SCHEMA,
    search_origin_fair,
)
from spider.purposeful_macro import (
    CEILING,
    CHECKPOINT_PREP,
    DISCOVERY_DEPTH,
    DISCOVERY_PAID,
    DISCOVERY_RSS_MB,
    DISCOVERY_TIME_S,
    DISCOVERY_UNIQUE,
    PROVENANCE,
    accept_improved_route,
    compose_discovered_route,
    discover_macros,
    roots_from_portfolio,
)
from spider.stock_boundary_bridge import load_verified_bridge_inputs

ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
CANONICAL = ROOT / "solutions" / "4925153_canonical.moves"
AUTONOMOUS = ROOT / "solutions" / "4925153_autonomous_185.moves"
PREVIOUS = ROOT / "artifacts" / "purposeful_macro_v0_134" / "results.json"
OUT = ROOT / "artifacts" / "origin_fair_v0_135" / "results.json"

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


def fingerprint(item: dict) -> dict:
    return {
        "actions": list(item["actions"]),
        "g_post": item["g_post"],
        "h_post": item["h_post"],
        "f_post": item["f_post"],
        "hits": item["hits"],
        "post_pack": item["post_pack"],
        "symmetry": item["symmetry"],
    }


def same_portfolio(live: list, recorded: list) -> bool:
    if len(live) != len(recorded):
        return False
    return all(fingerprint(left) == fingerprint(right) for left, right in zip(live, recorded))


def load_previous() -> dict:
    if not PREVIOUS.is_file():
        return {}
    return json.loads(PREVIOUS.read_text(encoding="utf-8"))


def main() -> None:
    before = hashes()
    if before != EXPECTED_HASHES:
        raise SystemExit(f"solution hash mismatch before the continuation: {before}")
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
    previous = load_previous()
    live_rows = [item.public() for item in discovery.portfolio]
    recorded_rows = list((previous.get("discovery") or {}).get("portfolio") or [])
    paired = bool(recorded_rows) and same_portfolio(live_rows, recorded_rows)
    print(
        f"DISCOVERY gate_b={discovery.gate_b} portfolio={len(discovery.portfolio)} "
        f"unique={discovery.unique} stop={discovery.stop_reason} "
        f"elapsed={discovery.elapsed_s:.3f}s paired_with_v0134={paired}",
        flush=True,
    )
    for index, row in enumerate(live_rows):
        print(
            f"ROOT {index} g={row['g_post']} h={row['h_post']} f={row['f_post']} "
            f"hits={row['hits']} actions={row['actions']}",
            flush=True,
        )
    continuation = None
    verification = None
    full_actions = []
    outcome = "discovery_miss"
    if discovery.gate_b and discovery.witness is not None:
        if not discovery.portfolio:
            outcome = "no_admissible_root"
        else:
            continuation = search_origin_fair(
                roots_from_portfolio(discovery.portfolio),
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
        raise SystemExit(f"solution hash mismatch after the continuation: {after}")
    historical = dict(HISTORICAL_V0134)
    historical["expansions_by_origin"] = list(HISTORICAL_V0134["expansions_by_origin"])
    baseline = (previous.get("continuation") or {}) if paired else historical
    payload = {
        "schema": SCHEMA,
        "deal": "4925153",
        "branch_intent": "local/origin-fair-continuation-v0-135",
        "outcome": outcome,
        "provenance": PROVENANCE if outcome == "improvement" else "no complete route established",
        "independent_cold_complete": False,
        "canonical_post_sd5_search_repeated": False,
        "post_sd5_budgets_increased": False,
        "continuation_caps_raised": False,
        "macro_generator_unchanged": True,
        "scheduling_variable": "origin_lane_keys_fn",
        "empty_count_is_objective": False,
        "v0_134_comparison": "paired" if paired else "historical only",
        "v0_134_artifact_present": bool(previous),
        "v0_134_baseline": baseline,
        "historical_v0134": historical,
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
        "v0_136_started": False,
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
            f"goal={continuation.goal_expansions} cost={continuation.cost_expansions} "
            f"elapsed={continuation.elapsed_s:.3f}s expansions={list(continuation.expansions_by_origin)}",
            flush=True,
        )
        for row in continuation.origins:
            print(
                f"ORIGIN {row['index']} status={row['status']} expanded={row['expanded']} "
                f"popped={row['popped']} selected={row['selected']} admitted={row['admitted']} "
                f"g={row['g']} h={row['h']} f={row['f']}",
                flush=True,
            )
    print(f"WROTE {OUT}", flush=True)


if __name__ == "__main__":
    main()
