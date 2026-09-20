#!/usr/bin/env python3
"""Spider Play Lab v0.103 — independent desktop play/replay/research application."""
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


class PlayLab(tk.Tk):
    def __init__(self, session=None):
        super().__init__()
        self.title("Spider Play Lab · v0.103")
        self.geometry("1420x900")
        self.minsize(1120, 680)
        self.configure(bg="#eef1e9")
        self.session = session
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
        self.bind("<Escape>", lambda e: self.refresh())
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
        style.configure("Treeview", rowheight=27, font=("Segoe UI", 9))
        header = ttk.Frame(self, padding=(18, 12))
        header.pack(fill="x")
        ttk.Label(header, text="SPIDER  /  PLAY LAB", font=("Segoe UI", 17, "bold")).pack(side="left")
        ttk.Label(header, text="v0.103   •   Every move preserved", foreground="#60776c").pack(side="right")
        toolbar = ttk.Frame(self, padding=(14, 0, 14, 10))
        toolbar.pack(fill="x")
        for label, callback in (("New deal", self.new_deal), ("Open session", self.open_session),
                                ("Load solution", self.load_solution), ("Save Session", self.save_session),
                                ("Export Current Line", self.export)):
            ttk.Button(toolbar, text=label, command=callback).pack(side="left", padx=3)
        ttk.Checkbutton(toolbar, text="Analysis / Omniscient View", variable=self.analysis,
                        command=self.refresh).pack(side="right", padx=6)
        middle = ttk.Frame(self)
        middle.pack(fill="both", expand=True)
        side = ttk.Frame(middle, padding=(16, 14), width=275)
        side.pack(side="right", fill="y")
        side.pack_propagate(False)
        ttk.Label(side, text="SESSION", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ttk.Label(side, textvariable=self.context, wraplength=240, justify="left").pack(anchor="w", pady=(8, 6))
        ttk.Button(side, text="Rename session", command=self.rename).pack(anchor="w", pady=(0, 10))
        ttk.Label(side, textvariable=self.summary, justify="left", font=("Segoe UI", 11)).pack(anchor="w")
        ttk.Separator(side).pack(fill="x", pady=14)
        ttk.Label(side, text="REPLAY ROUTE", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.route_combo = ttk.Combobox(side, state="readonly")
        self.route_combo.pack(fill="x", pady=5)
        self.route_combo.bind("<<ComboboxSelected>>", self.select_route)
        ttk.Label(side, textvariable=self.replay, wraplength=240, justify="left").pack(anchor="w", pady=6)
        ttk.Label(side, text="HISTORY & BRANCHES", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(12, 6))
        history_frame = ttk.Frame(side)
        history_frame.pack(fill="both", expand=True)
        self.history = ttk.Treeview(history_frame, show="tree", selectmode="browse", height=6)
        self.history.column("#0", width=215, minwidth=120)
        self.history.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(history_frame, command=self.history.yview)
        scroll.pack(side="right", fill="y")
        self.history.configure(yscrollcommand=scroll.set)
        self.history.bind("<<TreeviewSelect>>", self.select_history)
        ttk.Label(side, text="Select any state to revisit it.\nOld branches remain available.",
                  foreground="#60776c", font=("Segoe UI", 9)).pack(anchor="w", pady=(6, 0))
        board_frame = ttk.Frame(middle)
        board_frame.pack(side="left", fill="both", expand=True)
        self.board = SpiderBoard(board_frame, self.move, lambda: self.perform(("deal",)), self.feedback)
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
        ttk.Label(self, textvariable=self.message, padding=(18, 5, 18, 10), wraplength=1080).pack(fill="x")

    def feedback(self, text):
        self.message.set(text)

    def guarded(self, function):
        try:
            result = function()
            self.refresh()
            return result
        except AutosaveError as exc:
            self.refresh()
            self.feedback(str(exc))
            messagebox.showerror("Autosave needs attention", f"{exc}\n\nUse Save Session to retry or save a recovery copy. Do not close this window.", parent=self)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            self.feedback(str(exc))
            messagebox.showerror("Play Lab", str(exc), parent=self)

    def refresh(self):
        if not self.session:
            return
        s = self.session
        node = s.node
        self.board.update_session(s, self.analysis.get())
        self.context.set(f"Deal {s.deal_id}\n{s.name}")
        solved = s.state.is_solved()
        self.summary.set(f"MobilityWare cost   {node.g}\nActions   {node.ordinal}\nTableau moves   {node.ordinal-node.stock_deals}\nStock deals   {node.stock_deals} / 5\nFoundations   {node.foundations} / 8\nHidden cards   {node.face_down}\nEmpty columns   {node.empty_columns}\n{'SOLVED' if solved else 'In progress'}")
        route, position, branch = s.route_position()
        expected = s.expected_action()
        if route:
            text = (f"Branch from {route['name']}\nDivergence after action {position}\nParent g={s.nodes[route['nodes'][position]].g}"
                    if branch else f"Replay action {position} / {len(route['nodes'])-1}\n{route['name']}")
            self.replay.set(text + (f"\nNext: {format_action(expected)}" if expected else "\nFree play" if branch else "\nEnd of route"))
        else:
            self.replay.set("Play freely, or load a solution.")
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
        self._refreshing = False
        self.saved.set("UNSAVED — recovery needed" if s.dirty else "● Autosaved")
        if solved:
            self.feedback("Solved. Your full route is autosaved. Export Current Line to independently verify and save the solution.")

    def perform(self, action):
        if not self.session:
            return
        try:
            self.session.act(action)
        except ValueError as exc:
            self.feedback(f"That move is unavailable. {exc}")
            return  # ordinary illegal play is deliberately non-modal
        except AutosaveError as exc:
            self.refresh()
            self.feedback(str(exc))
            messagebox.showerror("Autosave needs attention", str(exc), parent=self)
            return
        self.feedback(f"Recorded: {format_action(action)}")
        self.refresh()

    def move(self, src, dst, k):
        if not self.session.state.can_move(src, dst, k):
            self.feedback("That destination is unavailable. Choose a rank one higher or an empty column.")
            return
        self.perform((src, dst, k))

    def navigate(self, action):
        if self.session:
            self.feedback("History navigation preserves every branch; only the selected line is exported.")
            self.guarded(lambda: self.session.goto(self.session.root) if action == "first"
                         else getattr(self.session, action)())

    def select_history(self, event):
        selected = self.history.selection()
        if not self._refreshing and selected and self.session and selected[0] != self.session.current:
            self.guarded(lambda: self.session.goto(selected[0]))

    def select_route(self, event):
        if self.session:
            def select():
                self.session.save()
                self.session.active_route = self.route_ids[self.route_combo.current()]
                self.session.goto(self.session.root)
            self.guarded(select)

    def can_replace(self):
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
        if not self.session:
            return
        if self.session.dirty:
            path = filedialog.asksaveasfilename(title="Save recovery copy", initialdir=sessions_dir(),
                initialfile=f"recovery_{self.session.id}.json", defaultextension=".json", parent=self)
            if path:
                self.guarded(lambda: self.session.save(Path(path)))
        else:
            self.guarded(self.session.save)

    def export(self):
        if not self.session:
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
        if self.session:
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
