"""Integrated human-strategy controller for Spider Solitaire.

The package is an experimental player. It does not write the production
incumbent registry, campaign data, or the canonical solution files.
"""

from .controller import solve
from .profiles import PROFILES, resolve_profile
from .registry import PRINCIPLES, coverage_matrix

SCHEMA_VERSION = "spider-human-strategy-0.122"

__all__ = [
    "SCHEMA_VERSION",
    "PROFILES",
    "PRINCIPLES",
    "coverage_matrix",
    "resolve_profile",
    "solve",
]
