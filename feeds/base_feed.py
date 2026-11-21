"""
feeds/base_feed.py
Interface canônica de alimentação de dados de mercado (Market Data Feed).
Desacopla a fonte de dados do motor determinístico de análise.
"""

from abc import ABC, abstractmethod
from typing import Callable, Optional, Dict, Any
from datetime import datetime
from dataclasses import dataclass

from core.models import Candle, Trade, BookSnapshot


@dataclass
class FeedHealth:
    connected: bool
    source_name: str
    last_event_time: Optional[datetime] = None
    last_received_time: Optional[datetime] = None
    latency_ms: float = 0.0
    is_flow_available: bool = False
    is_book_available: bool = False
    error_message: str = ""

    @property
    def is_healthy(self) -> bool:
        if not self.connected:
            return False
        if self.latency_ms > 10000.0:  # Latência > 10 segundos indica feed travado
            return False
        return True


class BaseMarketFeed(ABC):
    """Classe base abstrata para todos os feeds de mercado."""

    def __init__(self, source_name: str):
        self.source_name = source_name
        self.on_candle_callback: Optional[Callable[[Candle], None]] = None
        self.on_trade_callback: Optional[Callable[[Trade], None]] = None
        self.on_book_callback: Optional[Callable[[BookSnapshot], None]] = None
        self.health = FeedHealth(connected=False, source_name=source_name)

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
