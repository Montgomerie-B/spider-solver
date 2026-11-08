# Reference solutions

## Deal 4925153 verified games

Play Lab's "Load canonical solution or partial route" dialog opens this folder. These copies are the same bytes as the research files.

| File | Source |
|------|--------|
| `4925153_canonical.moves` | Canonical 172 |
| `4925153_autonomous_185.moves` | Autonomous 185 |
| `4925153_cold_164.moves` | Cold campaign 164 |
| `4925153_cold_162.moves` | Cold campaign 162 |
| `4925153_cold_160.moves` | Cold campaign 160 |
| `4925153_cold_158.moves` | Cold campaign 158 |
| `4925153_cold_feasibility_164.moves` | Method-capture feasibility 164 |
| `4925153_assisted_157.moves` | Suffix-assisted 157 |
| `4925153_assisted_156.moves` | Pre-120 assisted 156 |
| `4925153_assisted_151.moves` through `4925153_assisted_140.moves` | Pre-120 assisted 151–140 |

## Deal 4925153

| File | Description |
|------|-------------|
| `../solitaire solution.docx` | Narrative 172-move line (human prose) |
| `4925153_canonical.moves` | **Master verified line** — through deal #2 + 11 post-deal-2 moves (99 moves, 2 deals) |
| `4925153_through_jd.moves` | User line through JD on col 9 (13 moves) |
| `4925153_live.moves` | Moves 14–51 + **stock deal #1** (38 moves + `deal`) |
| `4925153_after_deal1.moves` | Checkpoint — merged 51 moves + deal #1 only |
| `4925153_checkpoint_deal1.moves` | Live + deal #1 + strict Word through JD→col4 |
| `4925153_validated.moves` | Strict Word export (stops at `10C col 1 → col 5`) |
| `4925153_reference.moves` | **Best replayable solution** — through deal #2 (88 moves + 2 deals) |

### Move list format

One action per line:

```
move <src_col> <dst_col> <k>
deal
```

Columns are **1-based** (1–10), left to right (MobilityWare UI).

Replay:

```
python tools/replay_moves_file.py --moves solutions/4925153_canonical.moves
```

Regression target: full win — canonical MW cost **163** (169 tableau lines + 5 deals; zero-cost moves reduce MW below line count). Optimizer record target: **119** MW moves. Run `python tools/optimize_deal.py` or `run_optimizer.bat`; best output: `4925153_best.moves`.