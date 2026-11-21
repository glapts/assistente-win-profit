"""
core/candle_aggregator.py
Agregador determinístico multi-timeframe.
Recebe candles de 1m e sincroniza o fechamento dos 7 períodos:
1m, 2m, 5m, 10m, 15m, 30m e 60m, com alinhamento exato aos minutos da sessão da B3.
"""

from typing import Dict, List, Optional, Callable
from datetime import datetime

from core.models import Candle


class MultiTimeframeCandleAggregator:
    """
    Constrói e mantém os 7 tempos gráficos simultâneos alinhados ao relógio do pregão.
    """

    SUPPORTED_TIMEFRAMES = [1, 2, 5, 10, 15, 30, 60, 240]

    def __init__(self, on_candle_closed: Callable[[Candle], None]):
        self.on_candle_closed = on_candle_closed
        
        # Buffers de construção intrabar por timeframe
        self.building_candles: Dict[int, Optional[Candle]] = {
            tf: None for tf in self.SUPPORTED_TIMEFRAMES if tf > 1
        }

    def process_1m_candle(self, c1m: Candle):
        """Processa um candle fechado de 1m e atualiza os timeframes superiores."""
        # 1m já está fechado, despachar imediatamente
        self.on_candle_closed(c1m)

        close_dt = c1m.close_time
        close_minute = close_dt.minute

        for tf in [2, 5, 10, 15, 30, 60, 240]:
            current = self.building_candles[tf]
            
            if current is None:
                # Iniciar nova barra
                self.building_candles[tf] = Candle(
                    timeframe=tf,
                    open_time=c1m.open_time,
                    close_time=c1m.close_time,
                    open=c1m.open,
                    high=c1m.high,
                    low=c1m.low,
                    close=c1m.close,
                    volume=c1m.volume,
                    trades_count=c1m.trades_count,
                    buy_volume=c1m.buy_volume,
                    sell_volume=c1m.sell_volume,
                    is_closed=False
                )
            else:
                # Atualizar barra em formação
                current.high = max(current.high, c1m.high)
                current.low = min(current.low, c1m.low)
                current.close = c1m.close
                current.close_time = c1m.close_time
                current.volume += c1m.volume
                current.trades_count += c1m.trades_count
                current.buy_volume += c1m.buy_volume
                current.sell_volume += c1m.sell_volume

            # Checar se a barra fechou no alinhamento da hora/minuto
            # Ex: 5m fecha quando close_minute % 5 == 0
            # 60m fecha quando close_minute == 0
            # 240m fecha a cada 4h (13:00, 17:00 ou fim de sessão 18:00)
            is_boundary = False
            if tf == 60:
                is_boundary = (close_minute == 0)
            elif tf == 240:
                is_boundary = (close_minute == 0 and (close_dt.hour in [13, 17, 18] or (close_dt.hour - 9) % 4 == 0))
            else:
                is_boundary = (close_minute % tf == 0)

            if is_boundary:
                closed_bar = self.building_candles[tf]
                closed_bar.is_closed = True
                self.on_candle_closed(closed_bar)
                self.building_candles[tf] = None
