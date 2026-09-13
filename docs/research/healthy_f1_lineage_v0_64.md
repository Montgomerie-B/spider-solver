# healthy_f1_lineage_v0_64

Verdict: `HEALTHY_F1_LINEAGE_LATE_COST_FAILURE`

The v0.63 F1 at **g=71 / fd=10 / rows=3 / Spades** was reconstructed from
the same policy (abort at 226.4 s, matching the original 226.4 s
milestone), independently replayed, and continued for 900 s.

The lineage **was not lost**. Every later epoch’s roots still carried
`v063_f1_g71`. It reached post-stock and F4 at g=197 — then had no
budget left. No complete route below 198. No new solution file.

Base: `62bfe99f3168076e721e2681e45b6bd38f42d045`
Branch: `agent/healthy-f1-lineage-continuation-v0-64`

---

## Verified F1 prefix

Replayed from untouched deal 4925153.

| | value |
|---|---|
| g | **71** |
| stock rows | **3** |
| face-down | **10** |
| F | **1** (spades) |
| deals | 2 |
| explicit actions | 74 |
| legal tableau | 10 |
| empty | 0 |
| n_ready after F1 | 1 (hearts) |
| hearts cover / blockers / gap | 8 / 40 / 10 |
| interference boundaries / layers | 15 / 15 |
| solved | no |

Digest and whole-game identity recorded in the JSON. Replay g, fd,
rows, and F match the v0.63 milestone. The prefix was not edited.

After this F1 the only ready suit is Hearts, and it is still awkward
(cover 8, 40 blockers). Operational viability did not claim Hearts was
a cheap F2.

---

## v0.63 ancestry audit

`ANCESTRY_NOT_RECORDED`

The published v0.63 JSON slimmed `full_actions` and `ordered_digest`
off foundation notes, so later-epoch descendants cannot be proven from
that artefact. A kernel bug ( `KernelResult.nodes` was empty during
`on_progress`) also meant live path attach could not have worked even
if the fields had been kept.

This experiment:

1. assigned `result.nodes = nodes` during search (telemetry/path only);
2. stored `full_actions` on foundation notes;
3. replayed the v0.63 policy from the opening with the same 900 s
   allocation and aborted at the matching F1 (226.4 s).

Lineage tags are scheduler metadata only. Packed SPK1/SPS1 and
cheapest-g TT are unchanged.

---

## Continuation architecture

Frozen v0.63 policy: COST / REVEAL / CONSTRUCTION / OPERATIONAL_READINESS
/ HORIZON / ECONOMY. No DURABILITY. No Deal-reception shaping.

Root: the verified F1 at absolute g=71, `lineage=["v063_f1_g71"]`.
Ceiling **197**. Remaining Deal bound. Width 256. Opening for replay
is still the untouched deal, so concatenated paths stay whole-game.

---

## Envelope

Continuation: 900 s · 800k unique · 2.5 GiB · ceiling 197.

Stopped on time. Unique 194,707. Expanded 35,705 (39.7 exp/s).

Reconstruction used 226 s of the same policy and is not counted in
those unique totals.

---

## Epoch descendant survival

All input roots after the F1 start are descendants (single-family
search). Counts:

| rows | input / lineage | unique | exp | min g | max g | max F | min fd | budget left |
|---|---|---|---|---|---|---|---|---|
| 3 | 1 / 1 | 66,976 | 18,902 | 71 | 91 | 1 | 9 | 126 |
| 2 | 132 / 132 | 50,967 | 6,748 | 72 | 140 | 1 | 2 | 125 |
| 1 | 191 / 191 | 31,733 | 6,319 | 73 | 151 | **2** | 2 | 124 |
| 0 | 205 / 205 | 45,031 | 3,736 | 74 | 197 | **4** | 1 | 123 |

No portfolio extinction. HORIZON expansions = 0 (a suit is always
ready after F1). cheap_fd and reveal stayed populated.

---

## Absolute g / foundation map (true F1 descendants only)

```
F1 root:     71   rows=3  fd=10  F=1 s
after SD3:   72   rows=2  F=1
after SD4:   73   rows=1  F=1
F2:         130   rows=1  fd=2   F=2 s,d     ΔF1=+59
after SD5:   74   cheapest deal-now; converting paths are later
F3:         193   rows=0  fd=2   F=3 h,s,d   ΔF1=+122
F4:         197   rows=0  fd=1   F=4         ΔF1=+126  ceiling
F5–F8 / solved:  not under 197
```

F2 at 130 / fd=2 is **not** the old global v0.63 F2 at 183. This F2
is a descendant of g=71.

---

## Comparison with autonomous 198 incumbent (control only)

| epoch | F1 lineage | incumbent 198 |
|---|---|---|
| rows=3 | g=71 F=1 fd=10 | g=59 F=0 fd=10 |
| rows=2 | min g=72 F=1 fd≥2 | g=74 F=0 fd=10 |
| rows=1 | min g=73; F2=130 fd=2 | g=85 F=0 fd=9 |
| rows=0 | min g=74 F=1; F3=193 | g=131 F=0 fd=3, then 67 MW to F8 |

The lineage **enters post-stock 57 MW cheaper** than the incumbent
(74 vs 131) and already has F=1. It still cannot convert: the
states that actually add F2–F4 sit at 130 then 193–197.

Incumbent remaining after SD5 is 67 MW to finish eight foundations.
This lineage’s converting F2 already costs 59 MW from F1, then 63 more
to F3.

---

## Post-stock

Strongest converting descendants: F=4, g=197, fd=1, cover=2. Ceiling
exhausted. Cheapest post-stock g=74 did not raise F. min fd=1, never a
fully excavated convert-and-finish.

Late-game issue: **high conversion cost after a decent F2**, not
lineage loss, not missing F1 excavation (fd=2 at F2). Search coverage
at rows=0 was 45k unique / 3.7k expanded — finite, but F4 at 197 with
no slack is a cost problem first.

---

## Optional canonical note (after search)

Canonical F1 is g=90 fd=8. This F1 is cheaper (71) and 2 fd worse.
After F1 only Hearts is ready and still awkward (blockers 40). Canonical
F2 (diamonds, g=139, fd=3) is in the same g-band as this lineage’s F2
(130, fd=2). The machine then pays 63 MW to F3; canonical finishes six
more foundations in 14 MW after SD5. Policy was not changed from that
observation.

---

## Interpretation

The healthy F1 is a real autonomous prefix, not a reporting ghost. The
v0.63 scheduler did not need a new heuristic to keep it: when search
starts there, descendants survive every Deal.

What fails is **cash-out after F2**. Remaining budget from g=130 to 197
is 67 MW — the same size as the incumbent’s entire post-SD5 solve —
and this lineage spends it on two more foundations without finishing.

---

## Next recommendation

Post-stock assembly / cost-to-go on this F1 lineage (F2 at 130, fd=2,
rows=1, then the 63 MW F3 cliff). Do not copy 172. Do not widen
runtime. Lineage preservation is not the bottleneck here.

---

## Files

New: `src/spider/healthy_f1.py`, research script, tests, docs
JSON/MD/progress.

Changed: `search_kernel.py` (live `result.nodes` during `on_progress`),
`whole_game_epoch_scheduler.py` (optional `initial_roots`, `abort_when`,
foundation `full_actions`, lineage telemetry),
`operational_policy.py` (pass-through only).
