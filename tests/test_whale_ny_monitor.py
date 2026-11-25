"""
tests/test_whale_ny_monitor.py
===============================================================================
SUITE DE TESTES UNITÁRIOS: WHALE FLOW US & NY CASH OPEN (11:30 BRT)
Valida todas as premissas da @ESPECIFICACAO_WHALE_FLOW_NY_1130.md
===============================================================================
"""

import unittest
from datetime import datetime, time as dtime

from whale_ny_monitor import (
    sanitize_price,
    sanitize_quantity,
    classify_broker,
    classify_magnitude,
    TimesTradesParser,
    WhaleClusterAggregator,
    WhaleCluster,
    TTRecord,
    SMCZonesManager,
    NYCashOpenManager,
    CrossMarketState,
    WhaleDecisionEngine
)


class TestWhaleNYMonitor(unittest.TestCase):

    def test_01_sanitization_price_with_asterisk(self):
        """Sanitização de preços com asterisco '*' e formatação brasileira de milhar."""
        self.assertEqual(sanitize_price("165.485*"), 165485.0)
        self.assertEqual(sanitize_price("165.500,00*"), 165500.0)
        self.assertEqual(sanitize_price("165700*"), 165700.0)
        self.assertEqual(sanitize_price("R$ 165.200*"), 165200.0)
        self.assertEqual(sanitize_price("165.515*"), 165515.0)

        # Quantidades
        self.assertEqual(sanitize_quantity("100"), 100)
        self.assertEqual(sanitize_quantity("1.400"), 1400)
        self.assertEqual(sanitize_quantity("2.010*"), 2010)

    def test_02_broker_taxonomy(self):
        """Classificação rigorosa das corretoras institucionais."""
        # Tier 1 US
        self.assertEqual(classify_broker("Morgan")[0], "TIER_1_US")
        self.assertEqual(classify_broker("Morgan Stanley")[0], "TIER_1_US")
        self.assertEqual(classify_broker("Goldman Sachs")[0], "TIER_1_US")
        self.assertEqual(classify_broker("J.P. Morgan")[0], "TIER_1_US")
        self.assertEqual(classify_broker("BofA Securities")[0], "TIER_1_US")
        self.assertEqual(classify_broker("Citi")[0], "TIER_1_US")

        # Tier 2 Global
        self.assertEqual(classify_broker("UBS")[0], "TIER_2_GLOBAL")
        self.assertEqual(classify_broker("Barclays")[0], "TIER_2_GLOBAL")
        self.assertEqual(classify_broker("BNP Paribas")[0], "TIER_2_GLOBAL")

        # Tier 3 DMA
        self.assertEqual(classify_broker("Ideal")[0], "TIER_3_DMA")
        self.assertEqual(classify_broker("BTG Pactual")[0], "TIER_3_DMA")
        self.assertEqual(classify_broker("XP Investimentos")[0], "TIER_3_DMA")

    def test_03_magnitude_classification(self):
        """Classificação de magnitude de lotes."""
        self.assertIsNone(classify_magnitude(399))
        self.assertEqual(classify_magnitude(400), "WHALE_BLOCK")
        self.assertEqual(classify_magnitude(999), "WHALE_BLOCK")
        self.assertEqual(classify_magnitude(1000), "MEGA_CLIMAX")
        self.assertEqual(classify_magnitude(1400), "MEGA_CLIMAX")

    def test_04_3s_iceberg_clustering(self):
        """Agregação temporal de ordens fatiadas dentro de 3.0 segundos."""
        agg = WhaleClusterAggregator(window_seconds=3.0)
        t0 = datetime(2026, 11, 25, 11, 33, 10, 0)

        # 1ª fatia: 150 contratos (ainda não atinge 400)
        r1 = TTRecord(t0, "Morgan", 165700.0, 150, "COMPRA", "TIER_1_US", 1.0)
        self.assertIsNone(agg.add_trade(r1))

        # 2ª fatia aos 1.5s: 150 contratos (acumula 300, ainda < 400)
        t1 = datetime(2026, 11, 25, 11, 33, 11, 500000)
        r2 = TTRecord(t1, "Morgan", 165700.0, 150, "COMPRA", "TIER_1_US", 1.0)
        self.assertIsNone(agg.add_trade(r2))

        # 3ª fatia aos 2.5s: 200 contratos (total = 500 contratos >= 400 -> Dispara Cluster!)
        t2 = datetime(2026, 11, 25, 11, 33, 12, 500000)
        r3 = TTRecord(t2, "Morgan", 165705.0, 200, "COMPRA", "TIER_1_US", 1.0)
        cluster = agg.add_trade(r3)

        self.assertNotNull = self.assertIsNotNone
        self.assertIsNotNone(cluster)
        self.assertEqual(cluster.total_quantity, 500)
        self.assertEqual(cluster.trades_count, 3)
        self.assertEqual(cluster.broker, "Morgan")
        self.assertEqual(cluster.magnitude, "WHALE_BLOCK")

    def test_05_ny_open_regimes(self):
        """Protocolo de regimes da Abertura de Nova York."""
        # 11:20 -> Pré-Abertura
        t_pre = datetime(2026, 11, 25, 11, 20, 0)
        reg_id, _, blocked = NYCashOpenManager.get_regime(t_pre)
        self.assertEqual(reg_id, "PRE_NY_OPEN")
        self.assertFalse(blocked)

        # 11:31 -> Leilão / Arbitragem ADRs (Bloqueio HOLD)
        t_auction = datetime(2026, 11, 25, 11, 31, 30)
        reg_id, _, blocked = NYCashOpenManager.get_regime(t_auction)
        self.assertEqual(reg_id, "AUCTION_HOLD")
        self.assertTrue(blocked)

        # 11:34 -> Fluxo Direcional NY Aberto
        t_open = datetime(2026, 11, 25, 11, 34, 0)
        reg_id, _, blocked = NYCashOpenManager.get_regime(t_open)
        self.assertEqual(reg_id, "NY_CASH_OPEN")
        self.assertFalse(blocked)

    def test_06_smc_proximity_and_decision_score(self):
        """Cálculo do Score de Assertividade na zona SMC."""
        zones_mgr = SMCZonesManager()
        engine = WhaleDecisionEngine(zones_mgr)
        cross = CrossMarketState(wsp_change_pct=-1.90, wdo_change_pct=0.30, di1f29_change_bps=5.0, blue_chips_alignment="BEARISH")

        t_trade = datetime(2026, 11, 25, 11, 33, 15)
        # Cluster Mega Clímax de 1.400 cts do Morgan no topo (165.700)
        cluster = WhaleCluster(
            cluster_id="TEST_01",
            start_time=t_trade,
            last_time=t_trade,
            broker="Morgan",
            tier="TIER_1_US",
            side="COMPRA",
            total_quantity=1400,
            trades_count=1,
            vwap_price=165700.0,
            magnitude="MEGA_CLIMAX"
        )

        alert = engine.evaluate_cluster(
            cluster=cluster,
            current_price=165700.0,
            cross_market=cross,
            choch_confirmed=True,
            delta_inverting=True,
            current_time=t_trade
        )

        self.assertIsNotNone(alert)
        self.assertEqual(alert.direction, "SHORT")
        self.assertEqual(alert.setup_type, "EXAUSTAO_TOPO")
        self.assertGreaterEqual(alert.score, 80)
        self.assertEqual(alert.stop_loss, 165700.0 + 250.0)
        self.assertEqual(alert.take_profit, 165700.0 - 400.0)

    def test_07_reverse_order_payload_chronological_processing(self):
        """Valida que ordens em ordem decrescente (mais recente no topo, padrão Profit) são ordenadas e disparam alerta."""
        from whale_ny_monitor import WhaleNYMonitor
        monitor = WhaleNYMonitor(mode="LIVE_CLIPBOARD")
        now = datetime(2026, 11, 25, 11, 33, 15)

        # Dados fatiados invertidos (como vem do Profit Pro: mais recente no topo)
        # Três fatias de 150 + 150 + 200 = 500 contratos em 3 segundos
        reverse_payload = f"""
11:33:14.800\tMorgan\t165.700*\t200\tXP\tComprador
11:33:13.450\tMorgan\t165.700*\t150\tBTG\tComprador
11:33:12.100\tMorgan\t165.700*\t150\tIdeal\tComprador
"""
        alerts = monitor.process_text_payload(reverse_payload, ref_date=now)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].broker, "Morgan")
        self.assertEqual(alerts[0].quantity, 500)
        self.assertEqual(alerts[0].direction, "SHORT")


if __name__ == "__main__":
    unittest.main()
