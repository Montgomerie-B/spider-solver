"""Resource profiles for counterfactual runs.

The pilot is sized for one search at a time on a 16 GB machine.
``deep`` is available only when that profile is requested by name.
"""

from __future__ import annotations

PROFILES = {
    "pilot": {
        "workers": 1,
        "total_time_s": 840.0,
        "screen_time_s": 12.0,
        "screen_unique": 20_000,
        "candidate_width": 12,
        "root_time_s": 45.0,
        "root_unique": 80_000,
        "deep_survivors": 2,
        "deep_time_s": 150.0,
        "deep_unique": 200_000,
        "max_depth": 64,
        "rss_abort_mb": 3072.0,
        "search_width": 1,
        "screen_fraction": 0.25,
        "root_fraction": 0.15,
    },
    "screen": {
        "workers": 1,
        "total_time_s": 90.0,
        "screen_time_s": 3.0,
        "screen_unique": 4_000,
        "candidate_width": 12,
        "root_time_s": 4.0,
        "root_unique": 4_000,
        "deep_survivors": 0,
        "deep_time_s": 0.0,
        "deep_unique": 1_000,
        "max_depth": 24,
        "rss_abort_mb": 2048.0,
        "search_width": 1,
        "screen_fraction": 0.7,
        "root_fraction": 0.3,
    },
    "deep": {
        "workers": 1,
        "total_time_s": 3600.0,
        "screen_time_s": 20.0,
        "screen_unique": 40_000,
        "candidate_width": 12,
        "root_time_s": 180.0,
        "root_unique": 200_000,
        "deep_survivors": 3,
        "deep_time_s": 600.0,
        "deep_unique": 400_000,
        "max_depth": 96,
        "rss_abort_mb": 4096.0,
        "search_width": 1,
        "screen_fraction": 0.2,
        "root_fraction": 0.15,
    },
}


def resolve_profile(name: str, overrides: dict | None = None) -> dict:
    if name not in PROFILES:
        raise KeyError(name)
    resolved = dict(PROFILES[name])
    for key, value in (overrides or {}).items():
        if value is not None and key in resolved:
            resolved[key] = value
    resolved["name"] = name
    resolved["workers_requested"] = int(resolved["workers"])
    resolved["workers_used"] = 1
    resolved["workers_note"] = (
        "One search runs at a time, so the RSS abort applies to a single frontier. "
        "A parallel worker pool is not started."
    )
    return resolved
