"""
Factor Regulator Module.

Provides:
- FactorRegulator: Factor duplication and complexity checking
- FactorConsistencyChecker: Semantic consistency between hypothesis, description, expression
- FactorQualityGate: Integrated quality gate
"""

from __future__ import annotations

from typing import Any


__all__ = [
    "FactorRegulator",
    "SubtreeBlacklist",
    "FactorConsistencyChecker",
    "ConsistencyCheckResult",
    "ComplexityChecker",
    "RedundancyChecker",
    "FactorQualityGate",
    "CONSISTENCY_CHECKER_AVAILABLE",
]


def __getattr__(name: str) -> Any:
    global CONSISTENCY_CHECKER_AVAILABLE

    if name == "CONSISTENCY_CHECKER_AVAILABLE":
        try:
            import quantaalpha.factors.regulator.consistency_checker  # noqa: F401
        except ImportError:
            CONSISTENCY_CHECKER_AVAILABLE = False
            return False
        CONSISTENCY_CHECKER_AVAILABLE = True
        return True

    if name == "FactorRegulator":
        from quantaalpha.factors.regulator.factor_regulator import FactorRegulator

        return FactorRegulator
    if name == "SubtreeBlacklist":
        from quantaalpha.factors.regulator.subtree_blacklist import SubtreeBlacklist

        return SubtreeBlacklist

    if name in {
        "FactorConsistencyChecker",
        "ConsistencyCheckResult",
        "ComplexityChecker",
        "RedundancyChecker",
        "FactorQualityGate",
    }:
        try:
            from quantaalpha.factors.regulator.consistency_checker import (
                ComplexityChecker,
                ConsistencyCheckResult,
                FactorConsistencyChecker,
                FactorQualityGate,
                RedundancyChecker,
            )
        except ImportError:
            CONSISTENCY_CHECKER_AVAILABLE = False
            return None

        CONSISTENCY_CHECKER_AVAILABLE = True
        mapping = {
            "FactorConsistencyChecker": FactorConsistencyChecker,
            "ConsistencyCheckResult": ConsistencyCheckResult,
            "ComplexityChecker": ComplexityChecker,
            "RedundancyChecker": RedundancyChecker,
            "FactorQualityGate": FactorQualityGate,
        }
        return mapping[name]

    raise AttributeError(name)
