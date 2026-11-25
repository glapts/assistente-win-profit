"""
core/models.py
Estruturas de dados canônicas para candles multi-timeframe, fluxo e SMC.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any


class AggressorSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    UNDEFINED = "UNDEFINED"


class MarketRegime(str, Enum):
    ALTA = "ALTA"
    BAIXA = "BAIXA"
    CONSOLIDACAO = "CONSOLIDAÇÃO"
    TRANSICAO = "TRANSIÇÃO"


class SetupStatus(str, Enum):
    AGUARDANDO = "AGUARDANDO"
    CONFIRMADO = "CONFIRMADO"
    INVALIDADO = "INVALIDADO"
    EXPIRADO = "EXPIRADO"
    BLOQUEADO = "BLOQUEADO"


class Direction(str, Enum):
    COMPRA = "COMPRA"
    VENDA = "VENDA"


@dataclass
class Candle:
    timeframe: int         # 1, 2, 5, 10, 15, 30, 60
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0          # Volume em contratos ou financeiro
    trades_count: int = 0
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    is_closed: bool = False
    
    @property
    def delta(self) -> float:
        return self.buy_volume - self.sell_volume

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low


@dataclass
class Trade:
    trade_id: str
    timestamp: datetime
    price: float
    quantity: int
    aggressor: AggressorSide
    broker_buyer: Optional[str] = None
    broker_seller: Optional[str] = None
    is_estimated_aggressor: bool = False


@dataclass
class BookLevel:
    price: float
    quantity: int
    order_count: int = 1


@dataclass
class BookSnapshot:
    timestamp: datetime
    bids: List[BookLevel] = field(default_factory=list)
    asks: List[BookLevel] = field(default_factory=list)

    @property
    def best_bid(self) -> Optional[float]:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> Optional[float]:
        return self.asks[0].price if self.asks else None

    @property
    def spread(self) -> Optional[float]:
        if self.best_bid is not None and self.best_ask is not None:
            return self.best_ask - self.best_bid
        return None


@dataclass
class BookEvent:
    timestamp: datetime
    event_type: str  # "ADD", "MODIFY", "DELETE", "TRADE"
    side: str        # "BID", "ASK"
    price: float
    quantity: int
    order_id: Optional[str] = None


@dataclass
class Pivot:
    pivot_type: str     # "HIGH" ou "LOW"
    price: float
    bar_index: int
    timestamp: datetime
    confirmed_bar_index: int  # Índice do candle onde foi confirmado (sem look-ahead bias)


@dataclass
class FairValueGap:
    direction: str      # "BULLISH" ou "BEARISH"
    top: float
    bottom: float
    start_bar: int
    end_bar: int
    timestamp: datetime
    timeframe: int
    is_mitigated: bool = False
    is_invalidated: bool = False

    @property
    def size(self) -> float:
        return self.top - self.bottom


@dataclass
class StructuralEvent:
    event_type: str     # "BOS", "CHOCH", "SWEEP", "FALSE_BREAKOUT"
    direction: str      # "BULLISH" ou "BEARISH"
    timeframe: int
    level_broken: float
    timestamp: datetime
    bar_index: int
    details: str = ""


@dataclass
class SignalSetup:
    timestamp: datetime
    setup_name: str
    direction: Direction
    symbol: str
    status: SetupStatus
    
    # Níveis de Preço
    entry_price: float
    stop_price: float
    stop_points: float
    target_price: float
    target_points: float
    risk_reward: float
    
    # Contexto e Estrutura
    timeframe_trigger: int
    in_trend_direction: bool
    sweep_level: Optional[float] = None
    sweep_time: Optional[datetime] = None
    fvg_zone: Optional[str] = None
    structure_event: Optional[str] = None
    
    # Evidências e Limitações
    book_evidence: Dict[str, Any] = field(default_factory=dict)
    flow_evidence: Dict[str, Any] = field(default_factory=dict)
    obstacles: List[str] = field(default_factory=list)
    facts_observed: List[str] = field(default_factory=list)
    interpretations: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)
    validity_deadline: Optional[datetime] = None
    invalidation_criteria: str = ""
