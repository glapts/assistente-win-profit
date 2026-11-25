"""
tests/test_microstructure_agents.py
Testes unitários rigorosos dos 4 agentes especialistas de microestrutura e ação de preço:
1. OrderBookAgent
2. ZoneViolationDefenseAgent
3. PullbackValueZoneAgent
4. ExtremesTapeAgent
"""

import unittest
from agents.order_book_agent import OrderBookAgent
from agents.zone_violation_agent import ZoneViolationDefenseAgent
from agents.pullback_value_agent import PullbackValueZoneAgent
from agents.extremes_tape_agent import ExtremesTapeAgent


class TestMicrostructureAgents(unittest.TestCase):

    # -------------------------------------------------------------
    # 1. OrderBookAgent Tests
    # -------------------------------------------------------------
    def test_order_book_agent_escora_passiva(self):
        """Testa detecção de Escora Passiva (VOC >= 1.5*VOV, delta_voc > 0, Score 80-100)."""
        agent = OrderBookAgent()
        context = {
            "of_compra": 171400.0,
            "of_venda": 171405.0,
            "voc": 3000.0,
            "vov": 1500.0,
            "delta_voc": 500.0,
            "delta_vov": -100.0,
            "delta_negocios": 20
        }
        verdict = agent.evaluate("COMPRA", context)
        self.assertEqual(verdict.agent_name, "OrderBookAgent")
        self.assertEqual(verdict.bias, "COMPRA")
        self.assertEqual(verdict.status_tag, "ESCORA_PASSIVA")
        self.assertGreaterEqual(verdict.score, 80.0)
        self.assertLessEqual(verdict.score, 100.0)

        # Checa publicação em context['book_insights']
        self.assertIn("book_insights", context)
        insights = context["book_insights"]
        self.assertTrue(insights["is_escora"])
        self.assertEqual(insights["spread_pts"], 5.0)
        self.assertAlmostEqual(insights["imbalance_ratio"], 3000.0 / 4500.0, places=2)

    def test_order_book_agent_blefe_pulling(self):
        """Testa detecção de Blefe/Pulling (queda > 40% sem execuções, Score < 40)."""
        agent = OrderBookAgent()
        context = {
            "of_compra": 171400.0,
            "of_venda": 171405.0,
            "voc": 1000.0,
            "vov": 1500.0,
            "delta_voc": -1000.0,  # Era 2000, caiu 1000 (-50%)
            "delta_vov": 50.0,
            "delta_negocios": 10   # Apenas 10 negócios executados
        }
        verdict = agent.evaluate("COMPRA", context)
        self.assertEqual(verdict.status_tag, "BLEFE_PULLING")
        self.assertLess(verdict.score, 40.0)
        self.assertEqual(verdict.bias, "VENDA")  # Blefe do comprador favorece venda
        self.assertTrue(any("cancelamento" in r.lower() or "queda" in r.lower() for r in verdict.reasons))

    def test_order_book_agent_spread_penalty(self):
        """Testa penalização de spread aberto (> 10 pts)."""
        agent = OrderBookAgent()
        context = {
            "of_compra": 171400.0,
            "of_venda": 171420.0,  # Spread de 20 pts
            "voc": 2000.0,
            "vov": 1800.0,
            "delta_voc": 0.0,
            "delta_vov": 0.0,
            "delta_negocios": 5
        }
        verdict = agent.evaluate("COMPRA", context)
        self.assertTrue(any("spread" in r.lower() for r in verdict.reasons))
        self.assertIn("book_insights", context)
        self.assertEqual(context["book_insights"]["spread_pts"], 20.0)

    # -------------------------------------------------------------
    # 2. ZoneViolationDefenseAgent Tests
    # -------------------------------------------------------------
    def test_zone_violation_compra_vencida(self):
        """Testa COMPRA_VENCIDA quando preço perde L_inf com V_V > V_C."""
        agent = ZoneViolationDefenseAgent()
        context = {
            "zone": (171000.0, 171050.0),
            "current_price": 170980.0,  # Perdeu L_inf (171000)
            "v_c": 1200.0,
            "v_v": 3500.0,              # V_V > V_C
            "book_insights": {"i_book": 0.30}
        }
        verdict = agent.evaluate("COMPRA", context)
        self.assertEqual(verdict.status_tag, "COMPRA_VENCIDA")
        self.assertEqual(verdict.bias, "VENDA")
        self.assertTrue(any("perdido" in r.lower() for r in verdict.reasons))

    def test_zone_violation_venda_vencida(self):
        """Testa VENDA_VENCIDA quando preço supera L_sup com V_C > V_V."""
        agent = ZoneViolationDefenseAgent()
        context = {
            "zone": (171000.0, 171050.0),
            "current_price": 171070.0,  # Superou L_sup (171050)
            "v_c": 4000.0,              # V_C > V_V
            "v_v": 800.0,
            "book_insights": {"i_book": 0.70}
        }
        verdict = agent.evaluate("VENDA", context)
        self.assertEqual(verdict.status_tag, "VENDA_VENCIDA")
        self.assertEqual(verdict.bias, "COMPRA")
        self.assertTrue(any("rompida" in r.lower() for r in verdict.reasons))

    def test_zone_violation_reacao_forte_defesa(self):
        """Testa P_defesa >= 75% gerando REACAO_FORTE_DEFESA."""
        agent = ZoneViolationDefenseAgent()
        context = {
            "zone": (171000.0, 171050.0),
            "current_price": 171045.0,  # Afastado 45 pts de L_inf (W=50) -> I_rep = 45/50 = 0.90
            "v_c": 3000.0,              # R_contratos = (3000-1000)/4000 = 0.50
            "v_v": 1000.0,
            "book_insights": {"i_book": 0.85}  # I_book = 0.85
        }
        # P_defesa = (0.45 * 0.50 + 0.35 * 0.90 + 0.20 * 0.85) * 100 = (0.225 + 0.315 + 0.17) * 100 = 71.0
        # Vamos aumentar R_contratos: V_C = 4500, V_V = 500 -> (4500-500)/5000 = 0.80
        # P_defesa = (0.45 * 0.80 + 0.35 * 0.90 + 0.20 * 0.85) * 100 = (0.36 + 0.315 + 0.17) * 100 = 84.5%
        context["v_c"] = 4500.0
        context["v_v"] = 500.0
        verdict = agent.evaluate("COMPRA", context)
        self.assertEqual(verdict.status_tag, "REACAO_FORTE_DEFESA")
        self.assertGreaterEqual(verdict.score, 75.0)
        self.assertEqual(verdict.bias, "COMPRA")

    # -------------------------------------------------------------
    # 3. PullbackValueZoneAgent Tests
    # -------------------------------------------------------------
    def test_pullback_value_agent_anti_esticado(self):
        """Testa Regra ANTI-ESTICADO: NUNCA valida compra no topo esticado (Score = 0.0, status_tag = 'ESTICADO')."""
        agent = PullbackValueZoneAgent()
        context = {
            "trend": "ALTA",
            "current_price": 172000.0,
            "is_stretched": True
        }
        verdict = agent.evaluate("COMPRA", context)
        self.assertEqual(verdict.status_tag, "ESTICADO")
        self.assertEqual(verdict.score, 0.0)
        self.assertEqual(verdict.bias, "NEUTRO")
        self.assertTrue(any("anti-esticado" in r.lower() for r in verdict.reasons))

    def test_pullback_value_agent_anti_esticado_venda(self):
        """Testa Regra ANTI-ESTICADO para VENDA no fundo esticado (Score = 0.0)."""
        agent = PullbackValueZoneAgent()
        context = {
            "trend": "BAIXA",
            "current_price": 169000.0,
            "is_stretched": True
        }
        verdict = agent.evaluate("VENDA", context)
        self.assertEqual(verdict.status_tag, "ESTICADO")
        self.assertEqual(verdict.score, 0.0)
        self.assertEqual(verdict.bias, "NEUTRO")

    def test_pullback_value_agent_confluencia_fvg_ob(self):
        """Testa confluência de retração em FVG/OB (15m, 10m, 5m com 50% CE) pontuando 85 a 100."""
        agent = PullbackValueZoneAgent()
        context = {
            "trend": "ALTA",
            "current_price": 171085.0,
            "pullback_zone": {
                "type": "FVG",
                "timeframe": 15,
                "top": 171170.0,
                "bottom": 171000.0,
                "ce_50": 171085.0
            }
        }
        verdict = agent.evaluate("COMPRA", context)
        self.assertEqual(verdict.status_tag, "PULLBACK_VALIDO")
        self.assertEqual(verdict.bias, "COMPRA")
        self.assertGreaterEqual(verdict.score, 85.0)
        self.assertLessEqual(verdict.score, 100.0)
        self.assertTrue(any("pullback" in r.lower() for r in verdict.reasons))

    # -------------------------------------------------------------
    # 4. ExtremesTapeAgent Tests
    # -------------------------------------------------------------
    def test_extremes_tape_agent_filter_passed(self):
        """Testa aprovação do filtro anti-falso positivo (Ultimo >= P_medio_reacao na Compra)."""
        agent = ExtremesTapeAgent()
        context = {
            "current_price": 171450.0,
            "agr_compra_300s": 8500.0,
            "agr_venda_300s": 4200.0,
            "delta_300s": 4300.0,
            "p_reacao_levels": [171400.0, 171410.0, 171420.0],  # Média = 171410.0
            "grandes_execucoes": [{"price": 171410.0, "qty": 200, "side": "BUY"}]
        }
        # current_price (171450) >= P_medio_reacao (171410) -> Passou!
        verdict = agent.evaluate("COMPRA", context)
        self.assertEqual(verdict.bias, "COMPRA")
        self.assertGreaterEqual(verdict.score, 80.0)
        self.assertEqual(verdict.status_tag, "ALINHADO")
        self.assertTrue(any("delta" in r.lower() for r in verdict.reasons))

    def test_extremes_tape_agent_filter_failed_trap(self):
        """Testa falha no filtro anti-falso positivo (preço colapsou abaixo de P_medio_reacao na Compra)."""
        agent = ExtremesTapeAgent()
        context = {
            "current_price": 171380.0,  # Colapsou para 171380
            "delta_300s": 1200.0,
            "p_reacao_levels": [171420.0, 171440.0],  # Média = 171430.0
        }
        # current_price (171380) < P_medio_reacao (171430) -> Falso Rompimento / Armadilha!
        verdict = agent.evaluate("COMPRA", context)
        self.assertEqual(verdict.status_tag, "COMPRA_VENCIDA")
        self.assertEqual(verdict.bias, "VENDA")  # Favorece venda após armadilha de compra
        self.assertLess(verdict.score, 40.0)
        self.assertTrue(any("falso rompimento" in r.lower() for r in verdict.reasons))

    def test_extremes_tape_agent_absorcao(self):
        """Testa detecção de absorção com P_defesa / REACAO_FORTE_DEFESA."""
        agent = ExtremesTapeAgent()
        context = {
            "current_price": 171410.0,
            "delta_300s": -2500.0,
            "flow_pattern": "Possível Absorção Compradora (forte venda absorvida passivamente)",
            "p_reacao_levels": [171400.0, 171405.0]  # Média = 171402.5 -> 171410 >= 171402.5
        }
        verdict = agent.evaluate("COMPRA", context)
        self.assertEqual(verdict.status_tag, "REACAO_FORTE_DEFESA")
        self.assertGreaterEqual(verdict.score, 90.0)
        self.assertTrue(any("absorção" in r.lower() for r in verdict.reasons))


if __name__ == "__main__":
    unittest.main()
