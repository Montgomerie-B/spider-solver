"""AUTO hardware snapshot. Disk speed is never a search input."""

from __future__ import annotations

import os
import platform
import socket
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

SOLVER_VERSION = "0.102"


@dataclass
class HardwareSnapshot:
    hostname: str
    machine_id: str
    physical_cores: int
    logical_cores: int
    ram_total_bytes: int
    ram_available_bytes: int
    ram_percent: float
    cpu_percent: float
    arch: str
    disk_free_bytes: Optional[int]
    solver_version: str = SOLVER_VERSION

    @property
    def ram_total_gb(self) -> float:
        return self.ram_total_bytes / (1024 ** 3)

    @property
    def ram_available_gb(self) -> float:
        return self.ram_available_bytes / (1024 ** 3)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["ram_total_gb"] = round(self.ram_total_gb, 2)
        d["ram_available_gb"] = round(self.ram_available_gb, 2)
        return d


def _cpu_counts() -> tuple[int, int]:
    logical = os.cpu_count() or 1
    physical = logical
    try:
        import psutil  # type: ignore

        phys = psutil.cpu_count(logical=False)
        logi = psutil.cpu_count(logical=True)
        if phys:
            physical = int(phys)
        if logi:
            logical = int(logi)
    except Exception:
        pass
    return max(1, physical), max(1, logical)


def _memory() -> tuple[int, int, float]:
    try:
        import psutil  # type: ignore

        vm = psutil.virtual_memory()
        return int(vm.total), int(vm.available), float(vm.percent)
    except Exception:
        pass
    if os.name == "nt":
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
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

        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        total = int(stat.ullTotalPhys)
        avail = int(stat.ullAvailPhys)
        pct = float(stat.dwMemoryLoad)
        return total, avail, pct
    return 16 * 1024 ** 3, 8 * 1024 ** 3, 50.0


def _cpu_percent() -> float:
    try:
        import psutil  # type: ignore

        return float(psutil.cpu_percent(interval=0.15))
    except Exception:
        return 0.0


def _disk_free(path: Optional[Path] = None) -> Optional[int]:
    try:
        import shutil

        usage = shutil.disk_usage(str(path or Path.cwd()))
        return int(usage.free)
    except Exception:
        return None


def machine_id(hostname: str, physical: int, logical: int, ram_total: int) -> str:
    ram_gb = int(round(ram_total / (1024 ** 3)))
    cpu = platform.processor() or platform.machine()
    return f"{hostname}|{cpu}|{physical}p/{logical}l|{ram_gb}GB"


def detect_hardware(*, cwd: Optional[Path] = None) -> HardwareSnapshot:
    """Snapshot current machine. Disk SPEED is not recorded or used."""

    host = socket.gethostname() or "unknown"
    physical, logical = _cpu_counts()
    total, avail, pct = _memory()
    return HardwareSnapshot(
        hostname=host,
        machine_id=machine_id(host, physical, logical, total),
        physical_cores=physical,
        logical_cores=logical,
        ram_total_bytes=total,
        ram_available_bytes=avail,
        ram_percent=pct,
        cpu_percent=_cpu_percent(),
        arch=platform.machine() or platform.architecture()[0],
        disk_free_bytes=_disk_free(cwd),
    )


def memory_pressure(snap: HardwareSnapshot, *, high_percent: float = 88.0, min_available_gb: float = 2.0) -> str:
    if snap.ram_available_gb < min_available_gb or snap.ram_percent >= high_percent:
        return "high"
    if snap.ram_percent >= 75.0 or snap.ram_available_gb < 3.5:
        return "elevated"
    return "ok"
