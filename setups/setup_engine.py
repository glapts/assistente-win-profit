"""
setups/setup_engine.py
Motor determinístico de geração e validação dos 8 setups obrigatórios de SMC + Tape Reading.
Respeita estritamente regras de risco/retorno, invalidação estrutural e confirmação de fluxo.
"""

from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta

from core.models import (
    SignalSetup, SetupStatus, Direction, MarketRegime, Candle
)
from core.contract import round_to_tick, calculate_financial_risk, WIN_SPEC, get_asset_spec
from analysis.market_structure import MultiTimeframeMarketEngine
from analysis.tape_reading import TapeReadingAnalyzer
from analysis.book_analyzer import BookAnalyzer
from analysis.smc_advanced import (
    SMCAdvancedOrchestrator, UnicornSetupCandidate, InversionFVG,
    KillzoneType, AMDPhase
)


class SetupEngine:
    """
    Avalia em sequência rigorosa:
    1. Regime de Mercado Multi-Timeframe
    2. Localização Estrutural (Extremos vs Centro)
    3. Elegibilidade dos 8 Setups Canônicos
    4. Confirmação do Fluxo (Delta / Absorção / Continuidade)
    5. Obstáculos e Espaço para o Alvo
    6. Stop e Invalidação (Modo Fixo vs Modo Estrutural)
    """

    def __init__(
        self,
        mode: str = "FIXO",
        asset_spec=None,
        smc_orchestrator: Optional[SMCAdvancedOrchestrator] = None,
        enable_smc_filters: bool = False,
        chattering_cooldown_seconds: int = 60
    ):
        self.mode = mode.upper()
        self.spec = asset_spec or WIN_SPEC
        self.active_setups: List[SignalSetup] = []
        self.smc_orchestrator = smc_orchestrator or SMCAdvancedOrchestrator(asset_spec=self.spec)
        self.enable_smc_filters = enable_smc_filters

        # Trava Anti-Chattering e Controle de Prioridade de Direção
        self.last_signal_direction: Optional[Direction] = None
        self.last_signal_time: Optional[datetime] = None
        self.last_signal_setup_name: Optional[str] = None
        self.chattering_cooldown_seconds: int = chattering_cooldown_seconds

    def evaluate(
        self,
        symbol: str,
        current_price: float,
        timestamp: datetime,
        structure_engine: MultiTimeframeMarketEngine,
        flow_analyzer: Optional[TapeReadingAnalyzer] = None,
        book_analyzer: Optional[BookAnalyzer] = None,
        feed_healthy: bool = True,
        sp500_filter: Optional[Any] = None
    ) -> Tuple[Optional[SignalSetup], str]:
        """
        Executa a verificação completa e retorna o setup mais qualificado
        ou a mensagem padrão 'SEM OPERAÇÃO — AGUARDAR' / 'ANÁLISE BLOQUEADA'.
        """
        if not feed_healthy:
            return None, "ANÁLISE BLOQUEADA — DADOS INSUFICIENTES OU DESATUALIZADOS"

        # 1. Regimes de Mercado
        regimes = structure_engine.get_regime_summary()
        context_dir, context_desc = structure_engine.get_context_direction()
        
        # Analisadores de tempos específicos
        a60 = structure_engine.analyzers[60]
        a30 = structure_engine.analyzers[30]
        a15 = structure_engine.analyzers[15]
        a10 = structure_engine.analyzers[10]
        a5 = structure_engine.analyzers[5]
        a2 = structure_engine.analyzers[2]
        a1 = structure_engine.analyzers[1]

        # 2. Diagnóstico de Fluxo e Book
        flow_available = flow_analyzer is not None and flow_analyzer.total_trades_count > 50
        flow_metrics = flow_analyzer.get_window_metrics(seconds=300) if flow_available else {}
        book_metrics = book_analyzer.evaluate_book_behavior(current_price) if book_analyzer else {}
        
        flow_confirmation_tag = "CONFIRMADO POR FLUXO" if flow_available else "SEM CONFIRMAÇÃO DE FLUXO"

        # Constantes dinâmicas proporcionais ao ativo
        tick = self.spec.tick_size
        tick_2 = tick * 2
        tick_3 = tick * 3
        tick_4 = tick * 4
        tick_6 = tick * 6
        tick_7 = tick * 7
        tick_8 = tick * 8
        disp_body = self.spec.min_displacement_body
        stop_pts = self.spec.default_stop_points
        delta_thresh = 50 if self.spec.symbol_base in ("WIN", "WDO") else 0

        # 3. Avaliar os Setups Canônicos e Módulo Especial de Abertura
        setup: Optional[SignalSetup] = None

        # Sincronização contínua com os motores SMC Avançados
        if a5.candles:
            self.smc_orchestrator.amd_engine.process_candle(a5.candles[-1])
            self.smc_orchestrator.ifvg_tracker.process_candle(a5.candles[-1], a5.fvgs)
        if a5.pivots:
            self.smc_orchestrator.pool_engine.update_from_pivots(a5.pivots, timeframe=5)
            self.smc_orchestrator.unicorn_engine.detect_breakers(a5.candles, a5.pivots, timeframe=5)

        # --- NOVOS SETUPS AVANÇADOS SMC / ICT INSTITUCIONAIS ---
        # 1. ICT Unicorn Model (Breaker Block + FVG sobrepostos)
        if not setup and a5.candles and a5.fvgs and a5.pivots:
            unicorns = self.smc_orchestrator.unicorn_engine.find_unicorn_confluences(a5.fvgs, timeframe=5)
            for uc in unicorns:
                if uc.overlap_bottom <= current_price <= uc.overlap_top:
                    is_bull = (uc.direction == Direction.COMPRA)
                    delta_val = flow_metrics.get("delta", 0) if flow_available else (delta_thresh if is_bull else -delta_thresh)
                    delta_ok = (delta_val >= -delta_thresh) if is_bull else (delta_val <= delta_thresh)
                    if delta_ok:
                        s_name = f"{'Compra' if is_bull else 'Venda'} Unicorn Model (Breaker + FVG 5m)"
                        setup = self._build_setup(
                            setup_name=s_name,
                            direction=uc.direction,
                            symbol=symbol,
                            current_price=current_price,
                            timestamp=timestamp,
                            tf_trigger=5,
                            in_trend=(uc.direction.value == context_dir),
                            invalidation_ref=uc.overlap_bottom - tick_3 if is_bull else uc.overlap_top + tick_3,
                            structure_desc=f"ICT Unicorn Model ({uc.timeframe}m): Reteste na confluência de Breaker Block [{uc.breaker.bottom:.0f}-{uc.breaker.top:.0f}] e FVG [{uc.fvg.bottom:.0f}-{uc.fvg.top:.0f}] com {uc.overlap_ratio*100:.0f}% de sobreposição",
                            flow_metrics=flow_metrics,
                            book_metrics=book_metrics,
                            flow_available=flow_available,
                            fvg_zone=f"[{uc.fvg.bottom:.0f}-{uc.fvg.top:.0f}]"
                        )
                        break

        # 2. Inversion FVG (iFVG - Reteste em Suporte/Resistência Invertido)
        if not setup and len(self.smc_orchestrator.ifvg_tracker.active_ifvgs) > 0:
            for ifvg in reversed(self.smc_orchestrator.ifvg_tracker.active_ifvgs):
                if ifvg.is_invalidated:
                    continue
                if ifvg.bottom <= current_price <= ifvg.top:
                    if ifvg.current_role == "SUPPORT":
                        delta_val = flow_metrics.get("delta", 0) if flow_available else delta_thresh
                        if delta_val >= -delta_thresh:
                            setup = self._build_setup(
                                setup_name=f"Compra no Reteste de Suporte Invertido (iFVG {ifvg.timeframe}m)",
                                direction=Direction.COMPRA,
                                symbol=symbol,
                                current_price=current_price,
                                timestamp=timestamp,
                                tf_trigger=ifvg.timeframe,
                                in_trend=(Direction.COMPRA.value == context_dir),
                                invalidation_ref=ifvg.bottom - tick_3,
                                structure_desc=f"Reteste em Suporte Invertido (iFVG {ifvg.timeframe}m): Ex-Bearish FVG [{ifvg.bottom:.0f}-{ifvg.top:.0f}] defendido por compradores",
                                flow_metrics=flow_metrics,
                                book_metrics=book_metrics,
                                flow_available=flow_available,
                                fvg_zone=f"[{ifvg.bottom:.0f}-{ifvg.top:.0f}]"
                            )
                            break
                    elif ifvg.current_role == "RESISTANCE":
                        delta_val = flow_metrics.get("delta", 0) if flow_available else -delta_thresh
                        if delta_val <= delta_thresh:
                            setup = self._build_setup(
                                setup_name=f"Venda no Reteste de Resistência Invertida (iFVG {ifvg.timeframe}m)",
                                direction=Direction.VENDA,
                                symbol=symbol,
                                current_price=current_price,
                                timestamp=timestamp,
                                tf_trigger=ifvg.timeframe,
                                in_trend=(Direction.VENDA.value == context_dir),
                                invalidation_ref=ifvg.top + tick_3,
                                structure_desc=f"Reteste em Resistência Invertida (iFVG {ifvg.timeframe}m): Ex-Bullish FVG [{ifvg.bottom:.0f}-{ifvg.top:.0f}] defendido por vendedores",
                                flow_metrics=flow_metrics,
                                book_metrics=book_metrics,
                                flow_available=flow_available,
                                fvg_zone=f"[{ifvg.bottom:.0f}-{ifvg.top:.0f}]"
                            )
                            break

        # --- MÓDULO ESPECIAL DE ABERTURA: 1ª Barra de 2m e 1ª Barra de 5m ---
        # Janela matinal de alta assimetria e liquidez institucional na B3 (09:02 às 10:15 para futuros, 10:02 às 10:45 para ações)
        is_equity = (self.spec.symbol_base == "VALE3" or self.spec.point_value == 1.0)
        is_morning_window = (
            (timestamp.hour == 10 and timestamp.minute <= 45) if is_equity
            else ((timestamp.hour == 9) or (timestamp.hour == 10 and timestamp.minute <= 15))
        )

        if not setup and is_morning_window:
            from datetime import time as dt_time
            t_session_start = dt_time(10, 0) if is_equity else dt_time(9, 0)
            
            # Filtrar estritamente candles que pertencem à sessão regular
            session_5m = [c for c in a5.candles if c.open_time.time() >= t_session_start]
            session_2m = [c for c in a2.candles if c.open_time.time() >= t_session_start]

            # 1. Opening Range com 1ª Barra de 5m
            if len(session_5m) >= 1:
                bar_5m_1 = session_5m[0]
                or_5m_high = bar_5m_1.high
                or_5m_low = bar_5m_1.low
                or_5m_body = bar_5m_1.close - bar_5m_1.open

                # Setup Abertura 1: Sweep da Máxima da 1ª Barra de 5m (Armadilha de Topo na Abertura)
                if len(session_5m) in [2, 3] or (len(session_2m) >= 3 and len(session_5m) == 1):
                    recent_high = max([c.high for c in session_5m] if len(session_5m) > 1 else [c.high for c in session_2m])
                    if recent_high > or_5m_high and current_price <= or_5m_high:
                        delta_val = flow_metrics.get("delta", 0) if flow_available else -delta_thresh
                        if delta_val <= delta_thresh:
                            setup = self._build_setup(
                                setup_name="Venda de Sweep da Máxima de Abertura (1ª Barra 5m)",
                                direction=Direction.VENDA,
                                symbol=symbol,
                                current_price=current_price,
                                timestamp=timestamp,
                                tf_trigger=5,
                                in_trend=False,
                                sweep_level=or_5m_high,
                                invalidation_ref=recent_high + tick_3,
                                structure_desc=f"Sweep da Máxima da 1ª barra de 5m ({or_5m_high:.2f}) com rejeição de topo e absorção vendedora",
                                flow_metrics=flow_metrics,
                                book_metrics=book_metrics,
                                flow_available=flow_available
                            )

                    # Setup Abertura 2: Sweep da Mínima da 1ª Barra de 5m (Armadilha de Fundo na Abertura)
                    recent_low = min([c.low for c in session_5m] if len(session_5m) > 1 else [c.low for c in session_2m])
                    if not setup and recent_low < or_5m_low and current_price >= or_5m_low:
                        delta_val = flow_metrics.get("delta", 0) if flow_available else delta_thresh
                        if delta_val >= -delta_thresh:
                            setup = self._build_setup(
                                setup_name="Compra de Sweep da Mínima de Abertura (1ª Barra 5m)",
                                direction=Direction.COMPRA,
                                symbol=symbol,
                                current_price=current_price,
                                timestamp=timestamp,
                                tf_trigger=5,
                                in_trend=False,
                                sweep_level=or_5m_low,
                                invalidation_ref=recent_low - tick_3,
                                structure_desc=f"Sweep da Mínima da 1ª barra de 5m ({or_5m_low:.2f}) com rejeição de fundo e absorção compradora",
                                flow_metrics=flow_metrics,
                                book_metrics=book_metrics,
                                flow_available=flow_available
                            )

                # Setup Abertura 3: Continuidade de Abertura (Opening Drive 5m)
                if not setup and abs(or_5m_body) >= (disp_body * 1.6):
                    if or_5m_body > 0 and current_price >= (bar_5m_1.open + or_5m_body * 0.25):
                        if (not flow_available) or (flow_metrics.get("delta", 0) >= -delta_thresh):
                            setup = self._build_setup(
                                setup_name="Compra de Continuidade da Abertura (Opening Drive 5m)",
                                direction=Direction.COMPRA,
                                symbol=symbol,
                                current_price=current_price,
                                timestamp=timestamp,
                                tf_trigger=5,
                                in_trend=True,
                                invalidation_ref=or_5m_low - tick_3,
                                structure_desc=f"Continuidade da 1ª barra de 5m compradora ({bar_5m_1.open:.2f} -> {bar_5m_1.close:.2f}) com fluxo a favor",
                                flow_metrics=flow_metrics,
                                book_metrics=book_metrics,
                                flow_available=flow_available
                            )
                    elif or_5m_body < 0 and current_price <= (bar_5m_1.open + or_5m_body * 0.25):
                        if (not flow_available) or (flow_metrics.get("delta", 0) <= delta_thresh):
                            setup = self._build_setup(
                                setup_name="Venda de Continuidade da Abertura (Opening Drive 5m)",
                                direction=Direction.VENDA,
                                symbol=symbol,
                                current_price=current_price,
                                timestamp=timestamp,
                                tf_trigger=5,
                                in_trend=True,
                                invalidation_ref=or_5m_high + tick_3,
                                structure_desc=f"Continuidade da 1ª barra de 5m vendedora ({bar_5m_1.open:.2f} -> {bar_5m_1.close:.2f}) com fluxo a favor",
                                flow_metrics=flow_metrics,
                                book_metrics=book_metrics,
                                flow_available=flow_available
                            )

            # 2. Opening Range com 1ª Barra de 2m (janela 09:02 a 09:05)
            elif not setup and len(session_2m) >= 1:
                bar_2m_1 = session_2m[0]
                or_2m_high = bar_2m_1.high
                or_2m_low = bar_2m_1.low
                or_2m_body = bar_2m_1.close - bar_2m_1.open

                # Sweep da 1ª barra de 2m
                if len(session_2m) >= 2:
                    c_recent = session_2m[-1]
                    if c_recent.high > or_2m_high and current_price <= or_2m_high:
                        setup = self._build_setup(
                            setup_name="Venda de Sweep da Máxima de Abertura (1ª Barra 2m)",
                            direction=Direction.VENDA,
                            symbol=symbol,
                            current_price=current_price,
                            timestamp=timestamp,
                            tf_trigger=2,
                            in_trend=False,
                            sweep_level=or_2m_high,
                            invalidation_ref=c_recent.high + tick_3,
                            structure_desc=f"Sweep da Máxima da 1ª barra de 2m ({or_2m_high:.2f}) na abertura",
                            flow_metrics=flow_metrics,
                            book_metrics=book_metrics,
                            flow_available=flow_available
                        )
                    elif not setup and c_recent.low < or_2m_low and current_price >= or_2m_low:
                        setup = self._build_setup(
                            setup_name="Compra de Sweep da Mínima de Abertura (1ª Barra 2m)",
                            direction=Direction.COMPRA,
                            symbol=symbol,
                            current_price=current_price,
                            timestamp=timestamp,
                            tf_trigger=2,
                            in_trend=False,
                            sweep_level=or_2m_low,
                            invalidation_ref=c_recent.low - tick_3,
                            structure_desc=f"Sweep da Mínima da 1ª barra de 2m ({or_2m_low:.2f}) na abertura",
                            flow_metrics=flow_metrics,
                            book_metrics=book_metrics,
                            flow_available=flow_available
                        )
                # Continuidade da 1ª barra de 2m
                if not setup and abs(or_2m_body) >= (disp_body * 1.4):
                    if or_2m_body > 0 and current_price >= bar_2m_1.open:
                        setup = self._build_setup(
                            setup_name="Compra de Continuidade da Abertura (Opening Drive 2m)",
                            direction=Direction.COMPRA,
                            symbol=symbol,
                            current_price=current_price,
                            timestamp=timestamp,
                            tf_trigger=2,
                            in_trend=True,
                            invalidation_ref=or_2m_low - tick_3,
                            structure_desc=f"Continuidade da 1ª barra de 2m compradora ({bar_2m_1.open:.2f} -> {bar_2m_1.close:.2f})",
                            flow_metrics=flow_metrics,
                            book_metrics=book_metrics,
                            flow_available=flow_available
                        )
                    elif or_2m_body < 0 and current_price <= bar_2m_1.open:
                        setup = self._build_setup(
                            setup_name="Venda de Continuidade da Abertura (Opening Drive 2m)",
                            direction=Direction.VENDA,
                            symbol=symbol,
                            current_price=current_price,
                            timestamp=timestamp,
                            tf_trigger=2,
                            in_trend=True,
                            invalidation_ref=or_2m_high + tick_3,
                            structure_desc=f"Continuidade da 1ª barra de 2m vendedora ({bar_2m_1.open:.2f} -> {bar_2m_1.close:.2f})",
                            flow_metrics=flow_metrics,
                            book_metrics=book_metrics,
                            flow_available=flow_available
                        )

        # --- SETUP 7: Operação Longa após Sweep em 60m, 30m ou 15m ---
        for tf, analyzer in [(60, a60), (30, a30), (15, a15)]:
            if analyzer.last_sweep and (len(analyzer.candles) - 1 - analyzer.last_sweep.bar_index) <= 3:
                sw = analyzer.last_sweep
                if sw.direction == "BULLISH": # Sweep de fundo -> Compra longa
                    if self._is_flow_aligned(Direction.COMPRA, flow_metrics, flow_available):
                        setup = self._build_setup(
                            setup_name=f"Operação Longa após Sweep em {tf}m",
                            direction=Direction.COMPRA,
                            symbol=symbol,
                            current_price=current_price,
                            timestamp=timestamp,
                            tf_trigger=tf,
                            in_trend=(context_dir == Direction.COMPRA),
                            sweep_level=sw.level_broken,
                            invalidation_ref=sw.level_broken - tick_3, # 3 ticks abaixo da mínima do sweep
                            structure_desc=sw.details,
                            flow_metrics=flow_metrics,
                            book_metrics=book_metrics,
                            flow_available=flow_available
                        )
                        if setup:
                            break
                elif sw.direction == "BEARISH": # Sweep de topo -> Venda longa
                    if self._is_flow_aligned(Direction.VENDA, flow_metrics, flow_available):
                        setup = self._build_setup(
                            setup_name=f"Operação Longa após Sweep em {tf}m",
                            direction=Direction.VENDA,
                            symbol=symbol,
                            current_price=current_price,
                            timestamp=timestamp,
                            tf_trigger=tf,
                            in_trend=(context_dir == Direction.VENDA),
                            sweep_level=sw.level_broken,
                            invalidation_ref=sw.level_broken + tick_3,
                            structure_desc=sw.details,
                            flow_metrics=flow_metrics,
                            book_metrics=book_metrics,
                            flow_available=flow_available
                        )
                        if setup:
                            break

        # --- SETUP 10: Defesa Institucional em Topos e Fundos (SMC Premium/Discount + Rejeição 1m + Book + T&T) ---
        if not setup:
            setup = self._check_top_bottom_institutional_defense(
                symbol=symbol,
                current_price=current_price,
                timestamp=timestamp,
                structure_engine=structure_engine,
                flow_metrics=flow_metrics,
                book_metrics=book_metrics,
                flow_available=flow_available,
                context_dir=context_dir,
                tick=tick,
                tick_2=tick_2,
                tick_3=tick_3,
                tick_4=tick_4,
                tick_6=tick_6,
                delta_thresh=delta_thresh
            )

        # --- SETUP 1: Compra de Continuidade em Tendência de Alta ---
        # Avalia se há tendência de alta em qualquer tempo (1m, 2m, 5m, 10m, 15m, 30m, 60m) ou fluxo comprador
        is_bullish_trend = (
            context_dir == Direction.COMPRA
            or any(structure_engine.analyzers[tf].regime == MarketRegime.ALTA for tf in [1, 2, 5, 10, 15, 30, 60])
            or (flow_available and flow_metrics.get("delta", 0) >= delta_thresh)
        )
        if not setup and is_bullish_trend:
            # Varre os 7 tempos gráficos para FVG (do micro 1m ao macro 60m)
            target_fvg = None
            tf_fvg = 5
            for tf_cand in [1, 2, 5, 10, 15, 30, 60]:
                analyzer_cand = structure_engine.analyzers[tf_cand]
                f = next((x for x in reversed(analyzer_cand.fvgs) if x.direction == "BULLISH" and not x.is_invalidated), None)
                if f and (f.bottom <= current_price <= f.top + tick_6):
                    target_fvg = f
                    tf_fvg = tf_cand
                    break

            if target_fvg:
                if (not flow_available) or (flow_metrics.get("delta", 0) >= -delta_thresh):
                    setup = self._build_setup(
                        setup_name="Compra de Continuidade em Tendência de Alta",
                        direction=Direction.COMPRA,
                        symbol=symbol,
                        current_price=current_price,
                        timestamp=timestamp,
                        tf_trigger=tf_fvg,
                        in_trend=True,
                        fvg_zone=f"{target_fvg.bottom:.2f} - {target_fvg.top:.2f} (FVG de {tf_fvg}m)",
                        invalidation_ref=target_fvg.bottom - tick_2,
                        structure_desc=f"Recuo em FVG de {tf_fvg}m ({target_fvg.bottom:.2f}-{target_fvg.top:.2f})",
                        flow_metrics=flow_metrics,
                        book_metrics=book_metrics,
                        flow_available=flow_available
                    )

        # --- SETUP 2: Venda de Continuidade em Tendência de Baixa ---
        # Avalia se há tendência de baixa em qualquer tempo (1m, 2m, 5m, 10m, 15m, 30m, 60m) ou fluxo vendedor
        is_bearish_trend = (
            context_dir == Direction.VENDA
            or any(structure_engine.analyzers[tf].regime == MarketRegime.BAIXA for tf in [1, 2, 5, 10, 15, 30, 60])
            or (flow_available and flow_metrics.get("delta", 0) <= -delta_thresh)
        )
        if not setup and is_bearish_trend:
            target_fvg = None
            tf_fvg = 5
            for tf_cand in [1, 2, 5, 10, 15, 30, 60]:
                analyzer_cand = structure_engine.analyzers[tf_cand]
                f = next((x for x in reversed(analyzer_cand.fvgs) if x.direction == "BEARISH" and not x.is_invalidated), None)
                if f and (f.bottom - tick_6 <= current_price <= f.top):
                    target_fvg = f
                    tf_fvg = tf_cand
                    break

            if target_fvg:
                if (not flow_available) or (flow_metrics.get("delta", 0) <= delta_thresh):
                    setup = self._build_setup(
                        setup_name="Venda de Continuidade em Tendência de Baixa",
                        direction=Direction.VENDA,
                        symbol=symbol,
                        current_price=current_price,
                        timestamp=timestamp,
                        tf_trigger=tf_fvg,
                        in_trend=True,
                        fvg_zone=f"{target_fvg.bottom:.2f} - {target_fvg.top:.2f} (FVG de {tf_fvg}m)",
                        invalidation_ref=target_fvg.top + tick_2,
                        structure_desc=f"Retração em FVG de {tf_fvg}m ({target_fvg.bottom:.2f}-{target_fvg.top:.2f})",
                        flow_metrics=flow_metrics,
                        book_metrics=book_metrics,
                        flow_available=flow_available
                    )

        # --- SETUP 3 & 4: Compra/Venda após Sweep de Mínima/Máxima (Em todos os 7 Tempos) ---
        if not setup:
            for tf_sweep in [1, 2, 5, 10, 15, 30, 60]:
                an_sw = structure_engine.analyzers[tf_sweep]
                if an_sw.last_sweep and (len(an_sw.candles) - 1 - an_sw.last_sweep.bar_index) <= 2:
                    sw = an_sw.last_sweep
                    if sw.direction == "BULLISH":
                        if self._is_flow_aligned(Direction.COMPRA, flow_metrics, flow_available):
                            setup = self._build_setup(
                                setup_name=f"Compra após Falso Rompimento da Mínima (Sweep {tf_sweep}m)",
                                direction=Direction.COMPRA,
                                symbol=symbol,
                                current_price=current_price,
                                timestamp=timestamp,
                                tf_trigger=tf_sweep,
                                in_trend=(context_dir == Direction.COMPRA),
                                sweep_level=sw.level_broken,
                                invalidation_ref=sw.level_broken - tick_3,
                                structure_desc=sw.details,
                                flow_metrics=flow_metrics,
                                book_metrics=book_metrics,
                                flow_available=flow_available
                            )
                            if setup:
                                break
                    elif sw.direction == "BEARISH":
                        if self._is_flow_aligned(Direction.VENDA, flow_metrics, flow_available):
                            setup = self._build_setup(
                                setup_name=f"Venda após Falso Rompimento da Máxima (Sweep {tf_sweep}m)",
                                direction=Direction.VENDA,
                                symbol=symbol,
                                current_price=current_price,
                                timestamp=timestamp,
                                tf_trigger=tf_sweep,
                                in_trend=(context_dir == Direction.VENDA),
                                sweep_level=sw.level_broken,
                                invalidation_ref=sw.level_broken + tick_3,
                                structure_desc=sw.details,
                                flow_metrics=flow_metrics,
                                book_metrics=book_metrics,
                                flow_available=flow_available
                            )
                            if setup:
                                break

        # --- SETUP 5 & 6: Reversão Confirmada com CHoCH (Em todos os 7 Tempos) ---
        if not setup:
            for tf_ch in [1, 2, 5, 10, 15, 30, 60]:
                an_ch = structure_engine.analyzers[tf_ch]
                if an_ch.last_choch and (len(an_ch.candles) - 1 - an_ch.last_choch.bar_index) <= 2:
                    ch = an_ch.last_choch
                    if ch.direction == "BULLISH":
                        if self._is_flow_aligned(Direction.COMPRA, flow_metrics, flow_available):
                            setup = self._build_setup(
                                setup_name=f"Compra com Reversão Confirmada (CHoCH {tf_ch}m)",
                                direction=Direction.COMPRA,
                                symbol=symbol,
                                current_price=current_price,
                                timestamp=timestamp,
                                tf_trigger=tf_ch,
                                in_trend=False,
                                structure_desc=ch.details,
                                invalidation_ref=ch.level_broken - tick_6,
                                flow_metrics=flow_metrics,
                                book_metrics=book_metrics,
                                flow_available=flow_available
                            )
                            if setup:
                                break
                    elif ch.direction == "BEARISH":
                        if self._is_flow_aligned(Direction.VENDA, flow_metrics, flow_available):
                            setup = self._build_setup(
                                setup_name=f"Venda com Reversão Confirmada (CHoCH {tf_ch}m)",
                                direction=Direction.VENDA,
                                symbol=symbol,
                                current_price=current_price,
                                timestamp=timestamp,
                                tf_trigger=tf_ch,
                                in_trend=False,
                                structure_desc=ch.details,
                                invalidation_ref=ch.level_broken + tick_6,
                                flow_metrics=flow_metrics,
                                book_metrics=book_metrics,
                                flow_available=flow_available
                            )
                            if setup:
                                break

        # --- SETUP 9: Reteste de 50% do FVG de Deslocamento / Consequent Encroachment (C.E.) com BOS ---
        if not setup:
            for tf_ce in [1, 2, 5, 10, 15, 30, 60]:
                an_ce = structure_engine.analyzers[tf_ce]
                if len(an_ce.candles) < 3:
                    continue
                
                # Avalia as últimas barras fechadas (de 1 a 3 barras atrás)
                for lookback in range(1, min(4, len(an_ce.candles))):
                    cand = an_ce.candles[-lookback]
                    body_size = abs(cand.close - cand.open)
                    total_range = cand.high - cand.low
                    
                    min_body = self.spec.ce_body_low if tf_ce <= 2 else self.spec.ce_body_high
                    if body_size < min_body or total_range < self.spec.tick_size:
                        continue
                    
                    # 1. CANDLE COMPRADOR DE DESLOCAMENTO (BULLISH)
                    if cand.close > cand.open:
                        upper_wick = cand.high - cand.close
                        if upper_wick > total_range * 0.35:
                            continue
                        
                        ce_50 = cand.open + (body_size * 0.5)
                        
                        # Preço atual na zona de pullback do 50%
                        if (ce_50 - tick_7) <= current_price <= (cand.close - tick_4) or abs(current_price - ce_50) <= tick_8:
                            if (not flow_available) or flow_metrics.get("delta", 0) >= -delta_thresh:
                                inv_price = min(cand.low - tick_3, current_price - stop_pts)
                                setup = self._build_setup(
                                    setup_name=f"Compra no Reteste de 50% do FVG de Deslocamento (C.E. {tf_ce}m)",
                                    direction=Direction.COMPRA,
                                    symbol=symbol,
                                    current_price=current_price,
                                    timestamp=timestamp,
                                    tf_trigger=tf_ce,
                                    in_trend=True,
                                    fvg_zone=f"{ce_50:.2f} (50% C.E. do corpo {cand.open:.2f}->{cand.close:.2f})",
                                    structure_desc=f"Reteste de 50% C.E. ({ce_50:.2f}) da barra de força de {tf_ce}m",
                                    invalidation_ref=inv_price,
                                    flow_metrics=flow_metrics,
                                    book_metrics=book_metrics,
                                    flow_available=flow_available
                                )
                                break
                    
                    # 2. CANDLE VENDEDOR DE DESLOCAMENTO (BEARISH)
                    elif cand.close < cand.open:
                        lower_wick = cand.close - cand.low
                        if lower_wick > total_range * 0.35:
                            continue
                        
                        ce_50 = cand.open - (body_size * 0.5)
                        
                        # Preço atual na zona de pullback do 50%
                        if (cand.close + tick_4) <= current_price <= (ce_50 + tick_7) or abs(current_price - ce_50) <= tick_8:
                            if (not flow_available) or flow_metrics.get("delta", 0) <= delta_thresh:
                                inv_price = max(cand.high + tick_3, current_price + stop_pts)
                                setup = self._build_setup(
                                    setup_name=f"Venda no Reteste de 50% do FVG de Deslocamento (C.E. {tf_ce}m)",
                                    direction=Direction.VENDA,
                                    symbol=symbol,
                                    current_price=current_price,
                                    timestamp=timestamp,
                                    tf_trigger=tf_ce,
                                    in_trend=True,
                                    fvg_zone=f"{ce_50:.2f} (50% C.E. do corpo {cand.open:.2f}->{cand.close:.2f})",
                                    structure_desc=f"Reteste de 50% C.E. ({ce_50:.2f}) da barra de força de {tf_ce}m",
                                    invalidation_ref=inv_price,
                                    flow_metrics=flow_metrics,
                                    book_metrics=book_metrics,
                                    flow_available=flow_available
                                )
                                break
                if setup:
                    break

        # --- SETUP: Rompimento Estrutural de Fundo/Topo com Continuidade (BOS / Breakdown / Breakout nos 7 Tempos) ---
        # NOTA CENÁRIO 3: Desconsidera rompimentos secos de 1m (exige confirmação a partir do 2m/5m para mitigar entradas esticadas)
        if not setup:
            for tf_bos in [2, 5, 10, 15, 30, 60]:
                an_bos = structure_engine.analyzers[tf_bos]
                if len(an_bos.candles) < 2:
                    continue

                # 1. Checagem de BOS registrado recentemente (até 3 barras atrás)
                if an_bos.last_bos and (len(an_bos.candles) - 1 - an_bos.last_bos.bar_index) <= 3:
                    bos = an_bos.last_bos
                    if bos.direction == "BEARISH" and ((not flow_available) or flow_metrics.get("delta", 0) <= delta_thresh):
                        setup = self._build_setup(
                            setup_name=f"Venda de Rompimento Estrutural (BOS {tf_bos}m / Breakdown com Continuidade)",
                            direction=Direction.VENDA,
                            symbol=symbol,
                            current_price=current_price,
                            timestamp=timestamp,
                            tf_trigger=tf_bos,
                            in_trend=True,
                            structure_desc=f"{bos.details} com confirmação de agressão vendedora",
                            invalidation_ref=bos.level_broken + tick_6,
                            flow_metrics=flow_metrics,
                            book_metrics=book_metrics,
                            flow_available=flow_available
                        )
                        if setup:
                            break
                    elif bos.direction == "BULLISH" and ((not flow_available) or flow_metrics.get("delta", 0) >= -delta_thresh):
                        setup = self._build_setup(
                            setup_name=f"Compra de Rompimento Estrutural (BOS {tf_bos}m / Breakout com Continuidade)",
                            direction=Direction.COMPRA,
                            symbol=symbol,
                            current_price=current_price,
                            timestamp=timestamp,
                            tf_trigger=tf_bos,
                            in_trend=True,
                            structure_desc=f"{bos.details} com confirmação de agressão compradora",
                            invalidation_ref=bos.level_broken - tick_6,
                            flow_metrics=flow_metrics,
                            book_metrics=book_metrics,
                            flow_available=flow_available
                        )
                        if setup:
                            break

                # 2. Rompimento Dinâmico de Mínima/Máxima Recente dos candles (para início de pregão e rompimentos sem pivô clássico formado)
                if not setup and len(an_bos.candles) >= 3:
                    for lookback in [1, 2, 3]:
                        if len(an_bos.candles) <= lookback:
                            continue
                        brk_cand = an_bos.candles[-lookback]
                        prior_candles = an_bos.candles[:-lookback]
                        if not prior_candles:
                            continue

                        ref_low = min(c.low for c in prior_candles[-10:])
                        ref_high = max(c.high for c in prior_candles[-10:])

                        # Rompimento de Fundo: candle fechou abaixo da mínima prévia com corpo expressivo
                        if brk_cand.close < ref_low and (brk_cand.open - brk_cand.close) >= (disp_body * 0.6):
                            if current_price <= ref_low + tick_4:
                                if (not flow_available) or (flow_metrics.get("delta", 0) <= delta_thresh):
                                    setup = self._build_setup(
                                        setup_name=f"Venda de Rompimento de Fundo com Continuidade (Breakdown {tf_bos}m)",
                                        direction=Direction.VENDA,
                                        symbol=symbol,
                                        current_price=current_price,
                                        timestamp=timestamp,
                                        tf_trigger=tf_bos,
                                        in_trend=True,
                                        structure_desc=f"Fechamento abaixo do fundo ({ref_low:.{self.spec.decimals}f}) no {tf_bos}m com agressão vendedora",
                                        invalidation_ref=ref_low + tick_6,
                                        flow_metrics=flow_metrics,
                                        book_metrics=book_metrics,
                                        flow_available=flow_available
                                    )
                                    if setup:
                                        break

                        # Rompimento de Topo: candle fechou acima da máxima prévia com corpo expressivo
                        elif brk_cand.close > ref_high and (brk_cand.close - brk_cand.open) >= (disp_body * 0.6):
                            if current_price >= ref_high - tick_4:
                                if (not flow_available) or (flow_metrics.get("delta", 0) >= -delta_thresh):
                                    setup = self._build_setup(
                                        setup_name=f"Compra de Rompimento de Topo com Continuidade (Breakout {tf_bos}m)",
                                        direction=Direction.COMPRA,
                                        symbol=symbol,
                                        current_price=current_price,
                                        timestamp=timestamp,
                                        tf_trigger=tf_bos,
                                        in_trend=True,
                                        structure_desc=f"Fechamento acima do topo ({ref_high:.{self.spec.decimals}f}) no {tf_bos}m com agressão compradora",
                                        invalidation_ref=ref_high - tick_6,
                                        flow_metrics=flow_metrics,
                                        book_metrics=book_metrics,
                                        flow_available=flow_available
                                    )
                                    if setup:
                                        break
                if setup:
                    break

        # --- SETUP 8: Operações nos Extremos de Consolidação / Caixote Intradiário ---
        if not setup:
            for tf_box in [5, 2, 1]:
                an_box = structure_engine.analyzers[tf_box]
                if len(an_box.candles) >= 8:
                    recent = an_box.candles[-14:] if len(an_box.candles) >= 14 else an_box.candles
                    high_ref = max(c.high for c in recent)
                    low_ref = min(c.low for c in recent)
                    range_total = high_ref - low_ref
                    
                    # Amplitude mínima e máxima do caixote proporcional ao ativo
                    box_min = self.spec.default_stop_points
                    box_max = self.spec.default_stop_points * 3.6
                    if box_min <= range_total <= box_max:
                        rel_pos = (current_price - low_ref) / range_total
                        # Evitar região central (30% a 70%) - operar somente nas bordas extremas
                        if rel_pos <= 0.15: # Borda inferior do caixote
                            # FILTRO 1: HIERARQUIA MACRO (MTF DOMINANCE)
                            # Se o contexto macro for de BAIXA (Direction.VENDA), não comprar caixote intradiário pequeno (<=5m)
                            if context_dir == Direction.VENDA and tf_box <= 5:
                                continue
                            if (not flow_available) or flow_metrics.get("delta", 0) >= -delta_thresh:
                                setup = self._build_setup(
                                    setup_name=f"Operação no Extremo Inferior do Caixote ({tf_box}m)",
                                    direction=Direction.COMPRA,
                                    symbol=symbol,
                                    current_price=current_price,
                                    timestamp=timestamp,
                                    tf_trigger=tf_box,
                                    in_trend=(context_dir == Direction.COMPRA),
                                    invalidation_ref=low_ref - tick_4,
                                    structure_desc=f"Extremidade inferior do caixote ({low_ref:.2f} a {high_ref:.2f}). Região central evitada.",
                                    flow_metrics=flow_metrics,
                                    book_metrics=book_metrics,
                                    flow_available=flow_available
                                )
                                break
                        elif rel_pos >= 0.85: # Borda superior do caixote
                            # FILTRO 1: HIERARQUIA MACRO (MTF DOMINANCE)
                            # Se o contexto macro for de ALTA (Direction.COMPRA), não vender caixote intradiário pequeno (<=5m)
                            if context_dir == Direction.COMPRA and tf_box <= 5:
                                continue
                            if (not flow_available) or flow_metrics.get("delta", 0) <= delta_thresh:
                                setup = self._build_setup(
                                    setup_name=f"Operação no Extremo Superior do Caixote ({tf_box}m)",
                                    direction=Direction.VENDA,
                                    symbol=symbol,
                                    current_price=current_price,
                                    timestamp=timestamp,
                                    tf_trigger=tf_box,
                                    in_trend=(context_dir == Direction.VENDA),
                                    invalidation_ref=high_ref + tick_4,
                                    structure_desc=f"Extremidade superior do caixote ({low_ref:.2f} a {high_ref:.2f}). Região central evitada.",
                                    flow_metrics=flow_metrics,
                                    book_metrics=book_metrics,
                                    flow_available=flow_available
                                )
                                break

        if setup is None:
            return None, "SEM OPERAÇÃO — AGUARDAR"

        # Avaliação de Confluência e Gating com os 6 Módulos SMC Avançados
        is_cont = setup.in_trend_direction
        confluence = self.smc_orchestrator.evaluate_confluence(
            current_price=current_price,
            timestamp=timestamp,
            direction=setup.direction,
            is_continuation=is_cont,
            current_candle=a5.candles[-1] if a5.candles else None,
            pivots=a5.pivots,
            active_fvgs=a5.fvgs,
            flow_metrics=flow_metrics
        )

        setup.facts_observed.append(f"Score SMC Institucional: {confluence.total_score:.0f}/100")
        for c_info in confluence.confirmations:
            if c_info not in setup.facts_observed:
                setup.facts_observed.append(f"[CONFIRMAÇÃO SMC] {c_info}")

        if confluence.is_institutional_grade:
            setup.interpretations.append("⭐ OPERAÇÃO DE GRAU INSTITUCIONAL SMC (Confluência >= 65%).")

        if self.enable_smc_filters and confluence.is_vetoed:
            setup.status = SetupStatus.BLOQUEADO
            for v in confluence.veto_reasons:
                setup.obstacles.append(f"[VETO SMC] {v}")

        # FILTRO TAPE READING: VETO ESTRITO DE ABSORÇÃO CONTRÁRIA
        flow_pat = ""
        if flow_metrics and isinstance(flow_metrics, dict):
            flow_pat = flow_metrics.get("flow_pattern", "")
        elif hasattr(setup, 'flow_evidence') and isinstance(setup.flow_evidence, dict):
            flow_pat = setup.flow_evidence.get("flow_pattern", "")

        if setup.direction == Direction.COMPRA and "ABSORÇÃO VENDEDORA" in flow_pat.upper():
            setup.status = SetupStatus.BLOQUEADO
            obs_msg = "[VETO TAPE READING] Absorção Vendedora detectada: Compradores agrediram massivamente sem deslocamento positivo. Risco iminente de armadilha no topo."
            setup.obstacles.append(obs_msg)
            setup.interpretations.append("⛔ " + obs_msg)
            setup.limitations.append("OPERAÇÃO BLOQUEADA: Absorção vendedora ativa no Tape Reading.")
        elif setup.direction == Direction.VENDA and "ABSORÇÃO COMPRADORA" in flow_pat.upper():
            setup.status = SetupStatus.BLOQUEADO
            obs_msg = "[VETO TAPE READING] Absorção Compradora detectada: Vendedores agrediram massivamente sem deslocamento negativo. Risco iminente de armadilha no fundo."
            setup.obstacles.append(obs_msg)
            setup.interpretations.append("⛔ " + obs_msg)
            setup.limitations.append("OPERAÇÃO BLOQUEADA: Absorção compradora ativa no Tape Reading.")

        # FILTRO 2: PRIORIDADE ÚNICA E TRAVA ANTI-CHATTERING (DEBOUNCE / COOLDOWN)
        if self.last_signal_direction is not None and setup.direction != self.last_signal_direction:
            if self.last_signal_time is not None:
                elapsed = (timestamp - self.last_signal_time).total_seconds()
                # Permitir reversão imediata APENAS se for CHoCH, Unicorn, FVG de Deslocamento ou timeframes maiores (>=10m)
                is_major_reversal = (
                    ("choch" in setup.setup_name.lower()) or
                    ("unicorn" in setup.setup_name.lower()) or
                    ("deslocamento" in setup.setup_name.lower()) or
                    ("reteste de 50%" in setup.setup_name.lower()) or
                    (getattr(setup, 'timeframe_trigger', 1) >= 10)
                )
                if elapsed < self.chattering_cooldown_seconds and not is_major_reversal:
                    return None, f"ANTI-CHATTERING: Sinal de {setup.direction.value} silenciado por cooldown ({elapsed:.0f}s < {self.chattering_cooldown_seconds}s)"

        self.last_signal_direction = setup.direction
        self.last_signal_time = timestamp
        self.last_signal_setup_name = setup.setup_name

        # Avaliação do Filtro Macro e Confluência Institucional S&P 500
        if sp500_filter is not None:
            macro_res = sp500_filter.evaluate_macro_filter(direction=setup.direction, timestamp=timestamp)
            setup.macro_status = macro_res.tag
            setup.macro_reason = macro_res.reason

            if not macro_res.is_allowed:
                setup.status = SetupStatus.BLOQUEADO
                if macro_res.tag not in setup.invalidation_criteria:
                    setup.invalidation_criteria = f"{macro_res.tag} {macro_res.reason} | {setup.invalidation_criteria}"
                setup.obstacles.append(f"{macro_res.tag} {macro_res.reason}")
                setup.limitations.append(f"OPERAÇÃO BLOQUEADA PELO FILTRO S&P 500: {macro_res.reason}")
            elif macro_res.is_confluence_boost:
                setup.score_smc = min(100, getattr(setup, 'score_smc', 75) + macro_res.score_bonus)
                setup.facts_observed.append(f"{macro_res.tag} {macro_res.reason}")
                setup.interpretations.append(
                    f"Alinhamento Macro Institucional: S&P 500 confirmando {setup.direction.value} em NY "
                    f"(+20 Score SMC -> {setup.score_smc}/100)."
                )
            else:
                if macro_res.tag:
                    setup.facts_observed.append(f"{macro_res.tag} {macro_res.reason}")

        return setup, "SETUP ELEGÍVEL ENCONTRADO"

    def _check_top_bottom_institutional_defense(
        self,
        symbol: str,
        current_price: float,
        timestamp: datetime,
        structure_engine: MultiTimeframeMarketEngine,
        flow_metrics: Dict[str, any],
        book_metrics: Dict[str, any],
        flow_available: bool,
        context_dir: Optional[Direction],
        tick: float,
        tick_2: float,
        tick_3: float,
        tick_4: float,
        tick_6: float,
        delta_thresh: float
    ) -> Optional[SignalSetup]:
        """
        Setup 10: Identifica defesa institucional ativa nos topos e fundos antes de romper.
        Confluência quádrupla:
        1. Localização Estrutural: Topo (Premium / Vender Caro) ou Fundo (Discount / Comprar Barato)
        2. Desbalanceamento no Candle de 1m: Pavio de rejeição >= 35% e fechamento direcional / delta no 1m
        3. Times & Trades (Contratos a Mercado): Agressões ativas a mercado / delta alinhado / absorção
        4. Book de Ofertas (Ordens Penduradas): Presença de barreira de lotes passivos no Book (bids no fundo / asks no topo)
        """
        a1 = structure_engine.analyzers[1]
        a5 = structure_engine.analyzers[5]
        a15 = structure_engine.analyzers[15]
        a30 = structure_engine.analyzers[30]
        a60 = structure_engine.analyzers[60]

        if not a1.candles:
            return None

        # Candle de 1m de referência
        cand_1m = a1.candles[-1]
        if cand_1m.range < (tick * 4):
            return None

        # Identificar níveis relevantes de Topo e Fundo estruturais
        candidate_highs = []
        candidate_lows = []

        for tf, an in [(60, a60), (30, a30), (15, a15), (5, a5), (1, a1)]:
            if an.last_confirmed_high:
                candidate_highs.append(an.last_confirmed_high.price)
            if an.last_confirmed_low:
                candidate_lows.append(an.last_confirmed_low.price)
            if an.candles:
                candidate_highs.append(max(c.high for c in an.candles[-20:]))
                candidate_lows.append(min(c.low for c in an.candles[-20:]))

        if not candidate_highs or not candidate_lows:
            return None

        macro_high = max(candidate_highs)
        macro_low = min(candidate_lows)
        macro_range = macro_high - macro_low

        max_proximity = tick * 24 # 120 pts no WIN, 12 pts no WDO, 0.24 em ações
        min_stop = self.spec.default_stop_points * 0.4

        # =========================================================================
        # 1. AVALIAÇÃO DE DEFESA NO TOPO (VENDA CARA / SMC PREMIUM / BEM VENDIDO)
        # =========================================================================
        top_candidates = [h for h in candidate_highs if (h - current_price) >= -tick_2 and (h - current_price) <= max_proximity]
        if top_candidates:
            top_level = max(top_candidates)
            
            # SMC Premium: no terço superior do range ou muito próximo ao topo
            is_premium = (macro_range > 0 and (current_price - macro_low) / macro_range >= 0.65) or ((top_level - current_price) <= (tick * 16))
            
            if is_premium and current_price <= (top_level + tick_2):
                tested_top = (cand_1m.high >= top_level - tick_6)
                upper_wick = cand_1m.upper_wick
                wick_rejection = (cand_1m.range > 0 and (upper_wick / cand_1m.range) >= 0.35)
                bearish_close = (cand_1m.close <= cand_1m.open + (cand_1m.body * 0.4)) or (cand_1m.close < cand_1m.open)
                delta_imbalance_1m = (cand_1m.sell_volume > cand_1m.buy_volume) if (cand_1m.sell_volume > 0 or cand_1m.buy_volume > 0) else False

                if tested_top and (wick_rejection or delta_imbalance_1m) and bearish_close:
                    # FILTRO 3: VALIDAÇÃO ESTRITA DE TOPO (CHoCH OBRIGATÓRIO)
                    # Se estiver em tendência macro de alta (Direction.COMPRA), NÃO aceitar venda por mero pavio!
                    # Exigir CHoCH obrigatório no 1m: fechamento abaixo da mínima do candle anterior e fechamento vendedor
                    choch_top_ok = True
                    if context_dir == Direction.COMPRA:
                        if len(a1.candles) >= 2:
                            prev_1m = a1.candles[-2]
                            has_choch = (cand_1m.close < prev_1m.low) and (cand_1m.close < cand_1m.open)
                            if not has_choch:
                                choch_top_ok = False
                        else:
                            choch_top_ok = (cand_1m.close < cand_1m.open)

                    if choch_top_ok:
                        # Times & Trades
                        tnt_ok = True
                        if flow_available:
                            pattern = flow_metrics.get("flow_pattern", "")
                            delta_val = flow_metrics.get("delta", 0)
                            if "Continuidade Compradora" in pattern:
                                tnt_ok = False
                            elif delta_val > delta_thresh and "Absorção Vendedora" not in pattern:
                                tnt_ok = False

                        # Book de Ofertas
                        book_ok = True
                        if book_metrics and book_metrics.get("status") != "Análise indisponível por limitação dos dados":
                            imbalance = book_metrics.get("book_imbalance_top5", 0.0)
                            if imbalance > 0.20:
                                book_ok = False

                        if tnt_ok and book_ok:
                            raw_inv = max(top_level, cand_1m.high) + tick_3
                            inv_ref = max(raw_inv, current_price + min_stop) if self.mode != "FIXO" else raw_inv

                            return self._build_setup(
                                setup_name="Venda por Defesa Institucional no Topo (Tape Reading + Desbalanceamento 1m)",
                                direction=Direction.VENDA,
                                symbol=symbol,
                                current_price=current_price,
                                timestamp=timestamp,
                                tf_trigger=1,
                                in_trend=(context_dir == Direction.VENDA),
                                sweep_level=top_level,
                                invalidation_ref=inv_ref,
                                structure_desc=(
                                    f"Defesa de topo em {top_level:.{self.spec.decimals}f} antes do rompimento. "
                                    f"Rejeição no 1m (pavio superior: {upper_wick:.{self.spec.decimals}f}) com absorção e ordens de venda no Book/T&T"
                                ),
                                flow_metrics=flow_metrics,
                                book_metrics=book_metrics,
                                flow_available=flow_available
                            )

        # =========================================================================
        # 2. AVALIAÇÃO DE DEFESA NO FUNDO (COMPRA BARATA / SMC DISCOUNT / BEM COMPRADO)
        # =========================================================================
        bot_candidates = [l for l in candidate_lows if (current_price - l) >= -tick_2 and (current_price - l) <= max_proximity]
        if bot_candidates:
            bottom_level = min(bot_candidates)
            
            # SMC Discount: no terço inferior do range ou muito próximo ao fundo
            is_discount = (macro_range > 0 and (current_price - macro_low) / macro_range <= 0.35) or ((current_price - bottom_level) <= (tick * 16))
            
            if is_discount and current_price >= (bottom_level - tick_2):
                tested_bot = (cand_1m.low <= bottom_level + tick_6)
                lower_wick = cand_1m.lower_wick
                wick_rejection = (cand_1m.range > 0 and (lower_wick / cand_1m.range) >= 0.35)
                bullish_close = (cand_1m.close >= cand_1m.open - (cand_1m.body * 0.4)) or (cand_1m.close > cand_1m.open)
                delta_imbalance_1m = (cand_1m.buy_volume > cand_1m.sell_volume) if (cand_1m.sell_volume > 0 or cand_1m.buy_volume > 0) else False

                if tested_bot and (wick_rejection or delta_imbalance_1m) and bullish_close:
                    # FILTRO 3: VALIDAÇÃO ESTRITA DE FUNDO (CHoCH OBRIGATÓRIO)
                    # Se estiver em tendência macro de baixa (Direction.VENDA), NÃO comprar faca caindo por mero pavio!
                    # Exigir CHoCH obrigatório no 1m: fechamento acima da máxima do candle anterior e fechamento comprador
                    choch_bot_ok = True
                    if context_dir == Direction.VENDA:
                        if len(a1.candles) >= 2:
                            prev_1m = a1.candles[-2]
                            has_choch = (cand_1m.close > prev_1m.high) and (cand_1m.close > cand_1m.open)
                            if not has_choch:
                                choch_bot_ok = False
                        else:
                            choch_bot_ok = (cand_1m.close > cand_1m.open)

                    if choch_bot_ok:
                        # Times & Trades
                        tnt_ok = True
                        if flow_available:
                            pattern = flow_metrics.get("flow_pattern", "")
                            delta_val = flow_metrics.get("delta", 0)
                            if "Continuidade Vendedora" in pattern:
                                tnt_ok = False
                            elif delta_val < -delta_thresh and "Absorção Compradora" not in pattern:
                                tnt_ok = False

                        # Book de Ofertas
                        book_ok = True
                        if book_metrics and book_metrics.get("status") != "Análise indisponível por limitação dos dados":
                            imbalance = book_metrics.get("book_imbalance_top5", 0.0)
                            if imbalance < -0.20:
                                book_ok = False

                        if tnt_ok and book_ok:
                            raw_inv = min(bottom_level, cand_1m.low) - tick_3
                            inv_ref = min(raw_inv, current_price - min_stop) if self.mode != "FIXO" else raw_inv

                            return self._build_setup(
                                setup_name="Compra por Defesa Institucional no Fundo (Tape Reading + Desbalanceamento 1m)",
                                direction=Direction.COMPRA,
                                symbol=symbol,
                                current_price=current_price,
                                timestamp=timestamp,
                                tf_trigger=1,
                                in_trend=(context_dir == Direction.COMPRA),
                                sweep_level=bottom_level,
                                invalidation_ref=inv_ref,
                                structure_desc=(
                                    f"Defesa de fundo em {bottom_level:.{self.spec.decimals}f} antes do rompimento. "
                                    f"Reação no 1m (pavio inferior: {lower_wick:.{self.spec.decimals}f}) com absorção e ordens de compra no Book/T&T"
                                ),
                                flow_metrics=flow_metrics,
                                book_metrics=book_metrics,
                                flow_available=flow_available
                            )

        return None

    def _is_flow_aligned(
        self,
        direction: Direction,
        flow_metrics: Optional[Dict[str, any]],
        flow_available: bool
    ) -> bool:
        """
        Valida se o fluxo de ordens (Times & Trades / Delta) confirma a direção da operação.
        Impede disparos de VENDA contra fluxo comprador contínuo ou COMPRA contra fluxo vendedor contínuo.
        """
        if not flow_available or not flow_metrics:
            return True

        delta = flow_metrics.get("delta", 0)
        pattern = flow_metrics.get("flow_pattern", "")

        # Trava estrita específica para VALE3: Delta positivo bloqueia VENDA, Delta negativo bloqueia COMPRA
        if self.spec.symbol_base == "VALE3":
            if direction == Direction.VENDA:
                if delta > 0:
                    return False
                if "Continuidade Compradora" in pattern:
                    return False
                if "Absorção Compradora" in pattern:
                    return False
                return True
            elif direction == Direction.COMPRA:
                if delta < 0:
                    return False
                if "Continuidade Vendedora" in pattern:
                    return False
                if "Absorção Vendedora" in pattern:
                    return False
                return True

        # Lógica original inalterada para Mini-Índice (WIN) e Mini-Dólar (WDO)
        flow_thresh = 50 if self.spec.symbol_base in ("WIN", "WDO") else 2000

        if direction == Direction.VENDA:
            # 1. Bloqueio absoluto se houver agressão com continuidade compradora
            if "Continuidade Compradora" in pattern:
                return False
            # 2. Bloqueio se delta for comprador (> thresh) e não for absorção passiva vendedora
            if delta > flow_thresh and "Absorção Vendedora" not in pattern:
                return False
            return True

        elif direction == Direction.COMPRA:
            # 1. Bloqueio absoluto se houver agressão com continuidade vendedora
            if "Continuidade Vendedora" in pattern:
                return False
            # 2. Bloqueio se delta for vendedor (< -thresh) e não for absorção passiva compradora
            if delta < -flow_thresh and "Absorção Compradora" not in pattern:
                return False
            return True

        return True

    def _build_setup(
        self,
        setup_name: str,
        direction: Direction,
        symbol: str,
        current_price: float,
        timestamp: datetime,
        tf_trigger: int,
        in_trend: bool,
        invalidation_ref: float,
        structure_desc: str,
        sweep_level: Optional[float] = None,
        fvg_zone: Optional[str] = None,
        flow_metrics: Optional[Dict[str, any]] = None,
        book_metrics: Optional[Dict[str, any]] = None,
        flow_available: bool = True
    ) -> Optional[SignalSetup]:
        """Calcula preços de entrada, stop e alvo de acordo com o modo."""
        # Trava de Confluência: impedir gatilho oposto à agressão de fluxo comprovada
        if not self._is_flow_aligned(direction, flow_metrics, flow_available):
            return None

        entry_price = round_to_tick(current_price, self.spec.tick_size)
        
        if self.mode == "FIXO":
            stop_points = self.spec.default_stop_points
            target_points = self.spec.default_target_points
            
            if direction == Direction.COMPRA:
                stop_price = round_to_tick(entry_price - stop_points, self.spec.tick_size)
                target_price = round_to_tick(entry_price + target_points, self.spec.tick_size)
                # Rejeitar se a entrada já violou a premissa técnica
                if entry_price < invalidation_ref:
                    return None
            else:
                stop_price = round_to_tick(entry_price + stop_points, self.spec.tick_size)
                target_price = round_to_tick(entry_price - target_points, self.spec.tick_size)
                # Rejeitar se a entrada já violou a premissa técnica
                if entry_price > invalidation_ref:
                    return None
        else: # ESTRUTURAL
            min_stop = self.spec.default_stop_points * 0.4
            max_stop = self.spec.default_stop_points * 2.0
            if direction == Direction.COMPRA:
                stop_price = round_to_tick(invalidation_ref, self.spec.tick_size)
                stop_points = round(entry_price - stop_price, 4)
                if stop_points < min_stop or stop_points > max_stop:
                    return None
                target_points = round_to_tick(stop_points * 1.6, self.spec.tick_size)
                target_price = round_to_tick(entry_price + target_points, self.spec.tick_size)
            else:
                stop_price = round_to_tick(invalidation_ref, self.spec.tick_size)
                stop_points = round(stop_price - entry_price, 4)
                if stop_points < min_stop or stop_points > max_stop:
                    return None
                target_points = round_to_tick(stop_points * 1.6, self.spec.tick_size)
                target_price = round_to_tick(entry_price - target_points, self.spec.tick_size)

        rr = round(target_points / stop_points, 2) if stop_points > 0 else 1.60
        dec = self.spec.decimals
        
        unit_label = "pts" if self.spec.symbol_base in ("WIN", "WDO") else "reais"
        fmt_val = lambda v: f"{v:,.{dec}f}".replace(".", "X").replace(",", ".").replace("X", ",")
        
        facts = [
            f"Preço atual: {fmt_val(entry_price)}",
            f"Estrutura: {structure_desc}",
            f"Modo de cálculo: {self.mode} (Stop: {stop_points:.{dec}f} {unit_label} | Alvo: {target_points:.{dec}f} {unit_label})"
        ]
        
        if flow_available:
            delta_val = flow_metrics.get("delta", 0)
            pattern_val = flow_metrics.get("flow_pattern", "N/D")
            facts.append(f"Fluxo recente: DELTA={delta_val:+d} | Padrão={pattern_val}")
        else:
            facts.append("Fluxo de ordens (Book/Times&Trades) indisponível no feed atual.")

        contracts_or_shares = getattr(self.spec, "contract_size", 1)
        risk_rs = calculate_financial_risk(stop_points, contracts_or_shares, self.spec.point_value)
        reward_rs = calculate_financial_risk(target_points, contracts_or_shares, self.spec.point_value)
        unit_name = "contrato" if self.spec.symbol_base in ("WIN", "WDO") else f"lote padrão ({contracts_or_shares} ações)"

        interpretations = [
            f"Setup {'a favor' if in_trend else 'contratendência'} em relação ao contexto macro.",
            f"Relação Retorno/Risco bruto: {rr:.2f} (R$ {risk_rs:.2f} de risco / R$ {reward_rs:.2f} de retorno por {unit_name})."
        ]

        limitations = [
            "Não há garantia de execução nos preços exatos (sujeito a slippage e latência).",
            "Níveis estruturais não comprovam localização de stops institucionais."
        ]
        if not flow_available:
            limitations.append("ANÁLISE ESTRUTURAL EXECUTADA SEM CONFIRMAÇÃO DE FLUXO.")

        initial_status = SetupStatus.CONFIRMADO if flow_available else SetupStatus.AGUARDANDO
        initial_obstacles = []
        flow_pat = flow_metrics.get("flow_pattern", "") if (flow_available and flow_metrics) else ""
        if direction == Direction.COMPRA and "ABSORÇÃO VENDEDORA" in flow_pat.upper():
            initial_status = SetupStatus.BLOQUEADO
            obs_msg = "[VETO TAPE READING] Absorção Vendedora detectada: Compradores agrediram massivamente sem deslocamento positivo. Risco iminente de armadilha no topo."
            initial_obstacles.append(obs_msg)
            interpretations.append("⛔ " + obs_msg)
            limitations.append("OPERAÇÃO BLOQUEADA: Absorção vendedora ativa no Tape Reading.")
        elif direction == Direction.VENDA and "ABSORÇÃO COMPRADORA" in flow_pat.upper():
            initial_status = SetupStatus.BLOQUEADO
            obs_msg = "[VETO TAPE READING] Absorção Compradora detectada: Vendedores agrediram massivamente sem deslocamento negativo. Risco iminente de armadilha no fundo."
            initial_obstacles.append(obs_msg)
            interpretations.append("⛔ " + obs_msg)
            limitations.append("OPERAÇÃO BLOQUEADA: Absorção compradora ativa no Tape Reading.")

        return SignalSetup(
            timestamp=timestamp,
            setup_name=setup_name,
            direction=direction,
            symbol=symbol,
            status=initial_status,
            entry_price=entry_price,
            stop_price=stop_price,
            stop_points=stop_points,
            target_price=target_price,
            target_points=target_points,
            risk_reward=rr,
            timeframe_trigger=tf_trigger,
            in_trend_direction=in_trend,
            sweep_level=sweep_level,
            fvg_zone=fvg_zone,
            structure_event=structure_desc,
            book_evidence=book_metrics or {},
            flow_evidence=flow_metrics or {},
            obstacles=initial_obstacles,
            facts_observed=facts,
            interpretations=interpretations,
            limitations=limitations,
            validity_deadline=timestamp + timedelta(minutes=tf_trigger * 3),
            invalidation_criteria=f"Superação do nível {fmt_val(stop_price)} ou quebra da premissa estrutural."
        )
