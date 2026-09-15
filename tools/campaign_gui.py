#!/usr/bin/env python3
"""Optiplex-first campaign GUI. AUTO hardware; no SSD assumptions."""

from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.campaign_scheduler import run_pending_jobs
from spider.campaign_store import add_candidate, enqueue_job, load_campaign, save_campaign
from spider.hardware import detect_hardware
from spider.hardware_profile import calibrate_and_save, load_profile, profile_mismatch, profile_path
from spider.resource_policy import recommend_config

DEFAULT_CAMPAIGN = ROOT / "campaigns" / "default"


class CampaignApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Spider Solver — Campaign (AUTO)")
        self.minsize(640, 560)
        self.geometry("760x640")
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
        ttk.Label(self, text="Target: Dell Optiplex (AUTO). Disk speed is not a search input.", font=("Segoe UI", 9)).pack(anchor=tk.W, padx=8)

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
        ttk.Button(bt, text="New / Open folder", command=self._choose_folder).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(bt, text="Create smoke jobs", command=self._smoke).pack(side=tk.LEFT, padx=(0, 6))
        self._start = ttk.Button(bt, text="Start / Resume", command=self._start_run)
        self._start.pack(side=tk.LEFT)

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
                    f"Profile: {profile_path()}",
                ]
            )
        )

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

    def _smoke(self) -> None:
        data = load_campaign(self._campaign_dir)
        if not data.get("candidates"):
            a = add_candidate(data, g=0, ordered_digest="", label="smoke_a")
            b = add_candidate(data, g=0, ordered_digest="", label="smoke_b")
            enqueue_job(data, a["id"], ceiling=186, time_s=6.0, max_unique=8_000)
            enqueue_job(data, b["id"], ceiling=186, time_s=6.0, max_unique=8_000)
            save_campaign(self._campaign_dir, data)
            self._log_line("Created two smoke jobs (6 s kernel probes).")
        else:
            self._log_line("Campaign already has candidates; not duplicating smoke jobs.")

    def _start_run(self) -> None:
        if self._running:
            return
        self._campaign_dir = Path(self._camp_var.get())
        snap = detect_hardware()
        if profile_mismatch(self._profile, snap):
            if messagebox.askyesno("Hardware changed", "Hardware profile does not match this machine. Recalibrate and resume?"):
                self._recalibrate()
                self.after(16000, self._start_run)
            return
        cfg = recommend_config(snap, measured_rss_mb=(self._profile or {}).get("peak_rss_mb"), measured_unique_per_s=(self._profile or {}).get("unique_per_s"))
        if self._mode.get() == "MANUAL":
            cfg.workers = int(self._workers.get())
            cfg.per_worker_rss_mb = float(self._rss.get())
        self._running = True
        self._start.configure(state=tk.DISABLED)
        self._log_line("Starting/resuming campaign…")

        def work():
            try:
                summary = run_pending_jobs(self._campaign_dir, cfg, on_log=self._log_line)
                self._log_q.put(f"Batch done {summary}")
            except Exception as exc:
                self._log_q.put(f"Run failed: {exc}")
            self._running = False
            self.after(0, lambda: self._start.configure(state=tk.NORMAL))

        threading.Thread(target=work, daemon=True).start()


def main() -> None:
    CampaignApp().mainloop()


if __name__ == "__main__":
    main()
