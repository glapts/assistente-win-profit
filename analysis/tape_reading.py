"""
analysis/tape_reading.py
Módulo de análise de Times & Trades (Fluxo de Ordens e Agressão).
Métricas determinísticas de agressão, delta, absorção e continuidade.
"""

from typing import List, Dict, Optional, Tuple, Deque
from collections import deque
from datetime import datetime, timedelta
import numpy as np

from core.models import Trade, AggressorSide


class TapeReadingAnalyzer:
    """
    Processa o fluxo de negócios tick-a-tick.
    Calcula delta, agressões relevantes (>= 100 contratos) e padrões de continuidade/absorção.
    """

    LARGE_TRADE_THRESHOLD: int = 100  # Filtro visual para negócios relevantes

    def __init__(self, window_seconds: int = 300, asset_spec: Optional[any] = None):
        self.window_seconds = window_seconds
        self.asset_spec = asset_spec
        is_vale = (asset_spec is not None and getattr(asset_spec, 'symbol_base', '') == 'VALE3')
        is_wdo = (asset_spec is not None and getattr(asset_spec, 'symbol_base', '') == 'WDO')
        if is_vale:
            self.large_trade_thresh = 1000
        elif is_wdo:
            self.large_trade_thresh = 30  # Negócios relevantes no Mini-Dólar (30+ contratos)
        else:
            self.large_trade_thresh = self.LARGE_TRADE_THRESHOLD  # 100 contratos no WIN
        self.trades_history: Deque[Trade] = deque(maxlen=20000)
        self.large_trades: List[Trade] = []
        
        # Métricas acumuladas da sessão
        self.total_buy_volume: int = 0
        self.total_sell_volume: int = 0
        self.total_undefined_volume: int = 0
        self.total_trades_count: int = 0

    def add_trade(self, trade: Trade):
        """Processa um negócio individual."""
        self.trades_history.append(trade)
        self.total_trades_count += 1
        
        if trade.aggressor == AggressorSide.BUY:
            self.total_buy_volume += trade.quantity
        elif trade.aggressor == AggressorSide.SELL:
            self.total_sell_volume += trade.quantity
        else:
            self.total_undefined_volume += trade.quantity
            
        if trade.quantity >= self.large_trade_thresh:
            self.large_trades.append(trade)
            # Limitar histórico de grandes ordens
            if len(self.large_trades) > 500:
                self.large_trades.pop(0)

    @property
    def cumulative_delta(self) -> int:
        return self.total_buy_volume - self.total_sell_volume

    def get_window_metrics(self, seconds: Optional[int] = None) -> Dict[str, any]:
        """Calcula métricas da janela recente (ex: últimos 300 segundos)."""
        sec = seconds or self.window_seconds
        if not self.trades_history:
            return {
                "buy_volume": 0,
                "sell_volume": 0,
                "delta": 0,
                "delta_ratio": 0.0,
                "trades_count": 0,
                "large_trades_count": 0,
                "large_trades": [],
                "price_displacement_pts": 0.0,
                "flow_pattern": "SEM DADOS DE FLUXO"
            }
        
        last_time = self.trades_history[-1].timestamp
        cutoff = last_time - timedelta(seconds=sec)
        
        window_trades = [t for t in self.trades_history if t.timestamp >= cutoff]
        if not window_trades:
            return self.get_window_metrics(seconds=sec*2) if sec < 3600 else {
                "buy_volume": 0, "sell_volume": 0, "delta": 0, "delta_ratio": 0.0,
                "trades_count": 0, "large_trades_count": 0, "large_trades": [],
                "price_displacement_pts": 0.0, "flow_pattern": "SEM DADOS SUFICIENTES"
            }

        buy_vol = sum(t.quantity for t in window_trades if t.aggressor == AggressorSide.BUY)
        sell_vol = sum(t.quantity for t in window_trades if t.aggressor == AggressorSide.SELL)
        delta = buy_vol - sell_vol
        total_vol = buy_vol + sell_vol
        delta_ratio = (delta / total_vol) if total_vol > 0 else 0.0
        
        w_large = [t for t in window_trades if t.quantity >= self.large_trade_thresh]
        
        start_price = window_trades[0].price
        end_price = window_trades[-1].price
        price_displacement = end_price - start_price
        
        # Classificação do padrão de fluxo
        pattern = self._classify_flow_pattern(delta, price_displacement, total_vol)
        
        return {
            "buy_volume": buy_vol,
            "sell_volume": sell_vol,
            "delta": delta,
            "delta_ratio": round(delta_ratio, 3),
            "trades_count": len(window_trades),
            "large_trades_count": len(w_large),
            "large_trades": [
                {
                    "time": t.timestamp.strftime("%H:%M:%S.%f")[:-3],
                    "price": t.price,
                    "qty": t.quantity,
                    "side": t.aggressor.value,
                    "buyer": t.broker_buyer or "N/D",
                    "seller": t.broker_seller or "N/D"
                }
                for t in w_large[-5:]
            ],
            "start_price": start_price,
            "end_price": end_price,
            "price_displacement_pts": price_displacement,
            "flow_pattern": pattern
        }

    def _classify_flow_pattern(self, delta: int, price_displacement: float, total_volume: int) -> str:
        """
        Classificação determinística de padrões:
        - Agressão com continuidade: delta forte na direção do deslocamento do preço.
        - Possível absorção: delta elevado mas deslocamento do preço estagnado ou contrário.
        - Perda de continuidade: preço estagnou após esforço agressor.
        """
        is_vale = (self.asset_spec is not None and getattr(self.asset_spec, 'symbol_base', '') == 'VALE3')
        is_wdo = (self.asset_spec is not None and getattr(self.asset_spec, 'symbol_base', '') == 'WDO')
        if is_vale:
            # Calibração estrita para ações VALE3 (reais e centavos)
            if total_volume < 1000:
                return "Volume insuficiente para classificação institucional"
            
            delta_pct = (delta / total_volume) if total_volume > 0 else 0
            
            # Absorção Vendedora em VALE3 (forte venda absorvida passivamente sem deslocamento de baixa)
            if delta < 0 and abs(delta_pct) >= 0.25 and price_displacement >= -0.05:
                return "Possível Absorção Compradora (Forte venda absorvida passivamente sem deslocamento de baixa)"
            
            # Absorção Compradora em VALE3 (forte compra absorvida passivamente sem deslocamento de alta)
            if delta > 0 and delta_pct >= 0.25 and price_displacement <= 0.05:
                return "Possível Absorção Vendedora (Forte compra absorvida passivamente sem deslocamento de alta)"

            # Continuidade de Alta em VALE3 (avanço de preço >= 15 centavos)
            if delta > 0 and price_displacement >= 0.15:
                return "Agressão com Continuidade Compradora (Delta positivo acompanhado de avanço do preço)"

            # Continuidade de Baixa em VALE3 (recuo de preço <= -15 centavos)
            if delta < 0 and price_displacement <= -0.15:
                return "Agressão com Continuidade Vendedora (Delta negativo acompanhado de recuo do preço)"

            return "Fluxo em Equilíbrio / Sem Predomínio Conclusivo"

        elif is_wdo:
            # Calibração estrita para Mini-Dólar B3 (WDO - Ticks de 0.5 pts)
            if total_volume < 50:
                return "Volume insuficiente para classificação"

            delta_pct = (delta / total_volume) if total_volume > 0 else 0

            # Absorção Vendedora em WDO (forte venda absorvida passivamente sem deslocamento de baixa <= 2 ticks / 1.0 pt)
            if delta < 0 and abs(delta_pct) >= 0.25 and price_displacement >= -1.0:
                return "Possível Absorção Compradora (Forte venda absorvida passivamente sem deslocamento de baixa)"

            # Absorção Compradora em WDO (forte compra absorvida passivamente sem deslocamento de alta <= 2 ticks / 1.0 pt)
            if delta > 0 and delta_pct >= 0.25 and price_displacement <= 1.0:
                return "Possível Absorção Vendedora (Forte compra absorvida passivamente sem deslocamento de alta)"

            # Continuidade de Alta em WDO (avanço de preço >= 6 ticks / 3.0 pts)
            if delta > 0 and price_displacement >= 3.0:
                return "Agressão com Continuidade Compradora (Delta positivo acompanhado de avanço do preço)"

            # Continuidade de Baixa em WDO (recuo de preço <= -6 ticks / -3.0 pts)
            if delta < 0 and price_displacement <= -3.0:
                return "Agressão com Continuidade Vendedora (Delta negativo acompanhado de recuo do preço)"

            return "Fluxo em Equilíbrio / Sem Predomínio Conclusivo"

        # Padrão original para Mini-Índice (WIN - Ticks de 5 pontos)
        if total_volume < 100:
            return "Volume insuficiente para classificação"
        
        # Limiares objetivos
        delta_pct = (delta / total_volume) if total_volume > 0 else 0
        
        # Absorção Vendedora (preço não cai apesar de forte agressão de venda)
        if delta < 0 and abs(delta_pct) >= 0.25 and price_displacement >= -10.0:
            return "Possível Absorção Compradora (Forte venda absorvida passivamente sem deslocamento de baixa)"
        
        # Absorção Compradora (preço não sobe apesar de forte agressão de compra)
        if delta > 0 and delta_pct >= 0.25 and price_displacement <= 10.0:
            return "Possível Absorção Vendedora (Forte compra absorvida passivamente sem deslocamento de alta)"

        # Continuidade de Alta
        if delta > 0 and price_displacement >= 30.0:
            return "Agressão com Continuidade Compradora (Delta positivo acompanhado de avanço do preço)"

        # Continuidade de Baixa
        if delta < 0 and price_displacement <= -30.0:
            return "Agressão com Continuidade Vendedora (Delta negativo acompanhado de recuo do preço)"

        # Neutro / Equilíbrio
        return "Fluxo em Equilíbrio / Sem Predomínio Conclusivo"

    # Alias para compatibilidade
    get_flow_summary = get_window_metrics
