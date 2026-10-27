"""Matched post-SD5 search after proof-first unique admission.

Only the strict-improvement run is executed: ceiling 171, completion order,
80,000 retained identities, 90 seconds, 512 MB, one worker. Gate B and
Gate D are not repeated. The known suffix is not preloaded. Solution files
and the incumbent registry are not written.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")

from spider.assembly_lower_bound import completion_key, stock_empty_assembly_h
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.human_strategy.anchored import build_checkpoints
from spider.human_strategy.evaluation import admissible_remaining, same_suit_bonds
from spider.human_strategy.incumbent import verify_complete_solution
from spider.metrics import parse_moves_file, replay_actions_detailed
from spider.post_sd5_completion import public_search, search_post_sd5
from spider.research_actions import all_legal_actions, apply_action, face_down_count, step_cost

ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
CANONICAL = ROOT / "solutions" / "4925153_canonical.moves"
AUTONOMOUS = ROOT / "solutions" / "4925153_autonomous_185.moves"
OUT = ROOT / "artifacts" / "proof_first_v0_131" / "results.json"

EXPECTED_HASHES = {
    "solutions/4925153_canonical.moves": "18338A08576AD24E9AF1F4BA2E7DB3E28768788DD511E823193B1937F3FEEF33",
    "solutions/4925153_autonomous_185.moves": "B19C56E957AC2666298A80118D54FF7FCA6C8114ED7D27590E2E98A017D4FB73",
}

MAX_UNIQUE = 80_000
TIME_LIMIT_S = 90.0
RSS_ABORT_MB = 512.0
CEILING = 171

# v0.130 Gate C counted a proof-dead child before rejecting it.
V0_130_GATE_C = {
    "stop_reason": "unique limit",
    "solved": False,
    "negative_proof": False,
    "expanded": 1766,
    "unique": 80000,
    "generated": 171669,
    "duplicate_skips": 88971,
    "symmetry_collapses": 82177,
    "ceiling_prunes": 0,
    "lower_bound_prunes": 56394,
    "zero_cost_actions": 13577,
    "stale_skips": 20,
    "elapsed_s": 52.089,
    "peak_rss_mb": 108.17578125,
    "min_f": 168,
    "min_h": 3,
    "max_h": 19,
    "max_g": 168,
    "max_foundations_expanded": 5,
    "terminals": 0,
}


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


def post_sd5_index(actions) -> int:
    deals = 0
    for index, action in enumerate(actions):
        if action == ("deal",):
            deals += 1
            if deals == 5:
                return index + 1
    raise SystemExit("canonical route does not contain five stock deals")


def time_call(fn, repeats: int = 20) -> float:
    started = time.perf_counter()
    for _ in range(repeats):
        fn()
    return (time.perf_counter() - started) / repeats


def validate_checkpoint(actions, checkpoints, index: int) -> dict:
    checkpoint = checkpoints[index]
    state = checkpoint.state
    if checkpoint.g != 150 or checkpoint.stock_cards != 0:
        raise SystemExit(f"unexpected post-SD5 checkpoint g={checkpoint.g} stock={checkpoint.stock_cards}")
    suffix = actions[index:]
    assembly = int(stock_empty_assembly_h(state))
    admissible = int(admissible_remaining(state))
    if assembly > 22 or admissible > 22:
        raise SystemExit(f"bound exceeds the known suffix: assembly={assembly} admissible={admissible}")
    work = state.clone()
    g = checkpoint.g
    minimum_slack = 22
    for step, action in enumerate(suffix):
        remain = 172 - g
        h_assembly = int(stock_empty_assembly_h(work))
        h_adm = int(admissible_remaining(work))
        if h_assembly > remain or h_adm > remain:
            raise SystemExit(f"inadmissible at suffix step {step}: h={h_adm} remain={remain}")
        minimum_slack = min(minimum_slack, remain - h_adm)
        g += int(apply_action(work, action))
    if g != 172 or not work.is_solved() or len(work.foundations) != 8:
        raise SystemExit(f"known suffix did not solve: g={g} foundations={len(work.foundations)}")
    legal = all_legal_actions(state)
    return {
        "checkpoint_index": index,
        "deal_action_index": index - 1,
        "g": checkpoint.g,
        "suffix_actions": len(suffix),
        "suffix_cost": 22,
        "stock_cards": checkpoint.stock_cards,
        "foundations": checkpoint.foundations,
        "face_down": face_down_count(state),
        "bonds": same_suit_bonds(state),
        "empty_columns": checkpoint.empty_columns,
        "assembly_h": assembly,
        "admissible_h": admissible,
        "admissible_slack_to_171": 171 - (checkpoint.g + admissible),
        "minimum_suffix_slack_to_172": minimum_slack,
        "known_suffix_solves": True,
        "legal_actions": len(legal),
        "zero_cost_actions": sum(step_cost(state, action) == 0 for action in legal),
        "deal_legal": ("deal",) in legal,
        "admissible_seconds": round(time_call(lambda: admissible_remaining(state)), 6),
        "full_completion_key_seconds": round(time_call(lambda: completion_key(state, checkpoint.g)), 6),
        "reference_suffix_preloaded": False,
    }


def search_actions(row: dict):
    parsed = []
    for text in row["suffix"]:
        parts = text.split()
        if parts[0] != "move" or len(parts) != 4:
            raise SystemExit(f"unexpected suffix action {text}")
        parsed.append((int(parts[1]) - 1, int(parts[2]) - 1, int(parts[3])))
    return parsed


def accept_full_game(opening, prefix, suffix, claimed: int) -> dict:
    try:
        verified = verify_complete_solution(
            opening,
            list(prefix) + list(suffix),
            expected_cost=claimed,
            source="proof-first-admission",
            source_id="incumbent-guided-suffix",
        )
    except Exception as exc:
        return {"accepted": False, "error": str(exc)}
    return {
        "accepted": bool(verified.solved and verified.cost == claimed and verified.foundations == 8),
        "cost": verified.cost,
        "foundations": verified.foundations,
        "solved": verified.solved,
        "provenance": {
            "prefix": "reused_canonical_prefix",
            "suffix": "independently_discovered_suffix",
            "route": "incumbent_guided_suffix",
            "independent_cold_complete": False,
            "reference_suffix_preloaded": False,
        },
    }


def classify(row: dict) -> str:
    if row.get("full_game", {}).get("accepted") and int(row["solution_g"]) <= CEILING:
        return "improvement"
    if row["stop_reason"] == "complete" and not row["solved"] and row["negative_proof"]:
        return "negative_checkpoint"
    return "inconclusive"


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
    index = post_sd5_index(actions)
    checkpoint = checkpoints[index]
    validated = validate_checkpoint(actions, checkpoints, index)
    print(
        f"CHECKPOINT index={index} g={validated['g']} h={validated['admissible_h']} "
        f"fd={validated['face_down']} legal={validated['legal_actions']} "
        f"key_s={validated['full_completion_key_seconds']}",
        flush=True,
    )

    print(
        f"START C ordering=completion ceiling={CEILING} "
        f"max_unique={MAX_UNIQUE} time={TIME_LIMIT_S}",
        flush=True,
    )
    found = search_post_sd5(
        checkpoint.state.clone(),
        g0=checkpoint.g,
        ceiling=CEILING,
        ordering="completion",
        max_unique=MAX_UNIQUE,
        time_limit_s=TIME_LIMIT_S,
        rss_abort_mb=RSS_ABORT_MB,
        progress=True,
    )
    row = public_search(found)
    row["gate"] = "C"
    if found.solved:
        row["full_game"] = accept_full_game(
            opening,
            tuple(actions[:index]),
            search_actions(row),
            int(found.solution_g),
        )
    else:
        row["full_game"] = {"accepted": False}
    outcome = classify(row)
    print(
        f"DONE C stop={found.stop_reason} solved={found.solved} "
        f"g={found.solution_g} expanded={found.expanded} unique={found.unique} "
        f"generated={found.generated} dup={found.duplicate_skips} "
        f"symmetry={found.symmetry_collapses} ceiling_prunes={found.ceiling_prunes} "
        f"lb_prunes={found.lower_bound_prunes} "
        f"proof_ids={found.proof_prune_identities} "
        f"proof_unretained={found.proof_prune_unretained} "
        f"zero={found.zero_cost_actions} max_f={found.max_foundations_expanded} "
        f"elapsed={found.elapsed_s:.3f} peak={found.peak_rss_mb} "
        f"proof={found.negative_proof} outcome={outcome}",
        flush=True,
    )

    hashes_after = {key: sha256(ROOT / key) for key in EXPECTED_HASHES}
    payload = {
        "schema": "spider-proof-first-admission-0.131",
        "deal": "4925153",
        "workers": 1,
        "max_unique": MAX_UNIQUE,
        "time_limit_s": TIME_LIMIT_S,
        "rss_abort_mb": RSS_ABORT_MB,
        "ceiling": CEILING,
        "ordering": "completion lane prefix (g+h, h, -foundations, g)",
        "identity": "pack_whole_game_identity",
        "store": "pack_state",
        "bound": "admissible_remaining",
        "admission": "proof check before unique slot, best-g, node, and heap",
        "reference_suffix_preloaded": False,
        "production_incumbent_overwritten": False,
        "gates_not_run": ["B", "D"],
        "canonical_replay": canonical,
        "autonomous_replay": autonomous,
        "hashes_before": hashes,
        "hashes_after": hashes_after,
        "hashes_unchanged": hashes_after == EXPECTED_HASHES,
        "checkpoint": validated,
        "v0_130_gate_c": V0_130_GATE_C,
        "gate_c": row,
        "outcome": outcome,
        "outcome_scope": (
            "negative_checkpoint applies only to this fixed post-SD5 state"
            if outcome == "negative_checkpoint"
            else "a cap or time stop does not prove the checkpoint minimal"
        ),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"WROTE {OUT}", flush=True)
    print(
        f"OUTCOME {outcome} HASHES_OK {hashes_after == EXPECTED_HASHES} "
        f"ACCEPTED {row['full_game'].get('accepted')}",
        flush=True,
    )


if __name__ == "__main__":
    main()
