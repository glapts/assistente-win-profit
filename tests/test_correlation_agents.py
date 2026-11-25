"""
tests/test_correlation_agents.py
Testes unitários rigorosos dos 3 agentes de correlação de mercado:
1. MacroRatesAgent (DI1F29, DI1F31, WDOZ26 / WDOFUT)
2. BlueChipsFlowAgent (ITUB4, PETR4, VALE3)
3. GlobalIndexAgent (WSPZ26)
"""

import unittest
from datetime import datetime
from agents.macro_rates_agent import MacroRatesAgent
from agents.bluechips_flow_agent import BlueChipsFlowAgent
from agents.global_index_agent import GlobalIndexAgent
from harness.dde_snapshot import AssetSnapshot, TZ_BRASILIA


def _make_snap(symbol: str, ultimo: float, var: float = 0.0, saldo: float = 0.0, voc: float = 0.0, vov: float = 0.0, neg: int = 100) -> AssetSnapshot:
    return AssetSnapshot(
        symbol=symbol,
        timestamp=datetime.now(TZ_BRASILIA),
        ultimo=ultimo,
        abertura=ultimo,
        variacao=var,
        negocios=neg,
        quantidade=1000.0,
        of_compra=ultimo - 0.5,
        of_venda=ultimo,
        voc=voc,
        vov=vov,
        saldo_agressao=saldo
    )


class TestCorrelationAgents(unittest.TestCase):

    # -------------------------------------------------------------
    # 1. MacroRatesAgent Tests
    # -------------------------------------------------------------
    def test_macro_rates_venda_alinhada(self):
        """Testa VENDA no WIN com DI abrindo taxa e Dólar subindo (Score 75-100)."""
        agent = MacroRatesAgent()
        context = {
            "assets": {
                "DI1F29": _make_snap("DI1F29", 12.50, var=+0.08, saldo=+250.0),
                "DI1F31": _make_snap("DI1F31", 12.85, var=+0.06, saldo=+300.0),
                "WDOZ26": _make_snap("WDOZ26", 5480.0, var=+0.45, saldo=+1200.0, voc=500.0, vov=250.0)
            }
        }
        verdict = agent.evaluate("VENDA", context)
        self.assertEqual(verdict.agent_name, "MacroRatesAgent")
        self.assertEqual(verdict.bias, "VENDA")
        self.assertEqual(verdict.status_tag, "ALINHADO")
        self.assertGreaterEqual(verdict.score, 75.0)
        self.assertTrue(any("di1f29" in r.lower() for r in verdict.reasons))
        self.assertTrue(any("dólar" in r.lower() for r in verdict.reasons))

    def test_macro_rates_compra_alinhada(self):
        """Testa COMPRA no WIN com DI fechando taxa e Dólar recuando (Score 75-100)."""
        agent = MacroRatesAgent()
        context = {
            "assets": {
                "DI1F29": _make_snap("DI1F29", 12.35, var=-0.07, saldo=-400.0),
                "DI1F31": _make_snap("DI1F31", 12.70, var=-0.09, saldo=-500.0),
                "WDOZ26": _make_snap("WDOZ26", 5450.0, var=-0.50, saldo=-1500.0, voc=200.0, vov=600.0)
            }
        }
        verdict = agent.evaluate("COMPRA", context)
        self.assertEqual(verdict.bias, "COMPRA")
        self.assertEqual(verdict.status_tag, "ALINHADO")
        self.assertGreaterEqual(verdict.score, 75.0)
        self.assertTrue(any("risk-on" in r.lower() or "fechando" in r.lower() for r in verdict.reasons))

    def test_macro_rates_fallback_wdofut(self):
        """Testa fallback automático para WDOFUT quando WDOZ26 está sem liquidez."""
        agent = MacroRatesAgent()
        context = {
            "assets": {
                "DI1F29": _make_snap("DI1F29", 12.35, var=-0.05, saldo=-100.0),
                "DI1F31": _make_snap("DI1F31", 12.70, var=-0.05, saldo=-100.0),
                "WDOZ26": _make_snap("WDOZ26", 0.0, neg=0),  # Vazio
                "WDOFUT": _make_snap("WDOFUT", 5450.0, var=-0.40, saldo=-800.0, voc=150.0, vov=450.0)
            }
        }
        verdict = agent.evaluate("COMPRA", context)
        self.assertEqual(verdict.bias, "COMPRA")
        self.assertGreaterEqual(verdict.score, 75.0)
        self.assertEqual(verdict.metrics["wdo_symbol"], "WDOFUT")

    def test_macro_rates_dados_herdados_neutro(self):
        """Testa retorno NEUTRO (score = 50.0) quando dados estão ausentes ou zerados."""
        agent = MacroRatesAgent()
        context = {"assets": {}}
        verdict = agent.evaluate("COMPRA", context)
        self.assertEqual(verdict.bias, "NEUTRO")
        self.assertEqual(verdict.score, 50.0)
        self.assertTrue(any("indisponíveis" in r.lower() or "herdados" in r.lower() for r in verdict.reasons))

    # -------------------------------------------------------------
    # 2. BlueChipsFlowAgent Tests
    # -------------------------------------------------------------
    def test_bluechips_compra_alinhada(self):
        """Testa COMPRA no WIN quando pelo menos 2 das 3 ações líderes confirmam fluxo comprador."""
        agent = BlueChipsFlowAgent()
        context = {
            "assets": {
                "ITUB4": _make_snap("ITUB4", 35.50, var=+1.2, saldo=+450000.0),
                "PETR4": _make_snap("PETR4", 38.90, var=+0.8, saldo=+600000.0),
                "VALE3": _make_snap("VALE3", 62.00, var=-0.2, saldo=-100000.0)  # Divergente
            }
        }
        # 2 de 3 ações (ITUB4 e PETR4) com saldo comprador -> Score 75-100
        verdict = agent.evaluate("COMPRA", context)
        self.assertEqual(verdict.agent_name, "BlueChipsFlowAgent")
        self.assertEqual(verdict.bias, "COMPRA")
        self.assertEqual(verdict.status_tag, "ALINHADO")
        self.assertGreaterEqual(verdict.score, 75.0)
        self.assertEqual(verdict.metrics["compra_signals"], 2)

    def test_bluechips_venda_alinhada(self):
        """Testa VENDA no WIN quando pelo menos 2 das 3 ações apresentam saldo negativo ou book vendedor."""
        agent = BlueChipsFlowAgent()
        context = {
            "assets": {
                "ITUB4": _make_snap("ITUB4", 34.80, var=-0.9, saldo=-300000.0),
                "PETR4": _make_snap("PETR4", 38.00, var=+0.1, saldo=0.0, voc=100000.0, vov=250000.0), # VOV > VOC * 1.10
                "VALE3": _make_snap("VALE3", 61.20, var=-1.4, saldo=-500000.0)
            }
        }
        verdict = agent.evaluate("VENDA", context)
        self.assertEqual(verdict.bias, "VENDA")
        self.assertEqual(verdict.status_tag, "ALINHADO")
        self.assertGreaterEqual(verdict.score, 85.0)

    def test_bluechips_dados_insuficientes_neutro(self):
        """Testa retorno NEUTRO (score = 50.0) quando menos de 2 ações possuem dados válidos."""
        agent = BlueChipsFlowAgent()
        context = {
            "assets": {
                "PETR4": _make_snap("PETR4", 38.00)
                # ITUB4 e VALE3 ausentes
            }
        }
        verdict = agent.evaluate("COMPRA", context)
        self.assertEqual(verdict.bias, "NEUTRO")
        self.assertEqual(verdict.score, 50.0)
        self.assertTrue(any("insuficientes" in r.lower() or "herdados" in r.lower() for r in verdict.reasons))

    # -------------------------------------------------------------
    # 3. GlobalIndexAgent Tests
    # -------------------------------------------------------------
    def test_global_index_compra_alinhada(self):
        """Testa COMPRA no WIN quando WSPZ26 opera positivo com saldo_agressao > 0."""
        agent = GlobalIndexAgent()
        context = {
            "assets": {
                "WSPZ26": _make_snap("WSPZ26", 5880.0, var=+0.65, saldo=+850.0)
            }
        }
        verdict = agent.evaluate("COMPRA", context)
        self.assertEqual(verdict.agent_name, "GlobalIndexAgent")
        self.assertEqual(verdict.bias, "COMPRA")
        self.assertEqual(verdict.status_tag, "ALINHADO")
        self.assertGreaterEqual(verdict.score, 75.0)
        self.assertTrue(any("wspz26" in r.lower() for r in verdict.reasons))

    def test_global_index_venda_alinhada(self):
        """Testa VENDA no WIN quando WSPZ26 opera negativo com saldo_agressao < 0."""
        agent = GlobalIndexAgent()
        context = {
            "assets": {
                "WSPZ26": _make_snap("WSPZ26", 5820.0, var=-0.55, saldo=-1100.0)
            }
        }
        verdict = agent.evaluate("VENDA", context)
        self.assertEqual(verdict.bias, "VENDA")
        self.assertEqual(verdict.status_tag, "ALINHADO")
        self.assertGreaterEqual(verdict.score, 75.0)
        self.assertTrue(any("risk-off" in r.lower() or "negativo" in r.lower() for r in verdict.reasons))

    def test_global_index_dados_herdados_neutro(self):
        """Testa retorno NEUTRO (score = 50.0) quando WSPZ26 está sem dados."""
        agent = GlobalIndexAgent()
        context = {"assets": {}}
        verdict = agent.evaluate("COMPRA", context)
        self.assertEqual(verdict.bias, "NEUTRO")
        self.assertEqual(verdict.score, 50.0)
        self.assertTrue(any("ausentes" in r.lower() or "herdados" in r.lower() for r in verdict.reasons))


if __name__ == "__main__":
    unittest.main()
