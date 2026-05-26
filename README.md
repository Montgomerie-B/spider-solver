# Spider Solver

Human-like Spider Solitaire solver (MobilityWare rules) focused on **minimum moves** to solve known deals.

## Goal
Build a solver that reasons like a strong human: prioritizes permanent same-suit builds, minimizes move debt, and leverages full visibility of the deal.

## Current Deal
See `deals/4925153.txt` and `deals/Tableau.png`

## Structure
- `spider/` - Core engine
- `deals/` - Test deals
- `solvers/` - Different solver implementations

## Setup
```bash
pip install -r requirements.txt
```