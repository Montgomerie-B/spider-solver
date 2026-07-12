"""Shared optimizer loop for CLI and GUI."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional

from .deal import load_deal, tokens_from_file
from .engine import SpiderState
from .macro import MacroConfig, macro_solve_with_restarts
from .metrics import (
    CANONICAL_MW_COST,
    RECORD_MW_COST,
    Action,
    export_actions_to_moves_file,
    mw_cost_from_moves_file,
    parse_moves_file,
    replay_actions,
)
from .search import bounded_ucs, ida_star

LogCallback = Callable[[str], None]
StatsCallback = Callable[[dict], None]
ImprovementCallback = Callable[[int, List[Action]], None]


@dataclass
class OptimizerSettings:
    deal_path: Path
    aspire: int = RECORD_MW_COST
    bound: str | int = "auto"
    canonical_path: Path | None = None
    out_path: Path | None = None
    state_path: Path | None = None
    log_path: Path | None = None
    secs: float = 2.0
    beam: int = 1200
    finish: float = 8.0
    restarts: int = 6
    max_exp: int = 4000
    growth: float = 1.35
    run_forever: bool = True
    use_ucs: bool = False
    use_ida: bool = False
    prefix_moves: Optional[Path] = None


@dataclass
class OptimizerStats:
    best_cost: int = CANONICAL_MW_COST
    upper_bound: int = CANONICAL_MW_COST
    aspire: int = RECORD_MW_COST
    attempts: int = 0
    total_nodes: int = 0
    last_mw: int = 9999
    last_solved: bool = False
    last_elapsed: float = 0.0
    running: bool = False
    secs: float = 2.0
    beam: int = 1200
    finish: float = 8.0
    message: str = "Idle"


def load_state(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_state_file(
    path: Path,
    *,
    best_cost: int,
    bound: int,
    attempts: int,
    total_nodes: int,
    aspire: int,
) -> None:
    path.write_text(
        json.dumps(
            {
                "best_cost": best_cost,
                "upper_bound": bound,
                "attempts": attempts,
                "total_nodes": total_nodes,
                "aspire": aspire,
                "updated": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def resolve_upper_bound(settings: OptimizerSettings) -> int:
    if settings.bound != "auto":
        return int(settings.bound)
    canonical = settings.canonical_path
    if canonical and canonical.exists():
        return mw_cost_from_moves_file(canonical, settings.deal_path)
    return CANONICAL_MW_COST


def append_log(msg: str, log_path: Path | None, on_log: LogCallback | None) -> str:
    line = f"{datetime.now(timezone.utc).strftime('%H:%M:%S')} {msg}"
    if on_log:
        on_log(line)
    if log_path:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat()} {msg}\n")
    return line


class OptimizerSession:
    """Runs optimization in a background thread; call ``stop()`` to end."""

    def __init__(
        self,
        settings: OptimizerSettings,
        *,
        on_log: LogCallback | None = None,
        on_stats: StatsCallback | None = None,
        on_improvement: ImprovementCallback | None = None,
    ) -> None:
        self.settings = settings
        self.on_log = on_log
        self.on_stats = on_stats
        self.on_improvement = on_improvement
        self.stats = OptimizerStats(aspire=settings.aspire)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.stats.message = "Stopping…"

    def _emit_stats(self) -> None:
        if self.on_stats:
            self.on_stats(
                {
                    "best_cost": self.stats.best_cost,
                    "upper_bound": self.stats.upper_bound,
                    "aspire": self.stats.aspire,
                    "attempts": self.stats.attempts,
                    "total_nodes": self.stats.total_nodes,
                    "last_mw": self.stats.last_mw,
                    "last_solved": self.stats.last_solved,
                    "last_elapsed": self.stats.last_elapsed,
                    "running": self.stats.running,
                    "secs": self.stats.secs,
                    "beam": self.stats.beam,
                    "finish": self.stats.finish,
                    "message": self.stats.message,
                }
            )

    def _log(self, msg: str) -> None:
        append_log(msg, self.settings.log_path, self.on_log)

    def _save_improvement(self, cost: int, actions: List[Action]) -> None:
        out = self.settings.out_path
        if out:
            export_actions_to_moves_file(
                actions,
                out,
                header=f"MW cost {cost} — Spider Optimizer",
            )
        # Durable external archive (corrected mobilityware_moves; independent replay).
        try:
            from spider.solution_archive import record_solution_if_better

            deal_id = "4925153"
            if self.settings.deal_path is not None:
                deal_id = self.settings.deal_path.stem
            arch = record_solution_if_better(
                deal_id,
                actions,
                source="optimizer_session",
                experiment_id="optimizer_session",
                claimed_mobilityware_moves=None,  # never trust runner cost alone
            )
            if arch.current_best_updated:
                self._log(
                    f"EXTERNAL ARCHIVE updated mw={arch.candidate_mobilityware_moves} "
                    f"path={arch.parser_ready_path}"
                )
                if arch.candidate_mobilityware_moves is not None:
                    self.stats.best_cost = min(
                        self.stats.best_cost, int(arch.candidate_mobilityware_moves)
                    )
                    self.stats.upper_bound = min(
                        self.stats.upper_bound, int(arch.candidate_mobilityware_moves)
                    )
            elif arch.failure_reason:
                self._log(f"EXTERNAL ARCHIVE note: {arch.failure_reason}")
        except Exception as exc:  # noqa: BLE001 — never fail optimise path silently unlogged
            self._log(f"EXTERNAL ARCHIVE error: {exc}")
        state_path = self.settings.state_path
        if state_path:
            save_state_file(
                state_path,
                best_cost=self.stats.best_cost,
                bound=self.stats.upper_bound,
                attempts=self.stats.attempts,
                total_nodes=self.stats.total_nodes,
                aspire=self.stats.aspire,
            )
        if self.on_improvement:
            self.on_improvement(cost, actions)

    def _persist_stats(self) -> None:
        state_path = self.settings.state_path
        if state_path:
            save_state_file(
                state_path,
                best_cost=self.stats.best_cost,
                bound=self.stats.upper_bound,
                attempts=self.stats.attempts,
                total_nodes=self.stats.total_nodes,
                aspire=self.stats.aspire,
            )

    def _run_loop(self) -> None:
        s = self.settings
        root_dir = s.deal_path.resolve().parents[1] if s.deal_path else Path.cwd()
        canonical = s.canonical_path or (root_dir / "solutions" / "4925153_canonical.moves")
        out_path = s.out_path or (root_dir / "solutions" / "4925153_best.moves")
        state_path = s.state_path or (root_dir / "optimizer_state.json")
        log_path = s.log_path or (root_dir / "optimizer.log")

        s.canonical_path = canonical
        s.out_path = out_path
        s.state_path = state_path
        s.log_path = log_path

        upper_bound = resolve_upper_bound(s)
        persisted = load_state(state_path)
        if persisted.get("upper_bound"):
            upper_bound = min(upper_bound, int(persisted["upper_bound"]))

        self.stats.upper_bound = upper_bound
        self.stats.best_cost = int(persisted.get("best_cost", upper_bound))
        self.stats.attempts = int(persisted.get("attempts", 0))
        self.stats.total_nodes = int(persisted.get("total_nodes", 0))
        self.stats.secs = s.secs
        self.stats.beam = s.beam
        self.stats.finish = s.finish
        self.stats.running = True
        self.stats.message = "Running"
        self._emit_stats()

        tokens = tokens_from_file(s.deal_path)
        base_root = SpiderState.from_cards(load_deal(s.deal_path))

        # Support "scripted human approaches": replay a validated .moves prefix (e.g.
        # 4925153_reference.moves or after_deal1) to a strong mid-game state. The
        # remaining search optimizes only the suffix using the correct start_round
        # (for deal-aware reception in later macro phases). Totals are assembled on
        # any sub-solved result so best.moves is always a complete replayable solution.
        prefix_actions: List[Action] = []
        prefix_mw = 0
        start_round = 0
        search_root = base_root
        if s.prefix_moves and Path(s.prefix_moves).exists():
            ppath = Path(s.prefix_moves)
            prefix_actions = parse_moves_file(ppath)
            search_root = SpiderState.from_cards(load_deal(s.deal_path))
            prefix_mw = replay_actions(search_root, prefix_actions)
            start_round = (
                5 - (len(search_root.stock) // 10) if len(search_root.stock) >= 0 else 5
            )
            self._log(
                f"Using prefix {ppath.name}: {len(prefix_actions)} actions, "
                f"prefix_mw={prefix_mw}, start_round={start_round}"
            )

        self._log(
            f"START deal={s.deal_path.name} bound={upper_bound} aspire={s.aspire} "
            f"best={self.stats.best_cost}"
        )

        secs, beam, finish = s.secs, s.beam, s.finish

        try:
            while not self._stop.is_set():
                self.stats.attempts += 1
                t0 = time.time()

                # Compute remaining allowed cost for the *suffix* search. The overall
                # upper_bound / best_cost are always total MW (including any prefix).
                sub_upper = upper_bound - prefix_mw
                if sub_upper <= 0:
                    # Prefix alone already meets or exceeds bound; nothing to gain this attempt.
                    solved, actions, nodes, mw = False, [], 0, 9999
                elif s.use_ida:
                    r = ida_star(search_root.clone(), upper_bound=sub_upper, max_iterations=50)
                    solved, actions, nodes, mw = r.solved, r.actions, r.nodes, r.mw_cost
                elif s.use_ucs:
                    r = bounded_ucs(
                        search_root.clone(),
                        upper_bound=sub_upper,
                        max_nodes=500_000,
                        time_limit=finish * 10,
                        progress=False,
                    )
                    solved, actions, nodes, mw = r.solved, r.actions, r.nodes, r.mw_cost
                else:
                    cfg = MacroConfig(
                        per_round_secs=secs,
                        beam_width=beam,
                        finish_secs=finish,
                        max_expansions=s.max_exp,
                        upper_bound=sub_upper,
                        restarts=s.restarts,
                    )
                    result = macro_solve_with_restarts(
                        search_root, tokens, config=cfg, progress=False, start_round=start_round
                    )
                    solved = result.solved
                    actions = result.actions
                    nodes = result.nodes
                    mw = result.mw_cost
                    if s.run_forever:
                        secs = min(120.0, secs * s.growth)
                        beam = min(8000, int(beam * s.growth))
                        finish = min(600.0, finish * s.growth)
                        self.stats.secs, self.stats.beam, self.stats.finish = secs, beam, finish

                # Assemble totals when a suffix solve succeeded. This is what gets
                # persisted/saved/logged/compared so the optimizer produces complete
                # solutions even when bootstrapping from a human-scripted prefix.
                total_mw = prefix_mw + mw if solved else 9999
                total_actions = (prefix_actions + actions) if solved else []

                elapsed = time.time() - t0
                self.stats.total_nodes += nodes
                self.stats.last_mw = total_mw
                self.stats.last_solved = solved
                self.stats.last_elapsed = elapsed

                if solved:
                    if total_mw < self.stats.best_cost:
                        self.stats.best_cost = total_mw
                        upper_bound = total_mw
                        self.stats.upper_bound = upper_bound
                        self._save_improvement(total_mw, total_actions)
                        self._log(f"NEW BEST {total_mw} MW moves → {out_path.name}")
                    else:
                        # Still capture the first machine-found full solution even if
                        # its total cost is currently higher than the human canonical 163.
                        # This gives us a complete replayable win found by the solver+strategy.
                        self._save_improvement(total_mw, total_actions)
                        self._log(f"FOUND SOLUTION mw={total_mw} ( > current best {self.stats.best_cost}) → {out_path.name}")

                self._persist_stats()
                self._emit_stats()

                self._log(
                    f"Attempt {self.stats.attempts}: solved={solved} mw={total_mw} "
                    f"nodes={nodes} {elapsed:.1f}s best={self.stats.best_cost}"
                )

                if solved and total_mw <= s.aspire:
                    self.stats.message = f"Record reached ({s.aspire})!"
                    self._log(f"DONE — aspiration {s.aspire} reached")
                    break

                if not s.run_forever:
                    break
                if self.stats.best_cost <= s.aspire:
                    break

        except Exception as exc:
            self.stats.message = f"Error: {exc}"
            self._log(f"ERROR {exc}")
            self._emit_stats()
        finally:
            self.stats.running = False
            if self.stats.message == "Running":
                self.stats.message = "Stopped"
            self._emit_stats()
            self._log(f"STOP best={self.stats.best_cost} attempts={self.stats.attempts}")