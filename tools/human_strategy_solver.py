#!/usr/bin/env python3
"""Integrated human-strategy controller for Spider Solitaire. v0.116.

The controller does not start a historical campaign, write the production
incumbent, or change MobilityWare rules. ``--profile extended`` runs only
when named. ``--goal first-foundation`` keeps one foundation campaign.
``--goal foundations --target-foundations N`` continues after each removal.
The default goal ``play`` is the v0.108 controller.

    py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode cold --profile smoke
    py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode cold --profile pilot --goal first-foundation --time-limit 150
    py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode cold --profile pilot --goal foundations --target-foundations 2 --time-limit 150
    py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode optimise --incumbent solutions/4925153_autonomous_185.moves --profile pilot
    py -3 tools/human_strategy_solver.py --deal deals/4925153.txt --mode diagnose --root post-sd3 --profile smoke --time-limit 60
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from spider.counterfactual.experiment import reconstruct_roots
from spider.deal import load_deal
from spider.human_strategy import SCHEMA_VERSION, coverage_matrix, resolve_profile, solve
from spider.human_strategy.evaluation import cost_led_action
from spider.metrics import export_actions_to_moves_file, format_action, parse_moves_file, replay_actions
from spider.packed_state import unpack_state
from spider.research_actions import opening_from_deal

REPO = Path(__file__).resolve().parents[1]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Spider human-strategy controller v0.116")
    parser.add_argument("--deal", required=True)
    parser.add_argument("--mode", choices=("cold", "optimise", "diagnose"), default="cold")
    parser.add_argument(
        "--goal",
        choices=("play", "first-foundation", "foundations"),
        default="play",
        help=(
            "play keeps the v0.108 controller. first-foundation pursues one foundation. "
            "foundations pursues --target-foundations and then stops, unless all eight are removed."
        ),
    )
    parser.add_argument(
        "--target-foundations",
        type=int,
        default=None,
        help="How many foundations --goal foundations pursues, from 1 to 8. Default 8.",
    )
    parser.add_argument("--profile", choices=("smoke", "pilot", "extended"), default="smoke")
    parser.add_argument("--incumbent", help="Verified .moves file used only as an optimise ceiling")
    parser.add_argument(
        "--root",
        choices=("post-sd3",),
        help="Diagnose from a saved root. post-sd3 replays the 185 only to reach that state.",
    )
    parser.add_argument("--baseline", help="Moves file for --root post-sd3. Defaults to the autonomous 185.")
    parser.add_argument("--time-limit", type=float)
    parser.add_argument("--memory-mb", type=float)
    parser.add_argument("--strategic-width", type=int)
    parser.add_argument("--max-width", type=int)
    parser.add_argument("--tactical-nodes", type=int)
    parser.add_argument("--tactical-seconds", type=float)
    parser.add_argument("--tactical-cost", type=int)
    parser.add_argument("--max-steps", type=int)
    parser.add_argument("--frontier", type=int, help="Strategic lines retained at once, from 1 to 16.")
    parser.add_argument("--proposals", type=int, help="Alternatives saved at one decision, from 1 to 4.")
    parser.add_argument("--slice", type=int, help="New commits on one line before a queued line may run.")
    parser.add_argument("--line-attempts", type=int, help="New objective attempts on one line before yielding.")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--out")
    parser.add_argument("--no-portfolio", action="store_true")
    args = parser.parse_args(argv)

    if args.root and args.mode != "diagnose":
        print("--root post-sd3 is a diagnostic prefix of a known solution. Use --mode diagnose.", file=sys.stderr)
        return 2
    if args.mode == "cold" and args.incumbent:
        print("cold mode does not accept an incumbent sequence.", file=sys.stderr)
        return 2
    if args.mode == "optimise" and not args.incumbent:
        print("optimise mode requires --incumbent.", file=sys.stderr)
        return 2

    deal_path = _resolve(args.deal)
    profile = resolve_profile(args.profile).with_overrides(
        time_limit_s=args.time_limit,
        rss_abort_mb=args.memory_mb,
        strategic_width=args.strategic_width,
        max_width=args.max_width,
        tactical_nodes=args.tactical_nodes,
        tactical_time_s=args.tactical_seconds,
        tactical_max_cost=args.tactical_cost,
        max_steps=args.max_steps,
        workers=args.workers,
        frontier_limit=args.frontier,
        proposals_per_decision=args.proposals,
        slice_steps=args.slice,
        line_attempt_cap=args.line_attempts,
        consult_portfolio=False if args.no_portfolio else None,
    )
    opening = opening_from_deal(deal_path)
    deal_cards = load_deal(deal_path) if args.goal in {"first-foundation", "foundations"} else None
    incumbent_actions = None
    incumbent_mw = None
    opening_g = 0
    note = ""
    if args.mode == "optimise":
        incumbent_path = _resolve(args.incumbent)
        incumbent_actions = parse_moves_file(incumbent_path)
        incumbent_mw = replay_actions(opening.clone(), list(incumbent_actions))
        note = (
            f"Ceiling {incumbent_mw} comes from replaying {incumbent_path.name}. "
            "The sequence is not injected as a prefix. The production incumbent is not written."
        )
    elif args.root == "post-sd3":
        baseline = _resolve(args.baseline) if args.baseline else REPO / "solutions" / "4925153_autonomous_185.moves"
        roots = reconstruct_roots(deal_path, parse_moves_file(baseline), focus_column=4)
        root = roots["B"]
        opening = unpack_state(bytes.fromhex(root["ordered_digest"]))
        opening_g = int(root["cumulative_g"])
        note = (
            f"Diagnostic root only. The {baseline.name} prefix was replayed to reach "
            f"post-SD3 at g={opening_g}, hash {root['state_hash']}. "
            "This is not a cold start and not a new discovery. The suffix is not injected."
        )

    result = solve(
        opening,
        profile,
        mode=args.mode,
        incumbent_actions=incumbent_actions,
        incumbent_mw=incumbent_mw,
        opening_g=opening_g,
        provenance_note=note,
        goal=args.goal,
        deal_cards=deal_cards,
        target_foundations=args.target_foundations,
    )
    document = _document(args, deal_path, result, opening)
    out = Path(args.out) if args.out else REPO / "artifacts" / "human_strategy" / "v0_116" / f"{args.mode}_{args.profile}.json"
    if not out.is_absolute():
        out = REPO / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    moves_path = None
    if result.status == "SOLVED_VALID":
        moves_path = out.with_suffix(".moves")
        export_actions_to_moves_file(
            list(result.actions),
            moves_path,
            header=(
                f"v0.116 {args.mode} {args.profile} goal={args.goal} "
                f"mw={result.cumulative_g} replay_ok={result.replay and result.replay.get('ok')}"
            ),
        )
    print(f"status={result.status} mw={result.cumulative_g} solved={result.solved} steps={result.objectives_attempted}")
    print(f"elapsed_s={result.elapsed_s:.3f} peak_rss_mb={result.peak_rss_mb} unique_states={result.unique_states}")
    if result.decisions:
        first = result.decisions[0]
        print(f"first={first.chosen_kind} {first.chosen_id} cost_led={first.cost_led}")
    foundation = result.provenance.get("foundation") or []
    if foundation:
        last = foundation[-1]
        print(
            f"foundation={last.get('label')} "
            f"partial={result.provenance.get('partial_trajectory')} "
            f"foundations={result.foundations}"
        )
    fallback = result.provenance.get("kernel_fallback")
    if fallback:
        print(
            "kernel_fallback "
            f"stop={fallback['stop_reason']} unique={fallback['unique']} "
            f"expanded={fallback['expanded']} solved={fallback['solved']} "
            f"elapsed_s={fallback['elapsed_s']}"
        )
    print(f"wrote {out}")
    if moves_path is not None:
        print(f"wrote {moves_path}")
    return 0 if result.status != "INVALID" else 1


def _document(args, deal_path: Path, result, opening) -> dict:
    led = cost_led_action(opening)
    led_text = None if led is None else format_action(led)
    first = result.decisions[0] if result.decisions else None
    played = ""
    for decision in result.decisions:
        if decision.actions:
            played = decision.actions[0]
            break
    first_is_led = False
    if first is not None and led_text and first.status in {"achieved", "partial"}:
        matches_deal = first.chosen_kind == "DEAL_NOW" and led_text == "deal"
        matches_move = first.chosen_id.endswith(led_text)
        first_is_led = matches_deal or matches_move
    return {
        "schema": SCHEMA_VERSION,
        "deal": str(deal_path),
        "mode": args.mode,
        "goal": args.goal,
        "target_foundations": args.target_foundations,
        "profile": args.profile,
        "estimates_are_estimates": True,
        "comparison": {
            "cost_led_action": led_text,
            "controller_first": None if first is None else first.chosen_id,
            "controller_first_status": None if first is None else first.status,
            "controller_action": played or None,
            "differs_from_cost_led": bool(first is not None and not first_is_led),
            "note": (
                "cost_led is one-ply minimum immediate cost, with Deal winning ties. "
                "It is not a full search. differs_from_cost_led is true when the first "
                "committed objective is not that action, including a failed objective "
                "that plays nothing."
            ),
        },
        "result": result.to_dict(),
        "coverage": coverage_matrix(),
    }


def _resolve(text: str) -> Path:
    path = Path(text)
    if path.is_file():
        return path
    candidate = REPO / text
    if candidate.is_file():
        return candidate
    raise SystemExit(f"file not found: {text}")


if __name__ == "__main__":
    sys.exit(main())
