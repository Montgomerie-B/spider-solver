#!/usr/bin/env python3
"""Opt011B memory/checkpoint feasibility study — ceilings 0..N (not cost 7 production)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import tokens_from_file
from spider.deal_analysis import build_deal_analysis
from spider.planner.diagnostics.experiment_4925153_opt011_cmd43_51_corridor import (
    ARTIFACTS,
    DEAL,
    search_corridor,
    rss_bytes,
)

OUT = ARTIFACTS / "opt011b_feasibility.json"


def run_ceiling(ceiling: int, *, max_expanded: int = 2_000_000) -> dict:
    analysis = build_deal_analysis(tokens_from_file(DEAL))
    art = ARTIFACTS / f"feasibility_c{ceiling}"
    rt = art / "runtime"
    art.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    rss0 = rss_bytes()
    r = search_corridor(
        mode="exact",
        analysis=analysis,
        max_expanded=max_expanded,
        success_ceiling=ceiling,
        enable_checkpoint=True,
        checkpoint_dir=art,
        runtime_dir=rt,
        progress_path=art / "progress.jsonl",
        use_hybrid_ordering=False,  # deterministic engine order for study
        max_rss_gib=10.0,
        checkpoint_rss_headroom_gib=0.75,
    )
    ck = art / "opt011_checkpoint.json"
    ck_size = ck.stat().st_size if ck.is_file() else 0
    # resume timing
    t_res0 = time.time()
    if r["termination"] not in ("exhausted", "exact_improvement") and ck.is_file():
        try:
            search_corridor(
                mode="exact",
                analysis=analysis,
                max_expanded=r["expanded"] + 1,
                success_ceiling=ceiling,
                enable_checkpoint=False,
                checkpoint_dir=art,
                runtime_dir=rt / "resume",
                progress_path=art / "resume_progress.jsonl",
                resume=True,
                use_hybrid_ordering=False,
                force_stale_lock=True,
            )
            resume_s = time.time() - t_res0
        except Exception as exc:
            resume_s = None
            r["resume_error"] = str(exc)
    else:
        resume_s = 0.0
    n_states = int(r.get("final_tt") or 0)
    peak = int(r.get("rss_peak_bytes") or 0)
    bytes_per = (peak / n_states) if n_states else None
    return {
        "ceiling": ceiling,
        "termination": r.get("termination"),
        "status": r.get("status"),
        "expanded": r.get("expanded"),
        "generated": r.get("generated"),
        "final_frontier": r.get("final_frontier"),
        "peak_frontier": r.get("peak_frontier"),
        "final_tt": n_states,
        "peak_tt": r.get("peak_tt"),
        "runtime_seconds": r.get("runtime_seconds"),
        "expansions_per_sec": r.get("expansions_per_sec"),
        "rss_start": rss0,
        "rss_peak": peak,
        "rss_finish": r.get("rss_finish_bytes"),
        "bytes_per_retained_state_est": bytes_per,
        "checkpoint_bytes": ck_size,
        "checkpoint_resume_seconds": resume_s,
        "improvements": len(r.get("improvements") or []),
        "wall_seconds": time.time() - t0,
    }


def main() -> int:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    results = []
    for c in (0, 1, 2, 3):
        print(f"=== feasibility ceiling={c} ===", flush=True)
        row = run_ceiling(c)
        results.append(row)
        print(json.dumps(row, indent=2), flush=True)
        # stop escalating if memory or incomplete under pressure
        peak_gib = (row["rss_peak"] or 0) / (1024**3)
        if peak_gib > 6.0 or row["termination"] == "max_rss":
            print(f"stopping escalation: peak_gib={peak_gib:.2f}", flush=True)
            break
        if row["termination"] not in ("exhausted", "exact_improvement", "bounded_frontier_empty"):
            # incomplete at this ceiling — still record but continue carefully
            if peak_gib > 4.0:
                break
    report = {
        "runs": results,
        "note": (
            "Feasibility only; cost-7 production not launched. "
            "Extrapolation is approximate."
        ),
    }
    # crude cost-7 estimate from last complete layers
    complete = [r for r in results if r["termination"] == "exhausted"]
    if len(complete) >= 2:
        # exponential fit rough: ratio of last two
        a, b = complete[-2], complete[-1]
        if a["final_tt"] and b["final_tt"] and a["ceiling"] < b["ceiling"]:
            ratio = b["final_tt"] / max(1, a["final_tt"])
            layers = 7 - b["ceiling"]
            est_states = b["final_tt"] * (ratio**layers)
            bps = b.get("bytes_per_retained_state_est") or 0
            report["cost7_extrapolation"] = {
                "method": f"geometric growth ratio={ratio:.3f} from ceilings {a['ceiling']}->{b['ceiling']}",
                "est_states_range": [est_states * 0.3, est_states * 3.0],
                "est_peak_rss_gib_range": [
                    (est_states * 0.3 * bps) / (1024**3),
                    (est_states * 3.0 * bps) / (1024**3),
                ] if bps else None,
                "confidence": "low-medium — spider branching is highly state-dependent",
            }
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
