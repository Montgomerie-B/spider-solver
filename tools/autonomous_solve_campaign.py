#!/usr/bin/env python3
"""Headless campaign. Legacy cold/anchored commands stay. Method v1 adds four modes.

    py -3 tools/autonomous_solve_campaign.py --mode cold --deal deals/4925153.txt --time-limit 1500 --max-unique 1000000 --memory-mb 3000 --cost-ceiling 400 --checkpoint-s 600
    py -3 tools/autonomous_solve_campaign.py --mode opening-improve --incumbent-cost 158 --cost-ceiling 157 --authenticate docs/research/autonomous_solve_campaign/4925153_cold_158.moves --time-limit 3600 --max-unique 1200000 --memory-mb 3000
    py -3 tools/autonomous_solve_campaign.py --mode repair --route docs/research/autonomous_solve_campaign/4925153_cold_158.moves --time-limit 1200 --max-unique 80000 --memory-mb 3000 --repair-span 48 --repair-stride 16 --repair-windows 6
    py -3 tools/autonomous_solve_campaign.py --mode continue --from unfinished --time-limit 1500 --max-unique 1000000 --memory-mb 3000 --cost-ceiling 400
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from spider.autonomous_solve_campaign import (
    assert_cold_document,
    optimise_campaign_incumbent,
    run_campaign_attempt,
)
from spider.method_capture import (
    authenticate_route,
    clamp_rss_mb,
    load_recipe,
    probe_host_memory,
    run_method_attempt,
)
from spider.research_actions import opening_from_deal

REPO = Path(__file__).resolve().parents[1]


def _resolve(path: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = REPO / candidate
    return candidate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cold autonomous solve campaign for deal 4925153")
    parser.add_argument("--deal", default="deals/4925153.txt")
    parser.add_argument("--status", default="docs/autonomous_solve_campaign_status.json")
    parser.add_argument("--resume", default="")
    parser.add_argument(
        "--from",
        dest="resume_from",
        default="best",
        choices=("best", "untried", "foundations", "unfinished"),
    )
    parser.add_argument("--time-limit", type=float, required=True)
    parser.add_argument("--max-unique", type=int, required=True)
    parser.add_argument("--memory-mb", type=float, default=3000.0)
    parser.add_argument("--cost-ceiling", type=int, default=400)
    parser.add_argument("--checkpoint-s", type=float, default=600.0)
    parser.add_argument("--solution-dir", default="docs/research/autonomous_solve_campaign")
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument("--optimise-incumbent", default="")
    parser.add_argument("--window-s", type=float, default=25.0)
    parser.add_argument("--medium-s", type=float, default=45.0)
    parser.add_argument("--max-windows", type=int, default=32)
    parser.add_argument("--adaptive", action="store_true")
    parser.add_argument("--mode", default="", choices=("", "cold", "opening-improve", "repair", "continue"))
    parser.add_argument("--recipe", default="docs/research/method_capture_optimisation/method_v1.json")
    parser.add_argument("--incumbent-cost", type=int, default=None)
    parser.add_argument("--route", default="")
    parser.add_argument("--authenticate", default="")
    parser.add_argument("--repair-span", type=int, default=48)
    parser.add_argument("--repair-stride", type=int, default=16)
    parser.add_argument("--repair-windows", type=int, default=6)
    parser.add_argument("--historical-best", type=int, default=158)
    parser.add_argument("--min-slack", type=int, default=0)
    args = parser.parse_args(argv)
    if args.mode:
        if args.status == "docs/autonomous_solve_campaign_status.json":
            args.status = "docs/research/method_capture_optimisation/status.json"
        if args.solution_dir == "docs/research/autonomous_solve_campaign":
            args.solution_dir = "docs/research/method_capture_optimisation"
        if args.resume_from == "best":
            args.resume_from = "unfinished"

    deal = _resolve(args.deal)
    status = _resolve(args.status)
    if (
        args.fresh
        and status.is_file()
        and not args.resume
        and not args.optimise_incumbent
        and args.mode != "continue"
    ):
        status.unlink()
    host = probe_host_memory()
    total = int(host["total_bytes"])
    avail = int(host["available_bytes"])
    avail_mb = avail / (1024 * 1024) if avail else 0
    if args.mode:
        applied_mb = clamp_rss_mb(float(args.memory_mb), avail, workers=1)
    else:
        cap_mb = int(avail_mb * 0.40) if avail_mb else int(args.memory_mb)
        applied_mb = min(float(args.memory_mb), float(cap_mb) if cap_mb else float(args.memory_mb))
    machine = {
        "cpus": os.cpu_count(),
        "probe": host["probe"],
        "total_mb": round(total / (1024 * 1024), 1) if total else None,
        "available_mb": round(avail_mb, 1) if avail else None,
        "rss_cap_mb": applied_mb,
        "requested_rss_mb": float(args.memory_mb),
        "aggregate_cap_mb": applied_mb,
        "workers": 1,
        "child_processes": 0,
    }
    print(
        f"MACHINE cpus={machine['cpus']} total_mb={machine['total_mb']} "
        f"available_mb={machine['available_mb']} rss_cap_mb={applied_mb}",
        flush=True,
    )
    if args.mode:
        recipe = load_recipe(_resolve(args.recipe))
        opening = opening_from_deal(deal)
        authentication = None
        if args.authenticate:
            authentication = authenticate_route(opening, _resolve(args.authenticate))
            if args.incumbent_cost is not None and int(authentication["g"]) != int(args.incumbent_cost):
                raise SystemExit(
                    f"authenticated cost {authentication['g']} does not match scalar {args.incumbent_cost}"
                )
            print(
                f"AUTHENTICATED g={authentication['g']} hash={authentication['path_hash16']} "
                f"actions_loaded_into_search={authentication['actions_loaded_into_search']}",
                flush=True,
            )
        document = run_method_attempt(
            opening,
            mode=args.mode,
            status_path=status,
            recipe=recipe,
            time_limit_s=float(args.time_limit),
            max_unique=int(args.max_unique),
            rss_abort_mb=float(applied_mb),
            cost_ceiling=None if args.cost_ceiling is None else int(args.cost_ceiling),
            checkpoint_s=float(args.checkpoint_s),
            machine=machine,
            solution_dir=_resolve(args.solution_dir),
            incumbent_cost=args.incumbent_cost,
            route_path=_resolve(args.route) if args.route else None,
            resume_from=args.resume_from,
            repair_span=int(args.repair_span),
            repair_stride=int(args.repair_stride),
            repair_windows=int(args.repair_windows),
            window_s=float(args.window_s),
            medium_s=float(args.medium_s),
            historical_best_g=int(args.historical_best) if args.mode == "cold" else None,
            min_slack=int(args.min_slack),
            authentication=authentication,
            log=lambda line: print(line, flush=True),
        )
        print(f"COLD {document.get('cold_reproduction')}", flush=True)
        print(f"IMPROVEMENT {document.get('verified_improvement')}", flush=True)
        print(f"STATUS {status}", flush=True)
        return 0
    if args.optimise_incumbent:
        opening = opening_from_deal(deal)
        document = optimise_campaign_incumbent(
            opening,
            incumbent_path=_resolve(args.optimise_incumbent),
            status_path=status,
            time_limit_s=float(args.time_limit),
            rss_abort_mb=float(applied_mb),
            max_unique=int(args.max_unique),
            window_s=float(args.window_s),
            medium_s=float(args.medium_s),
            max_windows=int(args.max_windows),
            adaptive=bool(args.adaptive),
            solution_dir=_resolve(args.solution_dir),
            log=lambda line: print(line, flush=True),
        )
        print(f"CATEGORY {document['category']}", flush=True)
        print(f"STATUS {status}", flush=True)
        return 0
    resume = None
    if args.resume:
        resume_path = _resolve(args.resume)
        if "solutions" in resume_path.parts:
            raise SystemExit("cold campaign does not read the solutions directory")
        resume = json.loads(resume_path.read_text(encoding="utf-8"))
        assert_cold_document(resume)
    opening = opening_from_deal(deal)
    document = run_campaign_attempt(
        opening,
        status_path=status,
        time_limit_s=float(args.time_limit),
        max_unique=int(args.max_unique),
        rss_abort_mb=float(applied_mb),
        cost_ceiling=int(args.cost_ceiling),
        checkpoint_s=float(args.checkpoint_s),
        resume=resume,
        resume_from=args.resume_from,
        machine=machine,
        solution_dir=_resolve(args.solution_dir),
        log=lambda line: print(line, flush=True),
    )
    print(f"CATEGORY {document['category']}", flush=True)
    print(f"STATUS {status}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
