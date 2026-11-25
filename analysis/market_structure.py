"""
analysis/market_structure.py
Motor determinístico de Estrutura de Mercado e Smart Money Concepts (SMC).
Suporta os 7 tempos gráficos: 1m, 2m, 5m, 10m, 15m, 30m, 60m.
Sem uso de médias móveis e sem look-ahead bias (informação futura).
"""

from typing import List, Dict, Optional, Tuple
from datetime import datetime
import numpy as np

from core.models import (
    Candle, Pivot, FairValueGap, StructuralEvent, MarketRegime, Direction
)


class TimeframeStructureAnalyzer:
    """
    Analisa a estrutura de mercado para um tempo gráfico específico.
    Utiliza confirmação estrita à direita (right bars) para pivôs,
    garantindo zero look-ahead bias.
    """

    def __init__(
        self,
        timeframe: int,
        pivot_left_bars: int = 3,
        pivot_right_bars: int = 2,
        min_fvg_size: float = 10.0,
        min_displacement: float = 50.0
    ):
        self.timeframe = timeframe
        self.pivot_left = pivot_left_bars
        self.pivot_right = pivot_right_bars
        self.min_fvg_size = min_fvg_size
        self.min_displacement = min_displacement
        
        self.candles: List[Candle] = []
        self.pivots: List[Pivot] = []
        self.fvgs: List[FairValueGap] = []
        self.structural_events: List[StructuralEvent] = []
        
        # Estado estrutural
        self.regime: MarketRegime = MarketRegime.TRANSICAO
        self.last_confirmed_high: Optional[Pivot] = None
        self.last_confirmed_low: Optional[Pivot] = None
        self.previous_high: Optional[Pivot] = None
        self.previous_low: Optional[Pivot] = None
        
        # Histórico de quebras
        self.last_bos: Optional[StructuralEvent] = None
        self.last_choch: Optional[StructuralEvent] = None
        self.last_sweep: Optional[StructuralEvent] = None

    def add_candle(self, candle: Candle):
        """Adiciona um candle e processa a estrutura somente quando o candle fecha."""
        if not candle.is_closed:
            return
        
        self.candles.append(candle)
        current_bar_idx = len(self.candles) - 1
        
        # 1. Checagem de Pivôs retroativos (respeitando pivot_right)
        self._check_new_pivots(current_bar_idx)
        
        # 2. Checagem de FVG formado pelo trio [idx-2, idx-1, idx]
        self._check_new_fvg(current_bar_idx)
        
        # 3. Mitigação e Invalidação de FVGs existentes
        self._update_fvgs(candle)
        
        # 4. Avaliação de Sweeps e Rompimentos (BOS / CHoCH)
        self._evaluate_structural_breaks(current_bar_idx)
        
        # 5. Classificação de Regime de Mercado
        self._classify_regime()

    def _check_new_pivots(self, current_idx: int):
        """
        Um pivô no índice `target_idx` só é confirmado no `current_idx`
        se `current_idx >= target_idx + pivot_right`.
        """
        target_idx = current_idx - self.pivot_right
        if target_idx < self.pivot_left:
            return
        
        target_candle = self.candles[target_idx]
        is_pivot_high = True
        is_pivot_low = True
        
        # Verificar barras à esquerda
        for i in range(target_idx - self.pivot_left, target_idx):
            if self.candles[i].high >= target_candle.high:
                is_pivot_high = False
            if self.candles[i].low <= target_candle.low:
                is_pivot_low = False
                
        # Verificar barras à direita
        for i in range(target_idx + 1, target_idx + self.pivot_right + 1):
            if self.candles[i].high >= target_candle.high:
                is_pivot_high = False
            if self.candles[i].low <= target_candle.low:
                is_pivot_low = False
                
        if is_pivot_high:
            p = Pivot(
                pivot_type="HIGH",
                price=target_candle.high,
                bar_index=target_idx,
                timestamp=target_candle.close_time,
                confirmed_bar_index=current_idx
            )
            self.pivots.append(p)
            self.previous_high = self.last_confirmed_high
            self.last_confirmed_high = p
            
        if is_pivot_low:
            p = Pivot(
                pivot_type="LOW",
                price=target_candle.low,
                bar_index=target_idx,
                timestamp=target_candle.close_time,
                confirmed_bar_index=current_idx
            )
            self.pivots.append(p)
            self.previous_low = self.last_confirmed_low
            self.last_confirmed_low = p

    def seed_session_extremes(self, open_price: float, high_price: float, low_price: float, timestamp: datetime):
        """Inicializa os extremos da sessão (ABE, MAX, MIN) fornecidos pelo Profit Pro via DDE."""
        if self.last_confirmed_high is None and high_price > 0:
            self.last_confirmed_high = Pivot(
                pivot_type="HIGH",
                price=high_price,
                bar_index=0,
                timestamp=timestamp,
                confirmed_bar_index=0
            )
        if self.last_confirmed_low is None and low_price > 0:
            self.last_confirmed_low = Pivot(
                pivot_type="LOW",
                price=low_price,
                bar_index=0,
                timestamp=timestamp,
                confirmed_bar_index=0
            )
        if self.regime == MarketRegime.TRANSICAO and high_price > low_price:
            mid = (high_price + low_price) / 2.0
            if open_price > 0:
                if open_price < mid:
                    self.regime = MarketRegime.ALTA
                else:
                    self.regime = MarketRegime.BAIXA

    def _check_new_fvg(self, current_idx: int):
        """
        FVG de Alta: Low[3] > High[1]
        FVG de Baixa: High[3] < Low[1]
        Requer 3 candles fechados: c1 = [current-2], c2 = [current-1], c3 = [current]
        """
        if current_idx < 2:
            return
        
        c1 = self.candles[current_idx - 2]
        c2 = self.candles[current_idx - 1]
        c3 = self.candles[current_idx]
        
        # Tamanho mínimo de FVG configurado para o ativo
        MIN_FVG_SIZE = self.min_fvg_size
        
        # FVG de Alta
        if c3.low > c1.high and (c3.low - c1.high) >= MIN_FVG_SIZE:
            fvg = FairValueGap(
                direction="BULLISH",
                top=c3.low,
                bottom=c1.high,
                start_bar=current_idx - 2,
                end_bar=current_idx,
                timestamp=c3.close_time,
                timeframe=self.timeframe
            )
            self.fvgs.append(fvg)
            
        # FVG de Baixa
        elif c3.high < c1.low and (c1.low - c3.high) >= MIN_FVG_SIZE:
            fvg = FairValueGap(
                direction="BEARISH",
                top=c1.low,
                bottom=c3.high,
                start_bar=current_idx - 2,
                end_bar=current_idx,
                timestamp=c3.close_time,
                timeframe=self.timeframe
            )
            self.fvgs.append(fvg)

    def _update_fvgs(self, current_candle: Candle):
        """Atualiza mitigação de FVGs abertos."""
        for fvg in self.fvgs:
            if fvg.is_mitigated or fvg.is_invalidated:
                continue
            
            if fvg.direction == "BULLISH":
                # Se o preço penetrar no FVG
                if current_candle.low <= fvg.top:
                    fvg.is_mitigated = True
                if current_candle.close < fvg.bottom:
                    fvg.is_invalidated = True
            elif fvg.direction == "BEARISH":
                if current_candle.high >= fvg.bottom:
                    fvg.is_mitigated = True
                if current_candle.close > fvg.top:
                    fvg.is_invalidated = True

    def _evaluate_structural_breaks(self, current_idx: int):
        """
        Avalia se a barra atual causou:
        - Sweep de liquidez (superou extremo mas fechou dentro)
        - BOS (quebra na direção da tendência vigente)
        - CHoCH (quebra contrária à estrutura prévia)
        """
        candle = self.candles[current_idx]
        
        # Checar Sweep em Topo
        if self.last_confirmed_high:
            ref_high = self.last_confirmed_high.price
            if candle.high > ref_high and candle.close <= ref_high:
                # Sweep de Topo confirmado
                ev = StructuralEvent(
                    event_type="SWEEP",
                    direction="BEARISH",
                    timeframe=self.timeframe,
                    level_broken=ref_high,
                    timestamp=candle.close_time,
                    bar_index=current_idx,
                    details=f"Sweep de Máxima ({ref_high:.0f}): violou {candle.high:.0f} e fechou em {candle.close:.0f}"
                )
                self.structural_events.append(ev)
                self.last_sweep = ev

        # Checar Sweep em Fundo
        if self.last_confirmed_low:
            ref_low = self.last_confirmed_low.price
            if candle.low < ref_low and candle.close >= ref_low:
                # Sweep de Fundo confirmado
                ev = StructuralEvent(
                    event_type="SWEEP",
                    direction="BULLISH",
                    timeframe=self.timeframe,
                    level_broken=ref_low,
                    timestamp=candle.close_time,
                    bar_index=current_idx,
                    details=f"Sweep de Mínima ({ref_low:.0f}): violou {candle.low:.0f} e fechou em {candle.close:.0f}"
                )
                self.structural_events.append(ev)
                self.last_sweep = ev

        # Checar Rompimento Fechado (BOS ou CHoCH)
        # Rompimento de Alta: fechamento acima do último topo confirmado
        if self.last_confirmed_high and candle.close > self.last_confirmed_high.price:
            is_choch = (self.regime == MarketRegime.BAIXA)
            ev_type = "CHOCH" if is_choch else "BOS"
            ev = StructuralEvent(
                event_type=ev_type,
                direction="BULLISH",
                timeframe=self.timeframe,
                level_broken=self.last_confirmed_high.price,
                timestamp=candle.close_time,
                bar_index=current_idx,
                details=f"{ev_type} Comprador: Fechamento {candle.close:.0f} > Pivô {self.last_confirmed_high.price:.0f}"
            )
            self.structural_events.append(ev)
            if is_choch:
                self.last_choch = ev
            else:
                self.last_bos = ev

        # Rompimento de Baixa: fechamento abaixo do último fundo confirmado
        if self.last_confirmed_low and candle.close < self.last_confirmed_low.price:
            is_choch = (self.regime == MarketRegime.ALTA)
            ev_type = "CHOCH" if is_choch else "BOS"
            ev = StructuralEvent(
                event_type=ev_type,
                direction="BEARISH",
                timeframe=self.timeframe,
                level_broken=self.last_confirmed_low.price,
                timestamp=candle.close_time,
                bar_index=current_idx,
                details=f"{ev_type} Vendedor: Fechamento {candle.close:.0f} < Pivô {self.last_confirmed_low.price:.0f}"
            )
            self.structural_events.append(ev)
            if is_choch:
                self.last_choch = ev
            else:
                self.last_bos = ev

    def _classify_regime(self):
        """
        Classificação determinística do regime:
        - ALTA: Topos e fundos ascendentes confirmados ou sequência de impulsão compradora.
        - BAIXA: Topos e fundos descendentes confirmados ou sequência de impulsão vendedora.
        - CONSOLIDAÇÃO: Falha em progredir topos/fundos, sobreposição de ranges.
        - TRANSIÇÃO: CHoCH recente ou quebra de estrutura sem novo pivô confirmado.
        """
        if self.last_confirmed_high is None or self.last_confirmed_low is None:
            # Fallback direcional intradiário para tendências fortes sem formação de pivôs à direita
            if len(self.candles) >= 3:
                c_first = self.candles[0]
                c_last = self.candles[-1]
                # Se as barras estão trabalhando com deslocamento relevante em relação ao início da sessão
                disp_thresh = max(self.min_displacement * 1.5, 0.20)
                if c_last.close < c_first.open - disp_thresh:
                    self.regime = MarketRegime.BAIXA
                    return
                elif c_last.close > c_first.open + disp_thresh:
                    self.regime = MarketRegime.ALTA
                    return
            self.regime = MarketRegime.TRANSICAO
            return
        
        if self.previous_high is None or self.previous_low is None:
            # Com 1 topo e 1 fundo confirmados na sessão inicial:
            if self.last_confirmed_high.price > self.last_confirmed_low.price:
                self.regime = MarketRegime.ALTA
            else:
                self.regime = MarketRegime.BAIXA
            return

        hh = self.last_confirmed_high.price > self.previous_high.price
        hl = self.last_confirmed_low.price > self.previous_low.price
        lh = self.last_confirmed_high.price < self.previous_high.price
        ll = self.last_confirmed_low.price < self.previous_low.price

        if hh and hl:
            self.regime = MarketRegime.ALTA
        elif lh and ll:
            self.regime = MarketRegime.BAIXA
        elif (hh and ll) or (lh and hl):
            # Divergência estrutural ou contração/expansão
            self.regime = MarketRegime.CONSOLIDACAO
        else:
            self.regime = MarketRegime.TRANSICAO

    def check_displacement(self, lookback: int = 20) -> Tuple[bool, float]:
        """
        Calcula se o candle mais recente teve Deslocamento Quantitativo
        (corpo > 1.8x a mediana dos últimos `lookback` candles).
        Sem uso de médias móveis.
        """
        if len(self.candles) < lookback + 1:
            return False, 0.0
        
        recent_bodies = [c.body for c in self.candles[-lookback - 1:-1]]
        median_body = float(np.median(recent_bodies))
        curr_body = self.candles[-1].body
        
        has_displacement = (curr_body >= 1.8 * median_body) and (curr_body >= self.min_displacement)
        return has_displacement, curr_body


class MultiTimeframeMarketEngine:
    """
    Coordena a estrutura simultânea dos 7 tempos gráficos exigidos:
    60m, 30m (Contexto)
    15m, 10m (Estrutura Intermediária)
    5m       (Preparação)
    2m, 1m   (Gatilho)
    """

    SUPPORTED_TIMEFRAMES = [240, 60, 30, 15, 10, 5, 2, 1]

    def __init__(self, asset_spec=None):
        from core.contract import WIN_SPEC
        self.spec = asset_spec or WIN_SPEC
        self.analyzers: Dict[int, TimeframeStructureAnalyzer] = {
            tf: TimeframeStructureAnalyzer(
                timeframe=tf,
                min_fvg_size=self.spec.min_fvg_size,
                min_displacement=self.spec.min_displacement_body
            ) for tf in self.SUPPORTED_TIMEFRAMES
        }

    def seed_session_extremes(self, open_p: float, high_p: float, low_p: float, timestamp: datetime):
        """Dissemina os extremos oficiais da sessão para os tempos contextuais."""
        for tf in [240, 60, 30, 15, 10]:
            if tf in self.analyzers:
                self.analyzers[tf].seed_session_extremes(open_p, high_p, low_p, timestamp)

    def process_closed_candle(self, candle: Candle):
        if candle.timeframe in self.analyzers:
            self.analyzers[candle.timeframe].add_candle(candle)

    def get_regime_summary(self) -> Dict[str, str]:
        """Retorna o regime de cada um dos 7 tempos gráficos."""
        return {
            f"{tf}m": self.analyzers[tf].regime.value for tf in self.SUPPORTED_TIMEFRAMES
        }

    def get_context_direction(self) -> Tuple[Optional[Direction], str]:
        """
        Hierarquia de Contexto:
        Prioridade primária: 60m e 30m.
        Se 60m estiver em formação inicial ou transição, utiliza o consenso 30m e 15m.
        """
        r60 = self.analyzers[60].regime
        r30 = self.analyzers[30].regime
        r15 = self.analyzers[15].regime
        
        # 1. Alinhamento perfeito 60m + 30m
        if r60 == MarketRegime.ALTA and r30 == MarketRegime.ALTA:
            return Direction.COMPRA, "Tendência de Alta Alinhada (60m + 30m)"
        elif r60 == MarketRegime.BAIXA and r30 == MarketRegime.BAIXA:
            return Direction.VENDA, "Tendência de Baixa Alinhada (60m + 30m)"
        
        # 2. Consenso 30m + 15m (quando 60m ainda está em transição/início de pregão)
        elif r30 == MarketRegime.ALTA and r15 == MarketRegime.ALTA:
            return Direction.COMPRA, "Tendência de Alta Intermediária (30m + 15m)"
        elif r30 == MarketRegime.BAIXA and r15 == MarketRegime.BAIXA:
            return Direction.VENDA, "Tendência de Baixa Intermediária (30m + 15m)"

        # 3. Consenso Intradiário da Sessão (quando 60m/30m ainda estão em transição no início da manhã)
        elif self.analyzers[15].regime == MarketRegime.BAIXA or self.analyzers[5].regime == MarketRegime.BAIXA:
            return Direction.VENDA, "Tendência Intradiária de Baixa (Momentum 15m/5m)"
        elif self.analyzers[15].regime == MarketRegime.ALTA or self.analyzers[5].regime == MarketRegime.ALTA:
            return Direction.COMPRA, "Tendência Intradiária de Alta (Momentum 15m/5m)"

        elif r60 == MarketRegime.CONSOLIDACAO or r30 == MarketRegime.CONSOLIDACAO:
            return None, "Contexto em Consolidação"
        else:
            return None, f"Transição / Indefinido (60m: {r60.value}, 30m: {r30.value}, 15m: {r15.value})"
