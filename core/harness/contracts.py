"""
core/harness/contracts.py
Contratos de dados e esquemas Pydantic v2 do Execution Harness.
Define o modelo de comunicação entre Agentes de IA (Assíncronos) e o Harness (Determinístico).
Inclui validadores de integridade de domínio, TTL, invariantes de LONG/SHORT e controle de versão.
"""

from enum import Enum
from typing import List, Optional
from datetime import datetime
import math
from pydantic import BaseModel, Field, model_validator


class ExecutionMode(str, Enum):
    """
    Modo operacional do Harness:
      COPILOT   : Emite alertas visuais, sonoros e estruturados no SuperDOM/Console para ação humana.
      FULL_AUTO : Ponto de integração para despacho automatizado (consultivo / stub seguro).
    """
    COPILOT = "COPILOT"
    FULL_AUTO = "FULL_AUTO"


class ZoneType(str, Enum):
    BEARISH = "BEARISH"
    BULLISH = "BULLISH"
    BREAKER = "BREAKER"
    SWEEP_SSL = "SWEEP_SSL"
    SWEEP_BSL = "SWEEP_BSL"
    IFVG_BULLISH = "IFVG_BULLISH"
    IFVG_BEARISH = "IFVG_BEARISH"


class ZoneStatus(str, Enum):
    UNMITIGATED = "UNMITIGATED"
    TESTING_CONTINUATION = "TESTING_CONTINUATION"
    INVERTED_PENDING_RETEST = "INVERTED_PENDING_RETEST"
    TRIGGER_IFVG = "TRIGGER_IFVG"
    CANDIDATE = "CANDIDATE"
    VALIDATED = "VALIDATED"
    EMITTING = "EMITTING"
    EMITTED = "EMITTED"
    EXHAUSTED = "EXHAUSTED"
    INVALIDATED = "INVALIDATED"


class PrimarySetup(str, Enum):
    CONTINUATION_SELL = "CONTINUATION_SELL"
    CONTINUATION_BUY = "CONTINUATION_BUY"
    CONTINUATION_BUY_IF_CONFIRMED = "CONTINUATION_BUY_IF_CONFIRMED"
    INVERSION_SELL = "INVERSION_SELL"
    INVERSION_BUY = "INVERSION_BUY"
    LIQUIDITY_SWEEP_BUY = "LIQUIDITY_SWEEP_BUY"
    LIQUIDITY_SWEEP_SELL = "LIQUIDITY_SWEEP_SELL"


class TradingDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    BOTH = "BOTH"
    LONG_ONLY = "LONG_ONLY"
    SHORT_ONLY = "SHORT_ONLY"
    NONE = "NONE"


class PriceRegime(str, Enum):
    PREMIUM = "PREMIUM"         # Caro (> 50% Equilibrium) -> Vendas favorecidas
    DISCOUNT = "DISCOUNT"       # Barato (< 50% Equilibrium) -> Compras favorecidas
    EQUILIBRIUM = "EQUILIBRIUM" # Em cima do 50% (+/- margem)


class DealingRange(BaseModel):
    """Dealing Range Macro (normalmente extraído do gráfico de 60m)."""
    topo_estrutural: float = Field(..., description="Máxima macro da pernada")
    fundo_estrutural: float = Field(..., description="Mínima macro da pernada")
    equilibrium_50: float = Field(..., description="Ponto médio (50%) = (Topo + Fundo)/2")

    @model_validator(mode="after")
    def validate_equilibrium(self):
        if self.topo_estrutural <= self.fundo_estrutural:
            raise ValueError("topo_estrutural deve ser estritamente maior que fundo_estrutural")
        calculated = round((self.topo_estrutural + self.fundo_estrutural) / 2.0, 2)
        if abs(self.equilibrium_50 - calculated) > 5.0:
            self.equilibrium_50 = calculated
        return self


class FVGZone(BaseModel):
    """Representação de uma zona FVG ou Liquidity Sweep de 60 minutos."""
    id: str
    tipo_original: ZoneType
    top: float
    ce_50: float
    bottom: float
    setup_primario: PrimarySetup
    stop_sugerido_pts: float = 250.0
    alvo_sugerido_pts: float = 400.0
    status: ZoneStatus = ZoneStatus.UNMITIGATED
    inversion_level: Optional[float] = None
    notes: Optional[str] = None

    @model_validator(mode="after")
    def validate_bounds(self):
        if self.top < self.bottom:
            self.top, self.bottom = self.bottom, self.top
        if not (self.bottom <= self.ce_50 <= self.top):
            self.ce_50 = round((self.top + self.bottom) / 2.0, 2)
        return self


class Niveis60mContract(BaseModel):
    """Contrato JSON gerado pelo Gemini / Analista de 60m."""
    versao_contrato: str = "2.0"
    ativo: str = "WINZ26"
    data_referencia: str
    dealing_range: DealingRange
    zonas_fvg: List[FVGZone] = Field(default_factory=list, alias="zonas_fvg")


class CircuitBreakerState(BaseModel):
    """Estado do Circuit Breaker diário."""
    daily_stops_count: int = 0
    max_daily_stops: int = 2
    lockout_active: bool = False

    @model_validator(mode="after")
    def validate_counts(self):
        if self.daily_stops_count < 0:
            raise ValueError("daily_stops_count não pode ser negativo")
        if self.max_daily_stops <= 0:
            raise ValueError("max_daily_stops deve ser maior que zero")
        return self


class MacroRegimeState(BaseModel):
    """Parecer do Agente Macro & Global."""
    status: str = "RISK_ON"           # RISK_ON, RISK_OFF, NEUTRAL, EVENT_LOCKOUT
    sp500_bias: str = "BULLISH"       # BULLISH, BEARISH, NEUTRAL
    di_curve_bias: str = "STABLE"     # STABLE, STRESSED, FALLING
    dxy_bias: str = "BEARISH"         # BULLISH, BEARISH, NEUTRAL
    event_lockout: bool = False       # Trava de Payroll, FOMC, CPI
    lockout_reason: Optional[str] = None


class BasketRegimeState(BaseModel):
    """Parecer do Agente de Cesta & Arbitragem ("O Espelho")."""
    synthetic_ibov_alignment: str = "ALIGNED" # ALIGNED, DIVERGENT
    vale3_petr4_status: str = "POSITIVE"      # POSITIVE, NEGATIVE, NEUTRAL


class RuntimeStateContract(BaseModel):
    """Contrato consolidado pelo Orquestrador e injetado no Harness."""
    timestamp: str
    state_version: int = 1
    ttl_seconds: float = 120.0
    data_quality: str = "INTEGRITY_OK"
    execution_mode: ExecutionMode = ExecutionMode.COPILOT
    trading_enabled: bool = True
    allowed_direction: TradingDirection = TradingDirection.BOTH
    min_fvg_timeframe: int = 15
    risk_mode: str = "NORMAL"
    confidence_score: float = 0.85
    circuit_breaker: CircuitBreakerState = Field(default_factory=CircuitBreakerState)
    macro_regime: MacroRegimeState = Field(default_factory=MacroRegimeState)
    basket_regime: BasketRegimeState = Field(default_factory=BasketRegimeState)

    @model_validator(mode="after")
    def validate_confidence_range(self):
        if not (0.0 <= self.confidence_score <= 1.0):
            raise ValueError(f"confidence_score deve estar entre 0.0 e 1.0 (recebido: {self.confidence_score})")
        if self.ttl_seconds <= 0:
            raise ValueError("ttl_seconds deve ser positivo")
        return self

    def is_expired(self, current_time: Optional[datetime] = None) -> bool:
        """Verifica se o runtime_state ultrapassou o TTL seguro."""
        try:
            # Tentar parse ISO
            ts = datetime.fromisoformat(self.timestamp)
        except Exception:
            return True

        ref = current_time or datetime.now()
        # Se um tiver timezone e o outro não, normaliza
        if ts.tzinfo is not None and ref.tzinfo is None:
            ts = ts.replace(tzinfo=None)
        elif ts.tzinfo is None and ref.tzinfo is not None:
            ref = ref.replace(tzinfo=None)

        return (ref - ts).total_seconds() > self.ttl_seconds


class TradeSignal(BaseModel):
    """Payload de sinal gerado pelo Harness para Copiloto ou Execução."""
    id: str
    timestamp: str
    ativo: str
    direction: TradingDirection
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_points: float = 250.0
    gain_points: float = 400.0
    rr_ratio: float = 1.60
    zone_id: str
    setup_name: str
    regime: PriceRegime
    confidence_score: float
    execution_mode: ExecutionMode
    institutional_volume_detected: int
    explanation: str

    @model_validator(mode="after")
    def validate_signal_invariants(self):
        # 1. Direção deve ser unívoca para ordens individuais
        if self.direction not in (TradingDirection.LONG, TradingDirection.SHORT):
            raise ValueError(f"Direção inválida para TradeSignal: {self.direction}. Deve ser LONG ou SHORT.")

        # 2. Preços positivos e finitos
        for name, val in [("entry_price", self.entry_price), ("stop_loss", self.stop_loss), ("take_profit", self.take_profit)]:
            if not math.isfinite(val) or val <= 0:
                raise ValueError(f"{name} deve ser finito e positivo (recebido: {val})")

        # 3. Risco e Ganho estritamente positivos
        if self.risk_points <= 0:
            raise ValueError(f"risk_points deve ser maior que zero (recebido: {self.risk_points})")
        if self.gain_points <= 0:
            raise ValueError(f"gain_points deve ser maior que zero (recebido: {self.gain_points})")

        # 4. Invariantes de LONG e SHORT
        if self.direction == TradingDirection.LONG:
            if not (self.stop_loss < self.entry_price < self.take_profit):
                raise ValueError(
                    f"Invariante LONG violada: stop ({self.stop_loss}) < entrada ({self.entry_price}) < alvo ({self.take_profit})"
                )
        elif self.direction == TradingDirection.SHORT:
            if not (self.take_profit < self.entry_price < self.stop_loss):
                raise ValueError(
                    f"Invariante SHORT violada: alvo ({self.take_profit}) < entrada ({self.entry_price}) < stop ({self.stop_loss})"
                )

        # 5. Score de confiança
        if not (0.0 <= self.confidence_score <= 1.0):
            raise ValueError(f"confidence_score fora do intervalo [0.0, 1.0]: {self.confidence_score}")

        return self
