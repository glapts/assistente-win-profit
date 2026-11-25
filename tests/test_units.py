"""
tests/test_units.py
Bateria de testes unitários automatizados para integridade do sistema.
Verifica:
1. Regras do contrato WIN (tick 5, R$ 0,20 por ponto).
2. Ausência de look-ahead bias na confirmação de pivôs.
3. Validação determinística de FVG de 3 barras fechadas.
4. Cálculo de agressões e delta sem dupla contagem.
5. Classificações descritivas do Livro (ausência de afirmações manipulativas).
"""

import unittest
import sys
import os
from datetime import datetime, timedelta

# Garantir path do projeto no sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.contract import (
    validate_price_tick, round_to_tick, calculate_financial_risk,
    get_current_win_contract, TZ_BRASILIA
)
from core.models import Candle, Trade, BookSnapshot, BookLevel, AggressorSide
from analysis.market_structure import TimeframeStructureAnalyzer
from analysis.tape_reading import TapeReadingAnalyzer
from analysis.book_analyzer import BookAnalyzer


class TestWinAssistant(unittest.TestCase):

    def test_contract_rules(self):
        """Verifica regras de tick e financeiro do Mini-Índice B3."""
        self.assertTrue(validate_price_tick(171405.0))
        self.assertTrue(validate_price_tick(171400.0))
        self.assertFalse(validate_price_tick(171402.0))
        self.assertEqual(round_to_tick(171403.4), 171405.0)
        self.assertEqual(round_to_tick(171401.8), 171400.0)
        
        # 250 pontos * 0.20 = R$ 50.00
        self.assertEqual(calculate_financial_risk(250.0, 1), 50.0)
        # 400 pontos * 0.20 = R$ 80.00
        self.assertEqual(calculate_financial_risk(400.0, 1), 80.0)

    def test_multi_asset_specs(self):
        """Verifica especificações de microestrutura de WDO e VALE3."""
        from core.contract import get_asset_spec, get_current_wdo_contract, resolve_symbol
        
        # Teste WDO
        wdo_spec = get_asset_spec("WDOZ26")
        self.assertEqual(wdo_spec.tick_size, 0.5)
        self.assertEqual(wdo_spec.point_value, 10.0)
        self.assertEqual(wdo_spec.approach_radius, 5.0)
        self.assertEqual(round_to_tick(5531.3, wdo_spec.tick_size), 5531.5)
        self.assertEqual(calculate_financial_risk(5.0, 1, wdo_spec.point_value), 50.0)
        self.assertEqual(calculate_financial_risk(8.0, 1, wdo_spec.point_value), 80.0)
        
        # Teste VALE3
        vale_spec = get_asset_spec("VALE3")
        self.assertEqual(vale_spec.tick_size, 0.01)
        self.assertEqual(vale_spec.contract_size, 100)
        self.assertEqual(vale_spec.approach_radius, 0.30)
        self.assertEqual(round_to_tick(62.088, vale_spec.tick_size), 62.09)
        self.assertEqual(calculate_financial_risk(0.35, vale_spec.contract_size, vale_spec.point_value), 35.0)

        # Teste de resolução de símbolos
        self.assertTrue(resolve_symbol("WDO").startswith("WDO"))
        self.assertTrue(resolve_symbol("WIN").startswith("WIN"))
        self.assertEqual(resolve_symbol("VALE3"), "VALE3")

    def test_pivots_no_lookahead_bias(self):
        """
        Pivôs que exigem barras à direita (pivot_right=2) NÃO podem ser confirmados
        na barra de formação, apenas 2 barras depois.
        """
        analyzer = TimeframeStructureAnalyzer(timeframe=5, pivot_left_bars=2, pivot_right_bars=2)
        base_time = datetime(2026, 10, 29, 9, 0, 0, tzinfo=TZ_BRASILIA)
        
        # Sequência: barra 0, 1, 2(topo), 3, 4(confirmação)
        highs = [170000, 170100, 170500, 170200, 170150]
        for idx, h in enumerate(highs):
            c = Candle(
                timeframe=5,
                open_time=base_time + timedelta(minutes=idx * 5),
                close_time=base_time + timedelta(minutes=(idx + 1) * 5),
                open=h - 50, high=h, low=h - 100, close=h - 30,
                is_closed=True
            )
            analyzer.add_candle(c)
            if idx < 4:
                # Antes do candle 4 (2 barras após o topo), o topo NÃO deve estar confirmado
                self.assertEqual(len(analyzer.pivots), 0)

        # No candle 4 (índice 4), o topo do candle 2 (índice 2) deve estar confirmado!
        self.assertEqual(len(analyzer.pivots), 1)
        self.assertEqual(analyzer.pivots[0].bar_index, 2)
        self.assertEqual(analyzer.pivots[0].confirmed_bar_index, 4)
        self.assertEqual(analyzer.pivots[0].price, 170500)

    def test_fvg_calculation(self):
        """Valida que FVG exige 3 candles fechados e mede a lacuna exata."""
        analyzer = TimeframeStructureAnalyzer(timeframe=5)
        base_time = datetime(2026, 10, 29, 9, 0, 0, tzinfo=TZ_BRASILIA)
        
        # FVG de Alta: Low[c3] > High[c1]
        c1 = Candle(5, base_time, base_time + timedelta(minutes=5), 170000, 170100, 169950, 170080, is_closed=True)
        c2 = Candle(5, base_time + timedelta(minutes=5), base_time + timedelta(minutes=10), 170090, 170400, 170080, 170380, is_closed=True)
        c3 = Candle(5, base_time + timedelta(minutes=10), base_time + timedelta(minutes=15), 170390, 170500, 170200, 170450, is_closed=True)
        
        analyzer.add_candle(c1)
        analyzer.add_candle(c2)
        self.assertEqual(len(analyzer.fvgs), 0) # Com 2 candles, ainda não há FVG
        
        analyzer.add_candle(c3)
        self.assertEqual(len(analyzer.fvgs), 1)
        fvg = analyzer.fvgs[0]
        self.assertEqual(fvg.direction, "BULLISH")
        self.assertEqual(fvg.bottom, 170100) # High de c1
        self.assertEqual(fvg.top, 170200)    # Low de c3
        self.assertEqual(fvg.size, 100.0)

    def test_tape_reading_delta_no_double_count(self):
        """Valida que trades individuais não são duplicados no delta."""
        tape = TapeReadingAnalyzer(window_seconds=60)
        base_time = datetime.now(TZ_BRASILIA)
        
        t1 = Trade("1", base_time, 171400, 50, AggressorSide.BUY)
        t2 = Trade("2", base_time + timedelta(seconds=1), 171405, 30, AggressorSide.SELL)
        t3 = Trade("3", base_time + timedelta(seconds=2), 171405, 100, AggressorSide.BUY) # Large trade
        
        tape.add_trade(t1)
        tape.add_trade(t2)
        tape.add_trade(t3)
        
        self.assertEqual(tape.total_buy_volume, 150)
        self.assertEqual(tape.total_sell_volume, 30)
        self.assertEqual(tape.cumulative_delta, 120)
        self.assertEqual(len(tape.large_trades), 1)

    def test_book_analyzer_classification(self):
        """Garante que o book analyzer respeita as classificações permitidas."""
        book = BookAnalyzer()
        eval_empty = book.evaluate_book_behavior(171400.0)
        self.assertEqual(eval_empty["status"], "Análise indisponível por limitação dos dados")
        
        # Inserir snapshot normal
        now = datetime.now(TZ_BRASILIA)
        bids = [BookLevel(171400 - (i*5), 50) for i in range(1, 6)]
        asks = [BookLevel(171400 + (i*5), 50) for i in range(1, 6)]
        book.update_snapshot(BookSnapshot(now, bids, asks))
        
        eval_normal = book.evaluate_book_behavior(171400.0)
        self.assertEqual(eval_normal["classification"], "Evidência insuficiente")
        self.assertNotIn("spoofing confirmado", eval_normal["classification"].lower())

    def test_morning_opening_setups(self):
        """Garante que a 1ª barra de 2m e 5m da abertura geram setups imediatos na janela matinal."""
        from analysis.market_structure import MultiTimeframeMarketEngine
        from setups.setup_engine import SetupEngine
        from core.models import Direction

        engine = MultiTimeframeMarketEngine()
        setup_engine = SetupEngine(mode="FIXO")
        morning_time = datetime(2026, 10, 30, 9, 5, 0, tzinfo=TZ_BRASILIA)

        # 1. Primeira barra de 5m fecha às 09:05 com máxima 171500 e mínima 171200
        c1 = Candle(5, morning_time - timedelta(minutes=5), morning_time, 171300, 171500, 171200, 171450, is_closed=True)
        engine.process_closed_candle(c1)

        # 2. Segunda barra viola a máxima em 171550, mas devolve para 171480 às 09:07
        c2 = Candle(5, morning_time, morning_time + timedelta(minutes=5), 171450, 171550, 171460, 171480, is_closed=True)
        engine.process_closed_candle(c2)

        # Avaliar setup de sweep de abertura
        setup, reason = setup_engine.evaluate(
            symbol="WINZ26",
            current_price=171480,
            timestamp=morning_time + timedelta(minutes=3), # 09:08 da manhã
            structure_engine=engine,
            feed_healthy=True
        )

        self.assertIsNotNone(setup)
        self.assertEqual(setup.direction, Direction.VENDA)
        self.assertIn("Sweep da Máxima de Abertura", setup.setup_name)
        self.assertEqual(setup.stop_points, 250.0)
        self.assertEqual(setup.target_points, 400.0)
        self.assertEqual(setup.entry_price, 171480.0)
        self.assertEqual(setup.stop_price, 171730.0)
        self.assertEqual(setup.target_price, 171080.0)

    def test_fvg_1m_trigger_refinement(self):
        """Valida que um FVG formado no 1m atua como micro-gatilho de entrada alinhado ao contexto."""
        from analysis.market_structure import MultiTimeframeMarketEngine
        from setups.setup_engine import SetupEngine
        from core.models import Direction, MarketRegime

        engine = MultiTimeframeMarketEngine()
        setup_engine = SetupEngine(mode="FIXO")
        base_time = datetime(2026, 10, 30, 10, 30, 0, tzinfo=TZ_BRASILIA)

        # Simular contexto de alta em 60m, 30m e 5m
        engine.analyzers[60].regime = MarketRegime.ALTA
        engine.analyzers[30].regime = MarketRegime.ALTA
        engine.analyzers[5].regime = MarketRegime.ALTA

        # Criar FVG de alta no 1m: c1.high=171300, c3.low=171350 (lacuna de 50 pts)
        c1 = Candle(1, base_time, base_time + timedelta(minutes=1), 171200, 171300, 171180, 171280, is_closed=True)
        c2 = Candle(1, base_time + timedelta(minutes=1), base_time + timedelta(minutes=2), 171290, 171450, 171280, 171440, is_closed=True)
        c3 = Candle(1, base_time + timedelta(minutes=2), base_time + timedelta(minutes=3), 171440, 171500, 171350, 171490, is_closed=True)
        engine.process_closed_candle(c1)
        engine.process_closed_candle(c2)
        engine.process_closed_candle(c3)

        # Preço recua até a zona do FVG de 1m (171340)
        setup, reason = setup_engine.evaluate(
            symbol="WINZ26",
            current_price=171340.0,
            timestamp=base_time + timedelta(minutes=4),
            structure_engine=engine,
            feed_healthy=True
        )

        self.assertIsNotNone(setup)
        self.assertEqual(setup.direction, Direction.COMPRA)
        self.assertEqual(setup.timeframe_trigger, 1)
        self.assertIn("1m", setup.fvg_zone)
        self.assertEqual(setup.entry_price, 171340.0)
        self.assertEqual(setup.stop_points, 250.0)
        self.assertEqual(setup.target_points, 400.0)

    def test_alert_flow_colors(self):
        """Valida destaque colorido de agressão compradora (verde) e vendedora (vermelho)."""
        from analysis.alert_formatter import format_operational_alert
        from colorama import Fore

        flow = {
            "buy_volume": 12500,
            "sell_volume": 8300,
            "delta": 4200,
            "large_trades": [
                {"qty": 200, "price": 170500.0, "side": "BUY"},
                {"qty": 150, "price": 170495.0, "side": "SELL"}
            ],
            "price_displacement_pts": 35.0,
            "flow_pattern": "Agressão com Continuidade Compradora",
            "trades_count": 25
        }
        regimes = {"60m": "ALTA", "15m": "ALTA", "5m": "ALTA", "1m": "ALTA"}

        alert_colored = format_operational_alert(
            setup=None,
            regimes=regimes,
            use_color=True,
            flow_data=flow
        )

        # Verificar presença de seções e códigos de cores ANSI (Verde e Vermelho)
        self.assertIn("TIMES & TRADES", alert_colored)
        self.assertIn("Agressão compradora", alert_colored)
        self.assertIn("Agressão vendedora", alert_colored)
        self.assertIn(Fore.GREEN, alert_colored)
        self.assertIn(Fore.RED, alert_colored)
        self.assertIn("(BUY)", alert_colored)
        self.assertIn("(SELL)", alert_colored)

        # Versão sem cor para logs em disco
        alert_plain = format_operational_alert(
            setup=None,
            regimes=regimes,
            use_color=False,
            flow_data=flow
        )
        self.assertIn("12,500 contratos", alert_plain)
        self.assertIn("8,300 contratos", alert_plain)
        self.assertNotIn("\x1b[", alert_plain)

    def test_fvg_displacement_ce_50_setup(self):
        """Valida o novo Setup 9: Reteste de 50% do FVG de Deslocamento (Consequent Encroachment C.E.)."""
        from analysis.market_structure import MultiTimeframeMarketEngine
        from setups.setup_engine import SetupEngine
        from core.models import Direction

        engine = MultiTimeframeMarketEngine()
        setup_engine = SetupEngine(mode="FIXO")
        base_time = datetime(2026, 10, 30, 11, 0, 0, tzinfo=TZ_BRASILIA)

        # 1. TESTE DE COMPRA: Barra de 2m com corpo de 250 pts (170000 -> 170250)
        c0 = Candle(2, base_time - timedelta(minutes=6), base_time - timedelta(minutes=4), 169950, 170020, 169940, 170000, is_closed=True)
        c1 = Candle(2, base_time - timedelta(minutes=4), base_time - timedelta(minutes=2), 170000, 170050, 169980, 170010, is_closed=True)
        # Barra de deslocamento:
        c2 = Candle(2, base_time - timedelta(minutes=2), base_time, 170000, 170260, 169990, 170250, is_closed=True) # Corpo: 250 pts, C.E. 50%: 170125
        engine.process_closed_candle(c0)
        engine.process_closed_candle(c1)
        engine.process_closed_candle(c2)

        # Preço faz pullback no 50% (170125) -> current_price = 170130
        flow_buy = {"delta": 850, "buy_volume": 4500, "sell_volume": 3650}
        mock_flow_buy = type('obj', (object,), {
            'total_trades_count': 100,
            'get_window_metrics': lambda self, seconds=300: flow_buy
        })()
        setup_buy, _ = setup_engine.evaluate(
            symbol="WINZ26",
            current_price=170130.0,
            timestamp=base_time + timedelta(seconds=30),
            structure_engine=engine,
            flow_analyzer=mock_flow_buy,
            feed_healthy=True
        )

        self.assertIsNotNone(setup_buy)
        self.assertEqual(setup_buy.direction, Direction.COMPRA)
        self.assertIn("Compra no Reteste de 50% do FVG de Deslocamento", setup_buy.setup_name)
        self.assertEqual(setup_buy.stop_points, 250.0)
        self.assertEqual(setup_buy.target_points, 400.0)
        self.assertEqual(setup_buy.entry_price, 170130.0)
        self.assertEqual(setup_buy.stop_price, 169880.0)
        self.assertEqual(setup_buy.target_price, 170530.0)

        # 2. TESTE DE VENDA: Barra de 2m vendedora com corpo de 250 pts (170500 -> 170250)
        engine_sell = MultiTimeframeMarketEngine()
        c_s0 = Candle(2, base_time - timedelta(minutes=6), base_time - timedelta(minutes=4), 170550, 170580, 170500, 170520, is_closed=True)
        c_s1 = Candle(2, base_time - timedelta(minutes=4), base_time - timedelta(minutes=2), 170520, 170550, 170480, 170500, is_closed=True)
        c_s2 = Candle(2, base_time - timedelta(minutes=2), base_time, 170500, 170510, 170240, 170250, is_closed=True) # Corpo: 250 pts, C.E. 50%: 170375
        engine_sell.process_closed_candle(c_s0)
        engine_sell.process_closed_candle(c_s1)
        engine_sell.process_closed_candle(c_s2)

        flow_sell = {"delta": -900, "buy_volume": 2000, "sell_volume": 2900}
        mock_flow_sell = type('obj', (object,), {
            'total_trades_count': 100,
            'get_window_metrics': lambda self, seconds=300: flow_sell
        })()
        setup_sell, _ = setup_engine.evaluate(
            symbol="WINZ26",
            current_price=170370.0,
            timestamp=base_time + timedelta(seconds=30),
            structure_engine=engine_sell,
            flow_analyzer=mock_flow_sell,
            feed_healthy=True
        )

        self.assertIsNotNone(setup_sell)
        self.assertEqual(setup_sell.direction, Direction.VENDA)
        self.assertIn("Venda no Reteste de 50% do FVG de Deslocamento", setup_sell.setup_name)
        self.assertEqual(setup_sell.stop_points, 250.0)
        self.assertEqual(setup_sell.target_points, 400.0)
        self.assertEqual(setup_sell.entry_price, 170370.0)
        self.assertEqual(setup_sell.stop_price, 170620.0)
        self.assertEqual(setup_sell.target_price, 169970.0)

    def test_flow_confluence_blocks_opposing_setups(self):
        """Valida que fluxo com Continuidade Compradora bloqueia sumariamente VENDA por Sweep, e vice-versa."""
        from analysis.market_structure import MultiTimeframeMarketEngine
        from setups.setup_engine import SetupEngine
        from core.models import Direction, StructuralEvent

        engine = MultiTimeframeMarketEngine()
        setup_engine = SetupEngine(mode="FIXO")
        base_time = datetime(2026, 11, 4, 10, 44, 0, tzinfo=TZ_BRASILIA)

        # Injetar Sweep de topo no 2m (BEARISH Sweep)
        # c0 (topo anterior), c1 (sweep), c2 (rejeição)
        c0 = Candle(2, base_time - timedelta(minutes=4), base_time - timedelta(minutes=2), 169400, 169490, 169380, 169450, is_closed=True)
        c1 = Candle(2, base_time - timedelta(minutes=2), base_time, 169450, 169525, 169430, 169470, is_closed=True)
        c2 = Candle(2, base_time, base_time + timedelta(minutes=2), 169470, 169480, 169200, 169205, is_closed=True)
        engine.process_closed_candle(c0)
        engine.process_closed_candle(c1)
        engine.process_closed_candle(c2)

        # Forçar o last_sweep no analisador de 2m
        engine.analyzers[2].last_sweep = StructuralEvent(
            event_type="SWEEP",
            timeframe=2,
            timestamp=base_time + timedelta(minutes=2),
            direction="BEARISH",
            level_broken=169490.0,
            bar_index=len(engine.analyzers[2].candles) - 1,
            details="Sweep de Máxima (169490): violou 169525 e fechou em 169205"
        )

        # 1. CENÁRIO REAL DO USUÁRIO: Fluxo comprador agressivo (Delta +4550 e Continuidade Compradora)
        flow_buyer_continuity = {
            "delta": 4550,
            "buy_volume": 22903,
            "sell_volume": 18353,
            "flow_pattern": "Agressão com Continuidade Compradora (Delta positivo acompanhado de avanço do preço)"
        }
        mock_flow = type('obj', (object,), {
            'total_trades_count': 1500,
            'get_window_metrics': lambda self, seconds=300: flow_buyer_continuity
        })()

        setup, reason = setup_engine.evaluate(
            symbol="WINZ26",
            current_price=169340.0,
            timestamp=base_time + timedelta(minutes=2),
            structure_engine=engine,
            flow_analyzer=mock_flow,
            feed_healthy=True
        )

        # Deve ser BLOQUEADO! Nenhum setup de VENDA pode ser disparado contra fluxo comprador contínuo
        self.assertIsNone(setup)
        self.assertEqual(reason, "SEM OPERAÇÃO — AGUARDAR")

        # 2. CENÁRIO CORRETO DE ABSORÇÃO VENDEDORA: Delta positivo mas preço absorvido passivamente no topo
        flow_absorption = {
            "delta": 2500,
            "buy_volume": 15000,
            "sell_volume": 12500,
            "flow_pattern": "Possível Absorção Vendedora (Forte compra absorvida passivamente sem deslocamento de alta)"
        }
        mock_flow.get_window_metrics = lambda seconds=300: flow_absorption

        setup_abs, _ = setup_engine.evaluate(
            symbol="WINZ26",
            current_price=169340.0,
            timestamp=base_time + timedelta(minutes=2),
            structure_engine=engine,
            flow_analyzer=mock_flow,
            feed_healthy=True
        )

        # Com absorção vendedora passiva confirmada, a VENDA é AUTORIZADA
        self.assertIsNotNone(setup_abs)
        self.assertEqual(setup_abs.direction, Direction.VENDA)
        self.assertIn("Sweep 2m", setup_abs.setup_name)

    def test_institutional_defense_top_venda(self):
        """Valida detecção de defesa institucional no topo (SMC Premium + Rejeição 1m + T&T + Book)."""
        from analysis.market_structure import MultiTimeframeMarketEngine
        from setups.setup_engine import SetupEngine
        from core.models import Direction

        engine = MultiTimeframeMarketEngine()
        setup_engine = SetupEngine(mode="FIXO")
        test_time = datetime(2026, 11, 5, 11, 30, 0, tzinfo=TZ_BRASILIA)

        # Semear extremos da sessão com topo em 170.090 e fundo em 168.390 (gráfico do usuário)
        engine.seed_session_extremes(169365.0, 170090.0, 168390.0, test_time)

        # Candle de 1m testa a máxima (170.080), sofre rejeição com pavio superior de 40 pts e fecha em 170.020
        c1m = Candle(
            timeframe=1,
            open_time=test_time - timedelta(minutes=1),
            close_time=test_time,
            open=170040.0,
            high=170080.0,
            low=170010.0,
            close=170020.0,
            volume=500,
            buy_volume=180,
            sell_volume=320,
            is_closed=True
        )
        engine.process_closed_candle(c1m)

        # Mocks de Tape Reading e Book
        flow_seller = {
            "delta": -450,
            "buy_volume": 1200,
            "sell_volume": 1650,
            "flow_pattern": "Agressão com Continuidade Vendedora (Delta negativo acompanhado de recuo do preço)"
        }
        mock_flow = type('obj', (object,), {
            'total_trades_count': 600,
            'get_window_metrics': lambda self, seconds=300: flow_seller
        })()

        book_seller = {
            "status": "Comportamento de oferta observado",
            "book_imbalance_top5": -0.25,
            "classification": "Comportamento de oferta observado"
        }
        mock_book = type('obj', (object,), {
            'evaluate_book_behavior': lambda self, price: book_seller
        })()

        setup, reason = setup_engine.evaluate(
            symbol="WINZ26",
            current_price=170020.0,
            timestamp=test_time,
            structure_engine=engine,
            flow_analyzer=mock_flow,
            book_analyzer=mock_book,
            feed_healthy=True
        )

        self.assertIsNotNone(setup)
        self.assertEqual(setup.direction, Direction.VENDA)
        self.assertIn("Defesa Institucional no Topo", setup.setup_name)
        self.assertEqual(setup.entry_price, 170020.0)
        self.assertEqual(setup.stop_points, 250.0)
        self.assertEqual(setup.target_points, 400.0)

    def test_institutional_defense_bottom_compra(self):
        """Valida detecção de defesa institucional no fundo (SMC Discount + Reação 1m + T&T + Book)."""
        from analysis.market_structure import MultiTimeframeMarketEngine
        from setups.setup_engine import SetupEngine
        from core.models import Direction

        engine = MultiTimeframeMarketEngine()
        setup_engine = SetupEngine(mode="FIXO")
        test_time = datetime(2026, 11, 5, 12, 15, 0, tzinfo=TZ_BRASILIA)

        # Semear extremos da sessão com topo em 170.090 e fundo em 168.390 (gráfico do usuário)
        engine.seed_session_extremes(169365.0, 170090.0, 168390.0, test_time)

        # Candle de 1m testa a mínima (168.400), sofre reação com pavio inferior de 30 pts e fecha em 168.460
        c1m = Candle(
            timeframe=1,
            open_time=test_time - timedelta(minutes=1),
            close_time=test_time,
            open=168430.0,
            high=168470.0,
            low=168400.0,
            close=168460.0,
            volume=500,
            buy_volume=350,
            sell_volume=150,
            is_closed=True
        )
        engine.process_closed_candle(c1m)

        # Mocks de Tape Reading e Book
        flow_buyer = {
            "delta": 620,
            "buy_volume": 1800,
            "sell_volume": 1180,
            "flow_pattern": "Agressão com Continuidade Compradora (Delta positivo acompanhado de avanço do preço)"
        }
        mock_flow = type('obj', (object,), {
            'total_trades_count': 600,
            'get_window_metrics': lambda self, seconds=300: flow_buyer
        })()

        book_buyer = {
            "status": "Comportamento de oferta observado",
            "book_imbalance_top5": 0.25,
            "classification": "Comportamento de oferta observado"
        }
        mock_book = type('obj', (object,), {
            'evaluate_book_behavior': lambda self, price: book_buyer
        })()

        setup, reason = setup_engine.evaluate(
            symbol="WINZ26",
            current_price=168460.0,
            timestamp=test_time,
            structure_engine=engine,
            flow_analyzer=mock_flow,
            book_analyzer=mock_book,
            feed_healthy=True
        )

        self.assertIsNotNone(setup)
        self.assertEqual(setup.direction, Direction.COMPRA)
        self.assertIn("Defesa Institucional no Fundo", setup.setup_name)
        self.assertEqual(setup.entry_price, 168460.0)
        self.assertEqual(setup.stop_points, 250.0)
        self.assertEqual(setup.target_points, 400.0)

    def test_continuation_breakdown_of_bottom(self):
        """Garante que o rompimento de fundo com candle de deslocamento e continuidade gera setup nos tempos gráficos."""
        from analysis.market_structure import MultiTimeframeMarketEngine
        from setups.setup_engine import SetupEngine
        from core.models import Direction, MarketRegime

        engine = MultiTimeframeMarketEngine()
        setup_engine = SetupEngine(mode="FIXO")
        base_time = datetime(2026, 11, 5, 9, 20, 0, tzinfo=TZ_BRASILIA)

        # 3 candles de 5m:
        # c1: 170000 a 170500, fecha em 170300 (mínima 170000)
        c1 = Candle(5, base_time - timedelta(minutes=15), base_time - timedelta(minutes=10), 170100, 170500, 170000, 170300, is_closed=True)
        # c2: oscila entre 170300 e 169950, fecha em 170050 (fundo em 169950)
        c2 = Candle(5, base_time - timedelta(minutes=10), base_time - timedelta(minutes=5), 170300, 170350, 169950, 170050, is_closed=True)
        # c3: Rompe o fundo de 169950 com candle cheio de deslocamento (corpo de 200 pts) fechando em 169750
        c3 = Candle(5, base_time - timedelta(minutes=5), base_time, 170020, 170050, 169700, 169750, is_closed=True)

        engine.process_closed_candle(c1)
        engine.process_closed_candle(c2)
        engine.process_closed_candle(c3)

        # Preço atual fazendo reteste/continuidade em 169760
        flow_sell = {
            "delta": -1500,
            "buy_volume": 3000,
            "sell_volume": 4500,
            "flow_pattern": "Agressão com Continuidade Vendedora (Delta negativo acompanhado de recuo do preço)"
        }
        mock_flow = type('obj', (object,), {
            'total_trades_count': 500,
            'get_window_metrics': lambda self, seconds=300: flow_sell
        })()

        setup, reason = setup_engine.evaluate(
            symbol="WINZ26",
            current_price=169760.0,
            timestamp=base_time + timedelta(minutes=1),
            structure_engine=engine,
            flow_analyzer=mock_flow,
            feed_healthy=True
        )

        self.assertIsNotNone(setup)
        self.assertEqual(setup.direction, Direction.VENDA)
        self.assertIn("Rompimento de Fundo com Continuidade", setup.setup_name)
        self.assertEqual(setup.entry_price, 169760.0)
        self.assertEqual(setup.stop_points, 250.0)
        self.assertEqual(setup.target_points, 400.0)

    def test_fvg_mtf_scanner_unliquidated_lifecycle(self):
        """Valida detecção MTF (10m, 15m, 30m, 60m, 240m) e ciclo de vida/liquidação de FVGs."""
        from analysis.fvg_mtf_scanner import FGVMTFScanner, ActiveMTFFVG
        scanner = FGVMTFScanner(min_fvg_size=10.0)
        base_time = datetime(2026, 11, 5, 9, 0, 0, tzinfo=TZ_BRASILIA)

        # 1. Simular formação de FVG de Baixa no 60m:
        # c1: Low 170.170, High 170.220
        # c2: Deslocamento para baixo
        # c3: High 170.000, Low 169.900 -> FVG entre 170.000 (bottom = c3.high) e 170.170 (top = c1.low), CE = 170.085
        c1 = Candle(60, base_time, base_time + timedelta(hours=1), 170180, 170220, 170170, 170190, is_closed=True)
        c2 = Candle(60, base_time + timedelta(hours=1), base_time + timedelta(hours=2), 170110, 170120, 169950, 169960, is_closed=True)
        c3 = Candle(60, base_time + timedelta(hours=2), base_time + timedelta(hours=3), 169960, 170000, 169900, 169920, is_closed=True)

        scanner.register_candle(c1)
        scanner.register_candle(c2)
        scanner.register_candle(c3)

        open_fvgs = scanner.get_unliquidated_fvgs(timeframe=60)
        self.assertEqual(len(open_fvgs), 1)
        fvg = open_fvgs[0]
        self.assertEqual(fvg.direction, "BEARISH")
        self.assertEqual(fvg.bottom, 170000.0)
        self.assertEqual(fvg.top, 170170.0)
        self.assertEqual(fvg.ce_50, 170085.0)
        self.assertFalse(fvg.is_liquidated)

        # 2. Preço testa a zona sem romper o topo (ex: atinge 170.080) -> FVG permanece aberto
        c_test = Candle(60, base_time + timedelta(hours=3), base_time + timedelta(hours=4), 169920, 170080, 169910, 170020, is_closed=True)
        scanner.register_candle(c_test)
        self.assertFalse(fvg.is_liquidated)

        # 3. Preço rompe completamente o topo (atinge 170.200) -> FVG de baixa é liquidado e sai do radar
        c_break = Candle(60, base_time + timedelta(hours=4), base_time + timedelta(hours=5), 170020, 170200, 170010, 170180, is_closed=True)
        scanner.register_candle(c_break)
        self.assertTrue(fvg.is_liquidated)
        open_bearish = [f for f in scanner.get_unliquidated_fvgs(timeframe=60) if f.direction == "BEARISH"]
        self.assertEqual(len(open_bearish), 0)

    def test_fvg_mtf_early_approach_alerts_and_formatting(self):
        """Valida disparo de Alerta Antecipado (raio 100-150 pts), formatação de milhar e cores ANSI."""
        from analysis.fvg_mtf_scanner import FGVMTFScanner, ActiveMTFFVG, formatar_preco_win

        scanner = FGVMTFScanner(default_approach_radius=150.0)
        now = datetime.now(TZ_BRASILIA)

        # 1. Validação de formatação de milhar com ponto
        self.assertEqual(formatar_preco_win(170000.0), "170.000")
        self.assertEqual(formatar_preco_win(169880.0), "169.880")
        self.assertEqual(formatar_preco_win(170085.0), "170.085")

        # 2. Cenário 1: Preço a 169.880 subindo para FVG 60m em 170.000 (Faltam 120 pts -> Raio de 150 pts)
        fvg_bear = ActiveMTFFVG(
            timeframe=60,
            direction="BEARISH",
            top=170170.0,
            bottom=170000.0,
            ce_50=170085.0,
            formed_time=now
        )
        scanner.active_fvgs[60].append(fvg_bear)

        alerts_1 = scanner.scan_approach_alerts(169880.0, approach_radius=150.0)
        self.assertEqual(len(alerts_1), 1)
        al1 = alerts_1[0]
        self.assertEqual(al1.action_direction, "VENDA")
        self.assertEqual(al1.distance_to_zone, 120.0)
        self.assertEqual(al1.zone_start, 170000.0)
        self.assertEqual(al1.zone_end, 170170.0)

        alert_text_colored = scanner.format_power_shell_alert(al1, use_color=True)
        self.assertIn("[RADAR FVG ANTECIPADO]", alert_text_colored)
        self.assertIn("169.880", alert_text_colored)
        self.assertIn("170.000 (Faltam 120 pts)", alert_text_colored)
        self.assertIn("170.085 (VENDA)", alert_text_colored)
        self.assertIn("\033[1;93mPonto de 50% (CE)\033[0m", alert_text_colored)  # Rótulo em Amarelo
        self.assertIn("\033[1;91m", alert_text_colored)  # Vermelho para VENDA

        # Versão sem cor
        alert_text_plain = scanner.format_power_shell_alert(al1, use_color=False)
        self.assertNotIn("\033[", alert_text_plain)
        self.assertIn("170.085 (VENDA)", alert_text_plain)

        # 3. Cenário 2: Preço a 170.120 caindo para FVG 30m em 170.000 (Faltam 120 pts -> COMPRA)
        scanner2 = FGVMTFScanner(default_approach_radius=150.0)
        fvg_bull = ActiveMTFFVG(
            timeframe=30,
            direction="BULLISH",
            top=170000.0,
            bottom=169830.0,
            ce_50=169915.0,
            formed_time=now
        )
        scanner2.active_fvgs[30].append(fvg_bull)

        alerts_2 = scanner2.scan_approach_alerts(170120.0, approach_radius=150.0)
        self.assertEqual(len(alerts_2), 1)
        al2 = alerts_2[0]
        self.assertEqual(al2.action_direction, "COMPRA")
        self.assertEqual(al2.distance_to_zone, 120.0)

        alert2_colored = scanner2.format_power_shell_alert(al2, use_color=True)
        self.assertIn("170.120", alert2_colored)
        self.assertIn("169.915 (COMPRA)", alert2_colored)
        self.assertIn("\033[1;92m", alert2_colored)  # Verde para COMPRA

    def test_aggregator_240m_boundary(self):
        """Valida que o MultiTimeframeCandleAggregator fecha barras de 240m (4h) alinhadas ao pregão."""
        from core.candle_aggregator import MultiTimeframeCandleAggregator

        closed_candles = []
        agg = MultiTimeframeCandleAggregator(on_candle_closed=lambda c: closed_candles.append(c))

        base = datetime(2026, 11, 5, 9, 0, 0, tzinfo=TZ_BRASILIA)

        # Simular 240 minutos de pregão (09:00 até 13:00)
        for i in range(1, 241):
            t_open = base + timedelta(minutes=i - 1)
            t_close = base + timedelta(minutes=i)
            c = Candle(1, t_open, t_close, 170000 + i, 170010 + i, 169990 + i, 170005 + i, is_closed=True)
            agg.process_1m_candle(c)

        # Verificar barras de 240m fechadas
        c240 = [c for c in closed_candles if c.timeframe == 240]
        self.assertEqual(len(c240), 1)
        self.assertEqual(c240[0].close_time.hour, 13)
        self.assertEqual(c240[0].close_time.minute, 0)
        self.assertTrue(c240[0].is_closed)

    def test_vale3_flow_alignment_no_divergence(self):
        """
        Valida que para VALE3:
        1. Delta positivo (+4200 ações) JAMAIS gera sinal de VENDA.
        2. Delta negativo (-4200 ações) JAMAIS gera sinal de COMPRA.
        3. TapeReadingAnalyzer para VALE3 classifica deslocamento em centavos de reais.
        4. WIN e WDO permanecem com suas regras normais e intactas.
        """
        from setups.setup_engine import SetupEngine
        from core.contract import get_asset_spec
        from core.models import Direction
        from analysis.tape_reading import TapeReadingAnalyzer

        vale_spec = get_asset_spec("VALE3")
        win_spec = get_asset_spec("WIN")

        engine_vale = SetupEngine(mode="FIXO", asset_spec=vale_spec)
        engine_win = SetupEngine(mode="FIXO", asset_spec=win_spec)

        flow_positive_delta = {
            "buy_volume": 5700,
            "sell_volume": 1500,
            "delta": 4200,
            "price_displacement_pts": 0.0,
            "flow_pattern": "Possível Absorção Vendedora (Forte compra absorvida passivamente sem deslocamento de alta)"
        }

        flow_negative_delta = {
            "buy_volume": 1500,
            "sell_volume": 5700,
            "delta": -4200,
            "price_displacement_pts": -0.20,
            "flow_pattern": "Agressão com Continuidade Vendedora (Delta negativo acompanhado de recuo do preço)"
        }

        flow_buy_cont = {
            "buy_volume": 7000,
            "sell_volume": 1000,
            "delta": 6000,
            "price_displacement_pts": 0.25,
            "flow_pattern": "Agressão com Continuidade Compradora (Delta positivo acompanhado de avanço do preço)"
        }

        # 1. VALE3: Delta positivo bloqueia VENDA terminantemente (mesmo com absorção aparente)
        self.assertFalse(engine_vale._is_flow_aligned(Direction.VENDA, flow_positive_delta, flow_available=True))
        # 2. VALE3: Absorção vendedora também protege o comprador de comprar no topo absorvido
        self.assertFalse(engine_vale._is_flow_aligned(Direction.COMPRA, flow_positive_delta, flow_available=True))
        # 3. VALE3: Continuidade compradora confirmada permite COMPRA
        self.assertTrue(engine_vale._is_flow_aligned(Direction.COMPRA, flow_buy_cont, flow_available=True))

        # 4. VALE3: Delta negativo bloqueia COMPRA terminantemente
        self.assertFalse(engine_vale._is_flow_aligned(Direction.COMPRA, flow_negative_delta, flow_available=True))
        # 5. VALE3: Delta negativo com continuidade vendedora permite VENDA
        self.assertTrue(engine_vale._is_flow_aligned(Direction.VENDA, flow_negative_delta, flow_available=True))

        # 5. TapeReadingAnalyzer calibrado para VALE3
        tape_vale = TapeReadingAnalyzer(asset_spec=vale_spec)
        pat_vale_cont = tape_vale._classify_flow_pattern(delta=5000, price_displacement=0.20, total_volume=10000)
        self.assertIn("Continuidade Compradora", pat_vale_cont)

        # 6. Mini-Índice WIN preservado sem alterações
        tape_win = TapeReadingAnalyzer(asset_spec=win_spec)
        self.assertEqual(tape_win.large_trade_thresh, 100)


if __name__ == "__main__":
    unittest.main()
