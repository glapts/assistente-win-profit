"""
tests/test_execution_harness.py
Testes unitários e de integração para o ExecutionHarness, TelemetryLogger e painel de decisão multi-agente.
"""

import unittest
import json
import os
import tempfile
from datetime import datetime

from agents.base_agent import AgentVerdict
from harness.execution_harness import ExecutionHarness, HarnessVerdict
from harness.telemetry_logger import TelemetryLogger
from harness.dde_snapshot import HarnessFullSnapshot, AssetSnapshot
from analysis.alert_formatter import format_operational_alert
from core.models import SignalSetup, SetupStatus, Direction
from core.contract import TZ_BRASILIA


def _make_snap(symbol: str, ultimo: float, var: float = 0.0, saldo: float = 0.0, voc: float = 0.0, vov: float = 0.0, neg: int = 100, abertura: float = 0.0) -> AssetSnapshot:
    return AssetSnapshot(
        symbol=symbol,
        timestamp=datetime.now(TZ_BRASILIA),
        ultimo=ultimo,
        abertura=abertura or ultimo,
        variacao=var,
        negocios=neg,
        quantidade=1000.0,
        of_compra=ultimo - 0.5,
        of_venda=ultimo,
        voc=voc,
        vov=vov,
        saldo_agressao=saldo
    )


class TestExecutionHarness(unittest.TestCase):
    """Bateria de testes do Execution Harness e orquestrador dos 7 agentes."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_path = os.path.join(self.temp_dir.name, "test_signals_telemetry.jsonl")
        self.logger = TelemetryLogger(log_path=self.log_path)
        self.harness = ExecutionHarness(logger=self.logger)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_harness_weights_sum_to_one(self):
        """Valida que a soma exata dos pesos dos 7 agentes especialistas é 1.00."""
        total_weight = (
            self.harness.WEIGHT_ZONA_DEFESA +
            self.harness.WEIGHT_PULLBACK_SMC +
            self.harness.WEIGHT_TAPE_MEDIA +
            self.harness.WEIGHT_ORDER_BOOK +
            self.harness.WEIGHT_MACRO_RATES +
            self.harness.WEIGHT_BLUE_CHIPS +
            self.harness.WEIGHT_GLOBAL_INDEX
        )
        self.assertAlmostEqual(total_weight, 1.00, places=4)

    def test_order_of_execution_and_context_enrichment(self):
        """Valida que OrderBookAgent executa primeiro e popula context['book_insights']."""
        context = {
            "current_price": 171500.0,
            "win_book": {
                "of_compra": 171495.0,
                "of_venda": 171500.0,
                "spread_pts": 5.0,
                "voc": 2000.0,
                "vov": 1000.0,
                "delta_voc": 300.0,
                "delta_vov": -50.0,
                "delta_negocios": 30
            },
            "violation_zone": {
                "L_inf": 171450.0,
                "L_sup": 171500.0,
                "touched": True,
                "contracts_buy": 1200,
                "contracts_sell": 400,
                "delta_P_afastamento": 50.0
            }
        }
        # Antes da execução, book_insights não existe
        self.assertNotIn("book_insights", context)

        verdict = self.harness.evaluate_market_confluence("COMPRA", context)

        # Após execução, book_insights foi populado e compartilhado
        self.assertIn("book_insights", context)
        self.assertIn("i_book", context["book_insights"])
        self.assertEqual(verdict.side, "COMPRA")
        self.assertGreater(verdict.score_final, 0.0)

    def test_high_confluence_scenario_favoravel(self):
        """Valida cenário de confluência alta (Score >= 75%) classificado como FAVORÁVEL."""
        now = datetime.now(TZ_BRASILIA)
        snap = HarnessFullSnapshot(timestamp=now)
        snap.assets["WINZ26"] = _make_snap("WINZ26", 171500.0, var=0.85, saldo=12000.0, voc=2500.0, vov=1200.0)
        snap.assets["DI1F29"] = _make_snap("DI1F29", 12.10, var=-0.45, saldo=-4000.0)
        snap.assets["DI1F31"] = _make_snap("DI1F31", 12.35, var=-0.38, saldo=-3500.0)
        snap.assets["WDOZ26"] = _make_snap("WDOZ26", 5450.0, var=-0.65, saldo=-8500.0, voc=800.0, vov=1800.0)
        snap.assets["ITUB4"] = _make_snap("ITUB4", 35.50, var=1.20, saldo=450000.0, voc=200000.0, vov=80000.0)
        snap.assets["PETR4"] = _make_snap("PETR4", 39.80, var=1.85, saldo=720000.0, voc=350000.0, vov=120000.0)
        snap.assets["VALE3"] = _make_snap("VALE3", 64.20, var=0.90, saldo=310000.0, voc=180000.0, vov=90000.0)
        snap.assets["WSPZ26"] = _make_snap("WSPZ26", 6010.0, var=0.75, saldo=5500.0, abertura=5980.0)

        context = {
            "current_price": 171500.0,
            "dde_snapshot": snap,
            "win_book": {
                "of_compra": 171495.0,
                "of_venda": 171500.0,
                "spread_pts": 5.0,
                "voc": 2800.0,
                "vov": 1100.0,
                "delta_voc": 400.0,
                "delta_vov": -80.0,
                "delta_negocios": 45
            },
            "violation_zone": {
                "L_inf": 171450.0,
                "L_sup": 171500.0,
                "touched": True,
                "contracts_buy": 2500,
                "contracts_sell": 600,
                "delta_P_afastamento": 50.0
            },
            "pullback_zone": {
                "in_zone": True,
                "distance_to_fvg": 0.0,
                "distance_to_ob": 0.0,
                "zone_tfs": ["15m", "10m", "5m"]
            },
            "flow_metrics": {
                "buy_volume": 12000,
                "sell_volume": 4000,
                "delta": 8000,
                "trades_count": 350,
                "recent_trades": [
                    {"price": 171480.0, "qty": 100, "side": "BUY"},
                    {"price": 171490.0, "qty": 200, "side": "BUY"},
                    {"price": 171500.0, "qty": 300, "side": "BUY"}
                ]
            }
        }

        verdict = self.harness.evaluate_market_confluence("COMPRA", context, setup_name="Pullback em FVG 15m", entry_price=171500.0)

        self.assertGreaterEqual(verdict.score_final, 75.0)
        self.assertIn("FAVORÁVEL", verdict.classification)
        self.assertIn("4. PAINEL DE DECISÃO MULTI-AGENTE", verdict.panel_text)
        self.assertIn("FAVORÁVEL (CONFLUÊNCIA ALTA)", verdict.panel_text)

    def test_caution_scenario_cautela(self):
        """Valida cenário de blefe no book e contra-fluxo classificado como CAUTELA (< 50%)."""
        now = datetime.now(TZ_BRASILIA)
        snap = HarnessFullSnapshot(timestamp=now)
        snap.assets["WINZ26"] = _make_snap("WINZ26", 171000.0, var=-0.50, saldo=-8000.0, voc=800.0, vov=2500.0)
        snap.assets["DI1F29"] = _make_snap("DI1F29", 12.25, var=0.60, saldo=5000.0)
        snap.assets["DI1F31"] = _make_snap("DI1F31", 12.50, var=0.55, saldo=4500.0)
        snap.assets["WDOZ26"] = _make_snap("WDOZ26", 5520.0, var=0.80, saldo=9000.0, voc=2200.0, vov=700.0)
        snap.assets["ITUB4"] = _make_snap("ITUB4", 34.80, var=-1.10, saldo=-350000.0, voc=70000.0, vov=220000.0)
        snap.assets["PETR4"] = _make_snap("PETR4", 38.90, var=-1.40, saldo=-500000.0, voc=100000.0, vov=380000.0)
        snap.assets["VALE3"] = _make_snap("VALE3", 63.00, var=-0.80, saldo=-200000.0, voc=80000.0, vov=190000.0)
        snap.assets["WSPZ26"] = _make_snap("WSPZ26", 5950.0, var=-0.60, saldo=-4500.0, abertura=5980.0)

        context = {
            "current_price": 171500.0,
            "dde_snapshot": snap,
            # Blefe no book da ponta compradora
            "win_book": {
                "of_compra": 171480.0,
                "of_venda": 171500.0,
                "spread_pts": 20.0,
                "voc": 500.0,
                "vov": 2200.0,
                "delta_voc": -600.0,
                "delta_vov": 300.0,
                "voc_anterior": 1100.0,
                "delta_negocios": 5
            },
            # Compra rompida / vencida
            "violation_zone": {
                "L_inf": 171500.0,
                "L_sup": 171550.0,
                "touched": True,
                "contracts_buy": 300,
                "contracts_sell": 2400,
                "delta_P_afastamento": -40.0
            },
            # Esticado
            "is_stretched": True,
            "distancia_suporte_pts": 180.0,
            # Contra-fluxo violento
            "flow_metrics": {
                "buy_volume": 2000,
                "sell_volume": 11000,
                "delta": -9000,
                "trades_count": 250
            }
        }

        verdict = self.harness.evaluate_market_confluence("COMPRA", context, setup_name="Compra Esticada", entry_price=171500.0)

        self.assertLess(verdict.score_final, 50.0)
        self.assertIn("CAUTELA", verdict.classification)
        self.assertIn("CAUTELA (CONTRA-FLUXO, BLEFE NO BOOK OU ESTICADO)", verdict.panel_text)

    def test_telemetry_logger_jsonl_output(self):
        """Valida gravação e formato íntegro dos logs JSONL em disco."""
        context = {
            "current_price": 170000.0,
            "win_book": {
                "of_compra": 169995.0,
                "of_venda": 170000.0,
                "spread_pts": 5.0,
                "voc": 1500.0,
                "vov": 1500.0
            }
        }
        self.harness.evaluate_market_confluence(
            side="COMPRA",
            context=context,
            setup_name="Teste Telemetria",
            entry_price=170000.0
        )

        self.assertTrue(os.path.exists(self.log_path))
        with open(self.log_path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]

        self.assertEqual(len(lines), 1)
        record = json.loads(lines[0])

        self.assertEqual(record["side"], "COMPRA")
        self.assertEqual(record["setup_name"], "Teste Telemetria")
        self.assertEqual(record["entry_price"], 170000.0)
        self.assertIn("score_final", record)
        self.assertIn("classification", record)
        self.assertIn("p_defesa", record)
        self.assertIn("p_medio_reacao", record)
        self.assertIn("book_insights", record)
        self.assertIn("agents_verdicts", record)
        self.assertEqual(len(record["agents_verdicts"]), 7)

    def test_alert_formatter_includes_sections_3_and_4(self):
        """Valida que format_operational_alert integra as seções 3 e 4 completas sem quebrar."""
        now = datetime.now(TZ_BRASILIA)
        setup = SignalSetup(
            timestamp=now,
            setup_name="Compra por Teste de Suporte SMC",
            direction=Direction.COMPRA,
            symbol="WINZ26",
            status=SetupStatus.CONFIRMADO,
            entry_price=171500.0,
            stop_price=171250.0,
            stop_points=250.0,
            target_price=171900.0,
            target_points=400.0,
            risk_reward=1.60,
            timeframe_trigger=5,
            in_trend_direction=True,
            structure_event="Rompimento com continuidade",
            obstacles=["PASSAGEM LIVRE: Nenhum obstáculo mapeado"],
            facts_observed=["Preço: 171.500", "DELTA=+4200 contratos"],
            interpretations=["Setup 100% qualificado."],
            limitations=["Oscilação padrão"],
            invalidation_criteria="Perda de 171.250"
        )
        flow_data = {
            "buy_volume": 8000,
            "sell_volume": 3800,
            "delta": 4200,
            "trades_count": 210,
            "recent_trades": [
                {"price": 171490.0, "qty": 100, "side": "BUY"},
                {"price": 171500.0, "qty": 150, "side": "BUY"}
            ]
        }
        regimes = {60: "ALTA", 15: "ALTA", 5: "ALTA", 1: "ALTA"}

        alert = format_operational_alert(
            setup=setup,
            regimes=regimes,
            source_name="Nelogica ProfitPro (DDE)",
            delay_ms=0.5,
            quality_status="ÍNTEGRO (FLUXO + ESTRUTURA)",
            flow_data=flow_data,
            use_color=False
        )

        # 1. SuperDOM execution box
        self.assertIn("EXECUÇÃO NO SUPERDOM", alert)
        self.assertIn("1. COMANDO DE EXECUÇÃO:", alert)

        # 2. Seção 3 com Média Aritmética e Sub-bloco BOOK
        self.assertIn("3. CONFIRMAÇÃO DE FLUXO & BOOK (TAPE READING):", alert)
        self.assertIn("Média Aritmética de Reação (T&T)", alert)
        self.assertIn("BOOK:", alert)
        self.assertIn("Of.Compra", alert)
        self.assertIn("Of.Venda", alert)
        self.assertIn("Spread:", alert)
        self.assertIn("Volume de Ofertas", alert)
        self.assertIn("Dinâmica Stacking/Pulling", alert)

        # 3. Seção 4 Painel de Decisão Multi-Agente
        self.assertIn("4. PAINEL DE DECISÃO MULTI-AGENTE (HARNESS ZONA + PULLBACK + BOOK + DDE + TAPE) [DEMO]", alert)
        self.assertIn("ÍNDICE DE PREVISIBILIDADE", alert)
        self.assertIn("ZonaDefesa", alert)
        self.assertIn("PullbackSMC", alert)
        self.assertIn("TapeMedia", alert)
        self.assertIn("OrderBook", alert)
        self.assertIn("MacroRates", alert)
        self.assertIn("BlueChips", alert)
        self.assertIn("GlobalIndex", alert)
        self.assertIn("EXECUÇÃO RÁPIDA NO SUPERDOM", alert)


if __name__ == "__main__":
    unittest.main()
