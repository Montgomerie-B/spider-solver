"""Compare uniform-cost and goal-directed anchored search on the v0.128 windows.

Does not write ``solutions/`` or the incumbent registry. A candidate is
accepted only by ``verify_complete_solution``.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, "src")

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.human_strategy.anchored import (
    build_checkpoints,
    search_segment,
    segment_lower_bound,
)
from spider.human_strategy.incumbent import IncumbentRejected, verify_complete_solution
from spider.metrics import format_action, parse_moves_file, replay_actions_detailed
from spider.research_actions import rss_mb

ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
CANONICAL = ROOT / "solutions" / "4925153_canonical.moves"
AUTONOMOUS = ROOT / "solutions" / "4925153_autonomous_185.moves"
OUT = ROOT / "artifacts" / "anchored_v0_129" / "results.json"

EXPECTED_HASHES = {
    "solutions/4925153_canonical.moves": "18338A08576AD24E9AF1F4BA2E7DB3E28768788DD511E823193B1937F3FEEF33",
    "solutions/4925153_autonomous_185.moves": "B19C56E957AC2666298A80118D54FF7FCA6C8114ED7D27590E2E98A017D4FB73",
}

WINDOWS = (
    {"name": "165-168", "start": 165, "end": 168, "cost": 3, "actions": ("move 6 8 9", "move 6 3 1", "move 8 6 9")},
    {"name": "146-149", "start": 146, "end": 149, "cost": 3, "actions": ("move 3 10 2", "move 3 4 7", "move 10 3 2")},
    {"name": "20-24", "start": 20, "end": 24, "cost": 4, "actions": ("move 4 8 1", "move 4 10 1", "move 8 10 1", "move 8 4 1")},
    {"name": "76-80", "start": 76, "end": 80, "cost": 4, "actions": ("move 6 1 2", "move 6 5 1", "move 5 6 2", "move 1 6 2")},
    {"name": "160-170", "start": 160, "end": 170, "cost": 10, "actions": None},
)

MAX_UNIQUE = 20000
TIME_LIMIT_S = 30.0
RSS_ABORT_MB = 3072.0
TOTAL = 172


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def replay_label(path: Path) -> dict:
    opening = SpiderState.from_cards(list(load_deal(DEAL)))
    actions = parse_moves_file(path)
    detailed = replay_actions_detailed(opening, actions)
    detailed["solved"] = bool(opening.is_solved() and len(opening.foundations) == 8 and not opening.stock)
    detailed["foundations"] = len(opening.foundations)
    detailed["sha256"] = sha256(path)
    return detailed


def classify(found, replay_ok: bool, segment_cost: int) -> str:
    if replay_ok:
        return "verified_complete_game_saving"
    if found.status == "FOUND" and found.cost is not None and found.cost < segment_cost:
        return "segment_rejoin_pending_or_failed_full_replay"
    if found.status == "EXHAUSTED":
        return "fully_exhausted_window"
    if found.status in {"NOT_CHEAPER", "IMPOSSIBLE"}:
        return "fully_exhausted_window"
    if found.status == "INCONCLUSIVE" or found.stop_reason in {"time limit", "unique limit", "rss abort", "abort"}:
        return "budget_limited_inconclusive"
    return found.status


def max_expanded_g(found) -> int:
    if not found.expanded_by_g:
        return -1
    return max(layer for layer, _count in found.expanded_by_g)


def main() -> None:
    hashes = {key: sha256(ROOT / key) for key in EXPECTED_HASHES}
    if hashes != EXPECTED_HASHES:
        raise SystemExit(f"solution hash mismatch: {hashes}")
    canonical = replay_label(CANONICAL)
    autonomous = replay_label(AUTONOMOUS)
    if canonical["mobilityware_moves"] != 172 or canonical["foundations"] != 8 or not canonical["solved"]:
        raise SystemExit(f"172 replay failed: {canonical}")
    if autonomous["mobilityware_moves"] != 185 or autonomous["foundations"] != 8 or not autonomous["solved"]:
        raise SystemExit(f"185 replay failed: {autonomous}")

    opening = SpiderState.from_cards(list(load_deal(DEAL)))
    actions = parse_moves_file(CANONICAL)
    verify_complete_solution(
        opening,
        actions,
        expected_cost=172,
        source="imported",
        source_id="solutions/4925153_canonical.moves",
    )
    checkpoints = build_checkpoints(opening, actions)
    if checkpoints[-1].g != 172:
        raise SystemExit(f"checkpoint total {checkpoints[-1].g}")

    rows = []
    accepted = []
    for spec in WINDOWS:
        start, end = spec["start"], spec["end"]
        played = tuple(format_action(action) for action in actions[start:end])
        if spec["actions"] is not None and played != spec["actions"]:
            raise SystemExit(f"{spec['name']} actions {played} != {spec['actions']}")
        source = checkpoints[start]
        target = checkpoints[end]
        segment_cost = target.g - source.g
        if segment_cost != spec["cost"]:
            raise SystemExit(f"{spec['name']} cost {segment_cost} != {spec['cost']}")
        prefix = source.g
        suffix = TOTAL - target.g
        bound = segment_lower_bound(source.state, target.state)
        step_costs = [checkpoints[index + 1].g - checkpoints[index].g for index in range(start, end)]
        for policy, exhaustive in (("ucs", True), ("goal", False)):
            print(f"START {spec['name']} {policy}", flush=True)
            rss_before = rss_mb()
            found = search_segment(
                source.state,
                target.state,
                segment_cost,
                time_limit_s=TIME_LIMIT_S,
                max_unique=MAX_UNIQUE,
                rss_abort_mb=RSS_ABORT_MB,
                exhaustive=exhaustive,
                policy=policy,
            )
            rss_after = rss_mb()
            replacement = tuple(format_action(action) for action in found.actions)
            full_cost = None
            replay_ok = False
            replay_error = None
            provenance = None
            if found.status == "FOUND" and found.cost is not None and found.cost < segment_cost:
                spliced = list(actions[:start]) + list(found.actions) + list(actions[end:])
                try:
                    route = verify_complete_solution(
                        opening,
                        spliced,
                        source="discovered",
                        source_id=f"anchored-{policy}-v0.129",
                    )
                    full_cost = int(route.cost)
                    solved = bool(route.solved and route.foundations == 8)
                    replay_ok = bool(solved and full_cost <= 171)
                    provenance = {
                        "replacement": "independently_discovered_segment",
                        "prefix": "reused_verified_prefix",
                        "suffix": "reused_verified_suffix",
                        "route": "incumbent_guided_splice",
                        "independent_cold_complete": False,
                        "reference_actions_preloaded": False,
                        "policy": policy,
                        "cost_optimal_segment": bool(found.cost_optimal),
                    }
                    if replay_ok:
                        accepted.append(
                            {
                                "name": spec["name"],
                                "policy": policy,
                                "start": start,
                                "end": end,
                                "replacement": list(replacement),
                                "replacement_cost": int(found.cost),
                                "full_cost": full_cost,
                                "cost_optimal_segment": bool(found.cost_optimal),
                            }
                        )
                except IncumbentRejected as exc:
                    replay_error = str(exc)
            depth = max_expanded_g(found)
            row = {
                "name": spec["name"],
                "policy": policy,
                "exhaustive": exhaustive,
                "start": start,
                "end": end,
                "played_actions": list(played),
                "played_step_costs": step_costs,
                "played_cost": segment_cost,
                "prefix_cost": prefix,
                "suffix_cost": suffix,
                "kernel_ceiling": segment_cost - 1,
                "segment_lower_bound": bound,
                "source_g": source.g,
                "target_g": target.g,
                "source_public": source.public(),
                "target_public": target.public(),
                "status": found.status,
                "stop_reason": found.stop_reason,
                "outcome": classify(found, replay_ok, segment_cost),
                "proof": bool(found.proof),
                "cost_optimal": bool(found.cost_optimal),
                "expanded": found.expanded,
                "unique": found.unique,
                "generated": found.generated,
                "ceiling_prunes": found.ceiling_prunes,
                "lower_bound_prunes": found.lower_bound_prunes,
                "duplicate_skips": found.duplicate_skips,
                "stale_skips": found.stale_skips,
                "zero_cost_actions": found.zero_cost_actions,
                "target_rejoins": found.target_rejoins,
                "cheapest_or_first_cost": found.cost,
                "replacement_actions": list(replacement),
                "elapsed_s": round(found.elapsed_s, 3),
                "affinity_s": round(found.affinity_s, 3),
                "affinity_calls": found.affinity_calls,
                "peak_rss_mb": found.peak_rss_mb,
                "rss_before_mb": rss_before,
                "rss_after_mb": rss_after,
                "min_g": found.min_g,
                "max_g": found.max_g,
                "max_expanded_g": depth,
                "reached_g2": depth >= 2,
                "reached_g3": depth >= 3,
                "min_h": found.min_h,
                "max_h": found.max_h,
                "expanded_by_g": list(found.expanded_by_g),
                "generated_by_g": list(found.generated_by_g),
                "lane_exp": list(found.lane_exp),
                "full_replay_ok": replay_ok,
                "full_replay_cost": full_cost,
                "full_replay_error": replay_error,
                "provenance": provenance,
            }
            rows.append(row)
            print(
                f"DONE {spec['name']} {policy} status={found.status} stop={found.stop_reason} "
                f"expanded={found.expanded} unique={found.unique} generated={found.generated} "
                f"ceiling={found.ceiling_prunes} lb={found.lower_bound_prunes} "
                f"dup={found.duplicate_skips} zero={found.zero_cost_actions} "
                f"rejoins={found.target_rejoins} best={found.cost} "
                f"depth={depth} by_g={list(found.expanded_by_g)} "
                f"lanes={list(found.lane_exp)} elapsed={found.elapsed_s:.3f} "
                f"affinity_s={found.affinity_s:.3f} peak={found.peak_rss_mb} "
                f"optimal={found.cost_optimal}",
                flush=True,
            )
            if spec["name"] == "20-24" and policy == "ucs":
                if found.status != "EXHAUSTED" or found.target_rejoins != 0:
                    raise SystemExit("UCS negative control 20-24 did not stay exhausted")

    hashes_after = {key: sha256(ROOT / key) for key in EXPECTED_HASHES}
    payload = {
        "schema": "spider-goal-directed-anchored-0.129",
        "deal": "4925153",
        "workers": 1,
        "max_unique": MAX_UNIQUE,
        "time_limit_s": TIME_LIMIT_S,
        "rss_abort_mb": RSS_ABORT_MB,
        "reference_actions_preloaded": False,
        "production_incumbent_overwritten": False,
        "canonical_replay": canonical,
        "autonomous_replay": autonomous,
        "hashes_before": hashes,
        "hashes_after": hashes_after,
        "hashes_unchanged": hashes_after == EXPECTED_HASHES,
        "windows": rows,
        "accepted": accepted,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"WROTE {OUT}", flush=True)
    print(f"ACCEPTED {len(accepted)} HASHES_OK {hashes_after == EXPECTED_HASHES}", flush=True)


if __name__ == "__main__":
    main()
