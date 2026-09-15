#!/usr/bin/env python3
"""Campaign GUI. AUTO hardware; scientific worker = LEAN CONSEQUENCE."""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    ROOT = Path(sys._MEIPASS)
    sys.path.insert(0, str(ROOT))
else:
    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT / "src"))

from spider.app_paths import data_folder, default_campaigns_dir
from spider.campaign_bundle import export_campaign, import_campaign
from spider.campaign_exchange import ingest_results, publish_result
from spider.campaign_import_v084 import import_v084_population
from spider.campaign_scheduler import run_pending_jobs
from spider.campaign_store import load_campaign, new_campaign, save_campaign
from spider.campaign_worker import WORKER_MODE
from spider.hardware import detect_hardware
from spider.hardware_profile import calibrate_and_save, load_profile, profile_mismatch, profile_path
from spider.resource_policy import recommend_config

DEFAULT_CAMPAIGN = default_campaigns_dir() / "default"


class CampaignApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Spider Solver — Campaign (AUTO / LEAN CONSEQUENCE)")
        self.minsize(720, 620)
        self.geometry("820x700")
        self._log_q: queue.Queue[str] = queue.Queue()
        self._campaign_dir = DEFAULT_CAMPAIGN
        self._profile = load_profile()
        self._snap = detect_hardware()
        self._running = False
        self._build()
        self._refresh_hw()
        self._poll()
        if profile_mismatch(self._profile, self._snap):
            self.after(400, self._prompt_calibrate)

    def _build(self) -> None:
        pad = {"padx": 8, "pady": 4}
        ttk.Label(self, text="Deep campaign runner", font=("Segoe UI", 12, "bold")).pack(anchor=tk.W, **pad)
        ttk.Label(
            self,
            text="AUTO resources. Scientific worker = LEAN CONSEQUENCE. Disk speed unused.",
            font=("Segoe UI", 9),
        ).pack(anchor=tk.W, padx=8)
        self._camp_info = tk.StringVar(value="Campaign: —")
        ttk.Label(self, textvariable=self._camp_info, font=("Segoe UI", 9)).pack(anchor=tk.W, padx=8)

        hw = ttk.LabelFrame(self, text="Hardware")
        hw.pack(fill=tk.X, **pad)
        self._hw = tk.StringVar(value="detecting…")
        ttk.Label(hw, textvariable=self._hw, font=("Consolas", 9), justify=tk.LEFT).pack(anchor=tk.W, padx=8, pady=6)
        row = ttk.Frame(hw)
        row.pack(fill=tk.X, padx=8, pady=(0, 6))
        ttk.Button(row, text="Recalibrate", command=self._recalibrate).pack(side=tk.LEFT)

        adv = ttk.LabelFrame(self, text="Advanced / Resources (optional)")
        adv.pack(fill=tk.X, **pad)
        af = ttk.Frame(adv)
        af.pack(fill=tk.X, padx=8, pady=6)
        self._mode = tk.StringVar(value="AUTO")
        self._workers = tk.IntVar(value=1)
        self._rss = tk.DoubleVar(value=2560.0)
        ttk.Label(af, text="Mode").grid(row=0, column=0, sticky=tk.W)
        ttk.Combobox(af, textvariable=self._mode, values=("AUTO", "MANUAL"), width=10, state="readonly").grid(row=0, column=1, padx=6)
        ttk.Label(af, text="Workers").grid(row=0, column=2, sticky=tk.W)
        ttk.Spinbox(af, from_=1, to=8, textvariable=self._workers, width=4).grid(row=0, column=3, padx=6)
        ttk.Label(af, text="Per-worker RSS MB").grid(row=0, column=4, sticky=tk.W)
        ttk.Spinbox(af, from_=512, to=8192, increment=128, textvariable=self._rss, width=7).grid(row=0, column=5, padx=6)

        camp = ttk.LabelFrame(self, text="Campaign")
        camp.pack(fill=tk.X, **pad)
        self._camp_var = tk.StringVar(value=str(self._campaign_dir))
        ttk.Entry(camp, textvariable=self._camp_var).pack(fill=tk.X, padx=8, pady=4)
        bt = ttk.Frame(camp)
        bt.pack(fill=tk.X, padx=8, pady=(0, 6))
        ttk.Button(bt, text="New Campaign", command=self._new_campaign).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(bt, text="Open Campaign", command=self._choose_folder).pack(side=tk.LEFT, padx=(0, 4))
        self._start = ttk.Button(bt, text="Start", command=self._start_run)
        self._start.pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(bt, text="Resume", command=self._start_run).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(bt, text="Pause after current job", command=self._pause).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(bt, text="Stop", command=self._stop).pack(side=tk.LEFT, padx=(0, 4))
        row2 = ttk.Frame(camp)
        row2.pack(fill=tk.X, padx=8, pady=(0, 6))
        ttk.Button(row2, text="Export Campaign", command=self._export).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(row2, text="Import Campaign", command=self._import).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(row2, text="Shared Research Folder", command=self._shared).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(row2, text="Sync Results", command=self._sync).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(row2, text="Import v0.84 F2s", command=self._import_v084).pack(side=tk.LEFT, padx=(0, 4))
        row3 = ttk.Frame(camp)
        row3.pack(fill=tk.X, padx=8, pady=(0, 6))
        ttk.Button(row3, text="Open Data Folder", command=self._open_data).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(row3, text="Export Report", command=self._export_report).pack(side=tk.LEFT)

        logf = ttk.LabelFrame(self, text="Log")
        logf.pack(fill=tk.BOTH, expand=True, **pad)
        self._log = scrolledtext.ScrolledText(logf, height=14, font=("Consolas", 9), state=tk.DISABLED)
        self._log.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

    def _refresh_hw(self) -> None:
        snap = self._snap
        prof = self._profile or {}
        cfg = recommend_config(snap, measured_rss_mb=prof.get("peak_rss_mb"), measured_unique_per_s=prof.get("unique_per_s"))
        if self._mode.get() == "AUTO":
            self._workers.set(cfg.workers)
            self._rss.set(cfg.per_worker_rss_mb)
        thru = prof.get("unique_per_s")
        thru_s = "—" if thru is None else f"{thru:.0f} unique states/sec"
        cal = "missing / mismatch — Recalibrate" if profile_mismatch(prof, snap) else "ok"
        self._hw.set(
            "\n".join(
                [
                    f"Hardware mode: {self._mode.get()}",
                    f"CPU: {snap.physical_cores} physical / {snap.logical_cores} logical",
                    f"RAM: {snap.ram_total_gb:.0f} GB",
                    f"Search workers: {self._workers.get()}",
                    f"Per-worker RSS cap: {self._rss.get()/1024:.1f} GB",
                    f"Global campaign RAM limit: {cfg.global_ram_limit_gb:.0f} GB",
                    f"Measured throughput: {thru_s}",
                    f"Calibration status: {cal}",
                    f"Scientific worker mode = {WORKER_MODE}",
                    f"Profile: {profile_path()}",
                ]
            )
        )
        self._refresh_campaign_info()

    def _log_line(self, msg: str) -> None:
        self._log_q.put(msg)

    def _poll(self) -> None:
        try:
            while True:
                line = self._log_q.get_nowait()
                self._log.configure(state=tk.NORMAL)
                self._log.insert(tk.END, line + "\n")
                self._log.see(tk.END)
                self._log.configure(state=tk.DISABLED)
        except queue.Empty:
            pass
        self.after(200, self._poll)

    def _prompt_calibrate(self) -> None:
        if not messagebox.askyesno("Hardware profile", "No matching hardware profile. Calibrate now (~15 s)?"):
            self._log_line("Calibration deferred.")
            return
        self._recalibrate()

    def _recalibrate(self) -> None:
        self._log_line("Calibrating (~15 s representative search)…")

        def work():
            try:
                prof = calibrate_and_save(time_s=15.0)
                self._profile = prof
                self._snap = detect_hardware()
                self._log_q.put(f"Calibrated {prof.get('unique_per_s')} unique/s RSS={prof.get('peak_rss_mb')} workers={prof.get('workers')}")
            except Exception as exc:
                self._log_q.put(f"Calibration failed: {exc}")
            self.after(0, self._refresh_hw)

        threading.Thread(target=work, daemon=True).start()

    def _choose_folder(self) -> None:
        path = filedialog.askdirectory(initialdir=str(self._campaign_dir))
        if not path:
            return
        self._campaign_dir = Path(path)
        self._camp_var.set(str(self._campaign_dir))
        load_campaign(self._campaign_dir)
        self._log_line(f"Campaign folder {self._campaign_dir}")
        self._refresh_campaign_info()

    def _refresh_campaign_info(self) -> None:
        try:
            data = load_campaign(Path(self._camp_var.get()))
        except Exception:
            return
        jobs = data.get("jobs") or []
        pending = sum(1 for j in jobs if j.get("status") == "pending")
        done = sum(1 for j in jobs if j.get("status") == "done")
        imported = len(data.get("imported_results") or [])
        running = next((j for j in jobs if j.get("status") == "running"), None)
        self._camp_info.set(
            f"UUID {data.get('uuid')} · incumbent {data.get('incumbent_g')} · ceiling {data.get('production_ceiling')} · "
            f"candidates {len(data.get('candidates') or [])} · pending {pending} · done {done} · imported {imported} · "
            f"current {str((running or {}).get('id') or '—')[:8]} · worker {data.get('scientific_worker') or WORKER_MODE}"
        )

    def _new_campaign(self) -> None:
        path = filedialog.askdirectory(initialdir=str(default_campaigns_dir()))
        if not path:
            return
        self._campaign_dir = Path(path)
        self._camp_var.set(str(self._campaign_dir))
        data = new_campaign()
        save_campaign(self._campaign_dir, data)
        self._refresh_campaign_info()
        self._log_line(f"New campaign {data.get('uuid')} in {self._campaign_dir}")

    def _pause(self) -> None:
        (Path(self._camp_var.get()) / "_pause").write_text("1", encoding="utf-8")
        self._log_line("Pause requested after current job batch.")

    def _stop(self) -> None:
        (Path(self._camp_var.get()) / "_stop").write_text("1", encoding="utf-8")
        self._log_line("Stop requested after current job batch. Pending work remains.")

    def _import_v084(self) -> None:
        camp = import_v084_population()
        save_campaign(Path(self._camp_var.get()), camp)
        stats = camp.get("import_stats") or {}
        self._log_line(f"Imported v0.84 F2s {stats}")
        self._refresh_campaign_info()

    def _export(self) -> None:
        dest = filedialog.asksaveasfilename(defaultextension=".spidercampaign", filetypes=[("Campaign", "*.spidercampaign")])
        if not dest:
            return
        path = export_campaign(Path(self._camp_var.get()), Path(dest))
        self._log_line(f"Exported {path}")

    def _import(self) -> None:
        src = filedialog.askopenfilename(filetypes=[("Campaign", "*.spidercampaign")])
        if not src:
            return
        dest = filedialog.askdirectory(initialdir=str(default_campaigns_dir()))
        if not dest:
            return
        import_campaign(Path(src), Path(dest))
        self._campaign_dir = Path(dest)
        self._camp_var.set(str(dest))
        self._refresh_campaign_info()
        self._log_line(f"Imported campaign into {dest}")

    def _shared(self) -> None:
        path = filedialog.askdirectory()
        if not path:
            return
        data = load_campaign(Path(self._camp_var.get()))
        data["shared_folder"] = path
        save_campaign(Path(self._camp_var.get()), data)
        self._log_line(
            f"Shared Research Folder {path}. Live campaign stays local; only immutable exchange artefacts are published."
        )

    def _sync(self) -> None:
        data = load_campaign(Path(self._camp_var.get()))
        shared = data.get("shared_folder")
        if not shared:
            self._log_line("Set Shared Research Folder first.")
            return
        for job in data.get("jobs") or []:
            if job.get("status") == "done" and job.get("result"):
                publish_result(Path(shared), data, job)
        summary = ingest_results(Path(shared), Path(self._camp_var.get()))
        self._log_line(f"Sync {summary}")
        self._refresh_campaign_info()

    def _open_data(self) -> None:
        os.startfile(str(data_folder()))  # type: ignore[attr-defined]

    def _export_report(self) -> None:
        dest = filedialog.asksaveasfilename(defaultextension=".json")
        if not dest:
            return
        data = load_campaign(Path(self._camp_var.get()))
        Path(dest).write_text(json.dumps(data, indent=2), encoding="utf-8")
        self._log_line(f"Wrote report {dest}")

    def _start_run(self) -> None:
        if self._running:
            return
        self._campaign_dir = Path(self._camp_var.get())
        snap = detect_hardware()
        if profile_mismatch(self._profile, snap):
            if messagebox.askyesno("Hardware changed", "Hardware profile does not match this machine. Recalibrate and resume? Campaign scientific history is preserved."):
                self._recalibrate()
                self.after(16000, self._start_run)
            return
        cfg = recommend_config(snap, measured_rss_mb=(self._profile or {}).get("peak_rss_mb"), measured_unique_per_s=(self._profile or {}).get("unique_per_s"))
        if self._mode.get() == "MANUAL":
            cfg.workers = int(self._workers.get())
            cfg.per_worker_rss_mb = float(self._rss.get())
        for name in ("_pause", "_stop"):
            p = self._campaign_dir / name
            if p.exists():
                p.unlink()
        self._running = True
        self._start.configure(state=tk.DISABLED)
        self._log_line("Starting/resuming campaign with LEAN CONSEQUENCE worker…")

        def work():
            try:
                summary = run_pending_jobs(self._campaign_dir, cfg, on_log=self._log_line)
                self._log_q.put(f"Batch done {summary}")
            except Exception as exc:
                self._log_q.put(f"Run failed: {exc}")
            self._running = False
            self.after(0, lambda: self._start.configure(state=tk.NORMAL))
            self.after(0, self._refresh_campaign_info)

        threading.Thread(target=work, daemon=True).start()


def main() -> None:
    CampaignApp().mainloop()


if __name__ == "__main__":
    main()
