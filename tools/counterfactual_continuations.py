#!/usr/bin/env python3
"""Bounded counterfactual continuations for one known Spider solution. v0.106.

Does not start a campaign, write an incumbent, or change rules.
Exit 0 when the experiment finishes, including when no cheaper line is found.
Exit 1 when baseline action 25 is not the expected move.
Exit 2 when route validation fails.

Profile mode, the v0.106 experiment:

    py -3 tools/counterfactual_continuations.py --deal 4925153 --root pre-action-25 --policy all --profile pilot
    py -3 tools/counterfactual_continuations.py --deal 4925153 --root post-sd3 --policy all --profile pilot

``--profile deep`` runs only when that name is passed. The default worker count is one.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from spider.counterfactual.experiment import CounterfactualError, run_experiments
from spider.counterfactual.report import build_answers, render_report
from spider.counterfactual.runner import run_profile

REPO = Path(__file__).resolve().parents[1]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Spider counterfactual continuations v0.106")
    parser.add_argument("--deal", required=True)
    parser.add_argument("--baseline", help="Autonomous 185 moves. Defaults in profile mode.")
    parser.add_argument("--reference", help="Human canonical 172 moves. Defaults in profile mode.")
    parser.add_argument("--out", help="JSON output path")
    parser.add_argument("--report", help="Markdown report path")
    parser.add_argument("--focus-column", type=int, default=4)
    parser.add_argument("--root", choices=("pre-action-25", "post-sd3", "both"))
    parser.add_argument("--policy", default="all")
    parser.add_argument("--profile", choices=("pilot", "screen", "deep"))
    parser.add_argument("--workers", type=int)
    parser.add_argument("--total-time-s", type=float)
    parser.add_argument("--screen-time-s", type=float)
    parser.add_argument("--screen-unique", type=int)
    parser.add_argument("--root-time-s", type=float)
    parser.add_argument("--root-unique", type=int)
    parser.add_argument("--deep-time-s", type=float)
    parser.add_argument("--deep-unique", type=int)
    parser.add_argument("--deep-survivors", type=int)
    parser.add_argument("--max-depth", type=int)
    parser.add_argument("--rss-abort-mb", type=float)
    parser.add_argument("--candidate-width", type=int)
    parser.add_argument("--search-width", type=int)
    parser.add_argument("--time-s", type=float)
    parser.add_argument("--max-unique", type=int)
    parser.add_argument("--widen", type=int, default=2)
    parser.add_argument("--candidate-time-s", type=float)
    parser.add_argument("--candidate-unique", type=int)
    parser.add_argument("--ply-limit", type=int, default=8)
    args = parser.parse_args(argv)
    try:
        if args.profile or args.root:
            document = _run_profile_mode(args)
        else:
            document = _run_legacy_mode(args)
    except CounterfactualError as exc:
        print(str(exc), file=sys.stderr)
        return exc.code
    out = _output_path(args)
    out.parent.mkdir(parents=True, exist_ok=True)
    if document.get("mode") == "profile":
        document["answers"] = build_answers(document)
        document["outcome"] = document["answers"]["outcome"]
    out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    if args.report:
        report = Path(args.report)
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(render_report(document), encoding="utf-8")
    print(document["interpretation"][0])
    if document.get("outcome"):
        print(document["outcome"])
    return 0


def _run_profile_mode(args) -> dict:
    deal = _resolve_deal(args.deal)
    baseline = Path(args.baseline) if args.baseline else REPO / "solutions" / "4925153_autonomous_185.moves"
    reference = Path(args.reference) if args.reference else REPO / "solutions" / "4925153_canonical.moves"
    roots = ["pre-action-25", "post-sd3"] if args.root in (None, "both") else [args.root]
    overrides = {
        "workers": args.workers,
        "total_time_s": args.total_time_s if args.total_time_s is not None else args.time_s,
        "screen_time_s": args.screen_time_s,
        "screen_unique": args.screen_unique if args.screen_unique is not None else args.max_unique,
        "root_time_s": args.root_time_s,
        "root_unique": args.root_unique,
        "deep_time_s": args.deep_time_s,
        "deep_unique": args.deep_unique,
        "deep_survivors": args.deep_survivors,
        "max_depth": args.max_depth,
        "rss_abort_mb": args.rss_abort_mb,
        "candidate_width": args.candidate_width,
        "search_width": args.search_width,
    }
    return run_profile(
        deal,
        baseline,
        reference,
        roots=roots,
        policy=args.policy,
        profile_name=args.profile or "pilot",
        overrides=overrides,
        focus_column=args.focus_column,
        artifact_dir=_artifact_dir(args),
        progress=lambda message: print(message, file=sys.stderr, flush=True),
    )


def _run_legacy_mode(args) -> dict:
    if not args.baseline or not args.reference or not args.out:
        raise CounterfactualError(
            "legacy mode requires --baseline, --reference, and --out. "
            "Profile mode requires --profile or --root.",
            code=2,
        )
    return run_experiments(
        _resolve_deal(args.deal),
        Path(args.baseline),
        Path(args.reference),
        focus_column=args.focus_column,
        time_limit_s=8.0 if args.time_s is None else args.time_s,
        max_unique=5000 if args.max_unique is None else args.max_unique,
        widen_passes=args.widen,
        candidate_width=3 if args.candidate_width is None else args.candidate_width,
        candidate_time_s=5.0 if args.candidate_time_s is None else args.candidate_time_s,
        candidate_unique=2500 if args.candidate_unique is None else args.candidate_unique,
        ply_limit=args.ply_limit,
        progress=lambda message: print(message, file=sys.stderr, flush=True),
    )


def _resolve_deal(text: str) -> Path:
    raw = Path(text)
    if raw.is_file():
        return raw
    name = text if text.endswith(".txt") else f"{text}.txt"
    candidate = REPO / "deals" / name
    if candidate.is_file():
        return candidate
    raise CounterfactualError(f"deal not found: {text}", code=2)


def _output_path(args) -> Path:
    if args.out:
        return Path(args.out)
    root = args.root or "both"
    profile = args.profile or "pilot"
    return REPO / "artifacts" / "counterfactuals" / "v0_106" / f"{root}_{profile}.json"


def _artifact_dir(args) -> Path:
    if args.out:
        return Path(args.out).resolve().parent
    return REPO / "artifacts" / "counterfactuals" / "v0_106"


if __name__ == "__main__":
    raise SystemExit(main())
