"""
feeds/base_feed.py
Interface canônica de alimentação de dados de mercado (Market Data Feed).
Desacopla a fonte de dados do motor determinístico de análise.
Inclui máquina de estados de conexão formal e validação de frescor de dados.
"""

from abc import ABC, abstractmethod
from typing import Callable, Optional, Dict, Any
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

from core.models import Candle, Trade, BookSnapshot


class FeedConnectionStatus(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    RECONNECTING = "RECONNECTING"
    VALIDATING = "VALIDATING"


@dataclass
class FeedHealth:
    connected: bool
    source_name: str
    status: FeedConnectionStatus = FeedConnectionStatus.DISCONNECTED
    last_event_time: Optional[datetime] = None
    last_received_time: Optional[datetime] = None
    latency_ms: float = 0.0
    is_flow_available: bool = False
    is_book_available: bool = False
    error_message: str = ""

    def __post_init__(self):
        if self.connected and self.status == FeedConnectionStatus.DISCONNECTED:
            self.status = FeedConnectionStatus.CONNECTED

    @property
    def is_healthy(self) -> bool:
        if not self.connected:
            return False
        if self.status in (
            FeedConnectionStatus.DISCONNECTED,
            FeedConnectionStatus.DEGRADED,
            FeedConnectionStatus.STALE,
            FeedConnectionStatus.RECONNECTING,
            FeedConnectionStatus.VALIDATING
        ):
            return False
        if self.latency_ms > 5000.0:  # Latência > 5 segundos indica feed travado
            return False
        return True


class BaseMarketFeed(ABC):
    """Classe base abstrata para todos os feeds de mercado."""

    def __init__(self, source_name: str):
        self.source_name = source_name
        self.on_candle_callback: Optional[Callable[[Candle], None]] = None
        self.on_trade_callback: Optional[Callable[[Trade], None]] = None
        self.on_book_callback: Optional[Callable[[BookSnapshot], None]] = None
        self.health = FeedHealth(
            connected=False,
            source_name=source_name,
            status=FeedConnectionStatus.DISCONNECTED
        )

    def set_callbacks(
        self,
        on_candle: Optional[Callable[[Candle], None]] = None,
        on_trade: Optional[Callable[[Trade], None]] = None,
        on_book: Optional[Callable[[BookSnapshot], None]] = None
    ):
        self.on_candle_callback = on_candle
        self.on_trade_callback = on_trade
        self.on_book_callback = on_book

    @abstractmethod
    def connect(self) -> bool:
        pass

    @abstractmethod
    def disconnect(self):
        pass

    @abstractmethod
    def subscribe_symbol(self, symbol: str) -> bool:
        pass

    def get_health(self) -> FeedHealth:
        return self.health
