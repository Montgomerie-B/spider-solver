"""Parse natural-language solution text and replay via state-aware matching."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from .cards import Card
from .engine import SpiderState


@dataclass
class ParsedMove:
    kind: str  # deal | move
    src: Optional[int] = None  # 0-based
    dst: Optional[int] = None
    anchor: Optional[Card] = None
    use_run: bool = False
    explicit_cards: Optional[List[Card]] = None
    raw: str = ""


def _normalize(text: str) -> str:
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _cards_from_notation(blob: str) -> List[Card]:
    if "+" not in blob:
        return [Card.from_notation(blob)]
    parts = [p.strip().lower() for p in blob.split("+")]
    suit = parts[-1][-1]
    out: List[Card] = []
    for p in parts:
        if len(p) >= 2 and p[-1] in "shdc":
            out.append(Card.from_notation(p))
        else:
            out.append(Card.from_notation(p + suit))
    return out


def _col_to_index(n: int) -> int:
    return n - 1


# Ordered patterns (first match wins at each position). Longer/more specific first.
PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"Deal from stock\.?", re.I), "deal"),
    (
        re.compile(
            r"next\s+(\d+\+(?:\d+|10)[shdc])\s+col\s*(\d+)\s+to\s+col\s*(\d+)",
            re.I,
        ),
        "multi",
    ),
    (
        re.compile(
            r"(\d+\+(?:\d+|10)[shdc])\s+col\s*(\d+)\s+to\s+col\s*(\d+)",
            re.I,
        ),
        "multi",
    ),
    (
        re.compile(
            r"revealing\s+((?:\d+|10|[ajkq])[shdc])\s+col\s*(\d+)\s+allows\s+"
            r"((?:\d+|10|[ajkq])[shdc])\s+col\s*(\d+)\s+to\s+move\s+on\s+to\s+it",
            re.I,
        ),
        "allow_move",
    ),
    (
        re.compile(
            r"revealing\s+((?:\d+|10|[ajkq])[shdc])\s+col\s*(\d+)\s+which\s+moves?\s+to\s+"
            r"bottom\s+of\s+col\s*(\d+)",
            re.I,
        ),
        "reveal_move",
    ),
    (
        re.compile(
            r"revealing\s+((?:\d+|10|[ajkq])[shdc])\s+in\s+col\s*(\d+)\s+which\s+moves?\s+to\s+"
            r"bottom\s+of\s+col\s*(\d+)",
            re.I,
        ),
        "reveal_in_col",
    ),
    (
        re.compile(
            r"as\s+does\s+the\s+((?:\d+|10|[ajkq])[shdc])\s+run\s+from\s+col\s*(\d+)\s+to\s+col\s*(\d+)",
            re.I,
        ),
        "run_to_col",
    ),
    (
        re.compile(
            r"as\s+does\s+the\s+((?:\d+|10|[ajkq])[shdc])\s+run\s+from\s+col\s*(\d+)\s+to\s+col\s*(\d+)",
            re.I,
        ),
        "run_to_col",
    ),
    (
        re.compile(
            r"as\s+does\s+the\s+((?:\d+|10|[ajkq])[shdc])\s+run\s+from\s+col\s*(\d+)(?!\s+to\s+col)",
            re.I,
        ),
        "run_from_col",
    ),
    (
        re.compile(
            r"((?:\d+|10|[ajkq])[shdc])\s*(?:\(run\)|run)\s+(?:from\s+)?col\s*(\d+)\s+to\s+"
            r"(?:empty\s+|space\s+in\s+)?col\s*(\d+)",
            re.I,
        ),
        "run_move",
    ),
    (
        re.compile(
            r"((?:\d+|10|[ajkq])[shdc])\s+col\s*(\d+)\s+moves?\s+to\s+"
            r"((?:\d+|10|[ajkq])[shdc])\s+col\s*(\d+)",
            re.I,
        ),
        "move_to_card",
    ),
    (
        re.compile(
            r"((?:\d+|10|[ajkq])[shdc])\s+col\s*(\d+)\s+moves?\s+to\s+that",
            re.I,
        ),
        "move_to_that",
    ),
    (
        re.compile(
            r"and\s+the\s+((?:\d+|10|[ajkq])[shdc])\s+from\s+col\s*(\d+)\s+to\s+bottom\s+of\s+col\s*(\d+)",
            re.I,
        ),
        "from_to_bottom",
    ),
    (
        re.compile(
            r"((?:\d+|10|[ajkq])[shdc])\s+from\s+col\s*(\d+)\s+to\s+bottom\s+of\s+col\s*(\d+)",
            re.I,
        ),
        "from_to_bottom",
    ),
    (
        re.compile(
            r"((?:\d+|10|[ajkq])[shdc])\s+col\s*(\d+)\s+to\s+"
            r"((?:\d+|10|[ajkq])[shdc])\s+col\s*(\d+)",
            re.I,
        ),
        "card_to_card",
    ),
    (
        re.compile(
            r"((?:\d+|10|[ajkq])[shdc])\s*,?\s*which\s+moves?\s+to\s+bottom\s+of\s+col\s*(\d+)",
            re.I,
        ),
        "which_to",
    ),
    (
        re.compile(
            r"((?:\d+|10|[ajkq])[shdc])\s+which\s+follows\s+to\s+col\s*(\d+)",
            re.I,
        ),
        "follows",
    ),
    (
        re.compile(
            r"((?:\d+|10|[ajkq])[shdc])\s+in\s+col\s*(\d+)\.\s*This\s+moves?\s+to\s+col\s*(\d+)",
            re.I,
        ),
        "this_moves",
    ),
    (
        re.compile(
            r"((?:\d+|10|[ajkq])[shdc])\s+col\s*(\d+)\s+to\s+col\s*(\d+)",
            re.I,
        ),
        "simple",
    ),
]


def extract_moves_from_text(text: str) -> List[ParsedMove]:
    text = _normalize(text)
    # Strip non-move preamble
    text = re.sub(r"^Re your question,\s*", "", text, flags=re.I)
    text = re.sub(r"Important addition.*?two of them\.\s*", "", text, flags=re.I)
    text = re.sub(r"Deal solved in \d+ moves\.?\s*", "", text, flags=re.I)
    text = re.sub(r"\b(Continuing|Next is),?\s*", "", text, flags=re.I)

    moves: List[ParsedMove] = []
    last_dst: Optional[int] = None
    last_src: Optional[int] = None
    last_card: Optional[Card] = None
    pos = 0

    while pos < len(text):
        best_m = None
        best_kind = None
        for pat, kind in PATTERNS:
            m = pat.search(text, pos)
            if m and (best_m is None or m.start() < best_m.start()):
                best_m = m
                best_kind = kind
        if not best_m:
            break
        raw = best_m.group(0).strip()
        pos = best_m.end()

        if best_kind == "deal":
            moves.append(ParsedMove(kind="deal", raw=raw))
            last_dst = None
            continue

        pm: Optional[ParsedMove] = None
        if best_kind == "allow_move":
            pm = ParsedMove(
                kind="move",
                src=_col_to_index(int(best_m.group(4))),
                dst=_col_to_index(int(best_m.group(2))),
                anchor=Card.from_notation(best_m.group(3)),
                raw=raw,
            )
        elif best_kind in ("reveal_move", "reveal_in_col"):
            pm = ParsedMove(
                kind="move",
                src=_col_to_index(int(best_m.group(2))),
                dst=_col_to_index(int(best_m.group(3))),
                anchor=Card.from_notation(best_m.group(1)),
                raw=raw,
            )
        elif best_kind == "run_to_col":
            pm = ParsedMove(
                kind="move",
                src=_col_to_index(int(best_m.group(2))),
                dst=_col_to_index(int(best_m.group(3))),
                anchor=Card.from_notation(best_m.group(1)),
                use_run=True,
                raw=raw,
            )
        elif best_kind == "run_from_col":
            if last_dst is None:
                pos = best_m.start() + 1
                continue
            pm = ParsedMove(
                kind="move",
                src=_col_to_index(int(best_m.group(2))),
                dst=last_dst,
                anchor=Card.from_notation(best_m.group(1)),
                use_run=True,
                raw=raw,
            )
        elif best_kind == "multi":
            parts = _cards_from_notation(best_m.group(1))
            pm = ParsedMove(
                kind="move",
                src=_col_to_index(int(best_m.group(2))),
                dst=_col_to_index(int(best_m.group(3))),
                anchor=parts[0],
                explicit_cards=parts,
                raw=raw,
            )
        elif best_kind == "run_move":
            pm = ParsedMove(
                kind="move",
                src=_col_to_index(int(best_m.group(2))),
                dst=_col_to_index(int(best_m.group(3))),
                anchor=Card.from_notation(best_m.group(1)),
                use_run=True,
                raw=raw,
            )
        elif best_kind == "move_to_card":
            pm = ParsedMove(
                kind="move",
                src=_col_to_index(int(best_m.group(2))),
                dst=_col_to_index(int(best_m.group(4))),
                anchor=Card.from_notation(best_m.group(1)),
                raw=raw,
            )
        elif best_kind == "move_to_that":
            # "that" usually means the source column of the prior card-to-card move
            ref = last_src if last_src is not None else last_dst
            if ref is None:
                pos = best_m.start() + 1
                continue
            pm = ParsedMove(
                kind="move",
                src=_col_to_index(int(best_m.group(2))),
                dst=ref,
                anchor=Card.from_notation(best_m.group(1)),
                raw=raw,
            )
        elif best_kind in ("from_to_bottom",):
            pm = ParsedMove(
                kind="move",
                src=_col_to_index(int(best_m.group(2))),
                dst=_col_to_index(int(best_m.group(3))),
                anchor=Card.from_notation(best_m.group(1)),
                raw=raw,
            )
        elif best_kind == "card_to_card":
            pm = ParsedMove(
                kind="move",
                src=_col_to_index(int(best_m.group(2))),
                dst=_col_to_index(int(best_m.group(4))),
                anchor=Card.from_notation(best_m.group(1)),
                raw=raw,
            )
        elif best_kind == "which_to":
            if last_card is None:
                pos = best_m.start() + 1
                continue
            pm = ParsedMove(
                kind="move",
                src=None,
                dst=_col_to_index(int(best_m.group(2))),
                anchor=last_card,
                raw=raw,
            )
        elif best_kind == "follows":
            pm = ParsedMove(
                kind="move",
                src=None,
                dst=_col_to_index(int(best_m.group(2))),
                anchor=Card.from_notation(best_m.group(1)),
                raw=raw,
            )
        elif best_kind == "this_moves":
            pm = ParsedMove(
                kind="move",
                src=_col_to_index(int(best_m.group(2))),
                dst=_col_to_index(int(best_m.group(3))),
                anchor=Card.from_notation(best_m.group(1)),
                raw=raw,
            )
        elif best_kind == "simple":
            card = Card.from_notation(best_m.group(1))
            pm = ParsedMove(
                kind="move",
                src=_col_to_index(int(best_m.group(2))),
                dst=_col_to_index(int(best_m.group(3))),
                anchor=card,
                use_run="run" in raw.lower(),
                raw=raw,
            )

        if pm:
            moves.append(pm)
            if pm.dst is not None:
                last_dst = pm.dst
            if pm.src is not None:
                last_src = pm.src
            last_card = pm.anchor
            if pm.explicit_cards:
                last_card = pm.explicit_cards[-1]

    # Opening prose order != play order: 5+4S before 6S onto col 3.
    for i in range(len(moves) - 1):
        a, b = moves[i], moves[i + 1]
        if (
            a.kind == "move"
            and b.kind == "move"
            and b.explicit_cards
            and a.anchor
            and str(a.anchor).lower() == "6s"
            and "allows" in a.raw.lower()
        ):
            moves[i], moves[i + 1] = b, a
            break

    return moves


def _desc_run_len_from(up: List[Card], start: int) -> int:
    """Longest descending chain from ``up[start]`` through the pile top."""
    n = 1
    for i in range(start, len(up) - 1):
        if up[i].rank - 1 == up[i + 1].rank:
            n += 1
        else:
            break
    return n


def _same_suit_run_len_from(up: List[Card], start: int) -> int:
    """Longest same-suit descending chain from ``up[start]`` through the pile top."""
    suit = up[start].suit
    n = 1
    for i in range(start, len(up) - 1):
        if up[i].suit == suit and up[i + 1].suit == suit and up[i].rank - 1 == up[i + 1].rank:
            n += 1
        else:
            break
    return n


def _run_match_modes(pm: ParsedMove) -> List[bool]:
    """Prose with ``run`` → same-suit stack only; otherwise try single card, then run."""
    if pm.use_run:
        return [True]
    return [False, True]


def _run_size_for_anchor(up: List[Card], anchor: Card, use_run: bool) -> int:
    indices = [i for i, c in enumerate(up) if c.rank == anchor.rank and c.suit == anchor.suit]
    if not indices:
        raise ValueError(f"{anchor} not in pile {[str(c) for c in up]}")
    start = indices[-1]
    if use_run:
        # "QS run …" = anchor plus every card above it in the column, same suit, descending.
        run_len = _same_suit_run_len_from(up, start)
        if run_len != len(up) - start:
            raise ValueError(
                f"{anchor} same-suit run does not reach top (len {run_len}, "
                f"need {len(up) - start}): {[str(c) for c in up]}"
            )
    else:
        run_len = _desc_run_len_from(up, start)
    if run_len < 1:
        raise ValueError(f"no run at {anchor}: {[str(c) for c in up]}")
    if use_run:
        return run_len
    if start != len(up) - 1:
        raise ValueError(f"{anchor} is not top card in {[str(c) for c in up]}")
    return 1


def _match_move(state: SpiderState, pm: ParsedMove) -> Tuple[int, int, int]:
    if pm.explicit_cards:
        k = len(pm.explicit_cards)
        for src in [pm.src] if pm.src is not None else range(10):
            for dst in [pm.dst] if pm.dst is not None else range(10):
                if src == dst:
                    continue
                if state.can_move(src, dst, k):
                    up = state.columns[src].face_up[-k:]
                    if all(
                        up[i].rank == pm.explicit_cards[i].rank
                        and up[i].suit == pm.explicit_cards[i].suit
                        for i in range(k)
                    ):
                        return src, dst, k
        raise ValueError(f"no match for explicit {pm.explicit_cards}: {pm.raw!r}")

    assert pm.anchor is not None
    if pm.src is not None and pm.dst is not None:
        for use_run in _run_match_modes(pm):
            try:
                max_k = _run_size_for_anchor(
                    state.columns[pm.src].face_up, pm.anchor, use_run
                )
            except ValueError:
                continue
            for k in range(max_k, 0, -1):
                if state.can_move(pm.src, pm.dst, k):
                    return pm.src, pm.dst, k

    for src in range(10):
        up = state.columns[src].face_up
        if not up:
            continue
        for use_run in _run_match_modes(pm):
            try:
                max_k = _run_size_for_anchor(up, pm.anchor, use_run)
            except ValueError:
                continue
            for k in range(max_k, 0, -1):
                for dst in range(10):
                    if src == dst:
                        continue
                    if pm.dst is not None and dst != pm.dst:
                        continue
                    if pm.src is not None and src != pm.src:
                        continue
                    if state.can_move(src, dst, k):
                        return src, dst, k

    raise ValueError(
        f"no legal move for {pm.anchor} src={pm.src} dst={pm.dst}: {pm.raw!r} "
        f"tops={state.top_row()}"
    )


def apply_parsed_move(state: SpiderState, pm: ParsedMove) -> Tuple[int, int, int, int]:
    if pm.kind == "deal":
        return -1, -1, 0, state.deal()
    src, dst, k = _match_move(state, pm)
    return src, dst, k, state.move(src, dst, k)


def load_solution_text(path: Path) -> str:
    if path.suffix.lower() == ".docx":
        import zipfile
        import xml.etree.ElementTree as ET

        z = zipfile.ZipFile(path)
        root = ET.fromstring(z.read("word/document.xml"))
        paras = []
        for para in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
            texts = []
            for t in para.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"):
                if t.text:
                    texts.append(t.text)
                if t.tail:
                    texts.append(t.tail)
            line = "".join(texts).strip()
            if line:
                paras.append(line)
        return "\n".join(paras)
    return path.read_text(encoding="utf-8")