"""Optimise tab. Search runs in a child process so the board stays responsive."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from spider.app_paths import repo_root
from spider.autonomous_solve_campaign import atomic_write_json
from spider.packaged_runtime import ABSOLUTE_IDENTITY_CAP, load_manifest, resource_report
from spider.unattended_optimiser import (
    best_moves_path,
    coerce_run_start,
    default_optimiser_dir,
    open_verified_route,
    read_json,
    recover_campaign,
)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return float(default)
    return float(raw)


def _campaign_directory(directory: Path | None) -> Path:
    if directory is not None:
        return Path(directory)
    override = os.environ.get("SPIDER_PLAY_LAB_OPTIMISER_DIR")
    if override:
        return Path(override)
    return default_optimiser_dir()


def _alive(pid: int) -> bool:
    if int(pid) <= 0:
        return False
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return bool(ok) and int(code.value) == 259
    try:
        os.kill(int(pid), 0)
    except OSError:
        return False
    return True


def _kill_tree(pid: int) -> None:
    if int(pid) <= 0:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
            capture_output=True,
            check=False,
        )
        return
    try:
        os.kill(int(pid), 15)
    except OSError:
        return


def supervisor_command(directory: Path) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--optimiser-supervisor", "--campaign", str(directory)]
    play = Path(__file__).resolve().parents[2] / "tools" / "play_lab.py"
    return [sys.executable, str(play), "--optimiser-supervisor", "--campaign", str(directory)]


class OptimisePanel:
    def __init__(self, app, parent, *, directory: Path | None = None):
        import tkinter as tk
        from tkinter import ttk

        self.app = app
        self.directory = _campaign_directory(directory)
        self._poll_id = None
        self._closed = False
        self._stopping = False
        self._log_handle = None
        self._process = None
        self.duration_min = tk.DoubleVar(value=_env_float("SPIDER_PLAY_LAB_DURATION_MIN", 20))
        self.attempt_s = tk.DoubleVar(value=_env_float("SPIDER_PLAY_LAB_ATTEMPT_S", 180))
        self.max_unique = tk.IntVar(value=int(_env_float("SPIDER_PLAY_LAB_MAX_UNIQUE", 2_000_000)))
        self.requested_rss = tk.DoubleVar(value=_env_float("SPIDER_PLAY_LAB_RSS_MB", 3000))
        self.status = tk.StringVar(value="Idle. Deal 4925153 only. One worker.")
        self.best = tk.StringVar(value="Best 140 · target 139")
        self.job = tk.StringVar(value="No job yet")
        self.resources = tk.StringVar(value="")
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(2, 4))
        ttk.Button(buttons, text="Start", command=self.start).pack(side="left", padx=1)
        ttk.Button(buttons, text="Pause", command=self.pause).pack(side="left", padx=1)
        ttk.Button(buttons, text="Resume", command=self.resume).pack(side="left", padx=1)
        ttk.Button(buttons, text="Stop", command=self.stop).pack(side="left", padx=1)
        ttk.Button(buttons, text="Open verified best", command=self.open_best).pack(side="left", padx=6)
        form = ttk.Frame(frame)
        form.pack(fill="x")
        ttk.Label(form, text="Minutes").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(form, from_=0.1, to=360, increment=1, textvariable=self.duration_min, width=7).grid(row=0, column=1)
        ttk.Label(form, text="Attempt s").grid(row=0, column=2, sticky="w", padx=(6, 0))
        ttk.Spinbox(form, from_=1, to=7200, increment=10, textvariable=self.attempt_s, width=7).grid(row=0, column=3)
        ttk.Label(form, text="Unique").grid(row=1, column=0, sticky="w")
        ttk.Spinbox(
            form, from_=1, to=ABSOLUTE_IDENTITY_CAP, increment=1000,
            textvariable=self.max_unique, width=10,
        ).grid(row=1, column=1)
        ttk.Label(form, text="RSS MB").grid(row=1, column=2, sticky="w", padx=(6, 0))
        ttk.Spinbox(form, from_=256, to=8192, increment=128, textvariable=self.requested_rss, width=7).grid(row=1, column=3)
        ttk.Label(frame, textvariable=self.resources, wraplength=400, justify="left").pack(anchor="w", pady=(4, 0))
        ttk.Label(frame, textvariable=self.best, wraplength=400, justify="left").pack(anchor="w")
        ttk.Label(frame, textvariable=self.job, wraplength=400, justify="left").pack(anchor="w")
        ttk.Label(frame, textvariable=self.status, wraplength=400, justify="left").pack(anchor="w", pady=(0, 4))
        self.log = tk.Text(frame, height=8, wrap="word", font=("Segoe UI", 8), borderwidth=0)
        self.log.pack(fill="both", expand=True)
        self.log.configure(state="disabled")
        try:
            self._show_resources(resource_report(float(self.requested_rss.get()), int(self.max_unique.get())))
        except (OSError, ValueError, TypeError) as exc:
            self.resources.set(f"Resource probe unavailable: {exc}")
        self._refresh_from_disk()

    def shutdown(self) -> None:
        self._closed = True
        if self._poll_id is not None:
            try:
                self.app.after_cancel(self._poll_id)
            except Exception:
                pass
            self._poll_id = None
        if self._running():
            self.stop()
        if self._log_handle is not None:
            self._log_handle.close()
            self._log_handle = None

    def _settings(self) -> dict:
        return {
            "campaign_duration_s": float(self.duration_min.get()) * 60.0,
            "attempt_time_limit_s": float(self.attempt_s.get()),
            "max_unique": int(self.max_unique.get()),
            "requested_rss_mb": float(self.requested_rss.get()),
            "workers": 1,
        }

    def _show_resources(self, report: dict) -> None:
        available = int(report.get("available_bytes") or 0) / (1024 ** 3)
        limit = int(report.get("identity_limit") or report["effective_max_unique"])
        default = int(report.get("identity_default") or 2_000_000)
        self.resources.set(
            f"Workers 1. Requested {report['requested_rss_mb']:.0f} MB, "
            f"effective {report['effective_rss_mb']:.0f} MB. "
            f"Available RAM {available:.1f} GB. "
            f"Unique {report['effective_max_unique']:,} "
            f"(default {default:,}, RSS limit {limit:,}) "
            f"at {report['retained_state_bytes']} B each."
        )

    def _control_path(self) -> Path:
        return self.directory / "control.json"

    def _pid_path(self) -> Path:
        return self.directory / "supervisor.pid"

    def _pid(self) -> int:
        payload = read_json(self._pid_path())
        try:
            return int(payload.get("pid") or 0)
        except (TypeError, ValueError):
            return 0

    def _write_control(self, command: str, *, started: float | None = None) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        current = read_json(self._control_path())
        if started is None:
            started = current.get("run_started_at")
        payload = {
            "command": command,
            "run_started_at": started,
            "settings": self._settings(),
        }
        atomic_write_json(self._control_path(), payload)

    def _spawn(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        log_path = self.directory / "supervisor.log"
        self._log_handle = log_path.open("a", encoding="utf-8")
        flags = 0
        if os.name == "nt":
            flags = 0x00000200 | 0x08000000
        self._process = subprocess.Popen(
            supervisor_command(self.directory),
            cwd=str(repo_root()),
            stdout=self._log_handle,
            stderr=subprocess.STDOUT,
            creationflags=flags,
        )
        atomic_write_json(self._pid_path(), {"pid": int(self._process.pid)})

    def start(self) -> None:
        if self._running():
            self.status.set("Worker already running.")
            self._schedule()
            return
        if (self.directory / "campaign.json").is_file():
            recover_campaign(self.directory, requested_stop=False)
        self._write_control("run", started=time.time())
        self._spawn()
        self.status.set("Worker started. Replay and window controls stay available.")
        self._schedule()

    def pause(self) -> None:
        if not self._running():
            self.status.set("Nothing is running to pause.")
            return
        self._write_control("pause")
        self.status.set("Pause requested. The current attempt will finish, then the queue waits.")

    def resume(self) -> None:
        current = read_json(self._control_path())
        started = coerce_run_start(current, time.time())
        self._write_control("run", started=started)
        if not self._running():
            self._spawn()
            self.status.set("Worker resumed.")
        else:
            self.status.set("Resume requested.")
        self._schedule()

    def _running(self) -> bool:
        if self._process is not None:
            return self._process.poll() is None
        return bool(self._pid()) and _alive(self._pid())

    def stop(self) -> None:
        if self._stopping:
            return
        self._stopping = True
        try:
            self._write_control("stop")
            self.status.set("Stopping. The window stays responsive.")
            self._await_worker(2.0)
            if self._running():
                if self._process is not None and self._process.poll() is None:
                    self._process.kill()
                _kill_tree(self._pid())
                self._await_worker(3.0)
            recover_campaign(self.directory, requested_stop=True)
            self._refresh_from_disk()
            self.status.set("Stopped. An unfinished attempt is not an exhaustion claim.")
        finally:
            self._stopping = False

    def _await_worker(self, timeout: float) -> None:
        """Wait without freezing the Tk window."""

        deadline = time.time() + float(timeout)
        while time.time() < deadline:
            try:
                self.app.update()
            except Exception:
                return
            if not self._running():
                try:
                    self.app.update()
                except Exception:
                    return
                return
            time.sleep(0.05)

    def open_best(self) -> None:
        path = self._best_path()

        def operation():
            if self.app.session is None:
                from spider.play_session import PlaySession

                self.app.session = PlaySession.from_deal(repo_root() / "deals" / "4925153.txt")
            before_nodes = set(self.app.session.nodes)
            before_campaigns = set(self.app.session.campaigns)
            open_verified_route(self.app.session, path)
            if not before_nodes <= set(self.app.session.nodes):
                raise ValueError("opening the verified line dropped session history")
            if not before_campaigns <= set(self.app.session.campaigns):
                raise ValueError("opening the verified line dropped a named branch campaign")
            self.app.feedback(
                "Opened the verified line as a replay. Named branch campaigns remain in this session."
            )

        self.app.guarded(operation)

    def _best_path(self) -> Path:
        if self.directory.is_dir():
            found = best_moves_path(self.directory)
            if found is not None:
                return found
        manifest = load_manifest(repo_root())
        return repo_root() / manifest["seed"]["relative"]

    def _schedule(self) -> None:
        if self._closed:
            return
        if self._poll_id is not None:
            try:
                self.app.after_cancel(self._poll_id)
            except Exception:
                pass
        self._poll_id = self.app.after(400, self._poll)

    def _poll(self) -> None:
        self._poll_id = None
        if self._closed:
            return
        self._refresh_from_disk()
        if self._running():
            self._schedule()

    def _refresh_from_disk(self) -> None:
        if not self.directory.is_dir():
            return
        state = read_json(self.directory / "state.json")
        if not state:
            return
        best = state.get("best") or {}
        incumbent = state.get("incumbent_g", best.get("g", 140))
        ceiling = state.get("ceiling", 139)
        self.best.set(f"Best {incumbent} · target {ceiling} · hash {str(best.get('path_hash16') or '')[:16]}")
        current = state.get("current_job") or {}
        if current:
            self.job.set(
                f"Job {current.get('id')} action {current.get('index')} · "
                f"elapsed {state.get('elapsed_s') or 0}s · "
                f"states {state.get('unique') if state.get('unique') is not None else '—'} · "
                f"RAM {state.get('peak_rss_mb') if state.get('peak_rss_mb') is not None else '—'}"
            )
        else:
            remaining = state.get("queue_remaining")
            self.job.set(f"Phase {state.get('phase') or 'idle'} · queued {remaining if remaining is not None else 0}")
        resources = state.get("resources") or {}
        if resources:
            self._show_resources(resources)
        phase = state.get("phase") or "idle"
        alive = self._running()
        self.status.set(f"{phase} · worker {'running' if alive else 'stopped'}")
        lines = state.get("activity") or []
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.insert("end", "\n".join(lines))
        self.log.see("end")
        self.log.configure(state="disabled")
