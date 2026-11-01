"""Opt-in incumbent/prefix/suffix optimisation for deal 4925153.

Writes only under the chosen output directory. It does not update the
accepted method-capture ledger or the historical 158/164 route files.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.autonomous_solve_campaign import atomic_write_json
from spider.incumbent_suffix import authenticate_inputs, run_prefix_attempt


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Own-campaign suffix witnesses and prefix search")
    parser.add_argument("--output", default="docs/research/incumbent_suffix_optimisation")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("authenticate")
    search = sub.add_parser("search")
    search.add_argument("--at-action", type=int, required=True)
    search.add_argument("--time-limit", type=float, required=True)
    search.add_argument("--max-unique", type=int, required=True)
    search.add_argument("--memory-mb", type=float, default=3000.0)
    search.add_argument("--checkpoint-s", type=float, default=600.0)
    search.add_argument("--route", default="158")
    search.add_argument("--incumbent", type=int, default=158)
    search.add_argument("--ceiling", type=int, default=157)
    args = parser.parse_args(argv)
    output = Path(args.output)
    if args.command == "authenticate":
        payload = authenticate_inputs(ROOT)
        output.mkdir(parents=True, exist_ok=True)
        atomic_write_json(output / "witness_manifest.json", payload)
        print(
            "AUTHENTICATED "
            f"shared={payload['shared_prefix_actions']} "
            f"states={payload['distinct_physical_states']} "
            f"eligible={payload['last_eligible_index']} "
            f"splice_best={payload['splice']['best_total']} "
            f"matches={payload['splice']['exact_matches']}",
            flush=True,
        )
        return 0
    run_prefix_attempt(
        action_index=int(args.at_action),
        time_limit_s=float(args.time_limit),
        max_unique=int(args.max_unique),
        memory_mb=float(args.memory_mb),
        checkpoint_s=float(args.checkpoint_s),
        output_dir=output,
        root=ROOT,
        route_label=str(args.route),
        incumbent=int(args.incumbent),
        ceiling=int(args.ceiling),
        log=lambda line: print(line, flush=True),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
