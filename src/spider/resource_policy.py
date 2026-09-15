"""Conservative AUTO resource policy. Tuned so 16 GB Optiplex-class machines stay stable."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

from spider.hardware import HardwareSnapshot

# Optiplex-safe defaults. Never assume 128 GB.
OS_RESERVE_GB = 5.0
DEFAULT_WORKER_RSS_GB = 2.5
GLOBAL_FRACTION = 0.70  # 16 GB * 0.70 ≈ 11.2 GB campaign cap
SMALL_RAM_GB = 20.0


@dataclass
class ResourceConfig:
    mode: str
    workers: int
    per_worker_rss_mb: float
    global_ram_limit_gb: float
    max_unique: int
    notes: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def recommend_config(
    snap: HardwareSnapshot,
    *,
    measured_rss_mb: Optional[float] = None,
    measured_unique_per_s: Optional[float] = None,
    mode: str = "AUTO",
    workers_override: Optional[int] = None,
    rss_override_mb: Optional[float] = None,
) -> ResourceConfig:
    """Derive conservative worker/RSS/unique defaults. Disk speed is ignored."""

    total = max(4.0, snap.ram_total_gb)
    reserve = min(max(4.0, OS_RESERVE_GB), total * 0.35)
    global_gb = max(3.5, min(total - reserve, total * GLOBAL_FRACTION))
    measured = (measured_rss_mb or 400.0)
    per_gb = DEFAULT_WORKER_RSS_GB
    if measured_rss_mb is not None:
        per_gb = min(DEFAULT_WORKER_RSS_GB, max(0.75, (measured / 1024.0) * 3.0 + 0.4))
    per_gb = min(per_gb, global_gb * 0.45)
    per_mb = per_gb * 1024.0
    if rss_override_mb is not None:
        per_mb = float(rss_override_mb)
        per_gb = per_mb / 1024.0

    ram_workers = max(1, int(global_gb // (per_gb + 0.75)))
    cpu_workers = max(1, snap.physical_cores - 1) if snap.physical_cores >= 2 else 1
    workers = min(ram_workers, cpu_workers, 4)
    if total <= SMALL_RAM_GB:
        workers = 1
    if snap.ram_available_gb < 4.0:
        workers = 1
    if workers_override is not None:
        workers = max(1, int(workers_override))

    unique = 300_000 if workers == 1 else 180_000
    if measured_unique_per_s is not None and measured_unique_per_s < 80:
        unique = min(unique, 150_000)
    notes = (
        f"AUTO from {snap.physical_cores}p/{snap.logical_cores}l "
        f"{total:.0f}GB; disk speed unused"
    )
    return ResourceConfig(
        mode=mode,
        workers=workers,
        per_worker_rss_mb=round(per_mb, 1),
        global_ram_limit_gb=round(global_gb, 2),
        max_unique=int(unique),
        notes=notes,
    )
