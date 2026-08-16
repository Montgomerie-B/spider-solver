"""Spider Solitaire game engine (MobilityWare 4-suit rules)."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .cards import Card
from .rules import MobilityWareRules, MW_RULES, deal_cost, mw_move_cost


@dataclass
class Column:
    face_down: List[Card]
    face_up: List[Card]

    def top(self) -> Optional[Card]:
        return self.face_up[-1] if self.face_up else None

    def push(self, run: List[Card]) -> None:
        self.face_up.extend(run)

    def pop(self, k: int) -> List[Card]:
        run = self.face_up[-k:]
        self.face_up = self.face_up[:-k]
        return run

    def maybe_flip(self) -> bool:
        if not self.face_up and self.face_down:
            self.face_up.append(self.face_down.pop())
            return True
        return False

    def is_empty(self) -> bool:
        return (not self.face_down) and (not self.face_up)


class SpiderState:
    def __init__(
        self,
        columns: List[Column],
        stock: List[Card],
        foundations: Optional[List[List[Card]]] = None,
    ):
        self.columns = columns
        self.stock = stock
        self.foundations = foundations or []
        self._undo: list = []
        self.last_move = None

    @staticmethod
    def from_cards(cards: List[Card]) -> SpiderState:
        if len(cards) != 104:
            raise ValueError(f"need 104 cards, got {len(cards)}")
        cols = [Column([], []) for _ in range(10)]
        idx = 0
        for _ in range(5):
            for c in range(10):
                cols[c].face_down.append(cards[idx])
                idx += 1
        for c in range(4):
            cols[c].face_down.append(cards[idx])
            idx += 1
        for c in range(10):
            cols[c].face_up.append(cols[c].face_down.pop())
        stock = cards[idx:]
        return SpiderState(cols, stock)

    @staticmethod
    def is_desc_run(cards: List[Card]) -> bool:
        return all(cards[i].rank - 1 == cards[i + 1].rank for i in range(len(cards) - 1))

    @staticmethod
    def is_same_suit(cards: List[Card]) -> bool:
        return all(c.suit == cards[0].suit for c in cards) if cards else True

    @classmethod
    def is_movable_run(cls, cards: List[Card]) -> bool:
        """Whether cards form one legally movable Spider tableau block."""
        return cls.is_desc_run(cards) and cls.is_same_suit(cards)

    def can_move(self, src: int, dst: int, k: int) -> bool:
        if src == dst or k <= 0 or k > len(self.columns[src].face_up):
            return False
        run = self.columns[src].face_up[-k:]
        if not self.is_movable_run(run):
            return False
        top = self.columns[dst].top()
        return top is None or top.rank - 1 == run[0].rank

    def move(
        self,
        src: int,
        dst: int,
        k: int,
        rules: MobilityWareRules = MW_RULES,
    ) -> int:
        if not self.can_move(src, dst, k):
            raise ValueError(f"illegal move: col {src + 1} -> col {dst + 1}, k={k}")
        src_col = self.columns[src]
        dst_col = self.columns[dst]
        dest_was_empty = dst_col.is_empty()
        src_face_up = len(src_col.face_up)
        src_face_down = len(src_col.face_down)
        run = src_col.pop(k)
        dst_col.push(run)
        flipped = src_col.maybe_flip()
        removed = self.check_seq(dst)
        cost = mw_move_cost(
            cards_moved=k,
            source_face_up_count=src_face_up,
            dest_was_empty=dest_was_empty,
            source_face_down_count=src_face_down,
            rules=rules,
        )
        self._undo.append(("m", src, dst, k, flipped, removed, cost))
        self.last_move = (src, dst, k, flipped, removed)
        return cost

    def check_seq(self, col_idx: int) -> bool:
        col = self.columns[col_idx]
        if len(col.face_up) >= 13 and col.face_up[-13].rank == 13:
            tail = col.face_up[-13:]
            if self.is_movable_run(tail):
                col.face_up = col.face_up[:-13]
                self.foundations.append(tail)
                col.maybe_flip()
                return True
        return False

    def deal(self, rules: MobilityWareRules = MW_RULES) -> int:
        if len(self.stock) < 10:
            raise ValueError("cannot deal: stock has fewer than 10 cards")
        # MobilityWare deal files list stock bottom-to-top; the next deal is the
        # topmost 10 cards, written left-to-right onto columns 1..10.
        chunk = self.stock[-10:]
        self.stock = self.stock[:-10]
        dealt = []
        for c in range(10):
            card = chunk[c]
            self.columns[c].face_up.append(card)
            self.check_seq(c)
            dealt.append(card)
        self._undo.append(("d", dealt))
        self.last_move = ("deal",)
        return deal_cost()

    def enumerate_moves(self) -> List[Tuple[int, int, int]]:
        moves: List[Tuple[int, int, int]] = []
        for src in range(10):
            up = self.columns[src].face_up
            for k in range(1, len(up) + 1):
                run = up[-k:]
                if not self.is_movable_run(run):
                    continue
                for dst in range(10):
                    if src == dst:
                        continue
                    if self.can_move(src, dst, k):
                        moves.append((src, dst, k))
        return moves

    def top_row(self) -> list[Optional[Card]]:
        return [col.top() for col in self.columns]

    def clone(self) -> SpiderState:
        """Structural clone. Cards are frozen/immutable so list-of-Card is enough.

        Intentionally not a full object-graph deep copy (dominant historical
        cost in Opt012/Opt013 expansion). Undo history is not copied —
        search/diagnostic paths never need it.
        """
        cols = [
            Column(list(c.face_down), list(c.face_up)) for c in self.columns
        ]
        st = SpiderState(
            cols,
            list(self.stock),
            [list(f) for f in self.foundations],
        )
        st.last_move = self.last_move
        return st

    def is_solved(self) -> bool:
        return len(self.foundations) == 8 and not self.stock and all(
            c.is_empty() for c in self.columns
        )

    def render(self, reveal: bool = False) -> str:
        lines = []
        maxlen = max(len(c.face_down) + len(c.face_up) for c in self.columns)
        for r in range(maxlen):
            row = []
            for col in self.columns:
                fd = len(col.face_down)
                fu = len(col.face_up)
                total = fd + fu
                if r < fd:
                    row.append(f"[{col.face_down[r]}]" if reveal else "XX")
                elif r < total:
                    row.append(str(col.face_up[r - fd]))
                else:
                    row.append("  ")
            lines.append(" ".join(f"{cell:>3}" for cell in row))
        return "\n".join(lines)
