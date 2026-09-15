"""Short representative search calibration. Not a scientific campaign."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Optional

from spider.hardware import HardwareSnapshot, detect_hardware
from spider.packed_state import pack_state, unpack_state
from spider.research_actions import tableau_actions
from spider.search_kernel import SearchLimits, run_search
from spider.whole_game_anytime import opening_state


@dataclass
class CalibrationResult:
    elapsed_s: float
    unique: int
    expanded: int
    generated: int
    unique_per_s: float
    expanded_per_s: float
    peak_rss_mb: Optional[float]
    second_worker: Optional[dict]
    stop_reason: str

    def as_dict(self) -> dict:
        return asdict(self)


def calibrate_search(*, time_s: float = 15.0, unique: int = 40_000) -> CalibrationResult:
    """Run a 10–20 s kernel probe from the opening. No long scientific search."""

    opening = opening_state()
    root = {
        "g": 0,
        "ordered_digest": pack_state(opening).hex(),
        "symmetry_digest": pack_state(opening).hex(),
    }
    t0 = time.perf_counter()
    kr = run_search(
        [root],
        limits=SearchLimits(max_unique=int(unique), time_limit_s=float(time_s), rss_abort_mb=1536.0),
        identity_fn=pack_state,
        store_fn=pack_state,
        unpack_fn=unpack_state,
        lane_names=("cost", "reveal", "construction"),
        is_terminal=lambda st: False,
        actions_fn=tableau_actions,
        lower_bound_fn=None,
    )
    elapsed = max(1e-6, time.perf_counter() - t0)
    return CalibrationResult(
        elapsed_s=elapsed,
        unique=int(kr.unique),
        expanded=int(kr.expanded),
        generated=int(kr.generated),
        unique_per_s=float(kr.unique) / elapsed,
        expanded_per_s=float(kr.expanded) / elapsed,
        peak_rss_mb=kr.peak_rss_mb,
        second_worker=None,
        stop_reason=kr.stop_reason,
    )


def maybe_second_worker_probe(snap: HardwareSnapshot, first: CalibrationResult) -> Optional[dict]:
    """Only if RAM is clearly ample. Optiplex 16 GB skips this."""

    if snap.ram_available_gb < 8.0 or snap.ram_total_gb <= 20.0:
        return None
    return {
        "skipped": True,
        "reason": "second-worker probe reserved for large-RAM machines after first worker is proven",
    }
