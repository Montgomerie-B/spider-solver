"""Canvas board. Analysis visibility never changes engine playability."""
from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass

from .cards import Card, rank_str
from .engine import SpiderState

SUITS = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}
FELT = "#174b43"


@dataclass(frozen=True)
class DisplayCard:
    card: Card | None
    locked: bool
    anchor: int | None  # index in face_up, never an index into face_down


def column_cards(column, analysis: bool) -> list[DisplayCard]:
    return ([DisplayCard(c if analysis else None, True, None) for c in column.face_down]
            + [DisplayCard(c, False, i) for i, c in enumerate(column.face_up)])


def movable_count(state: SpiderState, column: int, anchor: int | None) -> int:
    if anchor is None or not 0 <= column < 10:
        return 0
    up = state.columns[column].face_up
    if not 0 <= anchor < len(up) or not state.is_movable_run(up[anchor:]):
        return 0
    return len(up) - anchor


class SpiderBoard(tk.Canvas):
    def __init__(self, master, on_move, on_deal, on_feedback, **kwargs):
        super().__init__(master, background=FELT, highlightthickness=0, **kwargs)
        self.on_move, self.on_deal, self.on_feedback = on_move, on_deal, on_feedback
        self.session = None
        self.analysis = False
        self.selected = None
        self.hitboxes = []
        self.press = None
        self.dragging = False
        self.bind("<Configure>", lambda e: self.draw())
        self.bind("<ButtonPress-1>", self.down)
        self.bind("<B1-Motion>", self.motion)
        self.bind("<ButtonRelease-1>", self.up)
        self.bind("<MouseWheel>", lambda e: self.yview_scroll(-int(e.delta / 120), "units"))

    def update_session(self, session, analysis=False):
        self.session, self.analysis = session, analysis
        self.selected = None
        self.draw()

    def card(self, x, y, w, h, display, *, selected=False, tag="board"):
        face = display.card
        fill = "#fffdf7" if not display.locked else "#c4d2cb" if face else "#285c67"
        border = "#f4c66b" if selected else "#8ca79c" if display.locked else "#d2d9cf"
        self.create_rectangle(x + 2, y + 3, x + w + 2, y + h + 3,
                              fill="#103e38", outline="", tags=tag)
        self.create_rectangle(x, y, x + w, y + h, fill=fill, outline=border,
                              width=3 if selected else 1, tags=tag)
        if face is None:
            self.create_rectangle(x + 5, y + 5, x + w - 5, y + h - 5,
                                  outline="#5b8290", tags=tag)
            self.create_text(x + w / 2, y + 12, text="◇  ◇  ◇", fill="#87a9b2",
                             font=("Segoe UI", 10), tags=tag)
            return
        ink = ("#8b7370" if face.suit in "hd" else "#687b75") if display.locked else (
            "#bd3f43" if face.suit in "hd" else "#253a3b")
        size = max(11, min(17, int(w * .19)))
        self.create_text(x + 8, y + 12, anchor="w", text=f"{rank_str(face.rank)}{SUITS[face.suit]}",
                         fill=ink, font=("Segoe UI", size, "bold"), tags=tag)
        if display.locked:
            self.create_text(x + w - 6, y + 12, anchor="e", text="×", fill="#6b7f78",
                             font=("Segoe UI", 10, "bold"), tags=tag)
        self.create_text(x + w / 2, y + h * .56, text=SUITS[face.suit], fill=ink,
                         font=("Segoe UI Symbol", int(w * .43)), tags=tag)
        self.create_text(x + w - 8, y + h - 12, anchor="e",
                         text=f"{rank_str(face.rank)}{SUITS[face.suit]}", fill=ink,
                         font=("Segoe UI", size, "bold"), tags=tag)

    def draw(self):
        if self.session is None:
            return
        self.delete("board")
        self.hitboxes = []
        state = self.session.state
        width = max(700, self.winfo_width())
        self.gap = max(9, width * .012)
        self.cw = min(104, (width - 2 * 44 - 9 * self.gap) / 10)
        self.ch = self.cw * 1.38
        self.left = (width - 10 * self.cw - 9 * self.gap) / 2
        self.top = 102
        self.create_text(self.left, 23, anchor="w", text="TABLEAU", fill="#b6d2c7",
                         font=("Segoe UI", 10, "bold"), tags="board")
        for f in range(8):
            x = self.left + 130 + f * 43
            complete = f < len(state.foundations)
            self.create_rectangle(x, 8, x + 33, 49, outline="#648d7f",
                                  fill="#e7ede2" if complete else "#20564b", tags="board")
            suit = SUITS[state.foundations[f][0].suit] if complete else "·"
            self.create_text(x + 16, 28, text=suit, fill="#b73e43" if complete and
                             state.foundations[f][0].suit in "hd" else "#92b8a9",
                             font=("Segoe UI Symbol", 20), tags="board")
        sx = width - self.left - 138
        self.stock_box = (sx, 9, sx + 138, 50)
        self.create_rectangle(*self.stock_box, fill="#e4ba69" if state.stock else "#40675c",
                              outline="", tags="board")
        self.create_text(sx + 69, 29, text=f"Deal stock  ·  {len(state.stock)//10} left",
                         fill="#203e37", font=("Segoe UI", 10, "bold"), tags="board")
        expected = self.session.expected_action()
        board_bottom = self.top + self.ch
        available = max(280, self.winfo_height() - self.top - (215 if self.analysis else 30))
        for col, column in enumerate(state.columns):
            x = self.left + col * (self.cw + self.gap)
            cards = column_cards(column, self.analysis)
            step = min(30, max(24, (available - self.ch) / max(1, len(cards) - 1)))
            mark = expected and expected != ("deal",) and col in expected[:2]
            self.create_text(x + self.cw / 2, 77, text=str(col + 1), fill="#f4c66b" if mark else "#bbd3c8",
                             font=("Segoe UI", 11, "bold"), tags="board")
            self.create_rectangle(x, self.top, x + self.cw, self.top + self.ch,
                                  outline="#70968a" if mark else "#396d5e", dash=(4, 4), tags="board")
            for i, display in enumerate(cards):
                y = self.top + i * step
                selected = self.selected is not None and self.selected[0] == col and not display.locked and (
                    display.anchor >= len(column.face_up) - self.selected[1])
                self.card(x, y, self.cw, self.ch, display, selected=selected)
                bottom = y + (step if i < len(cards)-1 else self.ch)
                self.hitboxes.append((x, y, x + self.cw, bottom, col, display.anchor))
                board_bottom = max(board_bottom, y + self.ch)
        if self.analysis:
            y = board_bottom + 36
            self.create_text(self.left, y, anchor="w", text="FUTURE STOCK  ·  locked, not playable  ·  columns 1–10",
                             fill="#bed0c8", font=("Segoe UI", 10, "bold"), tags="board")
            y += 25
            rounds = self.session.future_stock()
            for number, cards in rounds:
                self.create_text(self.left - 4, y + 12, anchor="e", text=f"SD{number}",
                                 fill="#b6c9c0", font=("Segoe UI", 9, "bold"), tags="board")
                for col, card in enumerate(cards):
                    x = self.left + col * (self.cw + self.gap)
                    self.create_rectangle(x, y, x + self.cw, y + 25, fill="#35695c", outline="#4b7a6c", tags="board")
                    self.create_text(x + self.cw / 2, y + 12, text=f"{rank_str(card.rank)}{SUITS[card.suit]}  ×",
                                     fill="#d4b8ae" if card.suit in "hd" else "#bbcfc4",
                                     font=("Segoe UI", 11, "bold"), tags="board")
                y += 30
            if not rounds:
                self.create_text(self.left, y, anchor="w", text="All five stock rounds have been dealt.",
                                 fill="#b6c9c0", tags="board")
            board_bottom = y + 20
        self.configure(scrollregion=(0, 0, width, board_bottom + 30))

    def hit(self, x, y):
        for x0, y0, x1, y1, col, anchor in reversed(self.hitboxes):
            if x0 <= x <= x1 and y0 <= y <= y1:
                return col, anchor
        return None

    def destination(self, x, y):
        if y < self.top:
            return None
        for col in range(10):
            x0 = self.left + col * (self.cw + self.gap)
            if x0 <= x <= x0 + self.cw:
                return col
        return None

    def down(self, event):
        self.focus_set()
        x, y = self.canvasx(event.x), self.canvasy(event.y)
        self.press = (x, y)
        self.dragging = False
        x0, y0, x1, y1 = self.stock_box
        if x0 <= x <= x1 and y0 <= y <= y1:
            self.press = None
            self.on_deal()
            return
        target = self.hit(x, y)
        dest = self.destination(x, y)
        if self.selected and dest is not None and dest != self.selected[0]:
            src, k = self.selected
            self.press = None
            self.on_move(src, dest, k)
            return
        if target:
            k = movable_count(self.session.state, *target)
            if k:
                self.selected = (target[0], k)
                self.draw()
            else:
                self.selected = None
                self.draw()
                self.on_feedback("Hidden cards are locked." if target[1] is None else "Select a descending run of one suit.")
        else:
            self.selected = None
            self.draw()

    def motion(self, event):
        if not self.press or not self.selected:
            return
        x, y = self.canvasx(event.x), self.canvasy(event.y)
        if abs(x-self.press[0]) + abs(y-self.press[1]) < 6:
            return
        self.dragging = True
        self.delete("drag")
        src, k = self.selected
        for i, card in enumerate(self.session.state.columns[src].face_up[-k:]):
            self.card(x - self.cw / 2, y - 12 + i * 26, self.cw, self.ch,
                      DisplayCard(card, False, i), selected=True, tag="drag")

    def up(self, event):
        self.delete("drag")
        if self.dragging and self.selected:
            dest = self.destination(self.canvasx(event.x), self.canvasy(event.y))
            if dest is not None:
                self.on_move(self.selected[0], dest, self.selected[1])
        self.press, self.dragging = None, False
