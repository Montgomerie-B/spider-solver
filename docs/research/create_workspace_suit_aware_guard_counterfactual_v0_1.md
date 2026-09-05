# CREATE_WORKSPACE suit-aware singleton-high guard counterfactual v0.1

**Status:** complete. Diagnostic only. No production or planner changes.

**Start SHA:** `df7e858a3e749b0ff7e7393f2405d1835a140800`

**Branch:** `agent/create-workspace-suit-aware-guard-counterfactual-v0-1`

**Decision: A. SUIT-BLIND GUARD IS THE PRIMARY P BLOCKER**

The previous harvest conclusion *E. SECONDARY TARGETS ONLY* was caused
by `CREATE_WORKSPACE` treating every singleton of `target.high_rank` as
the campaign high, including the off-suit queen of spades on natural R3.

Under a research-only suit-aware guard (G1), production-primary P
(`c 12-11`) accepts `(5, 1, 1)` and the unchanged planner realises the
clubs queen-jack edge through a full workspace lifecycle. Established S
(`c 11-10`) is bitwise-identical. The actual same-suit campaign high
remains protected. Unexpected regression count is 0.

Recommended next step (not taken):

> Bounded production-quality CREATE singleton-high guard correction with
> regression shadow.

Do not make that production change on this branch.

## Guard intent (H1 vs H2)

The production predicate, introduced in `a244206` with the v0.1 planner
and never commented, is rank-only:

```python
if len(col.face_up) == 1 and col.face_up[0].rank == target.high_rank:
    continue
```

Neighbouring campaign-high helpers are all suit-aware:

* `unique_usable_receiver_column` / `_rank_top_copies(state, target.suit, …)`
* `_occupies_unique_receiver` (`dest_top.suit != target.suit`)
* `_useful_card` (`card.suit == target.suit`)
* `_edge_count` / `_find_top`

No test, docstring, or commit message states that every suit copy of
`target.high_rank` is a protected rank-class resource. Harvest’s own
taxonomy named the reject `EXCLUDED_SINGLETON_CAMPAIGN_HIGH` and the
harvest report already noted it was suit-blind.

**H1 — exact campaign-high protection** is the only intent the repository
evidence supports.

**H2 — rank-class protection of every suit copy** is not established.
G1 is the H1 reading of the same predicate.

## Modes

* **G0 CURRENT** — unchanged production `_realise_create`.
* **G1 SUIT_AWARE_SINGLETON_HIGH** — yield every G0 candidate, then
  additionally consider sources that G0 skipped solely because they are
  a singleton of `target.high_rank` whose **suit is not** `target.suit`.
  Remaining CREATE predicates are the production ones.

Monkeypatch is restored in `finally`. Focused tests assert the production
function object is identical after every counterfactual call.

## Natural R3

Reconstructed from the stored five-move path
`(5,7,1), (2,7,1), (5,7,1), (5,7,1), (5,4,1)`.

| check | value |
| --- | --- |
| digest | `1c3d3ec77bf164ad` |
| face-down | 39 |
| fully revealed | 1 (col 5 = Qs) |
| empties | 0 |
| legal first-empty | `(5,1,1)` Qs → col 1 |
| resulting digest | `19e9e5d1326854ed` |
| resulting empties | 1 |

## Synthetic controls

| id | setup | G0 | G1 |
| --- | --- | --- | --- |
| C1 | Qc singleton, target `c 12-11` | reject singleton-high | reject singleton-high |
| C2 | Qs singleton, target `c 12-11` | reject singleton-high | **accept** |
| C3 | 5s singleton | agree (both accept) | agree |
| C4 unique receiver | Js onto unique Qc | `OCCUPIES_UNIQUE_RECEIVER` | same |
| C4 reservation | Jh onto reserved Qc | `RECEIVER_MISUSE_OR_OCCUPY` | same |
| C4 not one run | mixed overlay | `NOT_ONE_MOVABLE_RUN` | same |
| C4 face-down | buried singleton | `SOURCE_HAS_FACE_DOWN` | same |
| C4 idle empty | empty already present | `HAS_IDLE_EMPTY` | same |
| C4 join | partial packet | `NOT_ONE_MOVABLE_RUN` | same |

G1 does not emit the same-suit campaign high.

## Natural P CREATE

Target P = clubs 12-11, move `(5,1,1)`.

| | G0 | G1 |
| --- | --- | --- |
| emit | no | **yes** |
| predicate | `EXCLUDED_SINGLETON_CAMPAIGN_HIGH` | — |
| end digest | `19e9e5d1326854ed` | same replay |
| empties | 1 | 1 |
| cost | 1 | 1 |
| joins | 0/0 | 0/0 |

Qs is rank 12 but not clubs Q.

## Full P planner

| | P-G0 | P-G1 |
| --- | --- | --- |
| result | `NO_BOUNDED_PLAN` | **`REALISED_CAMPAIGN_PROGRESS`** |
| operators | — | CREATE, INVEST, REALISE, RECOVER |
| actions | — | `[5,1,1], [9,5,1], [9,4,1], [5,6,1]` |
| cost | 0 | 4 |
| visited | 2 | 10 |
| edge | 0 → 0 | 0 → 1 |
| unresolved | 0 | 0 |
| replay | — | OK |
| terminal | `1c3d3ec77bf164ad` | `554c339c714d204c` |

Classification: **`P_FULL_WORKSPACE_SUCCESS`**.

### P-G1 operator trace

```
state 1c3d3ec77bf164ad  empties=0
  CREATE_WORKSPACE      [5,1,1]  empties=1  obligations=0
  INVEST_WORKSPACE      [9,5,1]  empties=0  workspace live
  REALISE_CAMPAIGN_EDGE [9,4,1]  empties=0  workspace live  edge 0→1
  RECOVER_WORKSPACE     [5,6,1]  empties=1  workspace cleared
→ REALISED_CAMPAIGN_PROGRESS  terminal 554c339c714d204c
```

CREATE manufactures the first empty. INVEST borrows it. REALISE joins
the clubs Q-J edge. RECOVER restores the empty. No debt remains.

## S invariance

Established G0 trace reproduced under both modes:

`CREATE [5,1,1] → INVEST [9,5,1] → RECOVER [5,6,1]`
→ `PREPAID_DEPENDENCY` terminal `db8ff65b9ffe468d`.

G0 and G1 are equal on result, operators, actions, and terminal.

## All-R2 P/S matrix

69 scheduler-native P/S pairs across the four reconstructed harvest
states. **One** behaviour difference:

| digest | class | target | G0 | G1 |
| --- | --- | --- | --- | --- |
| `1c3d3e…` R3 | P | `c 12-11` | `NO_BOUNDED_PLAN` | `REALISED_CAMPAIGN_PROGRESS` |

All other pairs unchanged, including every S target and the three later
R2 states (their Qs singleton has no legal nonempty dest under either
guard).

## Synthetic / resource regression

W1, W1 negatives, W2, W2 negatives, W3, P1–P3, rework, reservation,
reservation-unthreatened: **all UNCHANGED**.

Unexpected delta count: **0**.

Expected delta count: **1** (natural R3 P only).

## Guard incidence

Existing natural datasets, no deeper production search.

* 25-expansion natural-shadow recapture (58 states, established stop):
  **0** singleton-high guard hits (CREATE still dies at face-down, as in
  the coverage anatomy).
* Four harvest R2 states: **5** current-guard hits.

| | n |
| --- | --- |
| current guard hits | 5 |
| true same-suit campaign-high | 1 (`edb1…` S `s 12-11`, Qs) |
| off-suit same-rank | 4 |
| off-suit where G1 emits a new CREATE | **1** (natural R3 P) |

The other three off-suit hits fail `NO_LEGAL_NONEMPTY_DEST` under both
modes. The R3 case is the only genuine new CREATE candidate. The guard
is not systematically suppressing a large hidden population in these
artefacts; it is suppressing the one first-empty that production P
needed.

## Why A, not B–E

* Not B: P-G1 is not CREATE-only; it realises the campaign edge and
  recovers workspace.
* Not C: P is no longer inferior to S once CREATE is suit-aware. S still
  prepays; P now realises.
* Not D: no repository evidence for rank-class protection; C1 shows the
  actual clubs queen remains protected under G1.
* Not E: R3 reconstructed; replay OK; no obligation leak; no source
  mutation; monkeypatch restored; production files untouched.

Priority starvation of the R3 parent (never popped; trimmed ~210) remains
a separate accessibility fact. This experiment isolates resource
capability only.

## Pytest

Focused tests cover C1–C4, natural P G0/G1 CREATE, established S G0
trace, restoration, and production source invariance.

`1883 passed, 37 xfailed in 1343.18s`

0 unexpected failures. Node-78 was not modified.
