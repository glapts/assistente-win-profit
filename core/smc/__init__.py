"""
core/smc/__init__.py
Módulos avançados de Smart Money Concepts (SMC/ICT) para WIN B3.
"""

from core.smc.dynamic_range_manager import (
    DynamicRangeManager,
    DynamicRangeState,
    DynamicRangeEvent,
    M5CandleBuilder
)
from core.smc.scalper_glaucio import (
    ScalperGlaucio,
    ScalperSignal,
    CandleM1,
    FVGZone
)

__all__ = [
    "DynamicRangeManager",
    "DynamicRangeState",
    "DynamicRangeEvent",
    "M5CandleBuilder",
    "ScalperGlaucio",
    "ScalperSignal",
    "CandleM1",
    "FVGZone"
]
