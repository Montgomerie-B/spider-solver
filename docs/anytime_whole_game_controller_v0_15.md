# Anytime whole-game controller v0.15

## Scope and verdict

v0.15 adds proof-neutral completion-harvest selection and bounded cash-out
continuity above the v0.14 source-completion ledger. It does not add a search
engine, global scheduler, frontier capacity, expansion, tactical resource,
closure width, tier, persistence, benchmark preference, route seed or proof
rule. Unrestricted Deal remains on.

The verified verdict is **PARTIAL**. Natural Gate Q corrected the v0.14
post-admission failure: four exact-TT-admitted completion states qualified,
were reserved one at a time, received exactly one fresh strategic expansion
each and immediately spent their special status. All four expansions produced
fresh same-suit construction; one also produced a matching dependency-chain
advance. No representative expired before expansion and none was admitted but
later unselected. The mechanism therefore works naturally, not only in a
fixture.

Gate Q did not remove foundation #2, and the authorized untouched Gate R did
not reach foundation #1. Per the v0.15 architecture gate, further local
controller micro-sprints should stop. The next architectural phase, if
explicitly authorized, should be a whole-deal backward/forward structural
scheduler. That scheduler is not implemented here.

## v0.14 blocker and post-TT selection map

v0.14 made source completions typed, replay-valid and durable through exact-TT
admission and lineage. Its natural Gate O produced five controller admissions
but expanded none of those states. The missing transition was therefore after
admission:

`successor -> exact TT -> admitted lazy node -> ordinary global queue -> no completion-specific next expansion`

The old same-target continuation reservation applied only at oversized
frontier trimming and did not guarantee a completion state one fresh analysis.
v0.15 inserts the bounded policy only after exact admission:

`successor -> exact TT -> completion qualification -> one in-capacity representative -> one normal fresh Stage-1 expansion -> ordinary descendants`

The strongest live qualifying representative receives queue coverage. It can
occupy at most one existing frontier slot. All other families continue through
the established portfolio and trim logic.

## Completion cash-out model

`CompletionCashOutOpportunity` binds one exact admitted state to one or more
newly durable `SourceCompletionEvent` objects and their semantic target
fingerprints. It is planning metadata, not a second Spider state. The model
also provides:

- `CompletionCashOutStatus` and `CompletionCashOutDisposition` for admission,
  qualification, reservation, expansion, spend, supersession, invalidation,
  expiry and post-admission selection loss;
- `CompletionStructuralMetrics` for transparent representative ordering;
- `CompletionHarvestAssessment` for fresh before/after structural evidence;
- `CompletionCashOutTrace` for bounded per-candidate audit rows;
- qualification, ranking, harvest-combination and cheaper-exact-state source
  satisfaction reconstruction helpers.

A state qualifies only after independent replay and successful exact-TT
admission, and only when fresh exact facts preserve a strong exposed,
actionable, consumed, integrated or source-chain completion. The event must be
new and must not already have spent its one cash-out. An ordinary card move or
same-suit join cannot qualify without the typed completion fact. A
multi-primitive successor may recontextualize its event onto the admitted
exact state only after fresh reconciliation proves that the requirement still
holds; a contradiction invalidates it.

Several completion events in one exact state form one opportunity, one
representative and one expansion. Equal geometry is deduplicated. A lower-`g`
identical exact state continues to win; proof-neutral current source
satisfaction is reconstructed there where possible rather than retaining the
expensive arrival.

## One representative and one expansion

Across the live strategic frontier, v0.15 ranks qualifying opportunities and
marks at most one `RESERVED`. The representative is protected only inside the
configured frontier capacity; it never changes the 256 benchmark width. A
stress fixture confirms that it displaces one ordinary slot when required.
Normal alternate-campaign, construction, workspace/reveal, purposeful Deal and
raw-fallback families remain represented by existing mechanisms.

When popped, the representative undergoes the controller's existing fresh
analysis and consumes one ordinary strategic expansion. It receives no extra
tactical grant, node allowance, analysis pass, terminal tier or continuation
credit. Its event IDs are marked spent before descendants are admitted. The
representative then becomes `SPENT`; descendants have ordinary priority and
economics. A persistent event cannot reserve again.

This is a new-fact evaluation opportunity, not protection for prior cost. A
high-investment branch with no downstream return receives no renewed status,
and a cheaper unrelated branch can win immediately after the one expansion.

## Fresh downstream harvest

The completion-state structure is compared with replay-valid fresh
descendants. The original exposure is not counted a second time. The explicit
classes are:

- `SOURCE_CONSUMED` and `SOURCE_INTEGRATED`;
- `SAME_SUIT_CONSTRUCTION`;
- `DEPENDENCY_CHAIN_ADVANCE`;
- `RECEIVER_UNLOCK` and `WORKSPACE_UNLOCK`;
- `NEW_REVEAL`;
- `TERMINAL_QUALIFICATION` and `FOUNDATION_REMOVAL`;
- `EPOCH_PREPARATION` and `OTHER_NAMED_STRUCTURAL_HARVEST`;
- `NO_DOWNSTREAM_HARVEST`.

Source consumption and integration are determined by freshly reconciling each
completed physical source against the cash-out start and descendant state.
When present, the ledger advances to `SOURCE_CONSUMED` or `SOURCE_INTEGRATED`.
Dependency advance is attributed only when the closure targets the completed
dependency, or a source-chain milestone has the same semantic target. Thus
unrelated closure progress cannot masquerade as completion harvest.

`SOURCE_BURIED` remains satisfied after exposure while the distinct
`SOURCE_EXPOSED_BUT_BLOCKED` predicate is evaluated normally. Clearing that
blocker, creating a receiver or integrating the source can be fresh harvest;
mere persistence of exposure is not.

A Deal is never harvest. Telemetry distinguishes a Deal descendant admitted
after cash-out from one actually selected for expansion.

## Structural economics and permanent moves

Qualifying representatives are ordered from exposed facts rather than a giant
completion bonus. The comparison includes corrected `g`, foundations,
permanent same-suit joins, mixed boundaries, source completion/actionability/
consumption/integration, dependency reduction, receiver and workspace effects,
face-down/reveal change, stock timing, rehandling debt, terminal readiness,
substantial milestone progress and legal mobility.

This is heuristic ordering only. The existing permanent-move rule remains:
a cheap stable same-suit join dominates a comparable mixed-suit park. A mixed
park still requires a bounded compensating benefit, an explicit exit route and
rehandling debt. Completion history supplies no proof dominance.

## Capability gates and unseen deals

All generic capability Gates A-L pass. They cover one expansion after
admission, no double cash-out, lower-`g` exact duplicate safety, natural source
consumption/integration machinery, follow-on blockers, explicit no-harvest,
higher-`g` completion versus a retained conservative branch, multiple events
in one representative, Deal preservation, terminal/foundation harvest,
frontier-width displacement and the sunk-cost negative case.

The focused v0.15 file contains 61 test functions and 62 parameterised cases;
v0.15 plus v0.14 passes 134 tests. The requested broader controller and
structural cohort passes 787 tests with the unchanged 37 expected historical
xfails.

Two deterministic unseen four-suit runs retained Unrestricted Deal and legal
replay. Seed 15015 selected one non-Deal action at corrected `g=1`, stock 50,
43 face-down cards, path `6658d75b20350d62`, endpoint
`d1c96332293b0a1f` and structural hash `76d0e2b82ef29ed7`; its short run exposed
seven construction opportunities and two Deal alternatives. Seed 15051
selected one Deal at corrected `g=1`, stock 40, 44 face-down cards, path
`b3ee7be38b53079a`, endpoint `c6d98f481cd1b71b` and structural hash
`915a8a45ac59bc4a`; it exposed three Deal alternatives. Neither short envelope
naturally admitted a completion, so no cash-out was required.

## Natural Gate Q

Gate Q began at the independently replayed machine F1 state at total corrected
`g=21`. Its frozen limits remained 90 seconds, 25 strategic expansions,
300,000 tactical nodes, frontier 256, closure beam 192, persistence three and
unchanged allocator/closure settings.

It reached all 25 expansions in 27.338 seconds. The selected replay-valid
five-action suffix added corrected `g=5`, used no Deal and ended at total
`g=26`, one Spade foundation, stock 30 and 32 face-down cards. Its path hash is
`f176dd9013e3fdb1`, endpoint hash `30496cf7f013e61f`, and structural hash
`31659973bc6dba50`.

The completion/cash-out funnel was:

- 41 source-targeted closure attempts;
- five trace-completed events and five controller-admitted events;
- four exact admitted completion states, including one state with two events;
- four cash-out-qualified states;
- four representatives reserved, expanded and spent;
- zero representatives expired before expansion;
- four ordinary downstream continuations admitted;
- zero source consumptions and zero source integrations;
- zero substantial source-chain milestones and zero terminal qualifications;
- one existing foundation, not F2.

The four candidate rows were:

| Suit/target | Event(s) | Added `g` | Exact state | Competing normal `g` | Fresh harvest |
|---|---|---:|---|---:|---|
| Hearts H#1 | `777b67536e46a012` | 5 | `feb5b0984286999a` | 2 | same-suit construction; matching dependency-chain advance |
| Hearts H#1 | `8b27fad8d42c6b15` | 8 | `a7698668a7adf175` | 2 | same-suit construction |
| Diamonds D#1 | `e649d0dd88173c31` | 15 | `541cd12e0c14baac` | 13 | same-suit construction |
| Diamonds D#1 | `40d82ceed93ff883`, `867d8144b314addc` | 18 | `dd00da8366ecdab3` | 15 | same-suit construction |

All four ended `CASH_OUT_SPENT` and ordinary economics resumed. There were
four `SAME_SUIT_CONSTRUCTION` assessments and one
`DEPENDENCY_CHAIN_ADVANCE`: Hearts had two construction harvests plus the
dependency advance, and Diamonds had two construction harvests. There was no
`NO_DOWNSTREAM_HARVEST`, branch abandonment, source consumption/integration or
terminal path. Four Deal descendants were admitted as ordinary alternatives,
but none was selected after cash-out and the selected Gate Q route used no
Deal.

Selection recorded four admitted, qualified, reserved, expanded and spent
states; zero freshly nonqualifying admissions, expired representatives,
admitted-not-selected states, invalidations or ordinary-slot displacements;
and one exact-duplicate source-completion suppression. Selection scans consumed
0.019 seconds. Exact TT recorded 60 new, three improved and 11 suppressed
arrivals. Proof telemetry recorded zero proof prunes, zero heuristic prunes and
three exact-loop suppressions. The controller consumed 257 tactical nodes and
3.712 tactical seconds from 34,272 nodes and 23.4 seconds granted; closure used
233 nodes and 3.707 seconds, with a 0.363-second maximum call.

The matching dependency advance and the natural correction of v0.14's
admitted-but-unselected class authorized Gate R.

## Untouched Gate R

Gate R started from the true untouched deal with `incumbent=None`, no prefix,
checkpoint, target suit/rank, source or canonical action. Its frozen limits
remained 180 seconds, 50 strategic expansions, 500,000 tactical nodes,
frontier 256, beam 192, persistence three and unchanged allocator/closure
settings.

It reached all 50 expansions in 54.603 seconds. The selected replay-valid route
had corrected `g=11`, 11 actions, one Deal, stock 40, 38 face-down cards and no
foundation. Its path hash is `1af0219baaeca71c`, endpoint hash
`5149eacdafc4635e`, and structural hash `4ed5d1c43e1f383f`.

The explored stock timeline retained exact legal Deal fallbacks and purposeful
Deal candidates for advancing to epochs two, four and five. The selected route
advanced one row only. The run made 74 source-targeted attempts and one Hearts
trace-completed source successor, but, as in v0.14 Gate P, that state did not
survive exact strategic admission. Therefore Gate R had zero admitted,
qualified, reserved, expanded or spent completion states and no cash-out
harvest by suit. It completed two substantial interval milestones, no
substantial source-chain milestone, no terminal qualification, F1 or F2.

Gate R used 414 closure/tactical nodes and 5.507 closure seconds, with a
0.373-second maximum call. Total measured tactical consumption was 465 nodes
and 5.516 seconds from 59,504 nodes and 40.9 seconds granted. Exact TT recorded
129 new arrivals, zero improvements and 21 suppressions; proof, heuristic and
exact-loop suppression counts were all zero.

F2 repeatability, optional F3 and optional whole-game runs were not authorized.
No complete or verified <=171 solution was produced.

## Proof safety and genericity

Exact TT remains `exact structural Spider state -> lowest corrected g`.
Completion events, representative status, cash-out spend, harvest history and
selection traces do not enter canonical identity. Exact lower-cost dominance
continues to reject equal/higher-cost duplicates. The only admissible bound
remains mandatory Deals plus the established paid-reveal lower bound. All
completion economics and lifecycle debt are ordering/coverage evidence only.

The allocator tier fingerprint, 12,000-node/four-second per-expansion ceilings,
dependency-closure limits, beam 192, frontier 256, persistence three and global
Gate ceilings are unchanged. No unused resource crosses a state. Production
policy contains no benchmark deal, suit/rank/column, route/hash, external 119
target, known checkpoint or prospective canonical action.

The canonical corrected-172 solution remains replay-valid at 174 explicit
commands, 169 tableau commands, five Deals, F8, path hash
`77d169da2538ba8c` and final-state hash `4e9861540eac570cb`. The machine F1
anchor remains corrected `g=21`, 21 actions, two Deals, Spades, stock 30, 33
face-down cards, path `924bfd20deac96af`, endpoint `fbea39bb5e2a3a47` and
structural hash `b7522950ea41ad9a`. The independent F1 remains corrected
`g=23`, 23 actions, two Deals, stock 30 and 32 face-down cards.

The definitive complete repository suite passed **1,378 ordinary tests, 37
expected historical xfails and the single inherited warning in 1,099.00
seconds**. No xfail was weakened.

## Precise blocker and architecture decision

The local completion execution mechanism is no longer the blocker. A natural
admitted completion now receives one bounded fresh expansion and produces
genuine structural harvest. Its privilege ends correctly. Yet ordinary local
continuity still does not coordinate enough full-deal structure to reach F2;
the untouched run does not even retain its one source-completion successor
through exact strategic admission and remains at F0.

The architecture decision is **B**: local execution machinery is sufficient
for this phase. Stop local-controller micro-sprints. If the user authorizes a
next task, specify and implement a generic whole-deal backward/forward
structural scheduler that derives earliest completion epochs, pre-Deal
structure, known-stock reception/free joins, high-leverage sources,
duplicate-card assignment, useful partial runs and pre-positioning targets,
then sends bounded targets to the existing forward tactical realisers. Do not
start that scheduler, v0.16 or another local continuity subsystem from this
task.
