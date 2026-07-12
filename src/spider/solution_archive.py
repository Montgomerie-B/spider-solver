#!/usr/bin/env python3
"""Durable external best-solution capture and archive.

A complete solution is operational only after independent replay and
atomic write to the external archive. Internal scores alone are never
sufficient evidence.

Default archive root (Windows): ``C:\\SpiderSolver\\solutions``
Override with environment variable: ``SPIDER_SOLUTION_ARCHIVE_ROOT``

Uses corrected ``mobilityware_moves`` only — never ``legacy_mw``.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.hash import zobrist
from spider.metrics import (
    Action,
    format_action,
    parse_moves_file,
    replay_actions_detailed,
)

# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------

DEFAULT_ARCHIVE_ROOT_WINDOWS = Path(r"C:\SpiderSolver\solutions")
ENV_ARCHIVE_ROOT = "SPIDER_SOLUTION_ARCHIVE_ROOT"
VALIDATOR_VERSION = "solution_archive_v1"
METRIC_VERSION = "mobilityware_moves_corrected_v1"

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DEAL_PATH = REPO_ROOT / "deals" / "4925153.txt"
DEFAULT_CANONICAL = REPO_ROOT / "solutions" / "4925153_canonical.moves"
EMERGENCY_RECOVERY = REPO_ROOT / "artifacts" / "solution_recovery"


MoveInput = Union[Sequence[Action], Sequence[str], Path, str]


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class ValidationResult:
    valid: bool
    solved: bool = False
    mobilityware_moves: Optional[int] = None
    explicit_commands: int = 0
    tableau_moves: int = 0
    stock_deals: int = 0
    automatic_foundation_removals: int = 0
    foundations: int = 0
    stock_remaining: int = 0
    path_hash: str = ""
    state_hash: str = ""
    actions: List[Action] = field(default_factory=list)
    failure_reason: str = ""
    counters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SolutionArchiveResult:
    candidate_valid: bool = False
    candidate_solved: bool = False
    candidate_mobilityware_moves: Optional[int] = None
    incumbent_mobilityware_moves: Optional[int] = None
    is_strict_improvement: bool = False
    external_archive_written: bool = False
    current_best_updated: bool = False
    historical_copy_written: bool = False
    human_readable_path: Optional[str] = None
    parser_ready_path: Optional[str] = None
    metadata_path: Optional[str] = None
    history_human_path: Optional[str] = None
    history_moves_path: Optional[str] = None
    path_hash: str = ""
    state_hash: str = ""
    failure_reason: str = ""
    emergency_recovery_path: Optional[str] = None
    source: str = ""
    deal_id: str = ""
    archive_root: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def default_archive_root() -> Path:
    env = os.environ.get(ENV_ARCHIVE_ROOT)
    if env:
        return Path(env)
    if sys.platform.startswith("win"):
        return DEFAULT_ARCHIVE_ROOT_WINDOWS
    # Non-Windows default for tests / portable use
    return Path.home() / "SpiderSolver" / "solutions"


def deal_archive_dir(deal_id: str, archive_root: Optional[Path] = None) -> Path:
    root = Path(archive_root) if archive_root else default_archive_root()
    return root / str(deal_id)


def current_best_human_path(deal_id: str, archive_root: Optional[Path] = None) -> Path:
    return deal_archive_dir(deal_id, archive_root) / f"{deal_id}_best_solution.txt"


def current_best_moves_path(deal_id: str, archive_root: Optional[Path] = None) -> Path:
    return deal_archive_dir(deal_id, archive_root) / f"{deal_id}_best_solution.moves.txt"


def metadata_path(deal_id: str, archive_root: Optional[Path] = None) -> Path:
    return deal_archive_dir(deal_id, archive_root) / f"{deal_id}_best_solution_metadata.json"


def history_dir(deal_id: str, archive_root: Optional[Path] = None) -> Path:
    return deal_archive_dir(deal_id, archive_root) / "history"


def archive_log_path(deal_id: str, archive_root: Optional[Path] = None) -> Path:
    return deal_archive_dir(deal_id, archive_root) / "solution_archive.log"


def deal_file_for(deal_id: str) -> Path:
    p = REPO_ROOT / "deals" / f"{deal_id}.txt"
    if not p.is_file():
        raise FileNotFoundError(f"deal file not found: {p}")
    return p


def canonical_repo_moves(deal_id: str) -> Path:
    return REPO_ROOT / "solutions" / f"{deal_id}_canonical.moves"


# ---------------------------------------------------------------------------
# Parsing / hashing
# ---------------------------------------------------------------------------


def normalize_actions(moves: MoveInput) -> List[Action]:
    if isinstance(moves, (str, Path)):
        return parse_moves_file(Path(moves))
    out: List[Action] = []
    for m in moves:
        if isinstance(m, str):
            p = m.strip().split()
            if not p:
                continue
            if p[0] == "deal":
                out.append(("deal",))
            elif p[0] == "move" and len(p) >= 4:
                out.append((int(p[1]) - 1, int(p[2]) - 1, int(p[3])))
            else:
                raise ValueError(f"bad move string: {m}")
        elif isinstance(m, tuple):
            if len(m) == 1 and m[0] == "deal":
                out.append(("deal",))
            elif len(m) == 3:
                out.append((int(m[0]), int(m[1]), int(m[2])))
            else:
                raise ValueError(f"bad action tuple: {m}")
        else:
            raise ValueError(f"unsupported move type: {type(m)}")
    return out


def path_hash(actions: Sequence[Action]) -> str:
    """Deterministic hash of the command sequence (0-based internal form)."""
    payload = repr([(a if a != ("deal",) else ("deal",)) for a in actions])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def actions_to_move_lines(actions: Sequence[Action]) -> List[str]:
    return [format_action(a) for a in actions]


# ---------------------------------------------------------------------------
# Independent validation
# ---------------------------------------------------------------------------


def validate_solution(
    deal_id: str,
    moves: MoveInput,
    *,
    claimed_mobilityware_moves: Optional[int] = None,
    expected_deal_id: Optional[str] = None,
) -> ValidationResult:
    """Independently replay and score a candidate. Never trust caller metrics."""
    if expected_deal_id is not None and str(expected_deal_id) != str(deal_id):
        return ValidationResult(
            valid=False,
            failure_reason=f"deal id mismatch: expected {expected_deal_id}, got {deal_id}",
        )
    try:
        actions = normalize_actions(moves)
    except Exception as exc:
        return ValidationResult(valid=False, failure_reason=f"parse failed: {exc}")
    if not actions:
        return ValidationResult(valid=False, failure_reason="empty move sequence")

    try:
        deal_path = deal_file_for(deal_id)
        state = SpiderState.from_cards(load_deal(deal_path))
        counters = replay_actions_detailed(state, actions)
    except Exception as exc:
        return ValidationResult(
            valid=False,
            failure_reason=f"replay failed: {exc}",
            actions=list(actions),
        )

    solved = state.is_solved()
    foundations = len(state.foundations)
    stock = len(state.stock)
    mw = int(counters["mobilityware_moves"])
    ph = path_hash(actions)
    sh = format(zobrist(state), "x")

    if not solved:
        return ValidationResult(
            valid=False,
            solved=False,
            mobilityware_moves=mw,
            explicit_commands=counters["explicit_commands"],
            tableau_moves=counters["tableau_moves"],
            stock_deals=counters["stock_deals"],
            automatic_foundation_removals=counters["automatic_foundation_removals"],
            foundations=foundations,
            stock_remaining=stock,
            path_hash=ph,
            state_hash=sh,
            actions=list(actions),
            failure_reason="not solved after full replay",
            counters=counters,
        )
    if foundations != 8:
        return ValidationResult(
            valid=False,
            solved=False,
            failure_reason=f"foundations={foundations} != 8",
            actions=list(actions),
            counters=counters,
        )
    if stock != 0:
        return ValidationResult(
            valid=False,
            solved=True,
            failure_reason=f"stock remaining={stock} != 0",
            actions=list(actions),
            counters=counters,
        )
    if claimed_mobilityware_moves is not None and claimed_mobilityware_moves != mw:
        return ValidationResult(
            valid=False,
            solved=True,
            mobilityware_moves=mw,
            failure_reason=(
                f"claimed mobilityware_moves={claimed_mobilityware_moves} "
                f"disagrees with independent replay={mw}"
            ),
            actions=list(actions),
            counters=counters,
            path_hash=ph,
            state_hash=sh,
        )

    return ValidationResult(
        valid=True,
        solved=True,
        mobilityware_moves=mw,
        explicit_commands=counters["explicit_commands"],
        tableau_moves=counters["tableau_moves"],
        stock_deals=counters["stock_deals"],
        automatic_foundation_removals=counters["automatic_foundation_removals"],
        foundations=8,
        stock_remaining=0,
        path_hash=ph,
        state_hash=sh,
        actions=list(actions),
        counters=counters,
    )


# ---------------------------------------------------------------------------
# Atomic IO
# ---------------------------------------------------------------------------


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _append_log(deal_id: str, message: str, archive_root: Optional[Path] = None) -> None:
    logp = archive_log_path(deal_id, archive_root)
    logp.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(logp, "a", encoding="utf-8") as f:
        f.write(f"{ts} {message}\n")
        f.flush()


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _git_commit() -> Optional[str]:
    try:
        import subprocess

        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0:
            return r.stdout.strip() or None
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Format writers
# ---------------------------------------------------------------------------


def format_human_readable(
    *,
    deal_id: str,
    validation: ValidationResult,
    source: str,
    created_utc: str,
    previous_incumbent: Optional[int],
    improvement: Optional[int],
    experiment_id: Optional[str],
    repository_commit: Optional[str],
) -> str:
    lines = [
        f"Deal: {deal_id}",
        f"Verified MobilityWare moves: {validation.mobilityware_moves}",
        f"Explicit commands: {validation.explicit_commands}",
        f"Tableau moves: {validation.tableau_moves}",
        f"Stock deals: {validation.stock_deals}",
        f"Automatic foundation removals: {validation.automatic_foundation_removals}",
        f"Solved: yes",
        f"Foundations: {validation.foundations}",
        f"Stock remaining: {validation.stock_remaining}",
        f"Path hash: {validation.path_hash}",
        f"Final state hash: {validation.state_hash}",
        f"Source: {source}",
        f"Created UTC: {created_utc}",
        f"Validator version: {VALIDATOR_VERSION}",
        f"Metric: corrected mobilityware_moves ({METRIC_VERSION})",
        f"Previous incumbent: {previous_incumbent if previous_incumbent is not None else 'none'}",
        f"Improvement: {improvement if improvement is not None else 'baseline'}",
        f"Repository commit: {repository_commit or 'unknown'}",
        f"Experiment id: {experiment_id or 'n/a'}",
        "",
        "Moves:",
    ]
    lines.extend(actions_to_move_lines(validation.actions))
    lines.append("")
    return "\n".join(lines)


def format_parser_ready(actions: Sequence[Action]) -> str:
    return "\n".join(actions_to_move_lines(actions)) + "\n"


# ---------------------------------------------------------------------------
# Incumbent load
# ---------------------------------------------------------------------------


def load_incumbent(
    deal_id: str,
    *,
    archive_root: Optional[Path] = None,
    include_repo_canonical: bool = False,
) -> Optional[ValidationResult]:
    """Load and independently re-validate external current best (if any).

    By default only the external archive (current-best + history) is considered.
    Pass ``include_repo_canonical=True`` for startup fallback selection.
    """
    moves_p = current_best_moves_path(deal_id, archive_root)
    if moves_p.is_file():
        v = validate_solution(deal_id, moves_p)
        if v.valid:
            return v
        # corrupt: preserve, try history
        corrupt_name = f"{moves_p.name}.corrupt.{_utc_stamp()}"
        try:
            shutil.copy2(moves_p, moves_p.with_name(corrupt_name))
            _append_log(
                deal_id,
                f"CORRUPT current-best moves preserved as {corrupt_name}: {v.failure_reason}",
                archive_root,
            )
        except OSError:
            pass

    # history newest first
    hdir = history_dir(deal_id, archive_root)
    if hdir.is_dir():
        hist = sorted(hdir.glob(f"{deal_id}_mw*_*.moves.txt"), reverse=True)
        for hp in hist:
            v = validate_solution(deal_id, hp)
            if v.valid:
                _append_log(
                    deal_id,
                    f"RECOVERY used history {hp.name} mw={v.mobilityware_moves}",
                    archive_root,
                )
                return v

    if include_repo_canonical:
        canon = canonical_repo_moves(deal_id)
        if canon.is_file():
            v = validate_solution(deal_id, canon)
            if v.valid:
                return v
    return None


def select_startup_incumbent(
    deal_id: str,
    *,
    archive_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Compare external best vs repo canonical; pick lowest verified."""
    root = Path(archive_root) if archive_root else default_archive_root()
    external = None
    moves_p = current_best_moves_path(deal_id, root)
    if moves_p.is_file():
        external = validate_solution(deal_id, moves_p)

    repo = None
    canon = canonical_repo_moves(deal_id)
    if canon.is_file():
        repo = validate_solution(deal_id, canon)

    conflict = None
    chosen: Optional[ValidationResult] = None
    source = ""

    if external and external.valid and repo and repo.valid:
        if external.mobilityware_moves != repo.mobilityware_moves:
            conflict = (
                f"external mw={external.mobilityware_moves} "
                f"vs repo mw={repo.mobilityware_moves}"
            )
        if external.mobilityware_moves <= repo.mobilityware_moves:  # type: ignore
            chosen, source = external, "external_current_best"
        else:
            chosen, source = repo, "repository_canonical"
    elif external and external.valid:
        chosen, source = external, "external_current_best"
    elif repo and repo.valid:
        chosen, source = repo, "repository_canonical"
    else:
        # try history then repo
        chosen = load_incumbent(
            deal_id, archive_root=root, include_repo_canonical=True
        )
        source = "history_or_repo_fallback" if chosen else "none"

    return {
        "incumbent": chosen,
        "source": source,
        "conflict": conflict,
        "archive_root": str(root),
        "external_valid": bool(external and external.valid),
        "repo_valid": bool(repo and repo.valid),
    }


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------


def record_solution_if_better(
    deal_id: str,
    moves: MoveInput,
    source: str,
    *,
    experiment_id: Optional[str] = None,
    repository_commit: Optional[str] = None,
    archive_root: Optional[Union[str, Path]] = None,
    claimed_mobilityware_moves: Optional[int] = None,
    force_baseline: bool = False,
) -> SolutionArchiveResult:
    """Validate candidate and archive only if strictly better than incumbent.

    ``force_baseline=True`` writes even when no prior incumbent exists (bootstrap).
    Equal scores never replace. Worse candidates never replace.
    """
    root = Path(archive_root) if archive_root else default_archive_root()
    result = SolutionArchiveResult(
        deal_id=str(deal_id),
        source=source,
        archive_root=str(root),
    )

    # Never accept legacy_mw claims
    if claimed_mobilityware_moves == 163 and str(deal_id) == "4925153":
        # 163 was the withdrawn legacy total; still validate independently —
        # only reject if claim is used without matching replay (handled below).
        pass

    validation = validate_solution(
        deal_id,
        moves,
        claimed_mobilityware_moves=claimed_mobilityware_moves,
        expected_deal_id=deal_id,
    )
    result.candidate_valid = validation.valid
    result.candidate_solved = validation.solved
    result.candidate_mobilityware_moves = validation.mobilityware_moves
    result.path_hash = validation.path_hash
    result.state_hash = validation.state_hash

    if not validation.valid:
        result.failure_reason = validation.failure_reason or "validation failed"
        _append_log(
            deal_id,
            f"REJECTED source={source} reason={result.failure_reason}",
            root,
        )
        return result

    # Load external archive incumbent only (not repo canonical).
    incumbent = load_incumbent(deal_id, archive_root=root, include_repo_canonical=False)
    if incumbent and incumbent.valid:
        result.incumbent_mobilityware_moves = incumbent.mobilityware_moves
    else:
        result.incumbent_mobilityware_moves = None

    cand_mw = int(validation.mobilityware_moves or 10**9)
    if result.incumbent_mobilityware_moves is not None:
        if cand_mw >= int(result.incumbent_mobilityware_moves) and not (
            force_baseline and cand_mw == int(result.incumbent_mobilityware_moves)
        ):
            # force_baseline with equal score is still no-op if external already has it
            result.is_strict_improvement = False
            result.failure_reason = (
                f"not strict improvement: candidate={cand_mw} "
                f"incumbent={result.incumbent_mobilityware_moves}"
            )
            _append_log(
                deal_id,
                f"NO_IMPROVE source={source} cand={cand_mw} "
                f"incumbent={result.incumbent_mobilityware_moves} hash={validation.path_hash}",
                root,
            )
            return result
        if cand_mw < int(result.incumbent_mobilityware_moves):
            result.is_strict_improvement = True
            previous = int(result.incumbent_mobilityware_moves)
            improvement = previous - cand_mw
        else:
            # equal + force_baseline but already present
            result.is_strict_improvement = False
            result.failure_reason = (
                f"not strict improvement: candidate={cand_mw} "
                f"incumbent={result.incumbent_mobilityware_moves}"
            )
            return result
    else:
        # No external incumbent — allow baseline write (bootstrap)
        result.is_strict_improvement = False
        previous = None
        improvement = "baseline"

    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    stamp = _utc_stamp()
    commit = repository_commit or _git_commit()
    mw_pad = f"{cand_mw:04d}"
    hist_base = f"{deal_id}_mw{mw_pad}_{stamp}_{validation.path_hash}"

    ddir = deal_archive_dir(deal_id, root)
    hdir = history_dir(deal_id, root)
    try:
        ddir.mkdir(parents=True, exist_ok=True)
        hdir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        result.failure_reason = f"cannot create archive dir: {exc}"
        emerg = _emergency_save(deal_id, validation, source)
        result.emergency_recovery_path = emerg
        return result

    human_text = format_human_readable(
        deal_id=deal_id,
        validation=validation,
        source=source,
        created_utc=created,
        previous_incumbent=previous,
        improvement=improvement if improvement is not None else "baseline",
        experiment_id=experiment_id,
        repository_commit=commit,
    )
    moves_text = format_parser_ready(validation.actions)
    meta = {
        "deal_id": deal_id,
        "mobilityware_moves": cand_mw,
        "explicit_commands": validation.explicit_commands,
        "tableau_moves": validation.tableau_moves,
        "stock_deals": validation.stock_deals,
        "automatic_foundation_removals": validation.automatic_foundation_removals,
        "solved": True,
        "foundations": 8,
        "stock_remaining": 0,
        "path_hash": validation.path_hash,
        "state_hash": validation.state_hash,
        "source": source,
        "created_utc": created,
        "validator_version": VALIDATOR_VERSION,
        "metric_version": METRIC_VERSION,
        "previous_incumbent": previous,
        "improvement": improvement,
        "experiment_id": experiment_id,
        "repository_commit": commit,
        "archive_root": str(root),
    }

    hist_human = hdir / f"{hist_base}.txt"
    hist_moves = hdir / f"{hist_base}.moves.txt"
    cur_human = current_best_human_path(deal_id, root)
    cur_moves = current_best_moves_path(deal_id, root)
    cur_meta = metadata_path(deal_id, root)

    try:
        # 1) immutable history first
        _atomic_write_text(hist_human, human_text)
        _atomic_write_text(hist_moves, moves_text)
        result.historical_copy_written = True
        result.history_human_path = str(hist_human)
        result.history_moves_path = str(hist_moves)

        # 2) replace current best
        _atomic_write_text(cur_moves, moves_text)
        _atomic_write_text(cur_human, human_text)
        _atomic_write_text(cur_meta, json.dumps(meta, indent=2) + "\n")

        # 3) read-back verification
        rb = validate_solution(deal_id, cur_moves)
        if not rb.valid or rb.mobilityware_moves != cand_mw:
            raise RuntimeError(
                f"read-back validation failed: {rb.failure_reason} "
                f"mw={rb.mobilityware_moves}"
            )
        if rb.path_hash != validation.path_hash:
            raise RuntimeError(
                f"read-back path hash mismatch: {rb.path_hash} vs {validation.path_hash}"
            )
        # human file must contain move lines
        human_body = cur_human.read_text(encoding="utf-8")
        for line in actions_to_move_lines(validation.actions):
            if line not in human_body:
                raise RuntimeError(f"human-readable missing move: {line}")
        meta_rb = json.loads(cur_meta.read_text(encoding="utf-8"))
        if int(meta_rb.get("mobilityware_moves", -1)) != cand_mw:
            raise RuntimeError("metadata mobilityware_moves mismatch after write")
        if meta_rb.get("path_hash") != validation.path_hash:
            raise RuntimeError("metadata path_hash mismatch after write")

        result.external_archive_written = True
        result.current_best_updated = True
        result.human_readable_path = str(cur_human)
        result.parser_ready_path = str(cur_moves)
        result.metadata_path = str(cur_meta)
        _append_log(
            deal_id,
            f"ARCHIVED improvement source={source} mw={cand_mw} "
            f"prev={previous} hash={validation.path_hash} "
            f"human={cur_human.name}",
            root,
        )
    except Exception as exc:
        result.failure_reason = f"archive write/verify failed: {exc}"
        result.external_archive_written = False
        result.current_best_updated = False
        emerg = _emergency_save(deal_id, validation, source)
        result.emergency_recovery_path = emerg
        _append_log(
            deal_id,
            f"ARCHIVE_FAIL source={source} mw={cand_mw} err={exc} emergency={emerg}",
            root,
        )
        # history may have been written — keep historical_copy_written flag

    return result


def _emergency_save(
    deal_id: str, validation: ValidationResult, source: str
) -> Optional[str]:
    try:
        d = EMERGENCY_RECOVERY / str(deal_id)
        d.mkdir(parents=True, exist_ok=True)
        stamp = _utc_stamp()
        p = d / f"emergency_mw{validation.mobilityware_moves}_{stamp}_{validation.path_hash}.moves.txt"
        _atomic_write_text(p, format_parser_ready(validation.actions))
        meta = d / f"emergency_mw{validation.mobilityware_moves}_{stamp}.json"
        _atomic_write_text(
            meta,
            json.dumps(
                {
                    "deal_id": deal_id,
                    "source": source,
                    "mobilityware_moves": validation.mobilityware_moves,
                    "path_hash": validation.path_hash,
                    "failure": "external archive write failed",
                },
                indent=2,
            )
            + "\n",
        )
        return str(p)
    except Exception:
        return None


def bootstrap_deal(
    deal_id: str = "4925153",
    *,
    archive_root: Optional[Union[str, Path]] = None,
    canonical_path: Optional[Path] = None,
) -> SolutionArchiveResult:
    """Independently validate repo canonical and install as external baseline."""
    root = Path(archive_root) if archive_root else default_archive_root()
    canon = Path(canonical_path) if canonical_path else canonical_repo_moves(deal_id)
    if not canon.is_file():
        r = SolutionArchiveResult(deal_id=deal_id, archive_root=str(root))
        r.failure_reason = f"canonical not found: {canon}"
        return r
    return record_solution_if_better(
        deal_id,
        canon,
        source="user-supplied canonical trace",
        archive_root=root,
        force_baseline=True,
        experiment_id="bootstrap_canonical",
    )


def verify_archive(
    deal_id: str,
    *,
    archive_root: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    root = Path(archive_root) if archive_root else default_archive_root()
    moves_p = current_best_moves_path(deal_id, root)
    human_p = current_best_human_path(deal_id, root)
    meta_p = metadata_path(deal_id, root)
    out: Dict[str, Any] = {
        "archive_root": str(root),
        "deal_id": deal_id,
        "moves_path": str(moves_p),
        "human_path": str(human_p),
        "metadata_path": str(meta_p),
        "moves_exists": moves_p.is_file(),
        "human_exists": human_p.is_file(),
        "metadata_exists": meta_p.is_file(),
    }
    if not moves_p.is_file():
        out["valid"] = False
        out["reason"] = "missing current-best moves file"
        return out
    v = validate_solution(deal_id, moves_p)
    out["validation"] = {
        "valid": v.valid,
        "mobilityware_moves": v.mobilityware_moves,
        "path_hash": v.path_hash,
        "solved": v.solved,
        "failure_reason": v.failure_reason,
    }
    out["valid"] = v.valid
    if meta_p.is_file():
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        out["metadata_matches"] = (
            int(meta.get("mobilityware_moves", -1)) == v.mobilityware_moves
            and meta.get("path_hash") == v.path_hash
        )
        if not out["metadata_matches"]:
            out["valid"] = False
            out["reason"] = "metadata mismatch with replay"
    return out


def list_history(
    deal_id: str,
    *,
    archive_root: Optional[Union[str, Path]] = None,
) -> List[Dict[str, Any]]:
    root = Path(archive_root) if archive_root else default_archive_root()
    hdir = history_dir(deal_id, root)
    if not hdir.is_dir():
        return []
    items = []
    for p in sorted(hdir.glob(f"{deal_id}_mw*_*.moves.txt")):
        items.append({"path": str(p), "name": p.name, "size": p.stat().st_size})
    return items


def show_best(
    deal_id: str,
    *,
    archive_root: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    root = Path(archive_root) if archive_root else default_archive_root()
    v = load_incumbent(deal_id, archive_root=root)
    return {
        "archive_root": str(root),
        "deal_id": deal_id,
        "human_readable_path": str(current_best_human_path(deal_id, root)),
        "parser_ready_path": str(current_best_moves_path(deal_id, root)),
        "metadata_path": str(metadata_path(deal_id, root)),
        "valid": bool(v and v.valid),
        "mobilityware_moves": v.mobilityware_moves if v else None,
        "path_hash": v.path_hash if v else None,
        "source_note": "independently re-validated",
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="python -m spider.solution_archive",
        description="External best-solution archive for Spider Solver",
    )
    ap.add_argument(
        "--archive-root",
        default=None,
        help=f"Override archive root (default/env: {default_archive_root()})",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_boot = sub.add_parser("bootstrap", help="Bootstrap canonical as external incumbent")
    p_boot.add_argument("--deal", default="4925153")

    p_con = sub.add_parser("consider", help="Validate and consider a move file")
    p_con.add_argument("--deal", default="4925153")
    p_con.add_argument("--moves", required=True)
    p_con.add_argument("--source", default="cli_consider")
    p_con.add_argument("--experiment-id", default=None)

    p_show = sub.add_parser("show", help="Show current best")
    p_show.add_argument("--deal", default="4925153")

    p_ver = sub.add_parser("verify", help="Verify archive integrity")
    p_ver.add_argument("--deal", default="4925153")

    p_hist = sub.add_parser("history", help="List historical archives")
    p_hist.add_argument("--deal", default="4925153")

    args = ap.parse_args(argv)
    root = Path(args.archive_root) if args.archive_root else default_archive_root()
    print(f"Archive root: {root}")

    if args.cmd == "bootstrap":
        r = bootstrap_deal(args.deal, archive_root=root)
        print(json.dumps(r.to_dict(), indent=2))
        return 0 if r.external_archive_written or r.current_best_updated else 1

    if args.cmd == "consider":
        r = record_solution_if_better(
            args.deal,
            Path(args.moves),
            source=args.source,
            experiment_id=args.experiment_id,
            archive_root=root,
        )
        print(json.dumps(r.to_dict(), indent=2))
        return 0 if r.candidate_valid else 1

    if args.cmd == "show":
        print(json.dumps(show_best(args.deal, archive_root=root), indent=2))
        return 0

    if args.cmd == "verify":
        out = verify_archive(args.deal, archive_root=root)
        print(json.dumps(out, indent=2))
        return 0 if out.get("valid") else 1

    if args.cmd == "history":
        print(json.dumps(list_history(args.deal, archive_root=root), indent=2))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
