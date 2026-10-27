"""Complete the canonical post-SD5 position under an absolute cost ceiling.

The known 22-move suffix is a validation oracle. It is not inserted into
the frontier. Solutions and the incumbent registry are not written.
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
OUT = ROOT / "artifacts" / "post_sd5_v0_130" / "results.json"

EXPECTED_HASHES = {
    "solutions/4925153_canonical.moves": "18338A08576AD24E9AF1F4BA2E7DB3E28768788DD511E823193B1937F3FEEF33",
    "solutions/4925153_autonomous_185.moves": "B19C56E957AC2666298A80118D54FF7FCA6C8114ED7D27590E2E98A017D4FB73",
}

MAX_UNIQUE = 80_000
TIME_LIMIT_S = 90.0
RSS_ABORT_MB = 512.0


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


def gate_a(opening, actions, checkpoints, index: int) -> dict:
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
    samples = []
    for step, action in enumerate(suffix):
        remain = 172 - g
        h_assembly = int(stock_empty_assembly_h(work))
        h_adm = int(admissible_remaining(work))
        if h_assembly > remain or h_adm > remain:
            raise SystemExit(f"inadmissible at suffix step {step}: h={h_adm} remain={remain}")
        minimum_slack = min(minimum_slack, remain - h_adm)
        if step in {0, 5, 10, 15, 21} or remain - h_adm == minimum_slack:
            samples.append(
                {
                    "suffix_step": step,
                    "g": g,
                    "remain": remain,
                    "assembly_h": h_assembly,
                    "admissible_h": h_adm,
                    "foundations": len(work.foundations),
                }
            )
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
        "prefix_actions": index,
        "stock_cards": checkpoint.stock_cards,
        "stock_rows": checkpoint.stock_rows,
        "foundations": checkpoint.foundations,
        "face_down": face_down_count(state),
        "bonds": same_suit_bonds(state),
        "empty_columns": checkpoint.empty_columns,
        "assembly_h": assembly,
        "admissible_h": admissible,
        "admissible_slack_to_172": 172 - (checkpoint.g + admissible),
        "admissible_slack_to_171": 171 - (checkpoint.g + admissible),
        "minimum_suffix_slack": minimum_slack,
        "known_suffix_solves": True,
        "legal_actions": len(legal),
        "zero_cost_actions": sum(step_cost(state, action) == 0 for action in legal),
        "deal_legal": ("deal",) in legal,
        "admissible_seconds": round(time_call(lambda: admissible_remaining(state)), 6),
        "full_completion_key_seconds": round(time_call(lambda: completion_key(state, checkpoint.g)), 6),
        "slack_samples": samples[:12],
    }


def run_gate(name: str, state, g0: int, ceiling: int, ordering: str) -> dict:
    print(f"START {name} ordering={ordering} ceiling={ceiling}", flush=True)
    found = search_post_sd5(
        state,
        g0=g0,
        ceiling=ceiling,
        ordering=ordering,
        max_unique=MAX_UNIQUE,
        time_limit_s=TIME_LIMIT_S,
        rss_abort_mb=RSS_ABORT_MB,
        progress=True,
    )
    row = public_search(found)
    row["gate"] = name
    print(
        f"DONE {name} stop={found.stop_reason} solved={found.solved} "
        f"g={found.solution_g} expanded={found.expanded} unique={found.unique} "
        f"generated={found.generated} dup={found.duplicate_skips} "
        f"symmetry={found.symmetry_collapses} ceiling_prunes={found.ceiling_prunes} "
        f"lb_prunes={found.lower_bound_prunes} zero={found.zero_cost_actions} "
        f"max_f={found.max_foundations_expanded} elapsed={found.elapsed_s:.3f} "
        f"peak={found.peak_rss_mb} proof={found.negative_proof}",
        flush=True,
    )
    return row


def accept_full_game(opening, prefix, suffix, claimed: int) -> dict:
    try:
        verified = verify_complete_solution(
            opening,
            list(prefix) + list(suffix),
            expected_cost=claimed,
            source="post-sd5-search",
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
    validated = gate_a(opening, actions, checkpoints, index)
    print(
        f"GATE A index={index} g={validated['g']} h={validated['admissible_h']} "
        f"fd={validated['face_down']} bonds={validated['bonds']} "
        f"legal={validated['legal_actions']} key_s={validated['full_completion_key_seconds']}",
        flush=True,
    )

    source = checkpoint.state.clone()
    prefix = tuple(actions[:index])
    gates = []
    control = run_gate("B", source, checkpoint.g, 172, "completion")
    if control["solved"]:
        control["full_game"] = accept_full_game(opening, prefix, search_actions(control), int(control["solution_g"]))
    else:
        control["full_game"] = {"accepted": False}
    gates.append(control)

    improvement = run_gate("C", source, checkpoint.g, 171, "completion")
    if improvement["solved"]:
        improvement["full_game"] = accept_full_game(
            opening, prefix, search_actions(improvement), int(improvement["solution_g"])
        )
    else:
        improvement["full_game"] = {"accepted": False}
    gates.append(improvement)

    compared = None
    if not improvement["solved"] and not improvement["negative_proof"]:
        compared = run_gate("D", source, checkpoint.g, 171, "cost")
        if compared["solved"]:
            compared["full_game"] = accept_full_game(
                opening, prefix, search_actions(compared), int(compared["solution_g"])
            )
        else:
            compared["full_game"] = {"accepted": False}
        gates.append(compared)

    hashes_after = {key: sha256(ROOT / key) for key in EXPECTED_HASHES}
    accepted = [
        row for row in gates
        if row.get("full_game", {}).get("accepted") and int(row["solution_g"]) <= 171
    ]
    payload = {
        "schema": "spider-post-sd5-completion-0.130",
        "deal": "4925153",
        "workers": 1,
        "max_unique": MAX_UNIQUE,
        "time_limit_s": TIME_LIMIT_S,
        "rss_abort_mb": RSS_ABORT_MB,
        "reference_suffix_preloaded": False,
        "production_incumbent_overwritten": False,
        "ordering": "completion lane prefix (g+h, h, -foundations, g); cost lane (g,)",
        "identity": "pack_whole_game_identity",
        "store": "pack_state",
        "bound": "admissible_remaining",
        "canonical_replay": canonical,
        "autonomous_replay": autonomous,
        "hashes_before": hashes,
        "hashes_after": hashes_after,
        "hashes_unchanged": hashes_after == EXPECTED_HASHES,
        "gate_a": validated,
        "gates": gates,
        "accepted_improvements": [
            {
                "gate": row["gate"],
                "cost": row["solution_g"],
                "suffix": row["suffix"],
                "provenance": row["full_game"].get("provenance"),
            }
            for row in accepted
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"WROTE {OUT}", flush=True)
    print(
        f"ACCEPTED {len(accepted)} HASHES_OK {hashes_after == EXPECTED_HASHES} "
        f"NEGATIVE_C {improvement['negative_proof']}",
        flush=True,
    )


def search_actions(row: dict):
    parsed = []
    for text in row["suffix"]:
        parts = text.split()
        if parts[0] != "move" or len(parts) != 4:
            raise SystemExit(f"unexpected suffix action {text}")
        parsed.append((int(parts[1]) - 1, int(parts[2]) - 1, int(parts[3])))
    return parsed


if __name__ == "__main__":
    main()
