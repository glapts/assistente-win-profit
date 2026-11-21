"""
tests/test_smc_advanced.py
Bateria de testes unitários automatizados para os 6 Módulos Avançados de SMC / ICT:
1. 🦄 ICT Unicorn Model (Breaker Block + FVG sobrepostos)
2. ⚡ SMT Divergence Engine (Correlação WIN vs WDO)
3. ⏳ Power of 3 (AMD / Judas Swing)
4. 🧲 Liquidity Pools (EQH / EQL)
5. 🔄 Inversion FVG (iFVG)
6. 🕒 Time-Based Gating & Killzones
7. 🏛️ Orquestrador Central de Confluência Institucional
"""

import unittest
from datetime import datetime, timedelta, time as dt_time

from core.contract import TZ_BRASILIA, WIN_SPEC, WDO_SPEC
from core.models import (
    Candle, Pivot, FairValueGap, Direction, SignalSetup, SetupStatus,
    BreakerBlock, InversionFVG, LiquidityPool, SMTDivergenceEvent,
    KillzoneType, AMDPhase
)
from analysis.smc_advanced import (
    KillzoneGate, PowerOfThreeEngine, LiquidityPoolEngine,
    InversionFVGTracker, SMTDivergenceEngine, ICTUnicornEngine,
    SMCAdvancedOrchestrator
)


class TestSMCAdvanced(unittest.TestCase):

    def setUp(self):
        self.base_time = datetime(2026, 11, 10, 9, 0, 0, tzinfo=TZ_BRASILIA)

    # -----------------------------------------------------------------
    # 1. TESTES DO ICT UNICORN MODEL (BREAKER BLOCK + FVG)
    # -----------------------------------------------------------------
    def test_unicorn_model_bearish_synthetic(self):
        """
        Valida formação de Bearish Unicorn:
        1. Topo A (171.000)
        2. Fundo B (170.500)
        3. Topo C (171.200 - Sweep de A)
        4. Deslocamento com CHoCH rompendo Fundo B (Fechamento 170.300)
        5. FVG de Baixa sobreposto à faixa do Fundo B [170.400 - 170.600]
        6. Interseção geométrica >= 30% confirmando o Unicorn
        """
        engine = ICTUnicornEngine(min_overlap_ratio=0.30, asset_spec=WIN_SPEC)

        # Candles sintéticos
        c1 = Candle(5, self.base_time, self.base_time + timedelta(minutes=5), 170800, 171000, 170700, 170950, is_closed=True)
        c2 = Candle(5, self.base_time + timedelta(minutes=5), self.base_time + timedelta(minutes=10), 170950, 170960, 170450, 170500, is_closed=True)
        c3 = Candle(5, self.base_time + timedelta(minutes=10), self.base_time + timedelta(minutes=15), 170500, 171200, 170480, 171150, is_closed=True)
        c4 = Candle(5, self.base_time + timedelta(minutes=15), self.base_time + timedelta(minutes=20), 171150, 171180, 170600, 170650, is_closed=True)
        c5 = Candle(5, self.base_time + timedelta(minutes=20), self.base_time + timedelta(minutes=25), 170650, 170680, 170250, 170300, is_closed=True)

        candles = [c1, c2, c3, c4, c5]

        # Pivôs correspondentes
        p1 = Pivot("HIGH", 171000.0, 0, c1.close_time, 2)
        p2 = Pivot("LOW", 170450.0, 1, c2.close_time, 3)
        p3 = Pivot("HIGH", 171200.0, 2, c3.close_time, 4)
        pivots = [p1, p2, p3]

        # Detectar Breaker
        breakers = engine.detect_breakers(candles, pivots, timeframe=5)
        self.assertTrue(len(breakers) >= 1)
        b = breakers[0]
        self.assertEqual(b.breaker_type, "BEARISH")
        self.assertEqual(b.sweep_level, 171200.0)

        # FVG sintético de Baixa que cruza a faixa do Breaker
        fvg = FairValueGap(
            direction="BEARISH",
            top=170650.0,
            bottom=170400.0,
            start_bar=2,
            end_bar=4,
            timestamp=c5.close_time,
            timeframe=5
        )

        unicorns = engine.find_unicorn_confluences([fvg], timeframe=5)
        self.assertEqual(len(unicorns), 1)
        u = unicorns[0]
        self.assertEqual(u.direction, Direction.VENDA)
        self.assertGreaterEqual(u.overlap_ratio, 0.30)
        self.assertGreater(u.overlap_top, u.overlap_bottom)

    # -----------------------------------------------------------------
    # 2. TESTES DA DIVERGÊNCIA SMT (WIN vs WDO)
    # -----------------------------------------------------------------
    def test_smt_bullish_divergence(self):
        """
        Bullish SMT no WIN:
        - WIN faz Lower Low (170.000 < 170.500)
        - WDO falha em fazer Higher High (5.520 <= 5.530)
        Resultado: Divergência Compradora gerada com sucesso.
        """
        engine = SMTDivergenceEngine()
        t_now = self.base_time + timedelta(hours=1)

        ev = engine.evaluate_smt_divergence(
            current_time=t_now,
            current_win_price=170000.0,
            current_wdo_price=5518.0,
            win_recent_low=170000.0,
            win_prev_low=170500.0,
            wdo_recent_high=5520.0,
            wdo_prev_high=5530.0
        )

        self.assertIsNotNone(ev)
        self.assertEqual(ev.divergence_type, "BULLISH")
        self.assertEqual(ev.win_extreme_type, "LOWER_LOW")
        self.assertEqual(ev.wdo_extreme_type, "LOWER_HIGH")
        self.assertIn("SMT BULLISH WIN", ev.details)

    def test_smt_bearish_divergence(self):
        """
        Bearish SMT no WIN:
        - WIN faz Higher High (173.000 > 172.500)
        - WDO falha em fazer Lower Low (5.480 >= 5.470)
        Resultado: Divergência Vendedora gerada com sucesso.
        """
        engine = SMTDivergenceEngine()
        t_now = self.base_time + timedelta(hours=2)

        ev = engine.evaluate_smt_divergence(
            current_time=t_now,
            current_win_price=173000.0,
            current_wdo_price=5482.0,
            win_recent_high=173000.0,
            win_prev_high=172500.0,
            wdo_recent_low=5480.0,
            wdo_prev_low=5470.0
        )

        self.assertIsNotNone(ev)
        self.assertEqual(ev.divergence_type, "BEARISH")
        self.assertEqual(ev.win_extreme_type, "HIGHER_HIGH")
        self.assertEqual(ev.wdo_extreme_type, "HIGHER_LOW")
        self.assertIn("SMT BEARISH WIN", ev.details)

    # -----------------------------------------------------------------
    # 3. TESTES DO POWER OF 3 (AMD: ACUMULAÇÃO / MANIPULAÇÃO / DISTRIBUIÇÃO)
    # -----------------------------------------------------------------
    def test_power_of_three_judas_swing(self):
        """
        Valida:
        1. Acumulação 09:00-09:15 registra faixa inicial.
        2. Manipulação 09:15-10:00 proíbe rompimento de continuidade (veto).
        3. Permite venda se houve sweep da máxima do range de abertura.
        """
        engine = PowerOfThreeEngine()

        # Candle na fase de acumulação (09:05)
        c_acc = Candle(5, self.base_time + timedelta(minutes=5), self.base_time + timedelta(minutes=10),
                       171000, 171300, 170900, 171200, is_closed=True)
        engine.process_candle(c_acc)
        self.assertEqual(engine.initial_high, 171300.0)
        self.assertEqual(engine.initial_low, 170900.0)

        # Candle na fase de manipulação (09:25) que viola a máxima (171.350) e fecha abaixo (171.250)
        c_judas = Candle(5, self.base_time + timedelta(minutes=25), self.base_time + timedelta(minutes=30),
                         171200, 171350, 171150, 171250, is_closed=True)
        engine.process_candle(c_judas)
        self.assertTrue(engine.judas_sweep_high)

        # Tentativa de Rompimento de Compra às 09:30 -> DEVE SER VETADO
        t_eval = datetime(2026, 11, 10, 9, 30, tzinfo=TZ_BRASILIA)
        allowed, reason, state = engine.evaluate_amd(t_eval, Direction.COMPRA, is_breakout=True, current_price=171360)
        self.assertFalse(allowed)
        self.assertIn("VETO AMD / JUDAS SWING", reason)

        # Operação de Venda por Rejeição do Judas -> DEVE SER PERMITIDA
        allowed_rev, reason_rev, state_rev = engine.evaluate_amd(t_eval, Direction.VENDA, is_breakout=False, current_price=171250)
        self.assertTrue(allowed_rev)
        self.assertIn("CONFIRMAÇÃO AMD: Judas Swing", reason_rev)

    # -----------------------------------------------------------------
    # 4. TESTES DE LIQUIDITY POOLS (EQH / EQL)
    # -----------------------------------------------------------------
    def test_liquidity_pools_and_magnet(self):
        """
        Valida detecção de EQH (Topos Duplos dentro da tolerância de 10 pts)
        e atuação de ímã de atração (vetando venda enquanto o EQH não for varrido).
        """
        engine = LiquidityPoolEngine(tolerance_pts=10.0, asset_spec=WIN_SPEC)

        p1 = Pivot("HIGH", 172000.0, 5, self.base_time + timedelta(minutes=25), 7)
        p2 = Pivot("HIGH", 172005.0, 12, self.base_time + timedelta(minutes=60), 14)
        engine.update_from_pivots([p1, p2], timeframe=5)

        self.assertEqual(len(engine.active_pools), 1)
        pool = engine.active_pools[0]
        self.assertEqual(pool.pool_type, "EQH")
        self.assertAlmostEqual(pool.price_level, 172005.0, delta=5.0)

        # Preço em 171.950 (55 pts abaixo do EQH): Venda DEVE ser vetada por ímã
        ok, magnet_pool, reason = engine.check_liquidity_magnet(171950.0, Direction.VENDA, search_radius=120.0)
        self.assertFalse(ok)
        self.assertIsNotNone(magnet_pool)
        self.assertIn("ÍMÃ DE LIQUIDEZ ATIVO", reason)

        # Candle de Sweep que viola o EQH e fecha dentro
        c_sweep = Candle(5, self.base_time + timedelta(minutes=70), self.base_time + timedelta(minutes=75),
                         171980, 172020, 171950, 172000, is_closed=True)
        swept = engine.check_pool_sweep(c_sweep)
        self.assertEqual(len(swept), 1)
        self.assertTrue(pool.is_swept)

        # Agora que foi varrido, o ímã não bloqueia mais a venda
        ok_after, _, _ = engine.check_liquidity_magnet(171990.0, Direction.VENDA, search_radius=120.0)
        self.assertTrue(ok_after)

    # -----------------------------------------------------------------
    # 5. TESTES DE INVERSION FVG (iFVG)
    # -----------------------------------------------------------------
    def test_inversion_fvg_creation_and_retest(self):
        """
        Valida que FVG Bullish rompido para baixo vira iFVG de Resistência:
        - FVG Bullish: [171.000 - 171.200]
        - Candle fecha em 170.900 (< 171.000) -> iFVG de RESISTANCE criado.
        - Reteste subsequente no iFVG aciona confluência de Venda.
        """
        tracker = InversionFVGTracker(asset_spec=WIN_SPEC)

        fvg = FairValueGap("BULLISH", 171200.0, 171000.0, 1, 3, self.base_time, 5)

        # Candle rompendo para baixo
        c_break = Candle(5, self.base_time + timedelta(minutes=15), self.base_time + timedelta(minutes=20),
                         171100, 171120, 170850, 170900, is_closed=True)
        tracker.process_candle(c_break, [fvg])

        self.assertEqual(len(tracker.active_ifvgs), 1)
        ifvg = tracker.active_ifvgs[0]
        self.assertEqual(ifvg.original_direction, "BULLISH")
        self.assertEqual(ifvg.current_role, "RESISTANCE")
        self.assertEqual(ifvg.bottom, 171000.0)
        self.assertEqual(ifvg.top, 171200.0)

        # Reteste no iFVG em 171.050: Venda deve ter confluência ativada
        hit_venda, obj_venda, reason_venda = tracker.check_ifvg_confluence(171050.0, Direction.VENDA)
        self.assertTrue(hit_venda)
        self.assertIn("Resistência Invertida", reason_venda)

        # Compra no mesmo nível: NÃO deve ter confluência de suporte
        hit_compra, _, _ = tracker.check_ifvg_confluence(171050.0, Direction.COMPRA)
        self.assertFalse(hit_compra)

    # -----------------------------------------------------------------
    # 6. TESTES DE KILLZONES E TIME-BASED GATING
    # -----------------------------------------------------------------
    def test_killzone_gating_scenarios(self):
        """
        Valida as janelas institucionais:
        - 10:15: Morning Prime -> Permitido tudo.
        - 12:45: Chop Zone / Almoço -> Veto total de continuidade.
        - 15:00: Afternoon Prime -> Permitido tudo.
        - 17:15: Off-hours -> Veto total.
        """
        gate = KillzoneGate()

        # 10:15 (Morning Prime)
        t_1015 = datetime(2026, 11, 10, 10, 15, tzinfo=TZ_BRASILIA)
        allowed, _ = gate.is_trade_allowed(t_1015, is_continuation_trade=True)
        self.assertTrue(allowed)

        # 12:45 (Almoço / Chop Zone)
        t_1245 = datetime(2026, 11, 10, 12, 45, tzinfo=TZ_BRASILIA)
        allowed_lunch_cont, reason_lunch = gate.is_trade_allowed(t_1245, is_continuation_trade=True)
        self.assertFalse(allowed_lunch_cont)
        self.assertIn("Chop Zone / Almoço B3", reason_lunch)

        # 15:00 (Afternoon Prime)
        t_1500 = datetime(2026, 11, 10, 15, 0, tzinfo=TZ_BRASILIA)
        allowed_afternoon, _ = gate.is_trade_allowed(t_1500, is_continuation_trade=True)
        self.assertTrue(allowed_afternoon)

        # 17:15 (Off-Hours)
        t_1715 = datetime(2026, 11, 10, 17, 15, tzinfo=TZ_BRASILIA)
        allowed_late, _ = gate.is_trade_allowed(t_1715, is_continuation_trade=False)
        self.assertFalse(allowed_late)

    # -----------------------------------------------------------------
    # 7. TESTE DO ORQUESTRADOR CENTRAL DE CONFLUÊNCIA SMC
    # -----------------------------------------------------------------
    def test_smc_orchestrator_confluence_score(self):
        """
        Valida que o orquestrador calcula corretamente o score integrado
        e gera grau institucional quando confluências de alto impacto coincidem.
        """
        orch = SMCAdvancedOrchestrator(asset_spec=WIN_SPEC)
        t_prime = datetime(2026, 11, 10, 10, 30, tzinfo=TZ_BRASILIA)

        # Sem confluências extras na Killzone
        score_base = orch.evaluate_confluence(
            current_price=171500.0,
            timestamp=t_prime,
            direction=Direction.COMPRA,
            is_continuation=False
        )
        self.assertFalse(score_base.is_vetoed)
        self.assertGreaterEqual(score_base.total_score, 65.0)  # Killzone dá +15 -> 65
        self.assertTrue(score_base.is_institutional_grade)

        # Na hora do almoço com trade de continuidade -> DEVE SER VETADO
        t_lunch = datetime(2026, 11, 10, 12, 30, tzinfo=TZ_BRASILIA)
        score_lunch = orch.evaluate_confluence(
            current_price=171500.0,
            timestamp=t_lunch,
            direction=Direction.COMPRA,
            is_continuation=True
        )
        self.assertTrue(score_lunch.is_vetoed)
        self.assertFalse(score_lunch.is_institutional_grade)
        self.assertTrue(any("KILLZONE" in r for r in score_lunch.veto_reasons))

    # -----------------------------------------------------------------
    # 8. TESTES DE INTEGRAÇÃO COM SETUPENGINE (GATILHOS E FILTROS DE VETO)
    # -----------------------------------------------------------------
    def test_setup_engine_unicorn_model_trigger(self):
        """
        Valida que o SetupEngine dispara o gatilho 'Venda Unicorn Model (Breaker + FVG 5m)'
        quando a confluência geométrica entre Breaker e FVG ocorre.
        """
        from analysis.market_structure import MultiTimeframeMarketEngine
        from setups.setup_engine import SetupEngine

        struct_engine = MultiTimeframeMarketEngine()
        setup_engine = SetupEngine(mode="FIXO")

        # Injetar Breaker no time frame de 5m
        c1 = Candle(5, self.base_time, self.base_time + timedelta(minutes=5), 170800, 171000, 170700, 170950, is_closed=True)
        c2 = Candle(5, self.base_time + timedelta(minutes=5), self.base_time + timedelta(minutes=10), 170950, 170960, 170450, 170500, is_closed=True)
        c3 = Candle(5, self.base_time + timedelta(minutes=10), self.base_time + timedelta(minutes=15), 170500, 171200, 170480, 171150, is_closed=True)
        c4 = Candle(5, self.base_time + timedelta(minutes=15), self.base_time + timedelta(minutes=20), 171150, 171180, 170600, 170650, is_closed=True)
        c5 = Candle(5, self.base_time + timedelta(minutes=20), self.base_time + timedelta(minutes=25), 170650, 170680, 170250, 170300, is_closed=True)

        for c in [c1, c2, c3, c4, c5]:
            struct_engine.process_closed_candle(c)

        # Injetar FVG sobreposto ao Breaker [170.450 - 170.960]
        fvg = FairValueGap("BEARISH", 170700.0, 170480.0, 2, 4, c5.close_time, 5)
        struct_engine.analyzers[5].fvgs.append(fvg)

        # Forçar pivôs do Breaker
        struct_engine.analyzers[5].pivots = [
            Pivot("HIGH", 171000.0, 0, c1.close_time, 2),
            Pivot("LOW", 170450.0, 1, c2.close_time, 3),
            Pivot("HIGH", 171200.0, 2, c3.close_time, 4)
        ]

        # Preço retestando a interseção do Unicorn (ex.: 170.550)
        t_eval = datetime(2026, 11, 10, 10, 0, tzinfo=TZ_BRASILIA)
        setup, reason = setup_engine.evaluate(
            symbol="WINZ26",
            current_price=170550.0,
            timestamp=t_eval,
            structure_engine=struct_engine
        )

        self.assertIsNotNone(setup)
        self.assertIn("Unicorn Model", setup.setup_name)
        self.assertEqual(setup.direction, Direction.VENDA)
        self.assertTrue(any("Score SMC Institucional" in f for f in setup.facts_observed))

    def test_setup_engine_lunch_chop_veto(self):
        """
        Valida que com enable_smc_filters=True, um setup de rompimento na hora do almoço
        é categoricamente BLOQUEADO com alerta de veto nas obstáculos.
        """
        from analysis.market_structure import MultiTimeframeMarketEngine
        from setups.setup_engine import SetupEngine

        struct_engine = MultiTimeframeMarketEngine()
        setup_engine = SetupEngine(mode="FIXO", enable_smc_filters=True)

        # Simular rompimento de topo às 12:35 (Almoço)
        t_lunch = datetime(2026, 11, 10, 12, 35, tzinfo=TZ_BRASILIA)
        c1 = Candle(5, t_lunch - timedelta(minutes=15), t_lunch - timedelta(minutes=10), 170000, 170200, 169950, 170150, is_closed=True)
        c2 = Candle(5, t_lunch - timedelta(minutes=10), t_lunch - timedelta(minutes=5), 170150, 170500, 170100, 170450, is_closed=True)
        for c in [c1, c2]:
            struct_engine.process_closed_candle(c)

        setup, reason = setup_engine.evaluate(
            symbol="WINZ26",
            current_price=170480.0,
            timestamp=t_lunch,
            structure_engine=struct_engine
        )

        if setup is not None:
            self.assertEqual(setup.status, SetupStatus.BLOQUEADO)
            self.assertTrue(any("VETO SMC" in obs or "KILLZONE" in obs for obs in setup.obstacles))


if __name__ == "__main__":
    unittest.main()
