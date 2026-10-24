"""Controlled counterfactual continuations. v0.106.

Policies filter or order actions for an existing search kernel.
They do not change engine legality or MobilityWare cost.
"""

from .experiment import CounterfactualError, run_experiments
from .policies import POLICIES
from .report import render_report

SCHEMA_VERSION = "spider-counterfactual-continuations-0.106"

__all__ = [
    "SCHEMA_VERSION",
    "CounterfactualError",
    "POLICIES",
    "render_report",
    "run_experiments",
]
