"""Bounded exact-state re-search of the five inconclusive 172 windows.

This driver calls the existing ``search_segment``. It does not preload the
played actions, does not write ``solutions/``, and does not update the
incumbent registry. A candidate is accepted only by ``verify_complete_solution``.
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
    states_rejoin,
)
from spider.human_strategy.evaluation import admissible_remaining
from spider.human_strategy.incumbent import IncumbentRejected, proof_prune, verify_complete_solution
from spider.metrics import format_action, parse_moves_file, replay_actions, replay_actions_detailed
from spider.packed_state import pack_state
from spider.research_actions import rss_mb

ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
CANONICAL = ROOT / "solutions" / "4925153_canonical.moves"
AUTONOMOUS = ROOT / "solutions" / "4925153_autonomous_185.moves"
OUT = ROOT / "artifacts" / "anchored_v0_128" / "results.json"

EXPECTED_HASHES = {
    "solutions/4925153_canonical.moves": "18338A08576AD24E9AF1F4BA2E7DB3E28768788DD511E823193B1937F3FEEF33",
    "solutions/4925153_autonomous_185.moves": "B19C56E957AC2666298A80118D54FF7FCA6C8114ED7D27590E2E98A017D4FB73",
}

# Checkpoint indices are actions already applied. The action slice is [start:end].
WINDOWS = (
    {
        "name": "165-168",
        "start": 165,
        "end": 168,
        "cost": 3,
        "actions": ("move 6 8 9", "move 6 3 1", "move 8 6 9"),
        "v0_118": "INCONCLUSIVE at the 2500 unique cap",
    },
    {
        "name": "146-149",
        "start": 146,
        "end": 149,
        "cost": 3,
        "actions": ("move 3 10 2", "move 3 4 7", "move 10 3 2"),
        "v0_118": "INCONCLUSIVE at the 2500 unique cap",
    },
    {
        "name": "20-24",
        "start": 20,
        "end": 24,
        "cost": 4,
        "actions": ("move 4 8 1", "move 4 10 1", "move 8 10 1", "move 8 4 1"),
        "v0_118": "INCONCLUSIVE at the 2500 unique cap",
    },
    {
        "name": "76-80",
        "start": 76,
        "end": 80,
        "cost": 4,
        "actions": ("move 6 1 2", "move 6 5 1", "move 5 6 2", "move 1 6 2"),
        "v0_118": "INCONCLUSIVE at the 2500 unique cap",
    },
    {
        "name": "160-170",
        "start": 160,
        "end": 170,
        "cost": 10,
        "actions": None,
        "v0_118": "INCONCLUSIVE at the 2500 unique cap",
    },
)

MAX_UNIQUE = 20000
TIME_LIMIT_S = 30.0
RSS_ABORT_MB = 3072.0
TOTAL = 172


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def layout(state: SpiderState) -> dict:
    columns = []
    for index, column in enumerate(state.columns, start=1):
        columns.append(
            {
                "column": index,
                "face_down": [str(card) for card in column.face_down],
                "face_up": [str(card) for card in column.face_up],
            }
        )
    foundations = []
    for sequence in state.foundations:
        foundations.append([str(card) for card in sequence])
    return {
        "columns": columns,
        "foundations": foundations,
        "stock": [str(card) for card in state.stock],
        "empty_columns": [index + 1 for index, column in enumerate(state.columns) if column.is_empty()],
        "state_id": pack_state(state).hex(),
    }


def overlaps(left: dict, right: dict) -> bool:
    return left["start"] < right["end"] and right["start"] < left["end"]


def splice(actions, pieces) -> list:
    ordered = sorted(pieces, key=lambda item: item["start"])
    out = []
    cursor = 0
    for piece in ordered:
        if piece["start"] < cursor:
            raise ValueError("overlapping splice")
        out.extend(actions[cursor : piece["start"]])
        out.extend(piece["replacement"])
        cursor = piece["end"]
    out.extend(actions[cursor:])
    return out


def replay_label(path: Path) -> dict:
    opening = SpiderState.from_cards(list(load_deal(DEAL)))
    actions = parse_moves_file(path)
    detailed = replay_actions_detailed(opening, actions)
    detailed["solved"] = bool(opening.is_solved() and len(opening.foundations) == 8 and not opening.stock)
    detailed["foundations"] = len(opening.foundations)
    detailed["sha256"] = sha256(path)
    return detailed


def main() -> None:
    hashes = {
        "solutions/4925153_canonical.moves": sha256(CANONICAL),
        "solutions/4925153_autonomous_185.moves": sha256(AUTONOMOUS),
    }
    if hashes != EXPECTED_HASHES:
        raise SystemExit(f"solution hash mismatch: {hashes}")
    canonical_replay = replay_label(CANONICAL)
    autonomous_replay = replay_label(AUTONOMOUS)
    if canonical_replay["mobilityware_moves"] != 172 or canonical_replay["foundations"] != 8:
        raise SystemExit(f"172 replay failed: {canonical_replay}")
    if autonomous_replay["mobilityware_moves"] != 185 or autonomous_replay["foundations"] != 8:
        raise SystemExit(f"185 replay failed: {autonomous_replay}")
    if not canonical_replay["solved"] or not autonomous_replay["solved"]:
        raise SystemExit("a historical route did not solve")

    opening = SpiderState.from_cards(list(load_deal(DEAL)))
    actions = parse_moves_file(CANONICAL)
    verified = verify_complete_solution(
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
        if prefix + segment_cost + suffix != TOTAL:
            raise SystemExit(f"{spec['name']} prefix/suffix does not add to 172")
        bound = segment_lower_bound(source.state, target.state)
        deals = sum(1 for action in actions[start:end] if action == ("deal",))
        step_costs = [checkpoints[index + 1].g - checkpoints[index].g for index in range(start, end)]
        h = admissible_remaining(source.state)
        print(
            f"START {spec['name']} cost={segment_cost} prefix={prefix} suffix={suffix} bound={bound}",
            flush=True,
        )
        rss_before = rss_mb()
        found = search_segment(
            source.state,
            target.state,
            segment_cost,
            time_limit_s=TIME_LIMIT_S,
            max_unique=MAX_UNIQUE,
            rss_abort_mb=RSS_ABORT_MB,
            exhaustive=True,
        )
        rss_after = rss_mb()
        replacement = tuple(format_action(action) for action in found.actions)
        full_cost = None
        replay_ok = False
        solved_replay = False
        replay_error = None
        provenance = None
        if found.status == "FOUND" and found.cost is not None and found.cost < segment_cost:
            spliced = list(actions[:start]) + list(found.actions) + list(actions[end:])
            try:
                route = verify_complete_solution(
                    opening,
                    spliced,
                    source="discovered",
                    source_id="anchored-rejoin-v0.128",
                )
                full_cost = int(route.cost)
                solved_replay = bool(route.solved and route.foundations == 8)
                replay_ok = bool(solved_replay and full_cost <= 171)
                provenance = {
                    "replacement": "independently_discovered_segment",
                    "prefix": "reused_verified_prefix",
                    "suffix": "reused_verified_suffix",
                    "route": "incumbent_guided_splice",
                    "independent_cold_complete": False,
                    "reference_actions_preloaded": False,
                }
                if replay_ok:
                    accepted.append(
                        {
                            "name": spec["name"],
                            "start": start,
                            "end": end,
                            "replacement": list(found.actions),
                            "replacement_text": list(replacement),
                            "replacement_cost": int(found.cost),
                            "full_cost": full_cost,
                        }
                    )
            except IncumbentRejected as exc:
                replay_error = str(exc)
        outcome = classify(
            found.status,
            found.stop_reason,
            replay_ok,
            solved_replay,
            found.cost,
            segment_cost,
        )
        row = {
            "name": spec["name"],
            "start": start,
            "end": end,
            "kind_expected": "reversal" if spec["name"] != "160-170" else "between_foundations",
            "played_actions": list(played),
            "played_step_costs": step_costs,
            "played_cost": segment_cost,
            "deals_inside": deals,
            "prefix_cost": prefix,
            "suffix_cost": suffix,
            "full_game_if_replacement_cost_0": prefix + suffix,
            "saving_required": 1,
            "kernel_ceiling": segment_cost - 1,
            "segment_lower_bound": bound,
            "source_admissible_remaining": h,
            "proof_prune_source_against_172": proof_prune(prefix, h, 172),
            "admissible_remaining_is_not_the_segment_bound": True,
            "v0_118_status": spec["v0_118"],
            "v0_118_termination": "unique limit",
            "source_public": source.public(),
            "target_public": target.public(),
            "source_layout": layout(source.state),
            "target_layout": layout(target.state),
            "states_rejoin_endpoints": states_rejoin(source.state, target.state),
            "reference_actions_preloaded": False,
            "status": found.status,
            "stop_reason": found.stop_reason,
            "proof_inside_ceiling": bool(found.proof and found.status in {"EXHAUSTED", "IMPOSSIBLE", "NOT_CHEAPER"}),
            "outcome": outcome,
            "expanded": found.expanded,
            "unique": found.unique,
            "generated": found.generated,
            "ceiling_prunes": found.ceiling_prunes,
            "lower_bound_prunes": found.lower_bound_prunes,
            "duplicate_skips": found.duplicate_skips,
            "stale_skips": found.stale_skips,
            "zero_cost_actions": found.zero_cost_actions,
            "target_rejoins": found.target_rejoins,
            "cheapest_replacement_cost": found.cost,
            "replacement_actions": list(replacement),
            "elapsed_s": round(found.elapsed_s, 3),
            "peak_rss_mb": found.peak_rss_mb,
            "rss_before_mb": rss_before,
            "rss_after_mb": rss_after,
            "min_g": found.min_g,
            "max_g": found.max_g,
            "min_h": found.min_h,
            "max_h": found.max_h,
            "lower_bound_calls": found.lower_bound_calls,
            "expanded_by_g": list(found.expanded_by_g),
            "generated_by_g": list(found.generated_by_g),
            "full_replay_solved": solved_replay,
            "full_replay_ok": replay_ok,
            "full_replay_cost": full_cost,
            "full_replay_error": replay_error,
            "provenance": provenance,
            "budget": {
                "max_unique": MAX_UNIQUE,
                "time_limit_s": TIME_LIMIT_S,
                "rss_abort_mb": RSS_ABORT_MB,
                "workers": 1,
                "exhaustive": True,
            },
        }
        rows.append(row)
        print(
            f"DONE {spec['name']} status={found.status} stop={found.stop_reason} "
            f"expanded={found.expanded} unique={found.unique} generated={found.generated} "
            f"ceiling_prunes={found.ceiling_prunes} lb_prunes={found.lower_bound_prunes} "
            f"transpositions={found.duplicate_skips} stale={found.stale_skips} "
            f"zero_cost={found.zero_cost_actions} rejoins={found.target_rejoins} "
            f"best={found.cost} elapsed={found.elapsed_s:.3f} peak={found.peak_rss_mb} "
            f"by_g={list(found.expanded_by_g)}",
            flush=True,
        )

    combinations = []
    if len(accepted) >= 2:
        disjoint = []
        for piece in accepted:
            if all(not overlaps(piece, prior) for prior in disjoint):
                disjoint.append(piece)
        if len(disjoint) >= 2:
            spliced = splice(actions, disjoint)
            try:
                route = verify_complete_solution(
                    opening,
                    spliced,
                    source="discovered",
                    source_id="anchored-combined-v0.128",
                )
                combinations.append(
                    {
                        "windows": [piece["name"] for piece in disjoint],
                        "cost": route.cost,
                        "foundations": route.foundations,
                        "solved": route.solved,
                        "accepted": bool(route.solved and route.cost <= 171),
                        "independent_cold_complete": False,
                    }
                )
            except IncumbentRejected as exc:
                combinations.append(
                    {
                        "windows": [piece["name"] for piece in disjoint],
                        "accepted": False,
                        "error": str(exc),
                    }
                )

    hashes_after = {
        "solutions/4925153_canonical.moves": sha256(CANONICAL),
        "solutions/4925153_autonomous_185.moves": sha256(AUTONOMOUS),
    }
    payload = {
        "schema": "spider-anchored-optimisation-0.128",
        "deal": "4925153",
        "incumbent": "solutions/4925153_canonical.moves",
        "incumbent_cost": verified.cost,
        "incumbent_source": verified.source,
        "workers": 1,
        "reference_actions_preloaded": False,
        "production_incumbent_overwritten": False,
        "canonical_replay": canonical_replay,
        "autonomous_replay": autonomous_replay,
        "hashes_before": hashes,
        "hashes_after": hashes_after,
        "hashes_unchanged": hashes_after == EXPECTED_HASHES,
        "windows": rows,
        "accepted": [
            {key: value for key, value in piece.items() if key != "replacement"}
            | {"replacement": piece["replacement_text"]}
            for piece in accepted
        ],
        "combinations": combinations,
        "verified_complete_savings": [piece["name"] for piece in accepted],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"WROTE {OUT}", flush=True)
    print(f"ACCEPTED {len(accepted)} COMBINATIONS {len(combinations)} HASHES_OK {hashes_after == EXPECTED_HASHES}", flush=True)


def classify(
    status: str,
    stop_reason: str,
    replay_ok: bool,
    solved_replay: bool,
    replacement_cost,
    segment_cost: int,
) -> str:
    if replay_ok:
        return "verified_complete_game_saving"
    if status == "FOUND" and solved_replay and replacement_cost is not None and replacement_cost >= segment_cost:
        return "target_state_join_without_savings"
    if status == "FOUND" and solved_replay:
        return "target_state_join_without_savings"
    if status == "FOUND":
        return "target_state_join_failed_full_replay"
    if status == "EXHAUSTED":
        return "fully_exhausted_window"
    if status == "INCONCLUSIVE" or stop_reason in {"time limit", "unique limit", "rss abort", "abort"}:
        return "budget_limited_inconclusive"
    if status in {"NOT_CHEAPER", "IMPOSSIBLE"}:
        return "fully_exhausted_window"
    return status


if __name__ == "__main__":
    main()
