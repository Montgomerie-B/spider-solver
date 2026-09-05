# Continuation-credit fidelity v0.1

**Status:** complete. No production behaviour change, no v0.9, no resource
planner run.

**Start SHA:** `debabe17359c2f986252220aae8ed8c113c352e6`

**Branch:** `agent/continuation-credit-fidelity-v0-1`

**Decision: B. PREVIOUS CONTINUATION FOREST WAS CREDIT-INCOMPLETE**

Previous Decision D must be qualified, not treated as settled. The later-phase
forest omitted every same-tableau credit-widened frontier node. Those nodes
exist, sit live at credit 1 after 25 CLEAN expansions, and in reconstructed
generation they are not equivalent to a CLEAN restart.

This does **not** prove that existing credit-4 fallback already solves
first-empty: credit 4 was never expanded or even queued in this 25-expansion
run.

Recommended next step (not taken here):

> Rerun the bounded later-phase continuation forest with faithful
> `(state, credit/context)` continuation identity.

## Gate A — static audit

Production widening (after each expansion, `anytime_controller.py`):

```
if credit < max_credit_level (4):
    next_credit = credit + 1
    if (canonical_state_key, next_credit) not yet expanded:
        widened = replace(node, node_id=uid, credit_level=next_credit)
        heapq.heappush(frontier, (_node_priority(widened), uid, widened))
```

- Does **not** call `_record_transition`.
- Does **not** call TT `admit`.
- Tableau state, `g`, actions, incoming edge, analysis and schedule are
  unchanged. Only `node_id` and `credit_level` change.
- Expansion identity is already `(canonical_state_key, credit_level)`.

`RAW_TABLEAU_MOVE` is enabled only at credit 4
(`raw_fallback_enabled` iff `RAW_LEGAL_FALLBACK`).

Previous harness `ProductionCapture` recorded `_record_transition` children
and `generate_strategic_successors` keyed by digest only. Frontier selection
iterated `capture.retained`. Restart was `solve_anytime(state)` which always
roots at CLEAN.

**Verdict: `PREVIOUS_FOREST_DROPPED_CREDIT`.**

## Gate B — observed 25-expansion opening run

Same envelope as the later-phase forest generation 0. Passive heap
observation of `StrategicSearchNode` triples only.

Stop: `strategic expansion limit`, 25 expansions. 83 pushes, 25 pops, 58
live frontier nodes.

Continuation identity `(digest, credit)` is sufficient to name the omitted
widened nodes. Exact-credit *expansion* replay at credit > 0 could not be
checked against a production expansion because none occurred.

## Gate C — credit distribution

Expanded: **25 at credit 0**. Zero at 1–4.

Terminal live frontier: **33 at credit 0, 25 at credit 1**. Zero at 2–4.

Widened same-state nodes: pushed 25, popped 0, expanded 0, live 25.

Tableau states observed at multiple credits: **25** (every expanded CLEAN
state has a live credit-1 clone).

## Gate D — previous forest vs actual frontier

Generation-1 roots (digest-only, restarted CLEAN):

| digest | actual credits | bucket |
| --- | --- | --- |
| `80765376ee888c25` | 0 | C1 |
| `caf822a7a13a0821` | 0 | C1 |
| `eb3e568b616e4b60` | 0 | C1 |
| `982d62a58d6006d6` | 0 | C1 |

Those four were CLEAN transition children, so C1. They were not the omitted
widened identities.

**C1 = 4, C2 = 0, C3 (gen-1 roots) = 0, C3 (omitted widened pushes) = 25.**

C2 and C3 are not collapsed. The material miss is C3: 25 live credit-1
nodes were ineligible for continuation selection because they never appear
as `_record_transition` children.

Later generations were grown from CLEAN `solve_anytime` restarts, so the
credit ladder was never walked after generation 0.

## Gate E — exact-credit successor fidelity

No production node with credit > 0 was expanded, so there is no original
non-CLEAN expansion to replay. **n = 0.**

CLEAN reconstruction of an observed credit-0 expansion matches (focused
test). Additional node context beyond `(state, credit, g)` is **not
demonstrated as required**; it is also **not demonstrated as sufficient for
credit > 0 expansions**, because those expansions did not happen.

## Gate G — CLEAN vs credit 1 on live widened nodes

Eight live credit-1 nodes reconstructed at credit 1 and at CLEAN:

4/8 differ. Differences are extra `ECONOMIC_PROJECT` successors at credit 1.
No `RAW_TABLEAU_MOVE` at credit 1 (as expected: raw fallback is credit 4).

Omitting those nodes therefore changes successor coverage, even though it
does not by itself produce reveals or empties.

## Gate F — credit-4 raw fallback

Credit-4 nodes captured: **0**. Raw moves: **0**. Reveals: **0**. Empties:
**0**. Buried-depth reductions: **0**. Overlap with lower-credit families:
n/A.

v0.8's credit widening *would* eventually enable raw fallback, but this
25-expansion envelope never pops a node past credit 1.

## Why B, not A/C/D/E

- **Not A:** 25 non-CLEAN live identities were omitted; reconstructed
  credit-1 coverage is not CLEAN-equivalent.
- **Not C:** credit 4 never appears; no reveal/empty raw path was generated.
- **Not D:** no failed exact-credit expansion replay at credit > 0; CLEAN
  reconstruction matches.
- **Not E:** two-expansion A/B observation is behaviourally inert.

Previous Decision D (production never reaches resource geometry in that
forest) remains a fact about a **CLEAN-only continuation forest**, not about
production's actual `(state, credit)` frontier.

## Pytest

`1854 passed, 37 xfailed in 1261.30s`

0 unexpected failures. Node-78 was not modified.
