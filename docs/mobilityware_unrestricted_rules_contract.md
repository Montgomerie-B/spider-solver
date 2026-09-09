# MobilityWare Unrestricted Deal — rules contract

This project solves **MobilityWare Spider Solitaire, 4-suit**, with
**Unrestricted Deal enabled**. That profile is the benchmark.

The engine and `src/spider/rules.py` (`MW_RULES`) are authoritative for
legality and MobilityWare move accounting. Search, planners, and solvers
must ask those APIs. They must not invent a stricter game.

## Deal

A remaining ten-card stock row may be dealt:

- with one or many tableau columns empty;
- while other legal tableau moves remain;
- repeatedly, without exhausting tableau play between deals;
- as the final stock row onto empty columns.

Deal places `stock[-10:]` left-to-right on columns 1–10 (deal files store
stock bottom-to-top). A Deal may complete a same-suit K–A run; removal is
automatic.

A restricted comparison profile (`RESTRICTED_DEAL_RULES`,
`can_deal_into_empty=False`) exists only for contrast. It is not the
benchmark.

## Tableau

- One face-up card may land on a face-up card exactly one rank higher,
  any suit.
- A multi-card block moves only if it is strictly descending and
  **same suit**.
- Any legal card or legal same-suit block may go to an empty column.
  Kings are not required.

## Flip and foundations

Exposing a face-down card flips it automatically, including after
foundation removal. A same-suit King-to-Ace run is removed automatically
and costs zero MobilityWare moves. Eight such runs, empty stock, and empty
tableau is a win.

## MobilityWare counting (corrected)

- Deal = 1
- Ordinary tableau move = 1
- Relocating an **entire** column (no face-down left) onto empty = 0
- Moving all current face-up cards onto empty while face-down remain = 1
- Automatic sequence removal = 0

> Search heuristics may rank or defer any legal action, including Deal,
> but they must never redefine that action as illegal. Proof pruning may
> rely only on rules-correct state semantics and the project's separately
> established proof-safe criteria.

Do not treat move-tier scores, Deal-preparation preference, or
“productive tableau first” as legality.
