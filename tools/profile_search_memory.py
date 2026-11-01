"""Profile retained memory of one opening ceiling-157 suit search.

The search is the reference kernel: scalar incumbent 158, no route, advice off.
A time or RSS stop is reported as itself and is not labelled fixed-work.
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.global_search_experiment import search_suit_ordered
from spider.method_capture import clamp_rss_mb, probe_host_memory
from spider.research_actions import opening_from_deal
from spider.search_memory_profile import account_retained


def _working_sets() -> dict:
    """Current and peak working set of this process. Search abort still uses peak."""

    try:
        import ctypes
        from ctypes import wintypes

        class _PMC(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = _PMC()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(_PMC), wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        handle = kernel32.GetCurrentProcess()
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return {}
        return {
            "working_set_bytes": int(counters.WorkingSetSize),
            "peak_working_set_bytes": int(counters.PeakWorkingSetSize),
            "pagefile_bytes": int(counters.PagefileUsage),
            "peak_pagefile_bytes": int(counters.PeakPagefileUsage),
        }
    except Exception:
        return {}


def _commit(repo: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-unique", type=int, required=True)
    parser.add_argument("--time-limit", type=float, default=900.0)
    parser.add_argument("--memory-mb", type=float, default=3000.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    memory = probe_host_memory()
    rss_cap = clamp_rss_mb(float(args.memory_mb), int(memory["available_bytes"]), workers=1)
    opening = opening_from_deal(ROOT / "deals" / "4925153.txt")
    diagnostics: dict = {}
    started = time.perf_counter()
    result = search_suit_ordered(
        opening,
        time_limit_s=float(args.time_limit),
        max_unique=int(args.max_unique),
        rss_abort_mb=float(rss_cap),
        seed=0,
        mode="optimise",
        incumbent_cost=158,
        cost_ceiling=157,
        advice_fn=None,
        prefix_actions=(),
        kernel_diagnostics=diagnostics,
    )
    # Measure before accounting. The id set built by the accountant is not search memory.
    memory_at_stop = _working_sets()
    profile = account_retained(diagnostics, ceiling=result.cost_ceiling)
    proof_identities = diagnostics.get("proof_prune_identities")
    proof_unretained = diagnostics.get("proof_prune_unretained")
    ceiling_prunes = diagnostics.get("ceiling_prunes")
    diagnostics.clear()
    fixed = result.stop_reason == "unique limit" and int(result.unique) >= int(args.max_unique)
    payload = {
        "schema": profile["schema"],
        "role": "reference_opening_profile",
        "deal_id": "4925153",
        "search": "search_suit_ordered",
        "mode": "optimise",
        "incumbent_cost": 158,
        "cost_ceiling": result.cost_ceiling,
        "advice": False,
        "route_actions_passed": False,
        "seed_recorded": 0,
        "representation": "reference",
        "ordering": "frozen_suit_v1",
        "commit": _commit(ROOT),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": memory,
        "requested_max_unique": int(args.max_unique),
        "requested_rss_mb": float(args.memory_mb),
        "rss_cap_mb": float(rss_cap),
        "time_limit_s": float(args.time_limit),
        "stop_reason": result.stop_reason,
        "completed_fixed_work": bool(fixed),
        "unique": int(result.unique),
        "expanded": int(result.expanded),
        "generated": int(result.generated),
        "duplicate_skips": int(result.duplicate_skips),
        "stale_skips": int(result.stale_skips),
        "lower_bound_prunes": int(result.lower_bound_prunes),
        "proof_prune_identities": None if proof_identities is None else int(proof_identities),
        "proof_prune_unretained": None if proof_unretained is None else int(proof_unretained),
        "ceiling_prunes": None if ceiling_prunes is None else int(ceiling_prunes),
        "rss_abort_uses": "peak_working_set",
        "process_memory_before_accounting": memory_at_stop,
        "max_foundations": int(result.max_foundations),
        "elapsed_s": result.elapsed_s,
        "cpu_s": result.cpu_s,
        "wall_s": round(time.perf_counter() - started, 3),
        "peak_rss_mb": result.peak_rss_mb,
        "expansions_per_s": None
        if not result.elapsed_s
        else round(int(result.expanded) / float(result.elapsed_s), 3),
        "profile": profile,
    }
    if result.peak_rss_mb and result.unique:
        payload["peak_rss_bytes_per_identity"] = round(
            float(result.peak_rss_mb) * 1024.0 * 1024.0 / int(result.unique),
            2,
        )
    current_bytes = memory_at_stop.get("working_set_bytes")
    if current_bytes is not None:
        payload["working_set_mb_before_accounting"] = round(int(current_bytes) / (1024.0 * 1024.0), 2)
        payload["unaccounted_bytes_at_stop"] = int(current_bytes) - int(profile["accounted_bytes"])
        payload["unaccounted_note"] = (
            "Current working set minus exclusive getsizeof. "
            "Allocator slack, the interpreter, and the suit census sit in the difference. "
            "The accountant's id set is created after this measurement."
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    temporary.replace(args.output)
    print(
        f"PROFILE unique={payload['unique']} stop={payload['stop_reason']} "
        f"fixed={payload['completed_fixed_work']} elapsed={payload['elapsed_s']} "
        f"peak_rss_mb={payload['peak_rss_mb']} accounted={profile['accounted_bytes']} "
        f"out={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
