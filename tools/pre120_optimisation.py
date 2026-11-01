"""Opt-in search for a game below the verified 157 route.

Writes only under the chosen output directory. The default is
docs/research/pre120_optimisation/. It does not rewrite the accepted 157
route, the historical 164/162/160/158 files, or the closed 120/130/140 searches.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.autonomous_solve_campaign import atomic_write_json
from spider.incumbent_suffix import (
    authenticate_campaign,
    load_campaign_routes,
    require_pre120_index,
    run_prefix_attempt,
    select_campaign_route,
    verified_published_incumbent,
)
from spider.research_actions import opening_from_deal


def _resolve_output(path: Path) -> Path:
    output = path if path.is_absolute() else ROOT / path
    resolved = output.resolve()
    forbidden = (ROOT / "docs" / "research" / "incumbent_suffix_optimisation").resolve()
    if resolved == forbidden:
        raise SystemExit("pre120 campaign does not write the accepted incumbent-suffix directory")
    if "solutions" in resolved.parts:
        raise SystemExit("pre120 campaign does not write the solutions directory")
    return output


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Search below the verified 157 game, before action 120")
    sub = parser.add_subparsers(dest="command", required=True)
    authenticate = sub.add_parser("authenticate")
    authenticate.add_argument("--output", default="docs/research/pre120_optimisation")
    search = sub.add_parser("search")
    search.add_argument("--output", default="docs/research/pre120_optimisation")
    search.add_argument("--at-action", type=int, required=True)
    search.add_argument("--time-limit", type=float, required=True)
    search.add_argument("--max-unique", type=int, default=2_000_000)
    search.add_argument("--memory-mb", type=float, default=3000.0)
    search.add_argument("--checkpoint-s", type=float, default=600.0)
    search.add_argument("--route", default="157")
    search.add_argument("--incumbent", type=int, default=157)
    search.add_argument("--ceiling", type=int, default=156)
    args = parser.parse_args(argv)
    output = _resolve_output(Path(args.output))
    if args.command == "authenticate":
        payload = authenticate_campaign(ROOT, output_dir=output, ceiling=156, incumbent=157)
        output.mkdir(parents=True, exist_ok=True)
        atomic_write_json(output / "witness_manifest.json", payload)
        historical = payload["historical"]
        splice = payload["splice"]
        print(
            "AUTHENTICATED "
            f"historical_states={historical['distinct_physical_states']} "
            f"historical_records={historical['splice_prefix_records']} "
            f"states={payload['distinct_physical_states']} "
            f"shared_157_158={payload['shared_prefix_157_158']} "
            f"eligible={payload['last_eligible_index']} "
            f"splice_best={splice['best_total']} "
            f"improving={splice['improving_combinations']}",
            flush=True,
        )
        return 0
    index = require_pre120_index(int(args.at_action))
    routes = load_campaign_routes(ROOT, output)
    route = select_campaign_route(routes, str(args.route))
    opening = opening_from_deal(ROOT / "deals" / "4925153.txt")
    published = verified_published_incumbent(output, opening, root=ROOT)
    incumbent = int(args.incumbent)
    if published is not None:
        incumbent = min(incumbent, int(published["g"]))
    ceiling = min(int(args.ceiling), incumbent - 1)
    print(
        "LAUNCH "
        f"route={route['label']} hash={route['path_hash16']} "
        f"index={index} incumbent={incumbent} ceiling={ceiling}",
        flush=True,
    )
    run_prefix_attempt(
        action_index=index,
        time_limit_s=float(args.time_limit),
        max_unique=int(args.max_unique),
        memory_mb=float(args.memory_mb),
        checkpoint_s=float(args.checkpoint_s),
        output_dir=output,
        root=ROOT,
        route_label=str(route["label"]),
        incumbent=int(incumbent),
        ceiling=int(ceiling),
        routes=routes,
        verify_published=True,
        improvement_below=157,
        log=lambda line: print(line, flush=True),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
