"""Canvas board. Analysis visibility never changes engine playability."""
from __future__ import annotations

import tkinter as tk
import time
from dataclasses import dataclass

from .cards import Card, rank_str
from .engine import SpiderState
from .deal import stock_deal_rounds

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


def future_cards(state: SpiderState, analysis: bool):
    """Presentation only. Every future card has no playable anchor, in both views."""
    start = (50 - len(state.stock)) // 10 + 1
    return [(number, [DisplayCard(c if analysis else None, True, None) for c in cards])
            for number, cards in enumerate(stock_deal_rounds(state.stock), start)]


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
        self.input_blocked = lambda: False
        self._display_state = None
        self._animation_job = None
        self._animation_done = None
        self.bind("<Configure>", self.resized)
        self.bind("<ButtonPress-1>", self.down)
        self.bind("<B1-Motion>", self.motion)
        self.bind("<ButtonRelease-1>", self.up)
        self.bind("<MouseWheel>", lambda e: self.yview_scroll(-int(e.delta / 120), "units"))

    def update_session(self, session, analysis=False):
        self.session, self.analysis = session, analysis
        self.selected = None
        self.draw()

    def resized(self, event=None):
        # Finish a visual transition instantly on resize; logical state is saved already.
        self.cancel_transition()
        self.draw()

    def cancel_transition(self):
        if self._animation_job is not None:
            self.after_cancel(self._animation_job)
            self._animation_job = None
        self.delete("transition")
        self.delete("effects")
        self._display_state = None
        done, self._animation_done = self._animation_done, None
        if done:
            done()

    def animate(self, before, after, action, duration, done):
        """Draw cloned snapshots and sprites only; never call move/deal here."""
        self.cancel_transition()
        self._animation_done = done
        self.selected = None
        self._display_state = before
        self.draw()
        sprites = []
        if action == ("deal",):
            moving = [(col, [card]) for col, card in enumerate(stock_deal_rounds(before.stock)[0])]
        else:
            src, dst, k = action
            moving = [(dst, before.columns[src].face_up[-k:])]
        for dst, cards in moving:
            end_x = self.left + dst * (self.cw + self.gap)
            dest_count = len(before.columns[dst].face_down) + len(before.columns[dst].face_up)
            end_y = self.top + dest_count * self.column_steps[dst]
            if action == ("deal",):
                start_x, start_y = self.stock_box[0], self.stock_box[1]
            else:
                source_count = len(before.columns[src].face_down) + len(before.columns[src].face_up)
                start_x = self.left + src * (self.cw + self.gap)
                start_y = self.top + (source_count - k) * self.column_steps[src]
                for i in range(source_count-k, source_count):
                    self.itemconfigure(f"card_{src}_{i}", state="hidden")
            tag = f"sprite_{dst}"
            for i, card in enumerate(cards):
                self.card(start_x, start_y + i * self.column_steps[dst], self.cw, self.ch,
                          DisplayCard(card, False, i), selected=True, tag=("transition", tag))
            sprites.append((tag, start_x, start_y, end_x, end_y, dst))
        start = time.perf_counter()
        previous = {tag: (x, y) for tag, x, y, *_ in sprites}

        def settle():
            self._animation_job = None
            self.delete("transition")
            self._display_state = None
            self.draw()
            for col, (old, new) in enumerate(zip(before.columns, after.columns)):
                if len(new.face_down) < len(old.face_down):
                    x = self.left + col * (self.cw + self.gap)
                    y = self.top + len(new.face_down) * self.column_steps[col]
                    self.create_rectangle(x, y, x+self.cw, y+self.ch, outline="#f4c66b", width=3, tags="effects")
            removed = len(after.foundations)-len(before.foundations)
            if removed:
                self.create_text(self.winfo_width()/2, 63, text=f"+{removed} complete K–A sequence{'s' if removed>1 else ''}",
                                 fill="#f4c66b", font=("Segoe UI", 12, "bold"), tags="effects")
            self._animation_job = self.after(140, self.cancel_transition)

        def frame():
            elapsed = (time.perf_counter()-start)*1000
            for tag, x0, y0, x1, y1, col in sprites:
                delay = col * .018 if action == ("deal",) else .12
                t = max(0.0, min(1.0, (elapsed/duration-delay)/(1-delay)))
                eased = t*t*(3-2*t)
                x, y = x0+(x1-x0)*eased, y0+(y1-y0)*eased
                px, py = previous[tag]
                self.move(tag, x-px, y-py)
                previous[tag] = (x, y)
            if elapsed >= duration:
                # Hold the intact arriving run briefly before engine flips/removals appear.
                self._animation_job = self.after(45, settle)
            else:
                self._animation_job = self.after(16, frame)
        frame()

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
        ink = ("#a34849" if face.suit in "hd" else "#445b53") if display.locked else (
            "#bd3f43" if face.suit in "hd" else "#253a3b")
        size = max(11, min(17, int(w * .19)))
        self.create_text(x + 8, y + 12, anchor="w", text=f"{rank_str(face.rank)}{SUITS[face.suit]}",
                         fill=ink, font=("Segoe UI", size, "bold"), tags=tag)
        if display.locked:
            self.create_text(x + w - 6, y + (h - 9 if w < 60 else 12), anchor="e", text="×", fill="#6b7f78",
                             font=("Segoe UI", 10, "bold"), tags=tag)
        self.create_text(x + w / 2, y + h * .56, text=SUITS[face.suit], fill=ink,
                         font=("Segoe UI Symbol", int(w * .43)), tags=tag)
        if w >= 60:
            self.create_text(x + w - 8, y + h - 12, anchor="e",
                             text=f"{rank_str(face.rank)}{SUITS[face.suit]}", fill=ink,
                             font=("Segoe UI", size, "bold"), tags=tag)

    def draw(self):
        if self.session is None:
            return
        self.delete("board")
        self.hitboxes = []
        state = self._display_state or self.session.state
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
        self.column_steps = []
        available = max(280, self.winfo_height() - self.top - (215 if self.analysis else 30))
        for col, column in enumerate(state.columns):
            x = self.left + col * (self.cw + self.gap)
            cards = column_cards(column, self.analysis)
            step = min(30, max(24, (available - self.ch) / max(1, len(cards) - 1)))
            self.column_steps.append(step)
            mark = expected and expected != ("deal",) and col in expected[:2]
            self.create_text(x + self.cw / 2, 77, text=str(col + 1), fill="#f4c66b" if mark else "#bbd3c8",
                             font=("Segoe UI", 11, "bold"), tags="board")
            self.create_rectangle(x, self.top, x + self.cw, self.top + self.ch,
                                  outline="#70968a" if mark else "#396d5e", dash=(4, 4), tags="board")
            for i, display in enumerate(cards):
                y = self.top + i * step
                selected = self.selected is not None and self.selected[0] == col and not display.locked and (
                    display.anchor >= len(column.face_up) - self.selected[1])
                self.card(x, y, self.cw, self.ch, display, selected=selected, tag=("board", f"card_{col}_{i}"))
                bottom = y + (step if i < len(cards)-1 else self.ch)
                self.hitboxes.append((x, y, x + self.cw, bottom, col, display.anchor))
                board_bottom = max(board_bottom, y + self.ch)
        self.tableau_bottom = board_bottom
        if self.analysis:
            y = board_bottom + 36
            self.create_text(self.left, y, anchor="w", text="FUTURE STOCK  ·  locked, not playable  ·  columns 1–10",
                             fill="#bed0c8", font=("Segoe UI", 10, "bold"), tags="board")
            y += 25
            rounds = future_cards(state, self.analysis)
            mini_w = min(48, self.cw * .7)
            mini_h = mini_w * 1.38
            for number, cards in rounds:
                self.create_text(self.left - 4, y + mini_h/2, anchor="e", text=f"SD{number}",
                                 fill="#b6c9c0", font=("Segoe UI", 9, "bold"), tags="board")
                for col, display in enumerate(cards):
                    x = self.left + col * (self.cw + self.gap) + (self.cw-mini_w)/2
                    self.card(x, y, mini_w, mini_h, display)
                y += mini_h + 9
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
        if y < self.top or y > self.tableau_bottom:
            return None
        for col in range(10):
            x0 = self.left + col * (self.cw + self.gap)
            if x0 <= x <= x0 + self.cw:
                return col
        return None

    def down(self, event):
        if self.session is None or self.input_blocked():
            return
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
        if self.input_blocked() or not self.press or not self.selected:
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
        if self.input_blocked():
            self.press, self.dragging = None, False
            return
        if self.dragging and self.selected:
            dest = self.destination(self.canvasx(event.x), self.canvasy(event.y))
            if dest is not None:
                self.on_move(self.selected[0], dest, self.selected[1])
        self.press, self.dragging = None, False
