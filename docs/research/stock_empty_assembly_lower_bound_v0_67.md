# stock_empty_assembly_lower_bound_v0_67

Verdict: `ASSEMBLY_BOUND_COST_IMPROVED`

Replay-valid autonomous complete solution at corrected **g = 192**, beating incumbent 198. v0.59 file was not overwritten.

## Admissibility argument

Stock-empty engine facts, tested mechanically:

* a legal tableau action carries one same-suit movable block;
* it merges with at most one same-suit destination component;
* `check_seq(dst)` removes at most one foundation;
* Deal is gone, so a foundation cannot be removed for free.

For a suit with `m` remaining foundations and `u` physical interval units minimally required to multicover ranks 1–13 at multiplicity `m`:

```text
suit_lb = max(m, u - m)
assembly_lb = sum(suit_lb)
```

`max` not sum: the last join may also trigger the foundation. Inactive while `stock_rows > 0` (returns 0). Undefined/infeasible cover falls back to `m`, never an unsafe high number.

The bound ignores blockers, parking, off-suit receivers, and geometry. It is a lower bound.

## Interval multicover

Visible same-suit descending components (including singletons) are intervals `[low, high]`. Face-down cards are singleton `[rank, rank]`. Foundated cards are absent.

Production algorithm: leftmost-residual / farthest-reaching greedy (optimal for intervals on a line). Cross-checked against brute-force subset search on 120 random instances with n ≤ 11 and demand 1 or 2: greedy = brute in every case.

## Known-route sanity (evaluation only)

| route | stock-empty states | h ≤ remaining | max h | min slack |
| --- | ---: | --- | ---: | ---: |
| autonomous 198 | 67 | yes, 0 violations | 31 | 0 |
| canonical 172 | 22 | yes, 0 violations | 18 | 0 |

## F2 verification

Loaded stored v0.65/v0.66 prefix, not re-searched.

| fact | value |
| --- | ---: |
| g | 130 |
| rows | 1 |
| fd | 2 |
| F | 2 |
| suits | Spades + Diamonds |
| actions | 134 |
| digest | `53504b310102000a00020d29…` |
| replay | valid |
| assembly_lb before SD5 | 0 |

## Envelope

| knob | v0.66 | v0.67 |
| --- | ---: | ---: |
| time | 900.4 s | 900.1 s |
| unique | 84,202 | 78,555 |
| ceiling | 197 | 197 |
| width | 256 | 256 |
| rows=1 alloc | 360.7 s | 360.6 s |
| post-stock alloc | 539.1 s | 539.1 s |
| expansions | 10,897 | 5,460 |
| exp/s | 12.1 | 6.07 |

v0.66 transition harvest frozen (DEAL_NOW kept). COMPLETION lane added for stock-empty only; v0.63 lanes retained. No DURABILITY.

## COMPLETION lane

Primary key `f = g + assembly_lb`, then h, −F, total multicover units, operational blockers, boundaries, −mobility, g. Inactive before stock exhaustion.

A state with f=193 outranks a high-F state with f=199.

## Lower-bound prune / performance

| metric | value |
| --- | ---: |
| bound calls | 82,567 |
| bound time | 12.4 s (150 µs/call) |
| proof-prunes | 57,270 |
| generated | 190,483 |
| prune fraction | 30.1% |
| prunes by F | F2 29522, F3 9343, F4 13668, F5 3822, F6 887, F7 28 |

h is not in identity. Exact TT remains cheapest-g.

## F3–F8 frontier including h / f / slack

| F | v0.66 g | v0.67 g | h | f | slack | proof-dead? |
| ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 3 | 173 | 173 | 14 | 187 | 10 | no |
| 4 | 181 | 181 | 12 | 193 | 4 | no |
| 5 | 186 | **185** | 8 | 193 | 4 | no |
| 6 | 194 | **187** | 6 | 193 | 4 | no |
| 7 | 196 | **191** | 1 | 192 | 5 | no |
| 8 | none | **192** | 0 | 192 | 5 | no |

v0.66 F7=196 with cover=4 was **proof-infeasible** under ceiling 197: u≥4, m=1, h≥3, f≥199, slack −2. The v0.67 cheap F7 is g=191, h=1 (two remaining club units), f=192, still inside budget, and converted.

## Best complete g

**192**. File: `solutions/4925153_autonomous_v0_67.moves`

Replay from untouched opening: legal, five Deals, corrected g=192, eight foundations, stock empty, tableau empty, solved. Concatenated autonomous prefix + rows=1 prep + SD5 + post-stock. No canonical input.

## Comparison with v0.66

Search no longer chases high-F states that cannot finish. Intermediate F3/F4 minima held; F5–F8 and the terminal improved. 57k proof-prunes removed the dead-end style of attractive but unaffordable F2–F6 boards.

## Next recommendation

Promote the new autonomous incumbent (192) and return to whole-game optimisation with this admissible stock-empty bound in place. Do not copy the canonical route.
