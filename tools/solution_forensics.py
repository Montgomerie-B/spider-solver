#!/usr/bin/env python3
"""Compare Spider solutions structurally. v0.105 diagnostic CLI.

Does not search, does not start campaigns, and does not change rules.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from spider.forensics.analyze import ForensicError, analyze_solution, compare_solutions
from spider.forensics.report import render_report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Spider solution forensics v0.105")
    parser.add_argument("--deal", required=True, help="Deal file, for example deals/4925153.txt")
    parser.add_argument("--solution", help="Analyse one trajectory")
    parser.add_argument("--a", help="Reference solution")
    parser.add_argument("--b", help="Comparison solution")
    parser.add_argument("--label", default="solution")
    parser.add_argument("--label-a", default="reference")
    parser.add_argument("--label-b", default="comparison")
    parser.add_argument("--expect-mw", type=int)
    parser.add_argument("--expect-a", type=int)
    parser.add_argument("--expect-b", type=int)
    parser.add_argument("--focus-column", type=int, help="1-based MobilityWare column to trace")
    parser.add_argument("--role-a", default="reference")
    parser.add_argument("--role-b", default="machine")
    parser.add_argument("--seed-limit", type=int, default=8)
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--out", required=True, help="JSON output path")
    parser.add_argument("--report", help="Markdown report path")
    args = parser.parse_args(argv)

    single = args.solution is not None
    pair = args.a is not None or args.b is not None
    if single == pair or (pair and (args.a is None or args.b is None)):
        print("Provide --solution, or both --a and --b.", file=sys.stderr)
        return 2
    try:
        if single:
            trajectory = analyze_solution(
                Path(args.deal),
                Path(args.solution),
                label=args.label,
                expected_mw=args.expect_mw,
                focus_column=args.focus_column,
                require_solved=not args.allow_partial,
            )
            document = {
                "schema": "spider-solution-forensics-0.105",
                "mode": "single",
                "trajectory": trajectory,
            }
            report_text = None
        else:
            document = compare_solutions(
                Path(args.deal),
                Path(args.a),
                Path(args.b),
                label_a=args.label_a,
                label_b=args.label_b,
                expected_a=args.expect_a,
                expected_b=args.expect_b,
                focus_column=args.focus_column,
                role_a=args.role_a,
                role_b=args.role_b,
                seed_limit=args.seed_limit,
                require_solved=not args.allow_partial,
            )
            report_text = render_report(document) if args.report else None
    except ForensicError as exc:
        print(str(exc), file=sys.stderr)
        if exc.details:
            print(json.dumps(exc.details, indent=2, sort_keys=True), file=sys.stderr)
        return 3 if "expected" in str(exc) or "not a complete" in str(exc) or "completion" in str(exc) else 2

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.report:
        if report_text is None:
            print("--report is written for a two-route comparison.", file=sys.stderr)
            return 2
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_text, encoding="utf-8")
    print(f"wrote {out}")
    if args.report and report_text is not None:
        print(f"wrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
