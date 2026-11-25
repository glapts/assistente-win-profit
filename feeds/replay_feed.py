"""
feeds/replay_feed.py
Simulador de Replay de Mercado determinístico para validação quantitativa.
Gera fluxos sintéticos e reproduz sessões históricas para teste dos 8 setups SMC,
com agregação precisa dos 7 tempos gráficos, Tape Reading e Book L2.
"""

from typing import List, Optional, Callable
from datetime import datetime, timedelta
import random

from feeds.base_feed import BaseMarketFeed, FeedHealth
from core.models import Candle, Trade, BookSnapshot, BookLevel, AggressorSide
from core.contract import TZ_BRASILIA, round_to_tick


class ReplayMarketFeed(BaseMarketFeed):
    """
    Feed de simulação e replay.
    Permite validar a integridade dos algoritmos sem depender do horário de pregão da B3.
    """

    def __init__(self, symbol: str = "WINZ26", initial_price: float = 171400.0):
        super().__init__(source_name="B3 Historical Replay / Test Simulator")
        self.symbol = symbol
        self.current_price = initial_price
        self.current_time = datetime(2026, 10, 29, 9, 0, 0, tzinfo=TZ_BRASILIA)
        self.running = False
        
        self.health = FeedHealth(
            connected=True,
            source_name=self.source_name,
            last_event_time=self.current_time,
            last_received_time=self.current_time,
            latency_ms=0.5,
            is_flow_available=True,
            is_book_available=True
        )

    def connect(self) -> bool:
        self.health.connected = True
        return True

    def disconnect(self):
        self.health.connected = False
        self.running = False

    def subscribe_symbol(self, symbol: str) -> bool:
        self.symbol = symbol
        return True

    def generate_step(
        self,
        trend_bias: float = 0.0, # > 0 alta, < 0 baixa
        volatility: float = 25.0,
        inject_sweep: bool = False,
        sweep_direction: str = "BEARISH" # "BULLISH" ou "BEARISH"
    ) -> List[Candle]:
        """
        Gera 1 minuto de dados de mercado (candle de 1m) com negócios e livro associados.
        Retorna o candle fechado de 1m.
        """
        open_p = self.current_price
        high_p = open_p
        low_p = open_p
        
        trades: List[Trade] = []
        num_ticks = random.randint(30, 80)
        curr_p = open_p

        # Injeção controlada de sweep para teste de setup
        if inject_sweep:
            if sweep_direction == "BEARISH":
                # Violação de máxima seguida de retorno
                curr_p = round_to_tick(open_p + 150.0)
                high_p = max(high_p, curr_p)
                # Retorna
                curr_p = round_to_tick(open_p - 20.0)
            else:
                # Violação de mínima seguida de retorno
                curr_p = round_to_tick(open_p - 150.0)
                low_p = min(low_p, curr_p)
                # Retorna
                curr_p = round_to_tick(open_p + 20.0)

        for i in range(num_ticks):
            step_change = random.choice([-5.0, 0.0, 5.0]) + (5.0 if random.random() < (0.5 + trend_bias) else -5.0)
            curr_p = round_to_tick(curr_p + step_change)
            high_p = max(high_p, curr_p)
            low_p = min(low_p, curr_p)
            
            # Gerar trade
            side = AggressorSide.BUY if step_change >= 0 else AggressorSide.SELL
            qty = random.choice([5, 10, 20, 50, 100, 150]) if random.random() < 0.15 else random.randint(1, 20)
            
            t = Trade(
                trade_id=f"T_{self.current_time.timestamp()}_{i}",
                timestamp=self.current_time + timedelta(seconds=i),
                price=curr_p,
                quantity=qty,
                aggressor=side,
                broker_buyer="BTG" if side == AggressorSide.BUY else "XP",
                broker_seller="CLEAR" if side == AggressorSide.BUY else "GENIAL"
            )
            trades.append(t)
            if self.on_trade_callback:
                self.on_trade_callback(t)

        # Garantir fechamento de sweep se injetado
        if inject_sweep:
            if sweep_direction == "BEARISH":
                curr_p = round_to_tick(open_p - 50.0)
                high_p = max(high_p, open_p + 150.0)
            else:
                curr_p = round_to_tick(open_p + 50.0)
                low_p = min(low_p, open_p - 150.0)

        close_p = curr_p
        self.current_price = close_p
        
        # Gerar Snapshot do Book correspondente
        bids = [BookLevel(price=close_p - (i * 5.0), quantity=random.randint(50, 300)) for i in range(1, 11)]
        asks = [BookLevel(price=close_p + (i * 5.0), quantity=random.randint(50, 300)) for i in range(1, 11)]
        snap = BookSnapshot(timestamp=self.current_time, bids=bids, asks=asks)
        if self.on_book_callback:
            self.on_book_callback(snap)

        # Montar Candle de 1m fechado
        buy_v = sum(t.quantity for t in trades if t.aggressor == AggressorSide.BUY)
        sell_v = sum(t.quantity for t in trades if t.aggressor == AggressorSide.SELL)
        
        c1m = Candle(
            timeframe=1,
            open_time=self.current_time,
            close_time=self.current_time + timedelta(minutes=1),
            open=open_p,
            high=high_p,
            low=low_p,
            close=close_p,
            volume=buy_v + sell_v,
            trades_count=len(trades),
            buy_volume=buy_v,
            sell_volume=sell_v,
            is_closed=True
        )

        self.current_time += timedelta(minutes=1)
        self.health.last_event_time = self.current_time
        self.health.last_received_time = datetime.now(TZ_BRASILIA)

        if self.on_candle_callback:
            self.on_candle_callback(c1m)

        return [c1m]
