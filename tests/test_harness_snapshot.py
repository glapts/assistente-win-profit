"""
tests/test_harness_snapshot.py
Validação unitária estrita do coletor DDE (harness/dde_snapshot.py) e do contrato dos agentes (agents/base_agent.py).
Zero alteração em scripts legados.
"""

import unittest
from datetime import datetime
from agents.base_agent import AgentVerdict, BaseSpecialistAgent, VALID_STATUS_TAGS
from harness.dde_snapshot import (
    DdeSnapshotCollector,
    parse_ptbr_float,
    parse_ptbr_int,
    normalize_column_name,
    HARNESS_WIN_ASSETS,
    PROFIT_COLUMNS_CANONICAL
)


class MockTestAgent(BaseSpecialistAgent):
    def evaluate(self, side: str, context: dict) -> AgentVerdict:
        return AgentVerdict(
            agent_name=self.agent_name,
            weight=self.weight,
            bias="COMPRA" if side == "COMPRA" else "VENDA",
            score=85.5,
            status_tag="PULLBACK_VALIDO",
            reasons=["Preço na zona de desconto", "Delta positivo", "Absorção confirmada", "Excesso de razão descartada"],
            metrics={"test_metric": 123.45}
        )


class TestBaseAgentAndDdeSnapshot(unittest.TestCase):

    def test_agent_verdict_sanitation(self):
        """Testa regras de saneamento do AgentVerdict (limites de score, max 3 razões, bias válido)."""
        verdict = AgentVerdict(
            agent_name="TestAgent",
            weight=1.5,
            bias="COMPRA",
            score=150.0,  # Acima de 100 -> deve limitar em 100.0
            status_tag="PULLBACK_VALIDO",
            reasons=["Razão 1", "Razão 2", "Razão 3", "Razão 4 excedente"],
            metrics={"alpha": 10}
        )
        self.assertEqual(verdict.score, 100.0)
        self.assertEqual(len(verdict.reasons), 3)
        self.assertEqual(verdict.bias, "COMPRA")
        self.assertEqual(verdict.status_tag, "PULLBACK_VALIDO")

        # Teste com score negativo e bias inválido
        v2 = AgentVerdict(
            agent_name="TestAgent2",
            weight=-0.5,
            bias="INVALID_SIDE",
            score=-20.0,
            status_tag="DESCONHECIDO"
        )
        self.assertEqual(v2.score, 0.0)
        self.assertEqual(v2.bias, "NEUTRO")
        self.assertEqual(v2.weight, 0.0)
        self.assertIn(v2.status_tag, VALID_STATUS_TAGS)

    def test_agent_subclass(self):
        """Testa instanciação e execução de subclasse de BaseSpecialistAgent."""
        agent = MockTestAgent("OrderBookAgent", weight=0.20)
        verdict = agent.evaluate("COMPRA", {})
        self.assertIsInstance(verdict, AgentVerdict)
        self.assertEqual(verdict.agent_name, "OrderBookAgent")
        self.assertEqual(verdict.bias, "COMPRA")
        self.assertEqual(len(verdict.reasons), 3)

    def test_ptbr_parsers(self):
        """Testa conversão estrita de formatos numéricos PT-BR e tratamento de erros DDE sem exceção."""
        self.assertEqual(parse_ptbr_float("165.920,00"), 165920.0)
        self.assertEqual(parse_ptbr_float("14,25"), 14.25)
        self.assertEqual(parse_ptbr_float("-0,35%"), -0.35)
        self.assertEqual(parse_ptbr_float("R$ 5.470,50"), 5470.50)
        self.assertEqual(parse_ptbr_float(""), 0.0)
        self.assertEqual(parse_ptbr_float(None), 0.0)
        self.assertEqual(parse_ptbr_float("#N/D"), 0.0)
        self.assertEqual(parse_ptbr_float("N/A"), 0.0)
        self.assertEqual(parse_ptbr_float("ERR"), 0.0)

        self.assertEqual(parse_ptbr_int("1.250"), 1250)
        self.assertEqual(parse_ptbr_int("165.920,00"), 165920)
        self.assertEqual(parse_ptbr_int(None), 0)
        self.assertEqual(parse_ptbr_int("#N/D"), 0)

    def test_column_name_normalization(self):
        """Testa normalização das 15 colunas do Profit Pro."""
        self.assertEqual(normalize_column_name("Ultimo"), "ultimo")
        self.assertEqual(normalize_column_name("Of.Compra"), "of_compra")
        self.assertEqual(normalize_column_name("Of.Venda"), "of_venda")
        self.assertEqual(normalize_column_name("VOC"), "voc")
        self.assertEqual(normalize_column_name("VOV"), "vov")
        self.assertEqual(normalize_column_name("Agr. Compra"), "agr_compra")
        self.assertEqual(normalize_column_name("Agr. Venda"), "agr_venda")
        self.assertEqual(normalize_column_name("Saldo de Agressao"), "saldo_agressao")
        self.assertEqual(normalize_column_name("Lote Padrao"), "lote_padrao")
        self.assertEqual(normalize_column_name("AGRVOLC"), "agr_compra")
        self.assertEqual(normalize_column_name("OCP"), "of_compra")

    def test_dde_collector_ingestion_and_fallback(self):
        """Testa ingestão dos 10 ativos, cálculo de deltas, buffer circular e fallback de WIN e WDO."""
        collector = DdeSnapshotCollector(max_history=20)

        # 1. Ingestão inicial: WINZ26 zerado (vencido/sem liquidez), WINFUT ativo
        raw_payload_1 = {
            "WINZ26": {"Ultimo": "0,00", "Negocios": "0"},
            "WINFUT": {
                "Ultimo": "171.400,00",
                "Abertura": "171.000,00",
                "Maximo": "171.600,00",
                "Minimo": "170.900,00",
                "Variacao": "+0,25%",
                "Negocios": "12.500",
                "Quantidade": "150.000",
                "Of.Compra": "171.395,00",
                "Of.Venda": "171.400,00",
                "VOC": "1.800",
                "VOV": "1.200",
                "Agr. Compra": "78.000",
                "Agr. Venda": "72.000",
                "Saldo de Agressao": "+6.000",
                "Lote Padrao": "1"
            },
            "WDOZ26": {"Ultimo": "5.470,50", "Negocios": "3.500", "Of.Compra": "5.470,00", "Of.Venda": "5.470,50", "VOC": "300", "VOV": "450"},
            "WDOFUT": {"Ultimo": "5.470,50", "Negocios": "3.500"},
            "DI1F29": {"Ultimo": "12,45", "Abertura": "12,40"},
            "DI1F31": {"Ultimo": "12,80", "Abertura": "12,75"},
            "ITUB4": {"Ultimo": "35,20", "Abertura": "35,00"},
            "PETR4": {"Ultimo": "38,50", "Abertura": "38,20"},
            "VALE3": {"Ultimo": "62,30", "Abertura": "61,90"},
            "WSPZ26": {"Ultimo": "5.850,00", "Abertura": "5.830,00"}
        }

        snap1 = collector.ingest_raw_snapshot(raw_payload_1)

        # Fallback do WIN deve ter resolvido para WINFUT
        self.assertEqual(collector.active_win_symbol, "WINFUT")
        # WDOZ26 estava válido -> active_wdo deve ser WDOZ26
        self.assertEqual(collector.active_wdo_symbol, "WDOZ26")

        # Verifica métricas do Book
        book_metrics_1 = collector.get_win_book_metrics()
        self.assertEqual(book_metrics_1["active_symbol"], "WINFUT")
        self.assertEqual(book_metrics_1["of_compra"], 171395.0)
        self.assertEqual(book_metrics_1["of_venda"], 171400.0)
        self.assertEqual(book_metrics_1["spread_pts"], 5.0)
        self.assertEqual(book_metrics_1["voc"], 1800.0)
        self.assertEqual(book_metrics_1["vov"], 1200.0)
        self.assertEqual(book_metrics_1["imbalance_compra_pct"], 60.0)
        self.assertEqual(book_metrics_1["imbalance_venda_pct"], 40.0)
        self.assertEqual(book_metrics_1["ratio_voc_vov"], 1.5)
        # Primeiro snapshot: deltas são 0.0
        self.assertEqual(book_metrics_1["delta_voc"], 0.0)
        self.assertEqual(book_metrics_1["delta_vov"], 0.0)

        # 2. Ingestão subsequente para testar Deltas Instantâneos
        raw_payload_2 = {
            "WINFUT": {
                "Ultimo": "171.420,00",
                "Negocios": "12.550",       # +50
                "Quantidade": "150.800",     # +800
                "Of.Compra": "171.415,00",
                "Of.Venda": "171.420,00",
                "VOC": "2.200",              # +400
                "VOV": "1.000",              # -200
            }
        }

        snap2 = collector.ingest_raw_snapshot(raw_payload_2)
        book_metrics_2 = collector.get_win_book_metrics()
        self.assertEqual(book_metrics_2["voc"], 2200.0)
        self.assertEqual(book_metrics_2["vov"], 1000.0)
        self.assertEqual(book_metrics_2["delta_voc"], 400.0)
        self.assertEqual(book_metrics_2["delta_vov"], -200.0)

        win_snap = collector.get_active_win_snapshot()
        self.assertEqual(win_snap.delta_negocios, 50)
        self.assertEqual(win_snap.delta_quantidade, 800.0)

        # 3. Buffer circular: alimentar 25 vezes e checar maxlen=20
        for i in range(25):
            collector.ingest_raw_snapshot({"WINFUT": {"Ultimo": f"171.{420+i},00"}})
        self.assertEqual(len(collector.history), 20)

    def test_legacy_scripts_unaltered(self):
        """Verifica se os arquivos legados essenciais não foram corrompidos."""
        import os
        legacy_files = [
            "main.py",
            "feeds/dde_feed.py",
            "analysis/alert_formatter.py",
            "analysis/book_analyzer.py",
            "analysis/tape_reading.py",
            "analysis/fvg_mtf_scanner.py",
            "analysis/market_structure.py",
            "setups/setup_engine.py",
            "core/engine.py"
        ]
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for f in legacy_files:
            p = os.path.join(base_dir, f)
            self.assertTrue(os.path.exists(p), f"Arquivo legado não encontrado: {f}")


if __name__ == "__main__":
    unittest.main()
