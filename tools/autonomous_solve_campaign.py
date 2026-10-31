#!/usr/bin/env python3
"""Headless cold campaign. One process, explicit budgets, sampled resume.

    py -3 tools/autonomous_solve_campaign.py --deal deals/4925153.txt --time-limit 1500 --max-unique 1000000 --memory-mb 3000 --cost-ceiling 400 --checkpoint-s 600 --status docs/autonomous_solve_campaign_status.json
    py -3 tools/autonomous_solve_campaign.py --deal deals/4925153.txt --resume docs/autonomous_solve_campaign_status.json --from best --time-limit 1500 --max-unique 700000 --memory-mb 3000 --cost-ceiling 400 --checkpoint-s 600 --status docs/autonomous_solve_campaign_status.json
"""

from __future__ import annotations

import argparse
import ctypes
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
from spider.research_actions import opening_from_deal

REPO = Path(__file__).resolve().parents[1]


def _memory() -> tuple:
    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatus()
    status.dwLength = ctypes.sizeof(MemoryStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return 0, 0
    return int(status.ullTotalPhys), int(status.ullAvailPhys)


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
    parser.add_argument("--from", dest="resume_from", default="best", choices=("best", "untried", "foundations"))
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
    args = parser.parse_args(argv)

    deal = _resolve(args.deal)
    status = _resolve(args.status)
    if args.fresh and status.is_file() and not args.resume and not args.optimise_incumbent:
        status.unlink()
    total, avail = _memory()
    avail_mb = avail / (1024 * 1024) if avail else 0
    cap_mb = int(avail_mb * 0.40) if avail_mb else int(args.memory_mb)
    applied_mb = min(float(args.memory_mb), float(cap_mb) if cap_mb else float(args.memory_mb))
    machine = {
        "cpus": os.cpu_count(),
        "total_mb": round(total / (1024 * 1024), 1) if total else None,
        "available_mb": round(avail_mb, 1) if avail else None,
        "rss_cap_mb": applied_mb,
        "requested_rss_mb": float(args.memory_mb),
        "workers": 1,
    }
    print(
        f"MACHINE cpus={machine['cpus']} total_mb={machine['total_mb']} "
        f"available_mb={machine['available_mb']} rss_cap_mb={applied_mb}",
        flush=True,
    )
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
