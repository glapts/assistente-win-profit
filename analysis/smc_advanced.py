"""
analysis/smc_advanced.py
Módulos Avançados de Smart Money Concepts (SMC) & Inner Circle Trader (ICT) para B3 (WIN e WDO).

Contém a implementação rigorosa dos 6 pilares:
1. 🦄 ICT Unicorn Model (Breaker Block + FVG sobrepostos)
2. ⚡ SMT Divergence Engine (Correlação intermercado WIN vs WDO)
3. ⏳ Power of 3 (AMD: Acumulação -> Manipulação/Judas Swing -> Distribuição)
4. 🧲 Liquidity Pools (Equal Highs & Equal Lows - EQH / EQL com tolerância em ticks)
5. 🔄 Inversion FVG (iFVG - Inversão de polaridade suporte/resistência)
6. 🕒 Time-Based Gating / Killzones Estritas da B3
"""

from typing import List, Dict, Optional, Tuple, Any
from datetime import datetime, time as dt_time, timedelta
import math

from core.models import (
    Candle, Pivot, FairValueGap, Direction, SignalSetup, SetupStatus,
    BreakerBlock, InversionFVG, LiquidityPool, SMTDivergenceEvent,
    KillzoneType, KillzoneSession, AMDPhase, AMDState,
    UnicornSetupCandidate, SMCConfluenceScore
)
from core.contract import AssetSpec, WIN_SPEC, round_to_tick


# =====================================================================
# 1. TIME-BASED GATING & KILLZONES ESTRITAS DA B3
# =====================================================================

class KillzoneGate:
    """
    Controla com precisão de nanossegundos as janelas operacionais da B3:
    - Killzone Matutina (09:30 - 11:30): Liquidez máxima e respeito técnico (Modo Padrão / Agressivo).
    - Chop Zone / Almoço (12:00 - 13:30): Bloqueio total de operações de continuidade e tendência.
    - Killzone Vespertina (14:30 - 16:30): Fluxo de continuação e rebalanceamento americano.
    - Fechamento Tóxico (> 16:30): Encerramento de exposições e proteção de capital.
    """

    def __init__(
        self,
        morning_start: dt_time = dt_time(9, 30),
        morning_end: dt_time = dt_time(11, 30),
        lunch_start: dt_time = dt_time(12, 0),
        lunch_end: dt_time = dt_time(13, 30),
        afternoon_start: dt_time = dt_time(14, 30),
        afternoon_end: dt_time = dt_time(16, 30),
        hard_stop_time: dt_time = dt_time(17, 0)
    ):
        self.morning_start = morning_start
        self.morning_end = morning_end
        self.lunch_start = lunch_start
        self.lunch_end = lunch_end
        self.afternoon_start = afternoon_start
        self.afternoon_end = afternoon_end
        self.hard_stop_time = hard_stop_time

    def evaluate_session(self, current_time: datetime, is_continuation_trade: bool = False) -> KillzoneSession:
        t = current_time.time()

        # Janela Matutina Prime
        if self.morning_start <= t <= self.morning_end:
            return KillzoneSession(
                current_time=current_time,
                active_killzone=KillzoneType.MORNING_PRIME,
                allows_continuation=True,
                allows_reversal=True,
                reason="Killzone Matutina B3 (09:30-11:30): Alta liquidez institucional e direção limpa."
            )

        # Chop Zone / Almoço
        if self.lunch_start <= t <= self.lunch_end:
            return KillzoneSession(
                current_time=current_time,
                active_killzone=KillzoneType.LUNCH_CHOP,
                allows_continuation=False,  # VETO ESTRITO
                allows_reversal=False,      # Proteção total de capital
                reason="Chop Zone / Almoço B3 (12:00-13:30): Liquidez rarefeita e armadilhas de HFT. Bloqueio ativo."
            )

        # Killzone Vespertina Prime
        if self.afternoon_start <= t <= self.afternoon_end:
            return KillzoneSession(
                current_time=current_time,
                active_killzone=KillzoneType.AFTERNOON_PRIME,
                allows_continuation=True,
                allows_reversal=True,
                reason="Killzone Vespertina B3 (14:30-16:30): Entrada de fluxo americano e forte direcional."
            )

        # Janela de Abertura / Judas Swing
        if dt_time(9, 15) <= t < self.morning_start:
            return KillzoneSession(
                current_time=current_time,
                active_killzone=KillzoneType.JUDAS_WINDOW,
                allows_continuation=False,  # Não permite romper topo/fundo aqui
                allows_reversal=True,       # Permite pegar rejeição de armadilha
                reason="Janela de Abertura / Judas Swing (09:15-09:30): Bloqueio de continuidade, autorizadas apenas reversões de sweep."
            )

        # Fora das janelas principais
        if t > self.hard_stop_time or t < dt_time(9, 0):
            return KillzoneSession(
                current_time=current_time,
                active_killzone=KillzoneType.OFF_HOURS,
                allows_continuation=False,
                allows_reversal=False,
                reason="Fora do Horário Regular Institucional. Operações desativadas para mitigar risco de leilão/spread."
            )

        return KillzoneSession(
            current_time=current_time,
            active_killzone=KillzoneType.OFF_HOURS,
            allows_continuation=not is_continuation_trade,
            allows_reversal=True,
            reason="Janela Intermediária B3: Exige confluência estrita para execução."
        )

    def is_trade_allowed(self, current_time: datetime, is_continuation_trade: bool = False) -> Tuple[bool, str]:
        session = self.evaluate_session(current_time, is_continuation_trade=is_continuation_trade)
        if is_continuation_trade and not session.allows_continuation:
            return False, f"VETO POR KILLZONE: {session.reason}"
        if not is_continuation_trade and not session.allows_reversal:
            return False, f"VETO POR KILLZONE: {session.reason}"
        return True, session.reason


# =====================================================================
# 2. POWER OF 3 (AMD: ACUMULAÇÃO -> MANIPULAÇÃO -> DISTRIBUIÇÃO)
# =====================================================================

class PowerOfThreeEngine:
    """
    Rastreia o ciclo institucional matinal clássico do ICT / SMC:
    1. 09:00 - 09:15: Acumulação (Define a faixa inicial de equilíbrio).
    2. 09:15 - 10:00: Manipulação (Judas Swing - Falso rompimento para capturar liquidez de varejo).
    3. 10:00 - 12:30: Distribuição (Deslocamento real direcionado pelas grandes instituições da B3).
    """

    def __init__(self, asset_spec: Optional[AssetSpec] = None):
        self.spec = asset_spec or WIN_SPEC
        self.reset_session()

    def reset_session(self):
        self.initial_high: Optional[float] = None
        self.initial_low: Optional[float] = None
        self.judas_sweep_high: bool = False
        self.judas_sweep_low: bool = False
        self.distribution_started: bool = False
        self.candles_history: List[Candle] = []

    def process_candle(self, candle: Candle):
        if not candle.is_closed:
            return
        self.candles_history.append(candle)
        t = candle.open_time.time()

        # Fase 1: 09:00 às 09:15 (Acumulação / Initial Range)
        if dt_time(9, 0) <= t < dt_time(9, 15):
            if self.initial_high is None or candle.high > self.initial_high:
                self.initial_high = candle.high
            if self.initial_low is None or candle.low < self.initial_low:
                self.initial_low = candle.low

        # Fase 2: 09:15 às 10:00 (Manipulação / Judas Swing)
        elif dt_time(9, 15) <= t < dt_time(10, 0):
            if self.initial_high is not None and candle.high > self.initial_high and candle.close <= self.initial_high:
                self.judas_sweep_high = True
            if self.initial_low is not None and candle.low < self.initial_low and candle.close >= self.initial_low:
                self.judas_sweep_low = True

    def get_phase(self, current_time: datetime) -> AMDPhase:
        t = current_time.time()
        if dt_time(9, 0) <= t < dt_time(9, 15):
            return AMDPhase.ACCUMULATION
        elif dt_time(9, 15) <= t < dt_time(10, 0):
            return AMDPhase.MANIPULATION
        elif dt_time(10, 0) <= t <= dt_time(12, 30):
            return AMDPhase.DISTRIBUTION
        return AMDPhase.OFF_CYCLE

    def evaluate_amd(
        self,
        current_time: datetime,
        direction: Direction,
        is_breakout: bool,
        current_price: float
    ) -> Tuple[bool, str, AMDState]:
        phase = self.get_phase(current_time)
        state = AMDState(
            phase=phase,
            initial_range_high=self.initial_high,
            initial_range_low=self.initial_low,
            judas_sweep_high=self.judas_sweep_high,
            judas_sweep_low=self.judas_sweep_low
        )

        # Regra 1: Durante a Acumulação (09:00 - 09:15), não operar rompimentos
        if phase == AMDPhase.ACCUMULATION:
            if is_breakout:
                state.details = "Bloqueio AMD: Fase de Acumulação inicial (09:00-09:15). Rompimentos proibidos."
                return False, state.details, state
            state.details = "Fase de Acumulação: Operações no interior da faixa permitidas."
            return True, state.details, state

        # Regra 2: Durante a Manipulação / Judas Swing (09:15 - 10:00)
        elif phase == AMDPhase.MANIPULATION:
            # Proibição categórica de rompimento de continuidade
            if is_breakout:
                state.details = "VETO AMD / JUDAS SWING: Rompimento na janela 09:15-10:00 possui alta probabilidade de falso estirão institucional."
                return False, state.details, state

            # Permissão exclusiva de Rejeição / Reversão pós-Sweep do Judas
            if direction == Direction.VENDA and self.judas_sweep_high:
                state.allowed_trade_direction = Direction.VENDA
                state.details = "CONFIRMAÇÃO AMD: Judas Swing na Máxima confirmado com retorno para dentro da faixa. Venda de alta probabilidade."
                return True, state.details, state

            if direction == Direction.COMPRA and self.judas_sweep_low:
                state.allowed_trade_direction = Direction.COMPRA
                state.details = "CONFIRMAÇÃO AMD: Judas Swing na Mínima confirmado com retorno para dentro da faixa. Compra de alta probabilidade."
                return True, state.details, state

            state.details = "Janela de Manipulação: Sem sweep confirmado da faixa de abertura. Aguardar."
            return False, state.details, state

        # Fase 3: Distribuição Real (10:00 - 12:30)
        elif phase == AMDPhase.DISTRIBUTION:
            # Se houve Judas na Máxima, a distribuição real esperada é de BAIXA (Venda a favor)
            if self.judas_sweep_high and direction == Direction.VENDA:
                state.details = "ALINHAMENTO INSTITUCIONAL AMD: Distribuição de Baixa pós-Judas Sweep na Máxima."
                return True, state.details, state

            # Se houve Judas na Mínima, a distribuição real esperada é de ALTA (Compra a favor)
            if self.judas_sweep_low and direction == Direction.COMPRA:
                state.details = "ALINHAMENTO INSTITUCIONAL AMD: Distribuição de Alta pós-Judas Sweep na Mínima."
                return True, state.details, state

            state.details = "Fase de Distribuição regular B3 liberada."
            return True, state.details, state

        state.details = "Fora do ciclo matinal AMD. Gating neutro."
        return True, state.details, state


# =====================================================================
# 3. MAPEAMENTO DE LIQUIDITY POOLS (EQH / EQL)
# =====================================================================

class LiquidityPoolEngine:
    """
    Identifica piscinas de liquidez institucional:
    - Equal Highs (EQH): Topos duplos/triplos com tolerância de 1-3 ticks (Buy-Side Liquidity - BSL).
    - Equal Lows (EQL): Fundos duplos/triplos com tolerância de 1-3 ticks (Sell-Side Liquidity - SSL).
    Atua como ímã de atração (vetando contra-tendência) e gatilho de reversão pós-sweep.
    """

    def __init__(self, tolerance_pts: float = 10.0, asset_spec: Optional[AssetSpec] = None):
        self.spec = asset_spec or WIN_SPEC
        self.tolerance_pts = tolerance_pts
        self.active_pools: List[LiquidityPool] = []

    def update_from_pivots(self, pivots: List[Pivot], timeframe: int = 5):
        """
        Agrupa pivôs consecutivos ou próximos que compartilham a mesma faixa de preço dentro da tolerância.
        Garante zero look-ahead bias: analisa apenas pivôs já confirmados à direita.
        """
        highs = [p for p in pivots if p.pivot_type == "HIGH"]
        lows = [p for p in pivots if p.pivot_type == "LOW"]

        new_pools: List[LiquidityPool] = []

        # Mapear EQH (Equal Highs)
        for i in range(len(highs)):
            p1 = highs[i]
            matched_touches = [p1.price]
            matched_times = [p1.timestamp]
            for j in range(i + 1, len(highs)):
                p2 = highs[j]
                if abs(p1.price - p2.price) <= self.tolerance_pts:
                    matched_touches.append(p2.price)
                    matched_times.append(p2.timestamp)

            if len(matched_touches) >= 2:
                avg_level = sum(matched_touches) / len(matched_touches)
                # Verificar se já existe pool próxima
                if not any(abs(pool.price_level - avg_level) <= self.tolerance_pts and pool.pool_type == "EQH" for pool in new_pools):
                    new_pools.append(LiquidityPool(
                        pool_type="EQH",
                        price_level=round_to_tick(avg_level, self.spec.tick_size),
                        touches=matched_touches,
                        timestamps=matched_times,
                        tolerance_pts=self.tolerance_pts,
                        timeframe=timeframe
                    ))

        # Mapear EQL (Equal Lows)
        for i in range(len(lows)):
            p1 = lows[i]
            matched_touches = [p1.price]
            matched_times = [p1.timestamp]
            for j in range(i + 1, len(lows)):
                p2 = lows[j]
                if abs(p1.price - p2.price) <= self.tolerance_pts:
                    matched_touches.append(p2.price)
                    matched_times.append(p2.timestamp)

            if len(matched_touches) >= 2:
                avg_level = sum(matched_touches) / len(matched_touches)
                if not any(abs(pool.price_level - avg_level) <= self.tolerance_pts and pool.pool_type == "EQL" for pool in new_pools):
                    new_pools.append(LiquidityPool(
                        pool_type="EQL",
                        price_level=round_to_tick(avg_level, self.spec.tick_size),
                        touches=matched_touches,
                        timestamps=matched_times,
                        tolerance_pts=self.tolerance_pts,
                        timeframe=timeframe
                    ))

        # Preservar o estado is_swept das pools existentes
        for np_pool in new_pools:
            for old in self.active_pools:
                if old.pool_type == np_pool.pool_type and abs(old.price_level - np_pool.price_level) <= self.tolerance_pts:
                    np_pool.is_swept = old.is_swept
                    np_pool.sweep_time = old.sweep_time

        self.active_pools = new_pools

    def check_pool_sweep(self, candle: Candle) -> List[LiquidityPool]:
        """
        Verifica se o candle atual varreu (swept) alguma piscina de liquidez ativa.
        """
        swept_pools: List[LiquidityPool] = []
        for pool in self.active_pools:
            if pool.is_swept:
                continue

            if pool.pool_type == "EQH":
                # Sweep de Topo Duplo: Preço superou o nível da piscina mas candle fechou no mesmo nível ou abaixo
                if candle.high > pool.price_level and candle.close <= (pool.price_level + self.tolerance_pts):
                    pool.is_swept = True
                    pool.sweep_time = candle.close_time
                    swept_pools.append(pool)

            elif pool.pool_type == "EQL":
                # Sweep de Fundo Duplo: Preço perdeu o nível da piscina mas candle fechou no mesmo nível ou acima
                if candle.low < pool.price_level and candle.close >= (pool.price_level - self.tolerance_pts):
                    pool.is_swept = True
                    pool.sweep_time = candle.close_time
                    swept_pools.append(pool)

        return swept_pools

    def check_liquidity_magnet(
        self,
        current_price: float,
        trade_direction: Direction,
        search_radius: float = 120.0
    ) -> Tuple[bool, Optional[LiquidityPool], str]:
        """
        Verifica se existe uma piscina de liquidez próxima atuando como ímã de preço:
        - Se o trade é de VENDA mas há um EQH não varrido logo acima, o trade é vetado (preço será atraído para varrer antes).
        - Se o trade é de COMPRA mas há um EQL não varrido logo abaixo, o trade é vetado.
        """
        for pool in self.active_pools:
            if pool.is_swept:
                continue

            # Se trade de VENDA e existe EQH logo acima a menos de search_radius
            if trade_direction == Direction.VENDA and pool.pool_type == "EQH":
                dist = pool.price_level - current_price
                if 0 < dist <= search_radius:
                    return False, pool, f"ÍMÃ DE LIQUIDEZ ATIVO: Piscina EQH ({pool.price_level:.0f}) a apenas {dist:.0f} pts acima. Risco de caça aos stops antes da queda."

            # Se trade de COMPRA e existe EQL logo abaixo a menos de search_radius
            if trade_direction == Direction.COMPRA and pool.pool_type == "EQL":
                dist = current_price - pool.price_level
                if 0 < dist <= search_radius:
                    return False, pool, f"ÍMÃ DE LIQUIDEZ ATIVO: Piscina EQL ({pool.price_level:.0f}) a apenas {dist:.0f} pts abaixo. Risco de caça aos stops antes da alta."

        return True, None, "Sem piscinas de liquidez perigosas bloqueando o caminho."


# =====================================================================
# 4. INVERSION FVG (iFVG — FVG INVERTIDO)
# =====================================================================

class InversionFVGTracker:
    """
    Gerencia o ciclo de vida institucional dos Fair Value Gaps violados:
    - FVG de Alta violado por fechamento de baixa -> Converte-se em Resistência Institucional.
    - FVG de Baixa violado por fechamento de alta -> Converte-se em Suporte Institucional.
    Monitora retestes da zona como gatilhos de continuação ou mitigação pós-CHoCH.
    """

    def __init__(self, asset_spec: Optional[AssetSpec] = None):
        self.spec = asset_spec or WIN_SPEC
        self.active_ifvgs: List[InversionFVG] = []

    def process_candle(self, candle: Candle, active_fvgs: List[FairValueGap]):
        """
        Avalia fechamento do candle contra a lista de FVGs abertos.
        Determinístico e sem look-ahead: somente fecha após o candle estar fechado.
        """
        if not candle.is_closed:
            return

        for fvg in active_fvgs:
            # 1. FVG de Alta violado: fechamento abaixo do bottom
            if fvg.direction == "BULLISH" and not fvg.is_invalidated:
                if candle.close < fvg.bottom:
                    fvg.is_invalidated = True
                    # Criar iFVG de Resistência
                    ifvg = InversionFVG(
                        original_direction="BULLISH",
                        current_role="RESISTANCE",
                        top=fvg.top,
                        bottom=fvg.bottom,
                        timeframe=fvg.timeframe,
                        inversion_time=candle.close_time,
                        inversion_candle_index=len(self.active_ifvgs)
                    )
                    self._add_or_update_ifvg(ifvg)

            # 2. FVG de Baixa violado: fechamento acima do top
            elif fvg.direction == "BEARISH" and not fvg.is_invalidated:
                if candle.close > fvg.top:
                    fvg.is_invalidated = True
                    # Criar iFVG de Suporte
                    ifvg = InversionFVG(
                        original_direction="BEARISH",
                        current_role="SUPPORT",
                        top=fvg.top,
                        bottom=fvg.bottom,
                        timeframe=fvg.timeframe,
                        inversion_time=candle.close_time,
                        inversion_candle_index=len(self.active_ifvgs)
                    )
                    self._add_or_update_ifvg(ifvg)

        # Atualizar retestes nos iFVGs ativos
        self._check_ifvg_retests(candle)

    def _add_or_update_ifvg(self, new_ifvg: InversionFVG):
        # Evitar duplicações idênticas
        for ex in self.active_ifvgs:
            if ex.current_role == new_ifvg.current_role and abs(ex.top - new_ifvg.top) <= 5 and abs(ex.bottom - new_ifvg.bottom) <= 5:
                return
        self.active_ifvgs.append(new_ifvg)

    def _check_ifvg_retests(self, candle: Candle):
        for ifvg in self.active_ifvgs:
            if ifvg.is_invalidated:
                continue

            # Reteste em Resistência (ex-Bullish FVG)
            if ifvg.current_role == "RESISTANCE":
                if candle.high >= ifvg.bottom and candle.close <= ifvg.top:
                    ifvg.is_retested = True
                    ifvg.retest_count += 1
                elif candle.close > ifvg.top:
                    # Invalidação secundária
                    ifvg.is_invalidated = True

            # Reteste em Suporte (ex-Bearish FVG)
            elif ifvg.current_role == "SUPPORT":
                if candle.low <= ifvg.top and candle.close >= ifvg.bottom:
                    ifvg.is_retested = True
                    ifvg.retest_count += 1
                elif candle.close < ifvg.bottom:
                    ifvg.is_invalidated = True

    def check_ifvg_confluence(
        self,
        current_price: float,
        direction: Direction,
        tolerance_pts: float = 15.0
    ) -> Tuple[bool, Optional[InversionFVG], str]:
        """
        Retorna se o preço atual está testando um iFVG a favor do trade.
        """
        for ifvg in reversed(self.active_ifvgs):
            if ifvg.is_invalidated:
                continue

            # Compra com reteste em iFVG de Suporte
            if direction == Direction.COMPRA and ifvg.current_role == "SUPPORT":
                if (ifvg.bottom - tolerance_pts) <= current_price <= (ifvg.top + tolerance_pts):
                    return True, ifvg, f"CONFLUÊNCIA iFVG ({ifvg.timeframe}m): Reteste em Suporte Invertido [{ifvg.bottom:.0f} - {ifvg.top:.0f}]."

            # Venda com reteste em iFVG de Resistência
            if direction == Direction.VENDA and ifvg.current_role == "RESISTANCE":
                if (ifvg.bottom - tolerance_pts) <= current_price <= (ifvg.top + tolerance_pts):
                    return True, ifvg, f"CONFLUÊNCIA iFVG ({ifvg.timeframe}m): Reteste em Resistência Invertida [{ifvg.bottom:.0f} - {ifvg.top:.0f}]."

        return False, None, "Sem confluência direta de iFVG no nível de preço."


# =====================================================================
# 5. SMT DIVERGENCE ENGINE (CORRELAÇÃO CRUZADA WIN vs WDO)
# =====================================================================

class SMTDivergenceEngine:
    """
    Smart Money Tool (SMT) para Mini-Índice (WIN) e Mini-Dólar (WDO):
    Detecta quebra de simetria na correlação estrita de mercado:
    - Bullish SMT no WIN: WIN faz Mínima Mais Baixa (Sweep), mas o WDO falha em fazer Máxima Mais Alta (absorção de venda no índice, ausência de compra no dólar).
    - Bearish SMT no WIN: WIN faz Máxima Mais Alta (Sweep), mas o WDO falha em fazer Mínima Mais Baixa (absorção de compra no índice, suporte sólido no dólar).
    """

    def __init__(self, window_seconds: int = 300):
        self.window_seconds = window_seconds
        self.win_pivots: List[Pivot] = []
        self.wdo_pivots: List[Pivot] = []
        self.active_divergences: List[SMTDivergenceEvent] = []

    def register_win_pivot(self, pivot: Pivot):
        self.win_pivots.append(pivot)

    def register_wdo_pivot(self, pivot: Pivot):
        self.wdo_pivots.append(pivot)

    def evaluate_smt_divergence(
        self,
        current_time: datetime,
        current_win_price: float,
        current_wdo_price: float,
        win_recent_low: Optional[float] = None,
        win_prev_low: Optional[float] = None,
        wdo_recent_high: Optional[float] = None,
        wdo_prev_high: Optional[float] = None,
        win_recent_high: Optional[float] = None,
        win_prev_high: Optional[float] = None,
        wdo_recent_low: Optional[float] = None,
        wdo_prev_low: Optional[float] = None
    ) -> Optional[SMTDivergenceEvent]:
        """
        Avaliação determinística da divergência SMT entre WIN e WDO.
        """
        # 1. Checagem de Bullish SMT no WIN (Compra Institucional no Índice)
        if win_recent_low is not None and win_prev_low is not None:
            if win_recent_low < win_prev_low:  # WIN fez Lower Low
                if wdo_recent_high is not None and wdo_prev_high is not None:
                    if wdo_recent_high <= wdo_prev_high:  # WDO falhou em fazer Higher High!
                        ev = SMTDivergenceEvent(
                            timestamp=current_time,
                            divergence_type="BULLISH",
                            win_extreme_type="LOWER_LOW",
                            win_price=win_recent_low,
                            win_previous_price=win_prev_low,
                            wdo_extreme_type="LOWER_HIGH",
                            wdo_price=wdo_recent_high,
                            wdo_previous_price=wdo_prev_high,
                            delta_seconds=0.0,
                            details="SMT BULLISH WIN: Índice rompeu mínima prévia enquanto o Dólar falhou em romper máxima. Absorção compradora institucional."
                        )
                        self.active_divergences.append(ev)
                        return ev

        # 2. Checagem de Bearish SMT no WIN (Venda Institucional no Índice)
        if win_recent_high is not None and win_prev_high is not None:
            if win_recent_high > win_prev_high:  # WIN fez Higher High
                if wdo_recent_low is not None and wdo_prev_low is not None:
                    if wdo_recent_low >= wdo_prev_low:  # WDO falhou em fazer Lower Low!
                        ev = SMTDivergenceEvent(
                            timestamp=current_time,
                            divergence_type="BEARISH",
                            win_extreme_type="HIGHER_HIGH",
                            win_price=win_recent_high,
                            win_previous_price=win_prev_high,
                            wdo_extreme_type="HIGHER_LOW",
                            wdo_price=wdo_recent_low,
                            wdo_previous_price=wdo_prev_low,
                            delta_seconds=0.0,
                            details="SMT BEARISH WIN: Índice rompeu máxima prévia enquanto o Dólar falhou em romper mínima. Absorção vendedora institucional."
                        )
                        self.active_divergences.append(ev)
                        return ev

        return None


# =====================================================================
# 6. ICT UNICORN MODEL (BREAKER BLOCK + FVG CONFLUENCE)
# =====================================================================

class ICTUnicornEngine:
    """
    O setup de maior probabilidade matemática de ICT (~68% a 72% de acerto):
    Combina geometricamente:
    - Um Breaker Block confirmado (Order block que falhou após sweep e quebra de estrutura BOS/CHoCH).
    - Um Fair Value Gap (FVG) não mitigado com sobreposição espacial na mesma faixa de preço.
    """

    def __init__(
        self,
        min_overlap_ratio: float = 0.30,
        asset_spec: Optional[AssetSpec] = None
    ):
        self.min_overlap_ratio = min_overlap_ratio
        self.spec = asset_spec or WIN_SPEC
        self.breakers: List[BreakerBlock] = []

    def detect_breakers(
        self,
        candles: List[Candle],
        pivots: List[Pivot],
        timeframe: int = 5
    ) -> List[BreakerBlock]:
        """
        Rastreia deterministamente a sequência estrutural de Breaker Block:
        - Bullish Breaker: Fundo 1 -> Topo 1 -> Fundo 2 (Sweep de F1) -> Rompimento acima de T1. O bloco de ordens de T1 torna-se suporte.
        - Bearish Breaker: Topo 1 -> Fundo 1 -> Topo 2 (Sweep de T1) -> Rompimento abaixo de F1. O bloco de ordens de F1 torna-se resistência.
        """
        # 1. Atualizar mitigação de breakers ativos com os candles mais recentes
        for b in self.breakers:
            if b.is_mitigated:
                continue
            for c in candles:
                if c.close_time <= b.timestamp:
                    continue
                if b.breaker_type == "BULLISH" and c.close < b.bottom:
                    b.is_mitigated = True
                    break
                elif b.breaker_type == "BEARISH" and c.close > b.top:
                    b.is_mitigated = True
                    break

        if len(pivots) < 3 or len(candles) < 5:
            return self.breakers

        for i in range(len(pivots) - 2):
            p1 = pivots[i]
            p2 = pivots[i + 1]
            p3 = pivots[i + 2]

            # 1. Bearish Breaker: p1=HIGH, p2=LOW, p3=HIGH (mais alto que p1)
            if p1.pivot_type == "HIGH" and p2.pivot_type == "LOW" and p3.pivot_type == "HIGH":
                if p3.price > p1.price:  # Sweep de Máxima
                    # Verificar se candles subsequentes fecharam abaixo de p2.price (CHoCH / quebra)
                    for c_idx in range(p3.confirmed_bar_index, len(candles)):
                        c = candles[c_idx]
                        if c.close < p2.price:
                            # Confirmado Bearish Breaker na região do pivô de baixa p2
                            b_candle = candles[p2.bar_index]
                            top_val = max(b_candle.high, b_candle.open)
                            bot_val = min(b_candle.low, b_candle.close)
                            
                            bb = BreakerBlock(
                                breaker_type="BEARISH",
                                top=top_val,
                                bottom=bot_val,
                                origin_candle_index=p2.bar_index,
                                sweep_level=p3.price,
                                breakout_level=p2.price,
                                timestamp=c.close_time,
                                timeframe=timeframe
                            )
                            if not any(abs(b.top - bb.top) <= 5 and b.breaker_type == "BEARISH" for b in self.breakers):
                                self.breakers.append(bb)
                            break

            # 2. Bullish Breaker: p1=LOW, p2=HIGH, p3=LOW (mais baixo que p1)
            elif p1.pivot_type == "LOW" and p2.pivot_type == "HIGH" and p3.pivot_type == "LOW":
                if p3.price < p1.price:  # Sweep de Mínima
                    for c_idx in range(p3.confirmed_bar_index, len(candles)):
                        c = candles[c_idx]
                        if c.close > p2.price:
                            b_candle = candles[p2.bar_index]
                            top_val = max(b_candle.high, b_candle.close)
                            bot_val = min(b_candle.low, b_candle.open)
                            
                            bb = BreakerBlock(
                                breaker_type="BULLISH",
                                top=top_val,
                                bottom=bot_val,
                                origin_candle_index=p2.bar_index,
                                sweep_level=p3.price,
                                breakout_level=p2.price,
                                timestamp=c.close_time,
                                timeframe=timeframe
                            )
                            if not any(abs(b.bottom - bb.bottom) <= 5 and b.breaker_type == "BULLISH" for b in self.breakers):
                                self.breakers.append(bb)
                            break

        # Atualizar mitigação de breakers ativos com candles posteriores
        for b in self.breakers:
            if b.is_mitigated:
                continue
            for c in candles:
                if c.close_time <= b.timestamp:
                    continue
                if b.breaker_type == "BULLISH" and c.close < b.bottom:
                    b.is_mitigated = True
                    break
                elif b.breaker_type == "BEARISH" and c.close > b.top:
                    b.is_mitigated = True
                    break

        return self.breakers

    def find_unicorn_confluences(
        self,
        fvgs: List[FairValueGap],
        timeframe: int = 5
    ) -> List[UnicornSetupCandidate]:
        """
        Cruza geometricamente os Breakers com FVGs não mitigados:
        Verifica se há sobreposição de preço acima do percentual configurado (ex.: >= 30%).
        """
        unicorns: List[UnicornSetupCandidate] = []

        for b in self.breakers:
            if b.is_mitigated:
                continue

            for fvg in fvgs:
                if fvg.is_mitigated or fvg.is_invalidated:
                    continue

                # Breaker de Baixa casa com FVG de Baixa
                if b.breaker_type == "BEARISH" and fvg.direction == "BEARISH":
                    ov_top = min(b.top, fvg.top)
                    ov_bot = max(b.bottom, fvg.bottom)
                    if ov_top > ov_bot:
                        ov_size = ov_top - ov_bot
                        min_size = min(b.size, fvg.size)
                        ratio = (ov_size / min_size) if min_size > 0 else 0
                        if ratio >= self.min_overlap_ratio:
                            unicorns.append(UnicornSetupCandidate(
                                breaker=b,
                                fvg=fvg,
                                direction=Direction.VENDA,
                                overlap_top=ov_top,
                                overlap_bottom=ov_bot,
                                overlap_ratio=ratio,
                                timeframe=timeframe,
                                timestamp=datetime.now()
                            ))

                # Breaker de Alta casa com FVG de Alta
                elif b.breaker_type == "BULLISH" and fvg.direction == "BULLISH":
                    ov_top = min(b.top, fvg.top)
                    ov_bot = max(b.bottom, fvg.bottom)
                    if ov_top > ov_bot:
                        ov_size = ov_top - ov_bot
                        min_size = min(b.size, fvg.size)
                        ratio = (ov_size / min_size) if min_size > 0 else 0
                        if ratio >= self.min_overlap_ratio:
                            unicorns.append(UnicornSetupCandidate(
                                breaker=b,
                                fvg=fvg,
                                direction=Direction.COMPRA,
                                overlap_top=ov_top,
                                overlap_bottom=ov_bot,
                                overlap_ratio=ratio,
                                timeframe=timeframe,
                                timestamp=datetime.now()
                            ))

        return unicorns


# =====================================================================
# 7. ORQUESTRADOR CENTRAL DE CONFLUÊNCIA SMC / ICT INSTITUCIONAL
# =====================================================================

class SMCAdvancedOrchestrator:
    """
    Orquestrador unificado que integra e pondera os 6 pilares de alta probabilidade:
    Gera um score de confluência institucional de 0 a 100 e atua como filtro de veto e disparador.
    """

    def __init__(self, asset_spec: Optional[AssetSpec] = None):
        self.spec = asset_spec or WIN_SPEC
        self.killzone_gate = KillzoneGate()
        self.amd_engine = PowerOfThreeEngine(asset_spec=self.spec)
        self.pool_engine = LiquidityPoolEngine(tolerance_pts=10.0, asset_spec=self.spec)
        self.ifvg_tracker = InversionFVGTracker(asset_spec=self.spec)
        self.smt_engine = SMTDivergenceEngine()
        self.unicorn_engine = ICTUnicornEngine(min_overlap_ratio=0.30, asset_spec=self.spec)

    def evaluate_confluence(
        self,
        current_price: float,
        timestamp: datetime,
        direction: Direction,
        is_continuation: bool,
        current_candle: Optional[Candle] = None,
        pivots: Optional[List[Pivot]] = None,
        active_fvgs: Optional[List[FairValueGap]] = None,
        flow_metrics: Optional[Dict[str, Any]] = None
    ) -> SMCConfluenceScore:
        score = 50.0  # Base neutra
        confirmations: List[str] = []
        vetoes: List[str] = []

        # 1. Avaliação de Killzone
        kz_session = self.killzone_gate.evaluate_session(timestamp, is_continuation_trade=is_continuation)
        if is_continuation and not kz_session.allows_continuation:
            vetoes.append(f"VETO KILLZONE: {kz_session.reason}")
        elif not is_continuation and not kz_session.allows_reversal:
            vetoes.append(f"VETO KILLZONE: {kz_session.reason}")
        else:
            if kz_session.active_killzone in (KillzoneType.MORNING_PRIME, KillzoneType.AFTERNOON_PRIME):
                score += 15.0
                confirmations.append(f"Killzone Institucional Ativa ({kz_session.active_killzone.value}): Alta liquidez.")

        # 2. Avaliação AMD / Judas Swing
        amd_allowed, amd_reason, amd_state = self.amd_engine.evaluate_amd(
            current_time=timestamp,
            direction=direction,
            is_breakout=is_continuation,
            current_price=current_price
        )
        if not amd_allowed:
            vetoes.append(f"VETO AMD: {amd_reason}")
        else:
            if "CONFIRMAÇÃO AMD" in amd_reason or "ALINHAMENTO INSTITUCIONAL" in amd_reason:
                score += 15.0
                confirmations.append(amd_reason)

        # 3. Avaliação de Ímãs de Liquidez (EQH / EQL)
        pool_ok, magnet_pool, magnet_reason = self.pool_engine.check_liquidity_magnet(
            current_price=current_price,
            trade_direction=direction,
            search_radius=120.0
        )
        if not pool_ok and magnet_pool:
            vetoes.append(f"VETO ÍMÃ DE LIQUIDEZ: {magnet_reason}")
        else:
            score += 5.0

        # 4. Avaliação de iFVG
        ifvg_hit, ifvg_obj, ifvg_reason = self.ifvg_tracker.check_ifvg_confluence(
            current_price=current_price,
            direction=direction
        )
        if ifvg_hit and ifvg_obj:
            score += 15.0
            confirmations.append(ifvg_reason)

        # 5. Avaliação Unicorn Model
        unicorn_cand = None
        if active_fvgs and pivots and current_candle:
            unicorns = self.unicorn_engine.find_unicorn_confluences(active_fvgs, timeframe=current_candle.timeframe)
            for uc in unicorns:
                if uc.direction == direction:
                    if uc.overlap_bottom <= current_price <= uc.overlap_top:
                        unicorn_cand = uc
                        score += 25.0
                        confirmations.append(
                            f"🦄 ICT UNICORN MODEL CONFIRMADO: Preço no Reteste da Interseção Breaker + FVG ({uc.timeframe}m) com {uc.overlap_ratio*100:.0f}% de sobreposição!"
                        )
                        break

        # 6. Avaliação de Divergência SMT
        smt_detected = False
        if len(self.smt_engine.active_divergences) > 0:
            last_smt = self.smt_engine.active_divergences[-1]
            if (direction == Direction.COMPRA and last_smt.divergence_type == "BULLISH") or \
               (direction == Direction.VENDA and last_smt.divergence_type == "BEARISH"):
                score += 20.0
                smt_detected = True
                confirmations.append(f"⚡ DIVERGÊNCIA SMT ATIVA: {last_smt.details}")

        total_score = min(100.0, max(0.0, score))
        is_institutional = (total_score >= 65.0) and (len(vetoes) == 0)

        return SMCConfluenceScore(
            total_score=total_score,
            is_institutional_grade=is_institutional,
            is_vetoed=len(vetoes) > 0,
            veto_reasons=vetoes,
            confirmations=confirmations,
            active_killzone=kz_session.active_killzone.value,
            amd_phase=amd_state.phase.value,
            unicorn_detected=unicorn_cand is not None,
            smt_divergence_detected=smt_detected,
            ifvg_active=ifvg_hit,
            liquidity_pool_magnet=magnet_pool.pool_type if magnet_pool else None
        )
