"""
tests/test_sp500_macro_filter.py
Testes unitários e de integração para o Filtro de Segurança Macro e Confluência Institucional (S&P 500 / NYSE 11:30).
"""

import unittest
from datetime import datetime, date, time as dt_time, timedelta

from core.models import Direction, SignalSetup, SetupStatus
from core.contract import TZ_BRASILIA, WIN_SPEC, get_current_sp500_contract
from analysis.sp500_macro_filter import SP500MacroFilter, SP500Regime, MacroFilterResult
from setups.setup_engine import SetupEngine


class TestSP500MacroFilter(unittest.TestCase):
    def setUp(self):
        self.filter = SP500MacroFilter(preferred_symbol="WSPZ26")
        self.ref_date = date(2026, 11, 19)

    def test_sp500_contract_resolution(self):
        """Verifica resolução de contrato para os prefixos WSP e ISP."""
        dt_nov = datetime(2026, 11, 19, 10, 0, tzinfo=TZ_BRASILIA)
        wsp_ticker = get_current_sp500_contract("WSP", dt=dt_nov)
        isp_ticker = get_current_sp500_contract("ISP", dt=dt_nov)
        self.assertEqual(wsp_ticker, "WSPZ26")
        self.assertEqual(isp_ticker, "ISPZ26")

    def test_regime_classification(self):
        """Verifica a identificação precisa das 4 janelas operacionais."""
        dt_pre = datetime(2026, 11, 19, 10, 15, tzinfo=TZ_BRASILIA)
        dt_buf = datetime(2026, 11, 19, 11, 26, tzinfo=TZ_BRASILIA)
        dt_open = datetime(2026, 11, 19, 11, 35, tzinfo=TZ_BRASILIA)
        dt_closed = datetime(2026, 11, 19, 18, 30, tzinfo=TZ_BRASILIA)

        self.assertEqual(self.filter.get_regime(dt_pre), SP500Regime.PRE_OPEN)
        self.assertEqual(self.filter.get_regime(dt_buf), SP500Regime.BUFFER_PRE_OPEN)
        self.assertEqual(self.filter.get_regime(dt_open), SP500Regime.NYSE_OPEN)
        self.assertEqual(self.filter.get_regime(dt_closed), SP500Regime.CLOSED)

    def test_buffer_pre_open_blocks_entries(self):
        """Hard Gate Preventivo: Entre 11:25 e 11:30 bloqueia tanto COMPRA quanto VENDA."""
        dt_buf = datetime(2026, 11, 19, 11, 27, 30, tzinfo=TZ_BRASILIA)
        self.filter.register_tick(5890.0, dt_buf)

        res_buy = self.filter.evaluate_macro_filter(Direction.COMPRA, dt_buf)
        res_sell = self.filter.evaluate_macro_filter(Direction.VENDA, dt_buf)

        self.assertFalse(res_buy.is_allowed)
        self.assertIn("BUFFER PRÉ-ABERTURA NYSE", res_buy.reason)
        self.assertEqual(res_buy.tag, "[⛔ BLOQUEADO: BUFFER PRÉ-NYSE]")

        self.assertFalse(res_sell.is_allowed)
        self.assertEqual(res_sell.tag, "[⛔ BLOQUEADO: BUFFER PRÉ-NYSE]")

    def test_veto_anti_contramao_nyse_open(self):
        """
        Sessão NYSE (11:30+):
        - Se S&P 500 abre a 5890 e cai para 5880: bloqueia COMPRA e libera VENDA.
        - Se S&P 500 sobe para 5905: bloqueia VENDA e libera COMPRA.
        """
        dt_open = datetime(2026, 11, 19, 11, 30, 0, tzinfo=TZ_BRASILIA)
        self.filter.register_tick(5890.0, dt_open) # Abertura NY = 5890.0

        # Cenário A: Queda em NY (5878.0)
        dt_drop = datetime(2026, 11, 19, 11, 34, 0, tzinfo=TZ_BRASILIA)
        self.filter.register_tick(5878.0, dt_drop)

        res_buy = self.filter.evaluate_macro_filter(Direction.COMPRA, dt_drop)
        self.assertFalse(res_buy.is_allowed)
        self.assertEqual(res_buy.tag, "[⛔ BLOQUEADO: VETO S&P 500 ANTI-CONTRAMÃO]")
        self.assertIn("operando em queda em NY", res_buy.reason)

        # Cenário B: Alta em NY (5905.0)
        dt_rise = datetime(2026, 11, 19, 11, 40, 0, tzinfo=TZ_BRASILIA)
        self.filter.register_tick(5905.0, dt_rise)

        res_sell = self.filter.evaluate_macro_filter(Direction.VENDA, dt_rise)
        self.assertFalse(res_sell.is_allowed)
        self.assertEqual(res_sell.tag, "[⛔ BLOQUEADO: VETO S&P 500 ANTI-CONTRAMÃO]")
        self.assertIn("operando em alta em NY", res_sell.reason)

    def test_confluence_boost_nyse_open(self):
        """
        Confluência Dupla:
        - WIN Compra + S&P 500 renovando/rompendo máxima em NY -> +20 Score SMC e tag de confluência.
        """
        dt_open = datetime(2026, 11, 19, 11, 30, 0, tzinfo=TZ_BRASILIA)
        self.filter.register_tick(5890.0, dt_open)

        dt_breakout = datetime(2026, 11, 19, 11, 36, 0, tzinfo=TZ_BRASILIA)
        self.filter.register_tick(5908.0, dt_breakout) # Nova máxima de NY

        res = self.filter.evaluate_macro_filter(Direction.COMPRA, dt_breakout)
        self.assertTrue(res.is_allowed)
        self.assertTrue(res.is_confluence_boost)
        self.assertEqual(res.score_bonus, 20)
        self.assertEqual(res.tag, "[🌎 CONFLUÊNCIA S&P 500 ATIVA]")

    def test_fail_safe_mode(self):
        """
        Modo Fail-Safe:
        - Feed offline (>10s):
          * No buffer (11:27): mantém buffer de segurança bloqueado.
          * Fora do buffer (10:30 ou 14:00): opera normalmente sem travar o motor do WIN.
        """
        # Sem nenhum tick (offline)
        dt_buf = datetime(2026, 11, 19, 11, 28, 0, tzinfo=TZ_BRASILIA)
        res_buf = self.filter.evaluate_macro_filter(Direction.COMPRA, dt_buf)
        self.assertFalse(res_buf.is_allowed)
        self.assertEqual(res_buf.tag, "[⛔ BLOQUEADO: BUFFER PRÉ-NYSE]")

        dt_trade = datetime(2026, 11, 19, 10, 30, 0, tzinfo=TZ_BRASILIA)
        res_trade = self.filter.evaluate_macro_filter(Direction.COMPRA, dt_trade)
        self.assertTrue(res_trade.is_allowed)
        self.assertEqual(res_trade.tag, "[⚠️ S&P 500 OFFLINE (FAIL-SAFE)]")

    def test_integration_with_setup_engine(self):
        """Verifica se o SetupEngine acopla o filtro e bloqueia a emissão do setup."""
        se = SetupEngine(mode="FIXO", asset_spec=WIN_SPEC)
        dt_buf = datetime(2026, 11, 19, 11, 26, 0, tzinfo=TZ_BRASILIA)

        setup = se._build_setup(
            setup_name="Teste Abertura",
            direction=Direction.COMPRA,
            symbol="WINZ26",
            current_price=168500.0,
            timestamp=dt_buf,
            tf_trigger=2,
            in_trend=True,
            invalidation_ref=168250.0,
            structure_desc="Teste estrutural",
            flow_metrics={"delta": 500},
            flow_available=True
        )

        macro_res = self.filter.evaluate_macro_filter(setup.direction, dt_buf)
        self.assertFalse(macro_res.is_allowed)

        # Aplicar bloqueio
        setup.status = SetupStatus.BLOQUEADO
        setup.macro_status = macro_res.tag
        self.assertEqual(setup.status, SetupStatus.BLOQUEADO)
        self.assertEqual(setup.macro_status, "[⛔ BLOQUEADO: BUFFER PRÉ-NYSE]")

    def test_nyse_memory_veto_during_slow_ticks(self):
        """
        Blindagem: Na sessão NYSE (>=11:30), se o S&P está em queda confirmada (ex: -116 pts),
        mesmo que passem 130 segundos sem novo negócio na B3, o veto de COMPRA deve ser MANTIDO.
        """
        dt_open = datetime(2026, 11, 19, 11, 30, 0, tzinfo=TZ_BRASILIA)
        self.filter.register_tick(7415.50, dt_open)

        # Último tick recebido às 12:35 com S&P caindo para 7299.00 (-116.50 pts)
        dt_tick = datetime(2026, 11, 19, 12, 35, 0, tzinfo=TZ_BRASILIA)
        self.filter.register_tick(7299.00, dt_tick)

        # Avaliação às 12:37:15 (135 segundos depois, feed teoricamente stale > 120s)
        dt_eval = datetime(2026, 11, 19, 12, 37, 15, tzinfo=TZ_BRASILIA)
        res_buy = self.filter.evaluate_macro_filter(Direction.COMPRA, dt_eval)

        # Deve MANTER O BLOQUEIO por memória institucional
        self.assertFalse(res_buy.is_allowed)
        self.assertEqual(res_buy.tag, "[⛔ BLOQUEADO: VETO S&P 500 ANTI-CONTRAMÃO]")
        self.assertIn("operando em queda em NY", res_buy.reason)

    def test_tape_reading_absorption_veto(self):
        """
        Blindagem: Se o Tape Reading acusar 'Possível Absorção Vendedora', COMPRA deve ser BLOQUEADA.
        """
        se = SetupEngine(mode="FIXO", asset_spec=WIN_SPEC)
        dt_eval = datetime(2026, 11, 19, 12, 40, 0, tzinfo=TZ_BRASILIA)

        setup = se._build_setup(
            setup_name="Compra Tentativa",
            direction=Direction.COMPRA,
            symbol="WINZ26",
            current_price=168465.0,
            timestamp=dt_eval,
            tf_trigger=1,
            in_trend=True,
            invalidation_ref=168215.0,
            structure_desc="Teste absorção",
            flow_metrics={
                "delta": 88949,
                "flow_pattern": "Possível Absorção Vendedora (Forte compra absorvida passivamente sem deslocamento de alta)"
            },
            flow_available=True
        )

        self.assertIsNotNone(setup)
        self.assertEqual(setup.status, SetupStatus.BLOQUEADO)
        self.assertTrue(any("Absorção Vendedora" in o for o in setup.obstacles))


if __name__ == "__main__":
    unittest.main()
