"""
Pacote core.harness
Execution Harness Determinístico para Mini-Índice B3 (WIN) — Profit Pro.
Responsável por:
  - Validação da regra Premium & Discount (Dealing Range 50%)
  - Máquina de estados FVG / iFVG
  - Filtro Anti-HFT e Tape Reading institucional
  - Modos Copiloto (Assistido) e Full-Auto (Totalmente Automatizado)
"""

from core.harness.contracts import (
    ExecutionMode,
    ZoneType,
    ZoneStatus,
    PrimarySetup,
    TradingDirection,
    PriceRegime,
    DealingRange,
    FVGZone,
    Niveis60mContract,
    RuntimeStateContract,
    TradeSignal
)

__all__ = [
    "ExecutionMode",
    "ZoneType",
    "ZoneStatus",
    "PrimarySetup",
    "TradingDirection",
    "PriceRegime",
    "DealingRange",
    "FVGZone",
    "Niveis60mContract",
    "RuntimeStateContract",
    "TradeSignal"
]
