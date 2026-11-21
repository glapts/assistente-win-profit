import unittest
from datetime import datetime, timedelta
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.models import Candle, Direction, MarketRegime
from core.contract import TZ_BRASILIA, WIN_SPEC
from analysis.market_structure import MultiTimeframeMarketEngine
from analysis.fvg_mtf_scanner import FGVMTFScanner, ActiveMTFFVG
from setups.setup_engine import SetupEngine


class TestImprovements(unittest.TestCase):
    def setUp(self):
        self.base_time = datetime(2026, 11, 10, 10, 0, 0, tzinfo=TZ_BRASILIA)

    def test_mtf_dominance_blocks_counter_trend_box(self):
        """Valida que o Filtro MTF Dominance bloqueia compras/vendas de caixote contra a tendência macro."""
        engine = MultiTimeframeMarketEngine()
        setup_engine = SetupEngine(mode="FIXO")
        
        # Simula contexto macro de ALTA (60m e 30m em ALTA)
        engine.analyzers[60].regime = MarketRegime.ALTA
        engine.analyzers[30].regime = MarketRegime.ALTA
        context_dir, _ = engine.get_context_direction()
        self.assertEqual(context_dir, Direction.COMPRA)
        
        # Cria caixote de 2m onde preço está na borda superior (rel_pos >= 0.85)
        for i in range(15):
            t = self.base_time + timedelta(minutes=2*i)
            c = Candle(2, t, t + timedelta(minutes=2), 174000, 174500, 174000, 174450, is_closed=True)
            engine.process_closed_candle(c)
            
        # Avalia a 174480 (topo do caixote)
        setup, reason = setup_engine.evaluate(
            symbol="WINZ26",
            current_price=174480.0,
            timestamp=self.base_time + timedelta(minutes=30),
            structure_engine=engine,
            feed_healthy=True
        )
        
        # Em tendência macro de ALTA, a venda no topo do caixote de 2m DEVE ser bloqueada/suprimida
        if setup:
            self.assertNotEqual(setup.setup_name, "Operação no Extremo Superior do Caixote (2m)")

    def test_strict_choch_on_top_defense(self):
        """Valida que a Venda por Defesa no Topo em tendência de alta exige CHoCH estrito no 1m."""
        engine = MultiTimeframeMarketEngine()
        setup_engine = SetupEngine(mode="FIXO")
        
        engine.analyzers[60].regime = MarketRegime.ALTA
        engine.analyzers[30].regime = MarketRegime.ALTA
        engine.seed_session_extremes(174000.0, 175200.0, 173800.0, self.base_time)
        
        # Barra 1: Barra compradora forte
        c1 = Candle(1, self.base_time, self.base_time + timedelta(minutes=1), 175000, 175150, 174980, 175140, is_closed=True)
        # Barra 2: Testa o topo com pavio, MAS NÃO quebra a mínima da barra 1 (fechamento 175050 > 174980)
        c2 = Candle(1, self.base_time + timedelta(minutes=1), self.base_time + timedelta(minutes=2), 175140, 175200, 175020, 175050, is_closed=True)
        
        engine.process_closed_candle(c1)
        engine.process_closed_candle(c2)
        
        flow_mock = type('obj', (object,), {
            'total_trades_count': 100,
            'get_window_metrics': lambda self, seconds=300: {"delta": -200, "flow_pattern": "Agressão Vendedora"}
        })()
        
        setup, _ = setup_engine.evaluate(
            symbol="WINZ26",
            current_price=175050.0,
            timestamp=self.base_time + timedelta(minutes=2),
            structure_engine=engine,
            flow_analyzer=flow_mock,
            feed_healthy=True
        )
        
        # Sem CHoCH (fechamento abaixo de 174980), o setup de Defesa no Topo NÃO PODE disparar venda em tendência de alta
        if setup:
            self.assertNotIn("Venda por Defesa Institucional no Topo", setup.setup_name)

    def test_anti_chattering_filter(self):
        """Valida que sinais rápidos alternados em menos de 60s são silenciados pela trava anti-chattering."""
        setup_engine = SetupEngine(mode="FIXO", chattering_cooldown_seconds=60)
        
        t0 = self.base_time
        # Registra um sinal de VENDA às 10:00:00
        setup_engine.last_signal_direction = Direction.VENDA
        setup_engine.last_signal_time = t0
        setup_engine.last_signal_setup_name = "Venda Teste"
        
        # Tenta disparar uma VENDA rápida de caixote às 10:00:15 (apenas 15s depois)
        engine = MultiTimeframeMarketEngine()
        engine.analyzers[60].regime = MarketRegime.TRANSICAO
        engine.analyzers[30].regime = MarketRegime.TRANSICAO
        
        # Simula caixote
        for i in range(15):
            t = t0 + timedelta(minutes=2*i)
            c = Candle(2, t, t + timedelta(minutes=2), 174000, 174500, 174000, 174450, is_closed=True)
            engine.process_closed_candle(c)
            
        setup, reason = setup_engine.evaluate(
            symbol="WINZ26",
            current_price=174480.0,
            timestamp=t0 + timedelta(seconds=15),
            structure_engine=engine,
            feed_healthy=True
        )
        
        # Deve ter sido bloqueado pelo Anti-Chattering
        self.assertIsNone(setup)
        self.assertIn("ANTI-CHATTERING", reason)

    def test_fvg_scanner_obstacle_info(self):
        """Valida que o scanner identifica corretamente obstáculos intraday vs macro e distância da borda."""
        scanner = FGVMTFScanner(asset_spec=WIN_SPEC, auto_load=False)
        scanner.active_fvgs = {tf: [] for tf in scanner.MONITORED_TIMEFRAMES}
        scanner.liquidated_archive = {tf: [] for tf in scanner.MONITORED_TIMEFRAMES}
        scanner._fvg_by_id = {}

        # FVG Bearish de 5m (Intraday) em 174.200 - 174.300
        fvg_5m = ActiveMTFFVG(
            timeframe=5,
            direction="BEARISH",
            top=174300.0,
            bottom=174200.0,
            ce_50=174250.0,
            formed_time=self.base_time
        )
        scanner.active_fvgs[5].append(fvg_5m)

        obs_info = scanner.get_closest_obstacle_info(Direction.COMPRA, entry_price=174000.0, target_price=174400.0)
        self.assertIsNotNone(obs_info)
        self.assertEqual(obs_info['distance'], 200.0)
        self.assertEqual(obs_info['edge_price'], 174200.0)
        self.assertFalse(obs_info['is_macro'])

        # FVG Bearish de 60m (Macro) em 174.350 - 174.450
        fvg_60m = ActiveMTFFVG(
            timeframe=60,
            direction="BEARISH",
            top=174450.0,
            bottom=174350.0,
            ce_50=174400.0,
            formed_time=self.base_time
        )
        scanner.active_fvgs[60].append(fvg_60m)

        all_obs = scanner.get_target_obstacles_info(Direction.COMPRA, entry_price=174000.0, target_price=174500.0)
        self.assertEqual(len(all_obs), 2)
        self.assertTrue(any(obs['is_macro'] for obs in all_obs))

    def test_fvg_flow_override_and_adaptive_target(self):
        """Melhorias A e B: Valida desbloqueio por Flow Override institucional e cálculo de Alvo Parcial."""
        from feeds.replay_feed import ReplayMarketFeed
        from core.engine import WinAnalysisAssistant
        from core.models import SignalSetup, SetupStatus

        feed = ReplayMarketFeed(symbol="WINZ26", initial_price=174000.0)
        assistant = WinAnalysisAssistant(feed=feed, symbol="WINZ26")
        assistant.fvg_scanner.active_fvgs = {tf: [] for tf in assistant.fvg_scanner.MONITORED_TIMEFRAMES}
        assistant.fvg_scanner.liquidated_archive = {tf: [] for tf in assistant.fvg_scanner.MONITORED_TIMEFRAMES}
        assistant.fvg_scanner._fvg_by_id = {}

        # Injeta FVG Intraday de 5m Bearish a 150 pts da entrada (174.150 - 174.250)
        fvg_5m = ActiveMTFFVG(
            timeframe=5,
            direction="BEARISH",
            top=174250.0,
            bottom=174150.0,
            ce_50=174200.0,
            formed_time=self.base_time
        )
        assistant.fvg_scanner.active_fvgs[5].append(fvg_5m)

        # Mock de setup de rompimento de alta
        setup = SignalSetup(
            timestamp=self.base_time,
            symbol="WINZ26",
            direction=Direction.COMPRA,
            setup_name="Rompimento de Alta com Momentum",
            status=SetupStatus.CONFIRMADO,
            entry_price=174000.0,
            stop_price=173850.0,
            stop_points=150.0,
            target_price=174400.0,
            target_points=400.0,
            risk_reward=2.67,
            timeframe_trigger=2,
            in_trend_direction=True
        )

        # Fluxo institucional massivo (Delta +4.500, Deslocamento +60 pts)
        mock_flow = {
            "buy_volume": 15000,
            "sell_volume": 10500,
            "delta": 4500,
            "price_displacement_pts": 60.0,
            "flow_pattern": "Agressão com Continuidade Compradora"
        }

        assistant.setup_engine.evaluate = lambda **kwargs: (setup, "OK")
        assistant.flow_analyzer.get_window_metrics = lambda seconds=300: mock_flow

        # Executa o ciclo de avaliação do engine
        alert = assistant.evaluate_now()

        # O setup DEVE ser confirmado via Flow Override
        self.assertEqual(setup.status, SetupStatus.CONFIRMADO)
        self.assertTrue(any("FLOW OVERRIDE ATIVO" in interp for interp in setup.interpretations))
        # Alvo parcial deve ser a borda inferior do FVG (174.150) a 150 pts de distância
        self.assertEqual(setup.partial_target_price, 174150.0)
        self.assertEqual(setup.partial_target_points, 150.0)

    def test_fvg_macro_strict_block(self):
        """Melhoria C: Valida que FVG Macro (60m) SEMPRE bloqueia, mesmo com Delta massivo."""
        from feeds.replay_feed import ReplayMarketFeed
        from core.engine import WinAnalysisAssistant
        from core.models import SignalSetup, SetupStatus

        feed = ReplayMarketFeed(symbol="WINZ26", initial_price=174000.0)
        assistant = WinAnalysisAssistant(feed=feed, symbol="WINZ26")
        assistant.fvg_scanner.active_fvgs = {tf: [] for tf in assistant.fvg_scanner.MONITORED_TIMEFRAMES}
        assistant.fvg_scanner.liquidated_archive = {tf: [] for tf in assistant.fvg_scanner.MONITORED_TIMEFRAMES}
        assistant.fvg_scanner._fvg_by_id = {}

        # Injeta FVG Macro de 60m Bearish a 150 pts da entrada (174.150 - 174.250)
        fvg_60m = ActiveMTFFVG(
            timeframe=60,
            direction="BEARISH",
            top=174250.0,
            bottom=174150.0,
            ce_50=174200.0,
            formed_time=self.base_time
        )
        assistant.fvg_scanner.active_fvgs[60].append(fvg_60m)

        setup = SignalSetup(
            timestamp=self.base_time,
            symbol="WINZ26",
            direction=Direction.COMPRA,
            setup_name="Rompimento de Alta com Momentum",
            status=SetupStatus.CONFIRMADO,
            entry_price=174000.0,
            stop_price=173850.0,
            stop_points=150.0,
            target_price=174400.0,
            target_points=400.0,
            risk_reward=2.67,
            timeframe_trigger=2,
            in_trend_direction=True
        )

        # Delta de +12.000 (fluxo institucional muito alto, mas contra FVG Macro de 60m)
        mock_flow = {
            "buy_volume": 20000,
            "sell_volume": 8000,
            "delta": 12000,
            "price_displacement_pts": 70.0,
            "flow_pattern": "Agressão com Continuidade Compradora"
        }

        assistant.setup_engine.evaluate = lambda **kwargs: (setup, "OK")
        assistant.flow_analyzer.get_window_metrics = lambda seconds=300: mock_flow

        assistant.evaluate_now()

        # DEVE ser BLOQUEADO por ser obstáculo institucional MACRO
        self.assertEqual(setup.status, SetupStatus.BLOQUEADO)
        self.assertTrue(any("BLOQUEIO MACRO FVG" in interp for interp in setup.interpretations))

    def test_fvg_weak_flow_remains_blocked(self):
        """Valida que FVG Intraday continua BLOQUEADO se o fluxo institucional for insuficiente."""
        from feeds.replay_feed import ReplayMarketFeed
        from core.engine import WinAnalysisAssistant
        from core.models import SignalSetup, SetupStatus

        feed = ReplayMarketFeed(symbol="WINZ26", initial_price=174000.0)
        assistant = WinAnalysisAssistant(feed=feed, symbol="WINZ26")
        assistant.fvg_scanner.active_fvgs = {tf: [] for tf in assistant.fvg_scanner.MONITORED_TIMEFRAMES}
        assistant.fvg_scanner.liquidated_archive = {tf: [] for tf in assistant.fvg_scanner.MONITORED_TIMEFRAMES}
        assistant.fvg_scanner._fvg_by_id = {}

        # Injeta FVG Intraday de 5m Bearish
        fvg_5m = ActiveMTFFVG(
            timeframe=5,
            direction="BEARISH",
            top=174250.0,
            bottom=174150.0,
            ce_50=174200.0,
            formed_time=self.base_time
        )
        assistant.fvg_scanner.active_fvgs[5].append(fvg_5m)

        setup = SignalSetup(
            timestamp=self.base_time,
            symbol="WINZ26",
            direction=Direction.COMPRA,
            setup_name="Rompimento de Alta com Momentum",
            status=SetupStatus.CONFIRMADO,
            entry_price=174000.0,
            stop_price=173850.0,
            stop_points=150.0,
            target_price=174400.0,
            target_points=400.0,
            risk_reward=2.67,
            timeframe_trigger=2,
            in_trend_direction=True
        )

        # Fluxo insuficiente (Delta de apenas +500)
        mock_flow = {
            "buy_volume": 3000,
            "sell_volume": 2500,
            "delta": 500,
            "price_displacement_pts": 15.0,
            "flow_pattern": "Agressão Compradora Moderada"
        }

        assistant.setup_engine.evaluate = lambda **kwargs: (setup, "OK")
        assistant.flow_analyzer.get_window_metrics = lambda seconds=300: mock_flow

        assistant.evaluate_now()

        # DEVE ser BLOQUEADO pois não atinge o limiar institucional de Flow Override
        self.assertEqual(setup.status, SetupStatus.BLOQUEADO)

    def test_fvg_flow_override_venda(self):
        """Melhoria A: Valida desbloqueio por Flow Override institucional para operações de VENDA."""
        from feeds.replay_feed import ReplayMarketFeed
        from core.engine import WinAnalysisAssistant
        from core.models import SignalSetup, SetupStatus

        feed = ReplayMarketFeed(symbol="WINZ26", initial_price=174000.0)
        assistant = WinAnalysisAssistant(feed=feed, symbol="WINZ26")
        assistant.fvg_scanner.active_fvgs = {tf: [] for tf in assistant.fvg_scanner.MONITORED_TIMEFRAMES}
        assistant.fvg_scanner.liquidated_archive = {tf: [] for tf in assistant.fvg_scanner.MONITORED_TIMEFRAMES}
        assistant.fvg_scanner._fvg_by_id = {}

        # Injeta FVG Bullish (Suporte) de 5m a 150 pts abaixo da entrada (173.850 - 173.750)
        fvg_5m = ActiveMTFFVG(
            timeframe=5,
            direction="BULLISH",
            top=173850.0,
            bottom=173750.0,
            ce_50=173800.0,
            formed_time=self.base_time
        )
        assistant.fvg_scanner.active_fvgs[5].append(fvg_5m)

        # Mock de setup de rompimento de baixa
        setup = SignalSetup(
            timestamp=self.base_time,
            symbol="WINZ26",
            direction=Direction.VENDA,
            setup_name="Rompimento de Baixa com Momentum",
            status=SetupStatus.CONFIRMADO,
            entry_price=174000.0,
            stop_price=174150.0,
            stop_points=150.0,
            target_price=173600.0,
            target_points=400.0,
            risk_reward=2.67,
            timeframe_trigger=2,
            in_trend_direction=True
        )

        # Fluxo institucional de venda (Delta -5.200, Deslocamento -65 pts)
        mock_flow = {
            "buy_volume": 8000,
            "sell_volume": 13200,
            "delta": -5200,
            "price_displacement_pts": -65.0,
            "flow_pattern": "Agressão com Continuidade Vendedora"
        }

        assistant.setup_engine.evaluate = lambda **kwargs: (setup, "OK")
        assistant.flow_analyzer.get_window_metrics = lambda seconds=300: mock_flow

        assistant.evaluate_now()

        # O setup de VENDA DEVE ser confirmado via Flow Override
        self.assertEqual(setup.status, SetupStatus.CONFIRMADO)
        self.assertTrue(any("FLOW OVERRIDE ATIVO" in interp for interp in setup.interpretations))
        # Alvo parcial deve ser a borda superior do FVG (173.850) a 150 pts de distância
        self.assertEqual(setup.partial_target_price, 173850.0)
        self.assertEqual(setup.partial_target_points, 150.0)

    def test_fvg_flow_override_absorption_blocks(self):
        """Valida que quando há absorção passiva contrária, o Flow Override NÃO desbloqueia a operação."""
        from feeds.replay_feed import ReplayMarketFeed
        from core.engine import WinAnalysisAssistant
        from core.models import SignalSetup, SetupStatus

        feed = ReplayMarketFeed(symbol="WINZ26", initial_price=174000.0)
        assistant = WinAnalysisAssistant(feed=feed, symbol="WINZ26")
        assistant.fvg_scanner.active_fvgs = {tf: [] for tf in assistant.fvg_scanner.MONITORED_TIMEFRAMES}
        assistant.fvg_scanner.liquidated_archive = {tf: [] for tf in assistant.fvg_scanner.MONITORED_TIMEFRAMES}
        assistant.fvg_scanner._fvg_by_id = {}

        fvg_5m = ActiveMTFFVG(
            timeframe=5,
            direction="BEARISH",
            top=174250.0,
            bottom=174150.0,
            ce_50=174200.0,
            formed_time=self.base_time
        )
        assistant.fvg_scanner.active_fvgs[5].append(fvg_5m)

        setup = SignalSetup(
            timestamp=self.base_time,
            symbol="WINZ26",
            direction=Direction.COMPRA,
            setup_name="Rompimento de Alta",
            status=SetupStatus.CONFIRMADO,
            entry_price=174000.0,
            stop_price=173850.0,
            stop_points=150.0,
            target_price=174400.0,
            target_points=400.0,
            risk_reward=2.67,
            timeframe_trigger=2,
            in_trend_direction=True
        )

        # Delta alto mas com absorção passiva de venda ativa
        mock_flow = {
            "buy_volume": 15000,
            "sell_volume": 10000,
            "delta": 5000,
            "price_displacement_pts": 45.0,
            "flow_pattern": "Possível Absorção Vendedora (Forte compra absorvida passivamente)"
        }

        assistant.setup_engine.evaluate = lambda **kwargs: (setup, "OK")
        assistant.flow_analyzer.get_window_metrics = lambda seconds=300: mock_flow

        assistant.evaluate_now()

        # Com padrão de absorção vendedora ativa, a compra deve permanecer BLOQUEADA
        self.assertEqual(setup.status, SetupStatus.BLOQUEADO)

    def test_alert_formatter_displays_partial_and_flow_override(self):
        """Valida que o alerta formatado exibe corretamente o Alvo Parcial e a tag de Flow Override."""
        from core.models import SignalSetup, SetupStatus
        from analysis.alert_formatter import format_operational_alert

        setup = SignalSetup(
            timestamp=self.base_time,
            symbol="WINZ26",
            direction=Direction.COMPRA,
            setup_name="Rompimento Institucional de Alta",
            status=SetupStatus.CONFIRMADO,
            entry_price=174000.0,
            stop_price=173850.0,
            stop_points=150.0,
            target_price=174400.0,
            target_points=400.0,
            risk_reward=2.67,
            timeframe_trigger=2,
            in_trend_direction=True,
            partial_target_price=174150.0,
            partial_target_points=150.0,
            interpretations=["⚡ FLOW OVERRIDE ATIVO: Delta institucional (+4500 ct) supera barreira intraday."]
        )

        alert = format_operational_alert(
            setup=setup,
            regimes={1: "ALTA", 2: "ALTA", 5: "ALTA", 10: "ALTA", 15: "ALTA", 30: "ALTA", 60: "ALTA"},
            use_color=False
        )

        self.assertIn("PARCIAL (BORDA)", alert)
        self.assertIn("174.150", alert)
        self.assertIn("FLOW OVERRIDE ATIVO", alert)
        self.assertIn("174.150 (150 pontos - PARCIAL FVG) | 174.400 (400 pontos - FINAL)", alert)

    def test_fvg_flow_override_smc_option2_thresholds(self):
        """Valida a calibração da Opção 2: Delta >= 3000 e Deslocamento entre 50 e 180 pts."""
        from feeds.replay_feed import ReplayMarketFeed
        from core.engine import WinAnalysisAssistant
        from core.models import SignalSetup, SetupStatus

        feed = ReplayMarketFeed(symbol="WINZ26", initial_price=174000.0)
        assistant = WinAnalysisAssistant(feed=feed, symbol="WINZ26")
        assistant.fvg_scanner.active_fvgs = {tf: [] for tf in assistant.fvg_scanner.MONITORED_TIMEFRAMES}
        assistant.fvg_scanner.liquidated_archive = {tf: [] for tf in assistant.fvg_scanner.MONITORED_TIMEFRAMES}
        assistant.fvg_scanner._fvg_by_id = {}

        fvg_5m = ActiveMTFFVG(
            timeframe=5,
            direction="BEARISH",
            top=174250.0,
            bottom=174150.0,
            ce_50=174200.0,
            formed_time=self.base_time
        )
        assistant.fvg_scanner.active_fvgs[5].append(fvg_5m)

        def make_setup():
            return SignalSetup(
                timestamp=self.base_time,
                symbol="WINZ26",
                direction=Direction.COMPRA,
                setup_name="Rompimento Institucional de Alta",
                status=SetupStatus.CONFIRMADO,
                entry_price=174000.0,
                stop_price=173850.0,
                stop_points=150.0,
                target_price=174400.0,
                target_points=400.0,
                risk_reward=2.67,
                timeframe_trigger=2,
                in_trend_direction=True
            )

        # 1. Delta exato de +3000 e deslocamento de +50 pts (limite mínimo aceito) -> CONFIRMADO
        s1 = make_setup()
        assistant.setup_engine.evaluate = lambda **kwargs: (s1, "OK")
        assistant.flow_analyzer.get_window_metrics = lambda seconds=300: {
            "buy_volume": 6000, "sell_volume": 3000, "delta": 3000,
            "price_displacement_pts": 50.0, "flow_pattern": "Agressão com Continuidade Compradora"
        }
        assistant.evaluate_now()
        self.assertEqual(s1.status, SetupStatus.CONFIRMADO)
        self.assertTrue(any("FLOW OVERRIDE ATIVO" in x for x in s1.interpretations))

        # 2. Delta de +3000 mas deslocamento de apenas +35 pts (< 50 pts) -> BLOQUEADO
        s2 = make_setup()
        assistant.setup_engine.evaluate = lambda **kwargs: (s2, "OK")
        assistant.flow_analyzer.get_window_metrics = lambda seconds=300: {
            "buy_volume": 6000, "sell_volume": 3000, "delta": 3000,
            "price_displacement_pts": 35.0, "flow_pattern": "Agressão com Continuidade Compradora"
        }
        assistant.evaluate_now()
        self.assertEqual(s2.status, SetupStatus.BLOQUEADO)

        # 3. Delta massivo de +10.000 mas deslocamento esticado de +220 pts (> 180 pts - Zona Premium) -> BLOQUEADO VETO SMC
        s3 = make_setup()
        assistant.setup_engine.evaluate = lambda **kwargs: (s3, "OK")
        assistant.flow_analyzer.get_window_metrics = lambda seconds=300: {
            "buy_volume": 15000, "sell_volume": 5000, "delta": 10000,
            "price_displacement_pts": 220.0, "flow_pattern": "Agressão com Continuidade Compradora"
        }
        assistant.evaluate_now()
        self.assertEqual(s3.status, SetupStatus.BLOQUEADO)
        self.assertTrue(any("VETO SMC [ZONA PREMIUM" in x for x in s3.interpretations))


if __name__ == "__main__":
    unittest.main()
