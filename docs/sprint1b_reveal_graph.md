# Sprint 1B — Perfect-Information Reveal / Unlock Graph

**Status:** Complete  
**Branch:** `dev/sprint1b-reveal-graph`  
**Baseline:** Sprint 1A `dev/sprint1a-foundation-feasibility` @ `6c788af`  
**Date:** 2026-08-12  

## Objective

Give the strategic planner a generic view of **what lies beneath every face-down card** and **what pursuing a reveal chain unlocks**, without pretending that reveals produce information value.

Reveals have **zero information value** for a perfect-information solver. Value is structural only.

## Implemented API

Module: `src/spider/planner/reveal_graph.py`

| Type | Role |
|------|------|
| `RevealCardFact` | One face-down card + dependency depth |
| `RevealChain` | Ordered hidden sequence per column |
| `RevealPrefix` | Stopping depth 1..N with tags |
| `FoundationRelevanceFact` | Suit/rank demand (no fixed copy IDs) |
| `StructuralTag` | Deterministic structural observations |
| `RevealOpportunity` | Prefix + simple heuristic assessment |
| `RevealGraphAnalysis` | Full state analysis |

Entry points:

- `build_reveal_chain(column, state)`
- `minimum_reveals_to_expose(chain, reveal_order)`
- `analyze_reveal_graph(state, cards=..., foundation_analysis=...)`
- `format_reveal_report(...)` / `format_chain` / `format_opportunity`

Diagnostic: `python -m spider.planner.diagnostics.reveal_graph_report`

## Hard facts vs heuristics

### HARD

- Ordered excavation sequence per column (`face_down[-1]` first).
- `minimum_reveals_to_expose` = flip count lower bound (not move count).
- Face-up material above the hidden section.
- Exhaustion of face-down section.
- New hidden frontier after a prefix.
- King presence as a **neutral** structural tag.
- Same-suit extend/receive *possibility* against currently face-up fragments.
- Foundation **suit/rank demand** via Sprint 1A availability (interchangeable physical copies).

### HEURISTIC only

- `heuristic_interest` / `heuristic_label` / `heuristic_reasons`
- Density of foundation-relevant and structural tags along a chain
- Preference language (“high downstream density”) — **not** proof pruning

### Lower-bound contract

Documented in `REVEAL_LOWER_BOUND_USAGE`:

- Safe as objective-specific flip lower bound for “expose T”.
- Safe inside `max(...)` with compatible bounds.
- **Not** automatically additive with manoeuvring/foundation move bounds.

## Tests

- `tests/test_reveal_graph.py` — 10 focused tests
- Sprint 1A tests remain green
- Full suite: see commit message / CI local run

## Benchmark highlights (deal 4925153 opening)

- All 10 columns have known hidden chains (4–5 cards).
- Top opportunities often favour **full-chain excavation** where several foundation-relevant cards and fragment extensions sit on one dependency spine (e.g. col 6: `3s -> 2s -> Qc -> Qs`).
- Immediate one-card reveals can score lower than multi-reveal prefixes that unlock deeper high-demand material — the intended perfect-information behaviour.
- Kings tagged neutrally; no generic King penalty.

## Human opening trace (canonical, to Deal 1)

The diagnostic ranks each human reveal’s **column** among columns by best interest *before* the move.

Findings (32 human reveals before Deal 1):

- Only **2/32** human reveals were in the analyser’s **#1** column at that state; **9/32** in the top 3; **23/32** outside the top 3.
- Opening: human starts on col 3 (`Qs`…), rank #2; soon digs col 6 (initially high interest) then continues to lower residual interest while col 5 (`4c -> 3h -> Ks -> 6d`) often remains the structural favourite.
- Later alignment improves: cmds 43–48 excavate cols 1 and 5 at ranks #1–#3.
- Perfect-information disagreement example: after the opening, the analyser repeatedly prefers fully excavating **col 5** (and similar dense spines) while the human spends many reveals on cols 8–10 residual tails.
- This is **diagnostic disagreement**, not a claim that the 172 route is wrong on move cost — tactical space/cost is Sprint 1C+.

## Limitations deferred to Sprint 1C

- Exact / estimated **move cost** to clear face-up blockers.
- Empty-column **lifecycle / recoverability**.
- Whether a fully face-up column is cheap to empty.
- Stock-reception interaction with reveal plans.
- Refined scoring (current heuristic is intentionally simple and can saturate when every rank has foundation demand).

## Files

- `src/spider/planner/reveal_graph.py`
- `src/spider/planner/diagnostics/reveal_graph_report.py`
- `tests/test_reveal_graph.py`
- `docs/sprint1b_reveal_graph.md` (this file)
