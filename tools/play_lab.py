#!/usr/bin/env python3
"""Spider Play Lab v0.104 — independent desktop play/replay/research application."""
from __future__ import annotations

import argparse
import json
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from spider.app_paths import repo_root
from spider.metrics import format_action
from spider.play_render import SpiderBoard
from spider.play_session import AutosaveError, PlaySession, sessions_dir
from spider.play_controller import PlayController, SPEEDS


class PlayLab(tk.Tk):
    def __init__(self, session=None):
        super().__init__()
        self.title("Spider Play Lab · v0.104")
        self.geometry("1420x900")
        self.minsize(1120, 680)
        self.configure(bg="#eef1e9")
        self.session = session
        self.controller = None
        self.speed = tk.StringVar(value="Normal")
        self.analysis = tk.BooleanVar(value=False)
        self.message = tk.StringVar(value="Open a recent session or start deal 4925153.")
        self.summary = tk.StringVar()
        self.context = tk.StringVar()
        self.replay = tk.StringVar()
        self.saved = tk.StringVar()
        self._refreshing = False
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.close)
        for key, action in (("<Left>", "undo"), ("<Right>", "next"),
                            ("<Control-z>", "undo"), ("<Control-y>", "redo")):
            self.bind(key, lambda e, a=action: self.navigate(a) if not isinstance(
                self.focus_get(), (tk.Entry, ttk.Entry, ttk.Combobox)) else None)
        self.bind("<Escape>", lambda e: self.change_view())
        if session:
            self.refresh()
        else:
            self.after(100, self.welcome)

    def _build(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#eef1e9")
        style.configure("TLabel", background="#eef1e9", foreground="#263e37", font=("Segoe UI", 10))
        style.configure("TButton", font=("Segoe UI", 10), padding=(10, 6))
        style.configure("Branch.TButton", background="#235e4e", foreground="white", font=("Segoe UI", 10, "bold"))
        style.map("Branch.TButton", background=[("active", "#31745f")])
        style.configure("Treeview", rowheight=27, font=("Segoe UI", 9))
        header = ttk.Frame(self, padding=(18, 12))
        header.pack(fill="x")
        ttk.Label(header, text="SPIDER  /  PLAY LAB", font=("Segoe UI", 17, "bold")).pack(side="left")
        ttk.Label(header, text="v0.104   •   Every move preserved", foreground="#60776c").pack(side="right")
        toolbar = ttk.Frame(self, padding=(14, 0, 14, 10))
        toolbar.pack(fill="x")
        for label, callback in (("New deal", self.new_deal), ("Open session", self.open_session),
                                ("Load solution", self.load_solution), ("Save Session", self.save_session),
                                ("Export Current Line", self.export)):
            ttk.Button(toolbar, text=label, command=callback).pack(side="left", padx=3)
        ttk.Checkbutton(toolbar, text="Analysis / Omniscient View", variable=self.analysis,
                        command=self.change_view).pack(side="right", padx=6)
        research = ttk.Frame(self, padding=(17, 0, 17, 9))
        research.pack(fill="x")
        ttk.Button(research, text="Start Branch Campaign", style="Branch.TButton", command=self.start_campaign).pack(side="left")
        ttk.Label(research, text="Name this position and explore; every alternative stays saved.",
                  foreground="#60776c").pack(side="left", padx=12)
        self.speed_combo = ttk.Combobox(research, state="readonly", textvariable=self.speed,
                                       values=list(SPEEDS), width=9)
        self.speed_combo.pack(side="right")
        self.speed_combo.bind("<<ComboboxSelected>>", self.change_speed)
        ttk.Label(research, text="Motion", padding=(8, 0)).pack(side="right")
        middle = ttk.Frame(self)
        middle.pack(fill="both", expand=True)
        side = ttk.Frame(middle, padding=(12, 10), width=310)
        side.pack(side="right", fill="y")
        side.pack_propagate(False)
        ttk.Label(side, text="SESSION", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ttk.Label(side, textvariable=self.context, wraplength=280, justify="left").pack(anchor="w", pady=(4, 4))
        ttk.Label(side, textvariable=self.summary, justify="left", font=("Segoe UI", 10)).pack(anchor="w")
        ttk.Separator(side).pack(fill="x", pady=8)
        ttk.Label(side, text="Parent replay / saved branch campaign", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.route_combo = ttk.Combobox(side, state="readonly")
        self.route_combo.pack(fill="x", pady=5)
        self.route_combo.bind("<<ComboboxSelected>>", self.select_route)
        self.campaign_combo = ttk.Combobox(side, state="readonly")
        self.campaign_combo.pack(fill="x", pady=(0, 4))
        self.campaign_combo.bind("<<ComboboxSelected>>", self.select_campaign)
        ttk.Label(side, textvariable=self.replay, wraplength=280, justify="left").pack(anchor="w", pady=(3, 8))
        self.tabs = ttk.Notebook(side)
        self.tabs.pack(fill="both", expand=True)
        record_frame = ttk.Frame(self.tabs)
        history_frame = ttk.Frame(self.tabs)
        self.tabs.add(record_frame, text="Clean move record")
        self.tabs.add(history_frame, text="All history")
        self.recorder = ttk.Treeview(record_frame, columns=("n", "g", "move"), show="headings", height=5)
        for key, label, width in (("n", "#", 37), ("g", "g", 36), ("move", "Current route", 178)):
            self.recorder.heading(key, text=label)
            self.recorder.column(key, width=width, minwidth=width, stretch=key=="move")
        self.recorder.tag_configure("stock", background="#dfebe1")
        self.recorder.tag_configure("origin", foreground="#855900", background="#f7e9c8")
        self.recorder.pack(side="left", fill="both", expand=True)
        record_scroll = ttk.Scrollbar(record_frame, command=self.recorder.yview)
        record_scroll.pack(side="right", fill="y")
        self.recorder.configure(yscrollcommand=record_scroll.set)
        self.recorder.bind("<Configure>", lambda e: self.recorder.yview_moveto(1.0))
        self.history = ttk.Treeview(history_frame, show="tree", selectmode="browse", height=6)
        self.history.column("#0", width=215, minwidth=120)
        self.history.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(history_frame, command=self.history.yview)
        scroll.pack(side="right", fill="y")
        self.history.configure(yscrollcommand=scroll.set)
        self.history.bind("<<TreeviewSelect>>", self.select_history)
        self.history.bind("<Configure>", lambda e: self.history.see(self.session.current)
                          if self.session and self.history.exists(self.session.current) else None)
        ttk.Label(side, text="Clean record = export. All history retains alternatives.", wraplength=280,
                  foreground="#60776c", font=("Segoe UI", 9)).pack(anchor="w", pady=(6, 0))
        board_frame = ttk.Frame(middle)
        board_frame.pack(side="left", fill="both", expand=True)
        self.board = SpiderBoard(board_frame, self.move, lambda: self.perform(("deal",)), self.feedback)
        self.board.input_blocked = self.is_busy
        self.board.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(board_frame, command=self.board.yview)
        scroll.pack(side="right", fill="y")
        self.board.configure(yscrollcommand=scroll.set)
        footer = ttk.Frame(self, padding=(16, 10))
        footer.pack(fill="x")
        for label, action in (("|‹ First", "first"), ("‹ Previous", "undo"),
                              ("Next ›", "next"), ("Last ›|", "last"), ("Undo", "undo"), ("Redo", "redo")):
            ttk.Button(footer, text=label, command=lambda a=action: self.navigate(a)).pack(side="left", padx=2)
        ttk.Label(footer, textvariable=self.saved, font=("Segoe UI", 9), foreground="#587264").pack(side="right")
        ttk.Button(footer, text="Rename session", command=self.rename).pack(side="right", padx=8)
        ttk.Label(self, textvariable=self.message, padding=(18, 5, 18, 10), wraplength=1080).pack(fill="x")

    def feedback(self, text):
        self.message.set(text)

    def guarded(self, function):
        if self.is_busy():
            return None
        try:
            result = function()
            if not self.is_busy():
                self.refresh()
            return result
        except AutosaveError as exc:
            self.refresh()
            self.feedback(str(exc))
            messagebox.showerror("Autosave needs attention", f"{exc}\n\nUse Save Session to retry or save a recovery copy. Do not close this window.", parent=self)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            self.feedback(str(exc))
            messagebox.showerror("Play Lab", str(exc), parent=self)

    def is_busy(self):
        return self.controller is not None and self.controller.busy

    def change_view(self):
        self.board.cancel_transition()
        self.refresh()

    def change_speed(self, event=None):
        self.board.cancel_transition()
        if self.controller:
            self.controller.speed = self.speed.get()

    def start_campaign(self):
        if not self.session or self.is_busy():
            return
        suggested = f"{self.session.deal_id} · action {self.session.node.ordinal} · branch {len(self.session.campaigns)+1}"
        name = simpledialog.askstring("Start Branch Campaign", "Name this research branch:", initialvalue=suggested, parent=self)
        if name is not None:
            if self.guarded(lambda: self.session.start_campaign(name)):
                self.tabs.select(0)
                self.feedback("Branch campaign started. Play freely; undo edits the clean line, never the saved history.")

    def select_campaign(self, event=None):
        if self.session and self.campaign_combo.current() >= 0:
            campaign_id = self.campaign_ids[self.campaign_combo.current()]
            self.guarded(lambda: self.session.select_campaign(campaign_id))

    def refresh(self, draw_board=True):
        if not self.session:
            return
        s = self.session
        if self.controller is None or self.controller.session is not s:
            self.controller = PlayController(s, self.board.animate, self.refresh)
            self.controller.speed = self.speed.get()
        node = s.node
        if draw_board:
            self.board.update_session(s, self.analysis.get())
        self.context.set(f"Deal {s.deal_id}\n{s.name}")
        solved = s.state.is_solved()
        self.summary.set(f"MW cost  {node.g}     ·     {'SOLVED' if solved else 'In progress'}\nActions  {node.ordinal}   ·   Tableau  {node.ordinal-node.stock_deals}\nStock  {node.stock_deals}/5   ·   Foundations  {node.foundations}/8\nHidden  {node.face_down}   ·   Empty columns  {node.empty_columns}")
        route, position, branch = s.route_position()
        expected = s.expected_action()
        if s.campaign:
            c = s.campaign
            self.replay.set(f"BRANCH CAMPAIGN · {c['name']}\nParent: {c['parent_solution'] or 'Manual play'}\nOrigin: action {c['origin_action']} · g={c['origin_g']}\nCurrent g: {node.g}" +
                            ("\nViewing outside the origin's descendants" if c['origin_node'] not in s.path_ids() else ""))
        elif route:
            text = (f"Branch from {route['name']}\nDivergence after action {position}\nParent g={s.nodes[route['nodes'][position]].g}"
                    if branch else f"REPLAY · action {position} / {len(route['nodes'])-1}")
            self.replay.set(text + (f"\nNext: {format_action(expected)}" if expected else "\nFree play" if branch else "\nEnd of route"))
        else:
            self.replay.set("PLAY · Play freely, or load a solution.")
        self.campaign_ids = list(s.campaigns)
        self.campaign_combo["values"] = [s.campaigns[c]["name"] for c in self.campaign_ids]
        if s.active_campaign in self.campaign_ids:
            self.campaign_combo.current(self.campaign_ids.index(s.active_campaign))
        else:
            self.campaign_combo.set("Saved branch campaigns" if s.campaigns else "No named branch campaigns yet")
        self.route_ids = list(s.routes)
        self.route_combo["values"] = [s.routes[r]["name"] for r in self.route_ids]
        if s.active_route in self.route_ids:
            self.route_combo.current(self.route_ids.index(s.active_route))
        else:
            self.route_combo.set("")
        self._refreshing = True
        existing = set(self.history.get_children(""))
        if not self.history.exists(s.root):
            self.history.delete(*existing)
        for node_id, n in s.nodes.items():
            fork = n.parent is not None and len(s.children[n.parent]) > 1
            label = "Starting deal" if n.parent is None else f"{n.ordinal}  {n.action}  · g={n.g}"
            if fork:
                label = f"↳ {label} [{node_id[:4]}]"
            if not self.history.exists(node_id):
                # A flat index stays usable at 200+ actions; the saved model is a tree.
                self.history.insert("", "end", iid=node_id, text=label, open=False)
            else:
                self.history.item(node_id, text=label)
        self.history.selection_set(s.current)
        self.history.see(s.current)
        current_id = s.current
        self.after_idle(lambda: self.history.see(current_id) if self.history.exists(current_id) else None)
        self.recorder.delete(*self.recorder.get_children())
        origin = s.campaign["origin_node"] if s.campaign else None
        if origin == s.root:
            self.recorder.insert("", "end", iid="origin", values=("◆", 0, "Branch origin"), tags="origin")
        for n in s.clean_record():
            self.recorder.insert("", "end", iid=n.id,
                values=(f"{n.ordinal:03}", n.g, n.action + (f"  [SD{n.stock_deals}]" if n.action=="deal" else "")),
                tags="stock" if n.action=="deal" else ())
            if n.id == origin:
                self.recorder.insert("", "end", iid="origin", values=("◆", n.g, "Branch origin"), tags="origin")
        if self.recorder.exists(s.current):
            self.recorder.selection_set(s.current)
            self.recorder.yview_moveto(1.0)
            # Campaign text can resize the panel after this refresh has returned.
            self.after_idle(lambda: self.recorder.yview_moveto(1.0))
        self._refreshing = False
        self.saved.set("UNSAVED — recovery needed" if s.dirty else "● Autosaved")
        if solved:
            self.feedback("Solved. Your full route is autosaved. Export Current Line to independently verify and save the solution.")
        elif self.message.get().startswith("Solved."):
            self.feedback("Current position restored. Every alternative remains saved in All history.")

    def perform(self, action):
        if not self.session or self.is_busy():
            return
        try:
            self.controller.run(lambda: self.session.act(action))
        except ValueError as exc:
            self.feedback(f"That move is unavailable. {exc}")
            return  # ordinary illegal play is deliberately non-modal
        except AutosaveError as exc:
            self.refresh()
            self.feedback(str(exc))
            messagebox.showerror("Autosave needs attention", str(exc), parent=self)
            return
        self.feedback(f"Recorded: {format_action(action)}")

    def move(self, src, dst, k):
        if not self.session or self.is_busy():
            return
        if not self.session.state.can_move(src, dst, k):
            self.feedback("That destination is unavailable. Choose a rank one higher or an empty column.")
            return
        self.perform((src, dst, k))

    def navigate(self, action):
        if self.session:
            self.feedback("History navigation preserves every branch; only the selected line is exported.")
            self.guarded(lambda: self.controller.run(
                lambda: self.session.goto(self.session.root) if action == "first" else getattr(self.session, action)(),
                animated=action in ("next", "redo")))

    def select_history(self, event):
        selected = self.history.selection()
        if not self._refreshing and selected and self.session and selected[0] != self.session.current:
            self.guarded(lambda: self.controller.run(lambda: self.session.goto(selected[0]), animated=False))

    def select_route(self, event):
        if self.session:
            self.guarded(lambda: self.session.select_route(self.route_ids[self.route_combo.current()]))

    def can_replace(self):
        if self.is_busy():
            return False
        if self.session and self.session.dirty:
            self.feedback("Save the unsaved session before opening another deal or session.")
            return False
        return True

    def new_deal(self, default=False):
        if not self.can_replace():
            return
        path = repo_root() / "deals" / "4925153.txt" if default else filedialog.askopenfilename(
            title="Open MobilityWare deal", initialdir=repo_root() / "deals", filetypes=[("Deal files", "*.txt"), ("All files", "*")], parent=self)
        if path:
            def create():
                session = PlaySession.from_deal(Path(path))
                self.session = session
                self.feedback("Click a source card, then its destination; or drag a same-suit run.")
            self.guarded(create)

    def open_session(self, path=None):
        if not self.can_replace():
            return
        path = path or filedialog.askopenfilename(title="Restore Play Lab session", initialdir=sessions_dir(),
            filetypes=[("Sessions / backups", "*.json *.bak"), ("All files", "*")], parent=self)
        if path:
            def restore():
                restored = PlaySession.load(Path(path))
                if str(path).endswith(".bak"):
                    restored.save(sessions_dir() / f"recovered_{restored.id}.json")
                self.session = restored
                self.feedback("Session restored; every history node was replay-checked.")
            self.guarded(restore)

    def load_solution(self):
        if self.is_busy():
            return
        if not self.session:
            self.new_deal(default=True)
        if not self.session:
            return
        path = filedialog.askopenfilename(title="Load canonical solution or partial route", initialdir=repo_root() / "solutions",
            filetypes=[("Move files", "*.moves *.moves.txt"), ("All files", "*")], parent=self)
        if path:
            if self.guarded(lambda: self.session.load_solution(Path(path))):
                self.feedback("Solution checked. Use Next/Previous, or play a different move to branch.")

    def save_session(self):
        if not self.session or self.is_busy():
            return
        if self.session.dirty:
            path = filedialog.asksaveasfilename(title="Save recovery copy", initialdir=sessions_dir(),
                initialfile=f"recovery_{self.session.id}.json", defaultextension=".json", parent=self)
            if path:
                self.guarded(lambda: self.session.save(Path(path)))
        else:
            self.guarded(self.session.save)

    def export(self):
        if not self.session or self.is_busy():
            return
        export_dir = sessions_dir().parent / "Exports"
        try:
            export_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.feedback(f"Cannot open export folder: {exc}")
            return
        path = filedialog.asksaveasfilename(title="Export current line", initialdir=export_dir,
            initialfile=f"{self.session.deal_id}_g{self.session.node.g}_{self.session.current[:8]}.moves",
            defaultextension=".moves", filetypes=[("Canonical moves", "*.moves")], parent=self)
        if path:
            result = self.guarded(lambda: self.session.export(Path(path)))
            if result:
                title = "VERIFIED SOLUTION" if result["solved"] else "VERIFIED PARTIAL LINE"
                messagebox.showinfo(title, f"MobilityWare cost: {result['mobilityware_moves']}\nActions: {result['explicit_commands']}\nDeals: {result['stock_deals']}\nFoundations: {result['foundations']}\nSolved: {result['solved']}\n\n{path}", parent=self)

    def rename(self):
        if self.session and not self.is_busy():
            name = simpledialog.askstring("Session name", "Name this session:", initialvalue=self.session.name, parent=self)
            if name and name.strip():
                self.session.name = name.strip()
                self.guarded(self.session.save)

    def welcome(self):
        dialog = tk.Toplevel(self)
        dialog.title("Welcome to Spider Play Lab")
        self.update_idletasks()
        x = max(0, self.winfo_rootx() + (self.winfo_width() - 680) // 2)
        y = max(0, self.winfo_rooty() + (self.winfo_height() - 390) // 2)
        dialog.geometry(f"680x390+{x}+{y}")
        dialog.transient(self)
        dialog.grab_set()
        ttk.Label(dialog, text="Pick up where you left off", font=("Segoe UI", 17, "bold"), padding=18).pack(anchor="w")
        ttk.Label(dialog, text="Recent sessions · all actions and branches are recovered by replay", padding=(18, 0)).pack(anchor="w")
        listing = tk.Listbox(dialog, font=("Segoe UI", 11), borderwidth=0, height=8)
        listing.pack(fill="both", expand=True, padx=18, pady=14)
        recent = sorted(sessions_dir().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:20]
        for path in recent:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                current = next(n for n in data["nodes"] if n["id"] == data["current"])
                listing.insert("end", f"{data['name']}  ·  g={current['g']}  ·  action {current['ordinal']}")
            except (ValueError, OSError, KeyError, TypeError, StopIteration):
                listing.insert("end", f"{path.name}  ·  needs recovery")
        def restore():
            selected = listing.curselection()
            if selected:
                dialog.destroy()
                self.open_session(recent[selected[0]])
        controls = ttk.Frame(dialog, padding=18)
        controls.pack(fill="x")
        ttk.Button(controls, text="Open selected session", command=restore).pack(side="left")
        ttk.Button(controls, text="Start deal 4925153", command=lambda: (dialog.destroy(), self.new_deal(default=True))).pack(side="right")
        listing.bind("<Double-1>", lambda e: restore())

    def close(self):
        self.board.cancel_transition()
        if self.session:
            try:
                self.session.save()
            except AutosaveError as exc:
                self.feedback(str(exc))
                messagebox.showerror("Session not saved", "Use Save Session to write a recovery copy before closing.", parent=self)
                return
        self.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deal", type=Path, help="Start a new session from this deal")
    parser.add_argument("--session", type=Path, help="Restore an existing session")
    parser.add_argument("--solution", type=Path, help="Validate and load a replay route")
    args = parser.parse_args()
    session = PlaySession.load(args.session) if args.session else (
        PlaySession.from_deal(args.deal) if args.deal else None)
    if args.solution:
        session = session or PlaySession.from_deal(repo_root() / "deals" / "4925153.txt")
        session.load_solution(args.solution)
    PlayLab(session).mainloop()


if __name__ == "__main__":
    main()
