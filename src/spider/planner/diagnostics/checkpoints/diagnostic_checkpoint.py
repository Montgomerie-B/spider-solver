#!/usr/bin/env python3
"""Atomic diagnostic checkpoint / resume for multi-day Opt009 searches.

Diagnostic-only. Not committed as a canonical project artefact by default.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class CheckpointError(Exception):
    """Incompatible or corrupt checkpoint."""


def build_config_identity(
    *,
    deal_id: str,
    experiment_id: str,
    ordering_mode: str,
    beam: int,
    extra: Optional[Dict[str, Any]] = None,
) -> str:
    """Stable hash of deal + experiment configuration for resume validation."""
    payload = {
        "deal_id": deal_id,
        "experiment_id": experiment_id,
        "ordering_mode": ordering_mode,
        "beam": beam,
        "extra": extra or {},
    }
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


def validate_checkpoint_identity(
    checkpoint: Dict[str, Any],
    *,
    deal_id: str,
    experiment_id: str,
    config_identity: str,
) -> None:
    if checkpoint.get("deal_id") != deal_id:
        raise CheckpointError(
            f"deal mismatch: checkpoint={checkpoint.get('deal_id')} expected={deal_id}"
        )
    if checkpoint.get("experiment_id") != experiment_id:
        raise CheckpointError(
            f"experiment_id mismatch: {checkpoint.get('experiment_id')} vs {experiment_id}"
        )
    if checkpoint.get("config_identity") != config_identity:
        raise CheckpointError(
            "config_identity mismatch — refuse resume "
            f"(got {checkpoint.get('config_identity')}, expected {config_identity})"
        )


@dataclass
class SearchCheckpointPayload:
    """Serializable search continuation state (compact, no prose)."""

    experiment_id: str
    deal_id: str
    config_identity: str
    ordering_mode: str
    schema_version: int = 1
    written_at: float = 0.0
    active_runtime_seconds: float = 0.0
    wall_elapsed_seconds: float = 0.0
    expanded: int = 0
    generated: int = 0
    seq: int = 0
    termination: str = "running"
    incumbent: Optional[Dict[str, Any]] = None
    best_candidates: List[Dict[str, Any]] = field(default_factory=list)
    # frontier: list of serialisable nodes (path labels, mw, depth, metrics)
    frontier: List[Dict[str, Any]] = field(default_factory=list)
    # transposition: list of [zobrist, best_mw]
    transposition: List[List[int]] = field(default_factory=list)
    best_depth: List[List[int]] = field(default_factory=list)
    counters: Dict[str, Any] = field(default_factory=dict)
    corridor_window: Optional[Dict[str, Any]] = None
    completed_windows: List[str] = field(default_factory=list)
    tie_break_seq: int = 0
    cache_policy: str = "rebuild_on_resume"
    notes: str = "diagnostic_only; not a canonical artefact"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SearchCheckpointPayload":
        return cls(
            experiment_id=str(d["experiment_id"]),
            deal_id=str(d["deal_id"]),
            config_identity=str(d["config_identity"]),
            ordering_mode=str(d.get("ordering_mode") or "hybrid_adapter"),
            schema_version=int(d.get("schema_version") or 1),
            written_at=float(d.get("written_at") or 0.0),
            active_runtime_seconds=float(d.get("active_runtime_seconds") or 0.0),
            wall_elapsed_seconds=float(d.get("wall_elapsed_seconds") or 0.0),
            expanded=int(d.get("expanded") or 0),
            generated=int(d.get("generated") or 0),
            seq=int(d.get("seq") or 0),
            termination=str(d.get("termination") or "running"),
            incumbent=d.get("incumbent"),
            best_candidates=list(d.get("best_candidates") or []),
            frontier=list(d.get("frontier") or []),
            transposition=list(d.get("transposition") or []),
            best_depth=list(d.get("best_depth") or []),
            counters=dict(d.get("counters") or {}),
            corridor_window=d.get("corridor_window"),
            completed_windows=list(d.get("completed_windows") or []),
            tie_break_seq=int(d.get("tie_break_seq") or d.get("seq") or 0),
            cache_policy=str(d.get("cache_policy") or "rebuild_on_resume"),
            notes=str(d.get("notes") or ""),
        )


class CheckpointStore:
    """Atomic checkpoint writer with retention of latest two valid files."""

    def __init__(
        self,
        directory: Path,
        *,
        experiment_id: str,
        prefix: str = "ckpt",
        retain: int = 2,
    ) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.experiment_id = experiment_id
        self.prefix = prefix
        self.retain = max(1, retain)
        self._write_count = 0

    def _path_for(self, index: int) -> Path:
        return self.directory / f"{self.prefix}_{self.experiment_id}_{index}.json"

    def list_checkpoints(self) -> List[Path]:
        paths = sorted(
            self.directory.glob(f"{self.prefix}_{self.experiment_id}_*.json"),
            key=lambda p: p.stat().st_mtime,
        )
        return paths

    def write_atomic(self, payload: SearchCheckpointPayload) -> Path:
        """Write via temp file + os.replace; keep latest `retain` checkpoints."""
        self._write_count += 1
        payload.written_at = time.time()
        data = payload.to_dict()
        # rotate slot 0/1
        slot = self._write_count % self.retain
        final = self._path_for(slot)
        tmp = final.with_suffix(".json.tmp")
        text = json.dumps(data, indent=2, default=str)
        # atomic write
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, final)
        # prune extras beyond retain (safety)
        paths = self.list_checkpoints()
        if len(paths) > self.retain:
            for old in paths[: len(paths) - self.retain]:
                try:
                    old.unlink()
                except OSError:
                    pass
        return final

    def load_latest(
        self,
        *,
        deal_id: str,
        experiment_id: str,
        config_identity: str,
    ) -> Tuple[SearchCheckpointPayload, Path]:
        paths = list(reversed(self.list_checkpoints()))
        if not paths:
            raise CheckpointError("no checkpoints found")
        last_err: Optional[Exception] = None
        for path in paths:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                validate_checkpoint_identity(
                    raw,
                    deal_id=deal_id,
                    experiment_id=experiment_id,
                    config_identity=config_identity,
                )
                return SearchCheckpointPayload.from_dict(raw), path
            except Exception as exc:  # noqa: BLE001 — try older checkpoint
                last_err = exc
                continue
        raise CheckpointError(f"no valid checkpoint: {last_err}")

    @property
    def write_count(self) -> int:
        return self._write_count
