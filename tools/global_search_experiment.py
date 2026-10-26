#!/usr/bin/env python3
"""Run the isolated legal-state experiment. Does not call the production controller.

    py -3 tools/global_search_experiment.py --variant strategy --time-limit 40 --max-unique 80000 --memory-mb 3072 --out artifacts/global_search/v0_124/experiment_c_40.json
    py -3 tools/global_search_experiment.py --variant kernel --time-limit 40 --max-unique 80000 --memory-mb 3072 --out artifacts/global_search/v0_124/control_b_40.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from spider.counterfactual.boundaries import parse_canonical
from spider.global_search_experiment import (
    SCHEMA,
    matching_ancestries,
    position_coverage,
    replay_cost,
    search_original_kernel,
    search_strategy_guided,
)
from spider.human_strategy.profiles import resolve_profile
from spider.research_actions import apply_action, face_down_count, opening_from_deal

REPO = Path(__file__).resolve().parents[1]


def _resolve(path: str) -> Path:
    candidate = Path(path)
    if not candidate.is_file():
        candidate = REPO / path
    return candidate


def _actions_from_fixture(path: Path) -> list:
    document = json.loads(path.read_text(encoding="utf-8"))
    return [parse_canonical(item) for item in document["actions"]]


def _coverage(args) -> int:
    """Measure legal coverage. Does not run a timed search and does not solve."""

    deal = _resolve(args.deal)
    opening = opening_from_deal(deal)
    g83 = _actions_from_fixture(_resolve(args.g83))
    policy_path = _resolve(args.policy_artifact)
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    result = policy["result"]
    profile = resolve_profile("pilot")
    before_deal, g_before = replay_cost(opening, g83[:17])
    after_deal, g_after = replay_cost(opening, g83[:18])
    historical_25, g_25 = replay_cost(opening, g83[:25])
    first_foundation = None
    state = opening.clone()
    cost = 0
    for index, action in enumerate(g83, start=1):
        cost += apply_action(state, action)
        if len(state.foundations) >= 1 and first_foundation is None:
            first_foundation = (state.clone(), cost, index)
            break
    if first_foundation is None:
        raise SystemExit("g83 fixture never removes a foundation")
    stall_actions = [parse_canonical(item) for item in result["actions"]]
    stall_state, stall_g = replay_cost(opening, stall_actions)
    branches = []
    frontier = (result.get("provenance") or {}).get("frontier") or {}
    for branch in frontier.get("branches") or []:
        if branch.get("actions"):
            branches.append(branch)
    ancestry = matching_ancestries(opening, g83[:25], branches)
    positions = [
        position_coverage(opening, profile, g=0, name="opening"),
        position_coverage(before_deal, profile, g=g_before, name="before_historical_action_18"),
        position_coverage(
            historical_25,
            profile,
            g=g_25,
            name="historical_25_action_state",
        ),
        position_coverage(
            first_foundation[0],
            profile,
            g=first_foundation[1],
            name="first_foundation_on_g83",
        ),
        position_coverage(after_deal, profile, g=g_after, name="after_historical_stock_deal"),
        position_coverage(stall_state, profile, g=stall_g, name="v0_123_planning_stall"),
    ]
    cheapest = ancestry.get("cheapest") or {}
    cheaper_state = None
    if cheapest:
        want_g = int(cheapest["g"])
        want_n = int(cheapest["actions"])
        for branch in branches:
            raw = branch.get("actions") or []
            if branch.get("label") != cheapest.get("label") or len(raw) < want_n:
                continue
            prefix = [parse_canonical(item) for item in raw[:want_n]]
            end, got = replay_cost(opening, prefix)
            if got == want_g:
                cheaper_state = position_coverage(
                    end,
                    profile,
                    g=got,
                    name="cheaper_ancestry_of_historical_25",
                )
                break
    if cheaper_state is not None:
        positions.insert(3, cheaper_state)
    import hashlib

    from spider.packed_state import pack_state

    stall_id = hashlib.sha256(pack_state(stall_state)).hexdigest()
    document = {
        "schema": SCHEMA,
        "kind": "legal_coverage",
        "deal": str(deal),
        "profile": "pilot",
        "strategic_width": profile.strategic_width,
        "question": (
            "A legal move can be excluded because no selected strategic objective proposes it. "
            "build_candidates scores engine-legal actions. The controller keeps strategic_width "
            "and executes one objective. The campaign yield at controller.py returns before "
            "applying a move when no campaign step is executable."
        ),
        "positions": positions,
        "historical_25_ancestry": ancestry,
        "stall": {
            "actions": len(stall_actions),
            "g": stall_g,
            "face_down": face_down_count(stall_state),
            "foundations": len(stall_state.foundations),
            "state_id": stall_id,
            "artifact_stop": result.get("status"),
            "artifact_g": result.get("cumulative_g"),
        },
        "g83_first_foundation_action_index": first_foundation[2],
        "note": (
            "Classes at these states are measured before search. "
            "safe_dominance and admissible_incumbent_prune are empty here because "
            "this pass does not run the frontier. heuristic_rank_cutoff is intentional "
            "ranking, not a correctness defect. distinct_successor_states counts "
            "authoritative children, not objectives."
        ),
    }
    out = Path(args.out)
    if not out.is_absolute():
        out = REPO / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2), encoding="utf-8")
    for row in positions:
        print(
            f"{row['name']}: legal={row['legal_count']} distinct={row['distinct_successor_states']} "
            f"scored={row['scored_count']} width={row['width']} "
            f"not_scored={len(row['not_scored'])} outside={len(row['outside_width'])} "
            f"selected={row['selected']}"
        )
    print(
        f"ancestry matches={ancestry['matches']} cheapest={ancestry.get('cheapest')} "
        f"dominates={ancestry['cheapest_dominates_target']}"
    )
    print(f"stall_id={stall_id} g={stall_g}")
    print(f"wrote {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Isolated legal-state search v0.124")
    parser.add_argument("--deal", default="deals/4925153.txt")
    parser.add_argument("--variant", choices=("strategy", "kernel"), default="strategy")
    parser.add_argument("--mode", choices=("cold", "optimise"), default="cold")
    parser.add_argument("--time-limit", type=float, default=40.0)
    parser.add_argument("--max-unique", type=int, default=80000)
    parser.add_argument("--memory-mb", type=float, default=3072.0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--incumbent-cost", type=int, default=None)
    parser.add_argument("--cost-ceiling", type=int, default=300)
    parser.add_argument("--out", required=True)
    parser.add_argument("--coverage", action="store_true")
    parser.add_argument(
        "--policy-artifact",
        default="artifacts/human_strategy/v0_123/experiment_c_policy.json",
    )
    parser.add_argument(
        "--g83",
        default="tests/fixtures/g83_4925153_actions.json",
    )
    args = parser.parse_args(argv)
    if args.coverage:
        return _coverage(args)
    deal = Path(args.deal)
    if not deal.is_file():
        deal = REPO / args.deal
    opening = opening_from_deal(deal)
    if args.variant == "kernel":
        if args.mode != "cold":
            raise SystemExit("the original kernel entry in this tool is cold only")
        payload = search_original_kernel(
            opening,
            time_limit_s=args.time_limit,
            max_unique=args.max_unique,
            rss_abort_mb=args.memory_mb,
            cost_ceiling=args.cost_ceiling,
        )
    else:
        result = search_strategy_guided(
            opening,
            time_limit_s=args.time_limit,
            max_unique=args.max_unique,
            rss_abort_mb=args.memory_mb,
            seed=args.seed,
            mode=args.mode,
            incumbent_cost=args.incumbent_cost,
            cost_ceiling=args.cost_ceiling,
        )
        payload = result.to_dict()
    document = {
        "schema": SCHEMA,
        "deal": str(deal),
        "result": payload,
    }
    out = Path(args.out)
    if not out.is_absolute():
        out = REPO / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2), encoding="utf-8")
    print(
        f"variant={payload.get('variant')} stop={payload.get('stop_reason')} "
        f"foundations={payload.get('max_foundations')} solved={payload.get('solved')} "
        f"unique={payload.get('unique')} elapsed={payload.get('elapsed_s')} "
        f"rss={payload.get('peak_rss_mb')}"
    )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
