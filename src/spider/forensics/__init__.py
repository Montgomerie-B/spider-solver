"""Solution forensics v0.105.

Trajectory instrumentation and causal comparison of complete Spider
solutions. This package does not search, does not change MobilityWare
rules, and does not read or write campaign or incumbent state.
"""

from .analyze import SCHEMA_VERSION, ForensicError, analyze_solution, compare_solutions

__all__ = [
    "SCHEMA_VERSION",
    "ForensicError",
    "analyze_solution",
    "compare_solutions",
]
