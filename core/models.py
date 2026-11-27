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
    def timestamp(self) -> datetime:
        return self.close_time

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
    partial_target_price: Optional[float] = None
    partial_target_points: Optional[float] = None
    
    # Evidências e Limitações
    book_evidence: Dict[str, Any] = field(default_factory=dict)
    flow_evidence: Dict[str, Any] = field(default_factory=dict)
    obstacles: List[str] = field(default_factory=list)
    facts_observed: List[str] = field(default_factory=list)
    interpretations: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)
    validity_deadline: Optional[datetime] = None
    invalidation_criteria: str = ""
    score_smc: int = 75
    macro_status: Optional[str] = None
    macro_reason: Optional[str] = None


# =====================================================================
# MODELOS AVANÇADOS SMC / ICT INSTITUCIONAIS
# =====================================================================

@dataclass
class BreakerBlock:
    """
    Representa um Breaker Block institucional formado após a captura de liquidez
    e quebra estrutural contrária (BOS/CHoCH).
    """
    breaker_type: str  # "BULLISH" ou "BEARISH"
    top: float
    bottom: float
    origin_candle_index: int
    sweep_level: float
    breakout_level: float
    timestamp: datetime
    timeframe: int
    is_mitigated: bool = False
    mitigation_time: Optional[datetime] = None

    @property
    def size(self) -> float:
        return self.top - self.bottom


@dataclass
class InversionFVG:
    """
    iFVG (Inversion Fair Value Gap): FVG que teve seu corpo completamente violado e
    fechado do outro lado, invertendo sua polaridade institucional.
    Bullish violado -> Resistência; Bearish violado -> Suporte.
    """
    original_direction: str  # "BULLISH" ou "BEARISH"
    current_role: str        # "RESISTANCE" ou "SUPPORT"
    top: float
    bottom: float
    timeframe: int
    inversion_time: datetime
    inversion_candle_index: int
    is_retested: bool = False
    retest_count: int = 0
    is_invalidated: bool = False

    @property
    def size(self) -> float:
        return self.top - self.bottom


@dataclass
class LiquidityPool:
    """
    Equal Highs (EQH - BSL) ou Equal Lows (EQL - SSL).
    Atua como ímã de atração de liquidez e gatilho de reversão pós-sweep.
    """
    pool_type: str  # "EQH" (Buy-Side Liquidity) ou "EQL" (Sell-Side Liquidity)
    price_level: float
    touches: List[float] = field(default_factory=list)
    timestamps: List[datetime] = field(default_factory=list)
    tolerance_pts: float = 10.0
    is_swept: bool = False
    sweep_time: Optional[datetime] = None
    timeframe: int = 5


@dataclass
class SMTDivergenceEvent:
    """
    Divergência SMT (Smart Money Technique) entre ativos inversamente/diretamente correlacionados (WIN vs WDO).
    """
    timestamp: datetime
    divergence_type: str  # "BULLISH" ou "BEARISH"
    win_extreme_type: str  # "LOWER_LOW" ou "HIGHER_HIGH"
    win_price: float
    win_previous_price: float
    wdo_extreme_type: str  # "LOWER_HIGH" ou "HIGHER_LOW"
    wdo_price: float
    wdo_previous_price: float
    delta_seconds: float
    details: str = ""


class KillzoneType(str, Enum):
    MORNING_PRIME = "MORNING_PRIME"         # 09:30 - 11:30
    LUNCH_CHOP = "LUNCH_CHOP"               # 12:00 - 13:30 (Bloqueio de continuidade)
    AFTERNOON_PRIME = "AFTERNOON_PRIME"     # 14:30 - 16:30
    JUDAS_WINDOW = "JUDAS_WINDOW"           # 09:15 - 10:00 (Apenas reversão de manipulação)
    OFF_HOURS = "OFF_HOURS"                 # Fora das janelas principais


@dataclass
class KillzoneSession:
    """
    Decisão determinística da janela horária ativa para permissão/bloqueio de trades.
    """
    current_time: datetime
    active_killzone: KillzoneType
    allows_continuation: bool
    allows_reversal: bool
    reason: str = ""


class AMDPhase(str, Enum):
    ACCUMULATION = "ACCUMULATION"     # 09:00 - 09:15
    MANIPULATION = "MANIPULATION"     # 09:15 - 10:00 (Judas Swing)
    DISTRIBUTION = "DISTRIBUTION"     # 10:00 - 12:30
    OFF_CYCLE = "OFF_CYCLE"


@dataclass
class AMDState:
    """
    Estado do ciclo Power of 3 (Acumulação, Manipulação, Distribuição).
    """
    phase: AMDPhase
    initial_range_high: Optional[float] = None
    initial_range_low: Optional[float] = None
    judas_sweep_high: bool = False
    judas_sweep_low: bool = False
    allowed_trade_direction: Optional[Direction] = None
    details: str = ""


@dataclass
class UnicornSetupCandidate:
    """
    Confluência geométrica estrita do ICT Unicorn Model:
    Breaker Block + Fair Value Gap (FVG) sobrepostos.
    """
    breaker: BreakerBlock
    fvg: FairValueGap
    direction: Direction
    overlap_top: float
    overlap_bottom: float
    overlap_ratio: float
    timeframe: int
    timestamp: datetime

    @property
    def overlap_size(self) -> float:
        return self.overlap_top - self.overlap_bottom


@dataclass
class SMCConfluenceScore:
    """
    Resultado consolidado da avaliação dos 6 pilares de SMC / ICT.
    """
    total_score: float  # 0.0 a 100.0
    is_institutional_grade: bool
    is_vetoed: bool
    veto_reasons: List[str] = field(default_factory=list)
    confirmations: List[str] = field(default_factory=list)
    active_killzone: str = ""
    amd_phase: str = ""
    unicorn_detected: bool = False
    smt_divergence_detected: bool = False
    ifvg_active: bool = False
    liquidity_pool_magnet: Optional[str] = None
