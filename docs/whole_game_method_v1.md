# Whole-game method v1

Frozen at `5fcd197b4f04c3b754a6bcd6c0b158a395f8a472` before any later search change. The machine-readable recipe is `docs/research/method_capture_optimisation/method_v1.json`. The runnable reference remains `search_suit_ordered` in `src/spider/global_search_experiment.py`. This capture does not copy the kernel into a second module.

The historical complete games for deal 4925153 stay where they are. This document records how they were produced. It does not feed their action lists into a cold search.

## Call

```text
search_suit_ordered(
    opening_from_deal("deals/4925153.txt"),
    time_limit_s=1500,
    max_unique=1_000_000,
    rss_abort_mb=3000,
    seed=0,
    mode="cold",
    cost_ceiling=400,
    advice_fn=None,
)
```

`seed` is stored on the result. Successor order does not read it. Advice is off, so `action_order` passed to `run_search` is `None`. `stop_on_first_terminal` is false. A finished game stays in the terminal list and the search continues until the time, unique, or RSS stop.

Cold mode refuses `incumbent_cost`. The paid ceiling is 400. `lower_bound_fn` is `None`, so this cold call does not apply `g + h` pruning. The ceiling still drops a child whose corrected cost is already above 400. Equality with a proof ceiling stays eligible when a later optimise call supplies `admissible_remaining`.

## Lane order

Seven lanes, lower tuple first, round-robin in this order: `cost`, `foundation`, `reveal`, `workspace`, `construction`, `prep`, `epoch`.

| Lane | Key, left to right |
| --- | --- |
| cost | `g` |
| foundation | `-foundations`, `-suit_completion_score`, `face_down`, `stock_rows`, `g` |
| reveal | `face_down`, `-foundations`, `-empty_n`, `g` |
| workspace | `-empty_n`, `face_down`, `-run_compression`, `g` |
| construction | `-same_suit_bonds`, `-longest_run`, `-merge_edges`, `face_down`, `g` |
| prep | `-stock_rows`, `face_down`, `-same_suit_bonds`, `-empty_n`, `g` |
| epoch | `stock_rows`, `-foundations`, `face_down`, `g` |

The foundation key before proximity is `(-foundations, face_down, stock_rows, g)`. Proximity is inserted in second position by `suit_lane_keys`. The other six keys come from `lane_keys` in `src/spider/whole_game_anytime.py`.

`suit_completion_score` is higher when a suit is closer to a removable king-to-ace run. Weights are length 100, king 250, ace 80, join 40, cover base 80 plus 20 per covering card, and penalties 2 exposed, 8 face-up, 20 face-down, 28 stock, 40 absent. The score orders the foundation lane. It is not an admissible remainder and it does not delete a legal move.

## Ties, duplicates, and reopening

Each heap entry is `(lane key..., insertion sequence, node index)`. Equal keys expand in insertion order. The sequence counter increases on every push.

A generated child is skipped when its corrected cost is greater than or equal to the best stored cost of that identity. A strictly cheaper arrival replaces that cost, stores a new node, and is pushed again. An identity already expanded at an equal or lower cost is a stale skip when it is popped.

`min_live_g` is the smallest `g` on a current heap top. `closed_g = min_live_g - 1` is a heap observation at return. It is not a claim that every cheaper state was expanded.

## Identity, storage, and reconstruction

Search identity is `pack_whole_game_identity`. While any stock card remains, that is ordered `pack_state` (`SPK1`): ten columns in physical order, because a later deal row lands left to right. After the stock is empty, identity is `pack_post_stock_symmetry_state` (`SPS1`): each column encoding stays exact and the ten encodings are sorted. Stored bytes for reconstruction are always ordered `pack_state`. Foundations inside a pack are sorted.

Each node keeps its parent index and the action that created it. `reconstruct` walks parents to the root. A prefix continuation, when one is used, replays that prefix from the opening and then appends the reconstructed suffix. Corrected `g` stays absolute from the opening.

## Legal moves and cost

The recipe passes `all_legal_actions`, which returns `enumerate_legal_actions`. That includes Deal when the MobilityWare rules say Deal is legal, including a deal into an empty column. The kernel's own default action function omits Deal. This recipe does not use that default.

Same-suit blocks are the engine's legal moves. Automatic removal of a finished king-to-ace sequence happens inside the apply step and is not written as an action. A tableau step costs 0 or 1. Moving a whole face-up column onto a structurally empty destination costs 0 only when the source column has no face-down cards. `zero_cost_actions` counts those zero-cost actions when they are considered.

A terminal state has eight foundations, an empty stock, and an empty tableau. The retained complete game is the terminal with the smallest `(corrected cost, ordered store)`.

## Three search records

These three facts are separate. The historical optimise-mode string `imported_verified_complete` only means a scalar incumbent was supplied.

| Record | Cold reproduction | Fresh-opening improvement | Route repair |
| --- | --- | --- | --- |
| Root ancestry | fresh opening | fresh opening | a verified prefix of this campaign's own complete route |
| Incumbent source | none | a verified scalar cost | that same complete route |
| Action guidance | none | none | the route's own actions, used only to choose rejoining windows |

A repair result is not a cold reproduction and not a scalar opening search. Only a complete legal game is a new best.

## What is saved

A campaign checkpoint can store configuration, source identity, ancestry, resource counters, the stop reason, and replayable action prefixes. The historical runner keeps up to 12 diversity leaders keyed by `(foundations, stock rows)`, milestone nodes, and a ring of 8 recently admitted nodes that had not been expanded. Each saved branch is replayed from the opening before it is trusted.

The kernel heap is not stored. `exact_frontier_retained` is false. A later process that replays one of those prefixes is a sampled reseed. `restart_inherits_exhaustion` is false. Timeout, RSS, unique cap, and a sampled reseed are not impossibility proofs.

The historical winning cold run checkpointed about every 300 seconds. Lane pop counts for the 164, 162, 160, 158, and ceiling-157 runs are absent from `docs/autonomous_solve_campaign_status.json` and are unknown here.

## Historical evidence on this deal

The cold opening search, ceiling 400, 1500 seconds, unique cap 1,000,000, requested RSS 3000 MB, found a complete game at corrected cost 164 and stopped on the time limit. Unique states reached 699,970, expansions 200,073, generated successors 5,439,427, peak RSS 1,565.078 MB. Deal admissions 80,087, tableau admissions 816,757, zero-cost admissions 119, zero-cost actions considered 872,276, ceiling prunes 0, lower-bound prunes 0. `min_live_g` was 7. That figure does not close costs at or below 6.

Fresh-opening scalar searches then found 162 under ceiling 163 in 1,200 seconds, 160 under ceiling 161 in 900 seconds, and 158 under ceiling 159 in 900 seconds. Each of those three games was validated independently. A further 900-second search with incumbent 158 and ceiling 157 reached 472,757 unique states, 107,356 expansions, 353,044 lower-bound prunes, peak RSS 906.28 MB, and 5 foundations. It did not finish a game. Anchored repair of the 164 route examined 6 windows and stayed at 164. Anchored repair of the 158 route examined 5 windows and stayed at 158. Both returned `NO_IMPROVEMENT` before their time budgets ended, because that optimiser stops the round when the batch does not improve.

The 158 working-tree file is CRLF. Its SHA-256 is `C5F4059E8288A8160449F5ACF2E8F8B3848368A63A1A99FAE8132E0358492CC1`. Git stores the LF form, blob `83430885e4c65b2c986b1cfa2b786914da256cb8`, 1,859 bytes, LF SHA-256 `D1CBE17BEDCA6625DD48223685908EB07C46990A70E0638A57F7E7C4AF19BD21`. The reported 16-hex action hash is `9145868d32e42008`. The file is evidence and is not rewritten to chase a hash.

Capture platform: CPython 3.14.5 on Windows-11-10.0.26200-SP0. Source LF SHA-256 values are in the JSON recipe.
