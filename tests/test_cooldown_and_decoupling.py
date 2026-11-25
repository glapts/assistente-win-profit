"""
tests/test_cooldown_and_decoupling.py
Testes unitários para:
1. Cooldown Inteligente de Zonas (10 min + 150 pts de afastamento) com limite de 3 toques.
2. Gatilho de Descolamento Macro (Commodities Vale/Petrobras e Dólar/DI anulam veto do S&P 500).
"""

import unittest
from datetime import datetime, timedelta

from core.harness.contracts import (
    FVGZone,
    ZoneType,
    ZoneStatus,
    PrimarySetup,
    TradingDirection,
    DealingRange,
    Niveis60mContract,
    RuntimeStateContract
)
from core.harness.state_machine import FVGStateMachine
from core.harness.execution_harness import ExecutionHarness
from core.agents.orchestrator import Orchestrator
from core.agents.macro_agent import MacroAgent
from core.agents.basket_agent import BasketAgent
from core.agents.sentinel_agent import SentinelAgent


class TestCooldownAndDecoupling(unittest.TestCase):
    def setUp(self):
        self.dealing_range = DealingRange(
            topo_estrutural=168000.0,
            fundo_estrutural=164000.0,
            equilibrium_50=166000.0
        )
        self.zone = FVGZone(
            id="ZONA_TEST_RESISTENCIA",
            tipo_original=ZoneType.BEARISH,
            top=167200.0,
            ce_50=167100.0,
            bottom=167000.0,
            setup_primario=PrimarySetup.CONTINUATION_SELL,
            stop_sugerido_pts=250.0,
            alvo_sugerido_pts=400.0,
            status=ZoneStatus.UNMITIGATED
        )
        self.niveis = Niveis60mContract(
            versao_contrato="2.0",
            ativo="WINZ26",
            data_referencia="2026-11-25",
            dealing_range=self.dealing_range,
            zonas_fvg=[self.zone]
        )

    def test_smart_cooldown_lifecycle_and_clearance(self):
        """Valida que a zona cumpre 10min de repouso E 150pts de afastamento antes de rearmar."""
        sm = FVGStateMachine(zones=[self.zone])
        t0 = datetime(2026, 11, 25, 14, 0, 0)

        # 1. Preço entra na zona
        sm.evaluate_price_tick(167100.0, t0)
        self.assertEqual(self.zone.status, ZoneStatus.TESTING_CONTINUATION)

        # 2. Simula emissão de sinal: entra em COOLDOWN inteligente
        self.zone.touch_count += 1
        self.zone.status = ZoneStatus.COOLDOWN
        self.zone.cooldown_until = t0 + timedelta(minutes=10)
        self.zone.max_clearance_reached = 0.0

        # 3. Durante os 10 min dentro do caixote (preço em 167050, clearance=0): NÃO rearma
        t_5m = t0 + timedelta(minutes=5)
        sm.evaluate_price_tick(167050.0, t_5m)
        self.assertEqual(self.zone.status, ZoneStatus.COOLDOWN)

        # 4. Passaram 11 minutos, MAS preço permaneceu na congestão (clearance=50 < 150pts): NÃO rearma
        t_11m = t0 + timedelta(minutes=11)
        sm.evaluate_price_tick(167050.0, t_11m)
        self.assertEqual(self.zone.status, ZoneStatus.COOLDOWN)

        # 5. Preço se afasta 200 pontos para baixo (166800): clearance = 167000 - 166800 = 200 >= 150pts!
        sm.evaluate_price_tick(166800.0, t_11m)
        self.assertEqual(self.zone.status, ZoneStatus.UNMITIGATED)
        self.assertEqual(self.zone.touch_count, 1)

        # 6. Preço volta a testar a zona após afastamento: Rearma para segundo teste!
        sm.evaluate_price_tick(167100.0, t_11m + timedelta(minutes=2))
        self.assertEqual(self.zone.status, ZoneStatus.TESTING_CONTINUATION)

    def test_exhausted_after_3_touches(self):
        """Valida que após 3 toques a zona fica definitivamente EXHAUSTED."""
        harness = ExecutionHarness(
            niveis_contract=self.niveis,
            runtime_state=RuntimeStateContract(
                timestamp=datetime.now().isoformat(),
                state_version=1,
                ttl_seconds=120.0,
                data_quality="INTEGRITY_OK",
                execution_mode="COPILOT",
                trading_enabled=True,
                allowed_direction="SHORT_ONLY",
                confidence_score=0.85
            ),
            session_storage_path=None
        )

        t0 = datetime(2026, 11, 25, 14, 0, 0)
        z = harness.state_machine.zones["ZONA_TEST_RESISTENCIA"]

        # Toque 1
        harness._emit_signal(z, TradingDirection.SHORT, 167100.0, t0, 150, True)
        self.assertEqual(z.status, ZoneStatus.COOLDOWN)
        self.assertEqual(z.touch_count, 1)

        # Toque 2
        harness._emit_signal(z, TradingDirection.SHORT, 167100.0, t0 + timedelta(minutes=15), 150, True)
        self.assertEqual(z.status, ZoneStatus.COOLDOWN)
        self.assertEqual(z.touch_count, 2)

        # Toque 3 (Máximo atingido)
        harness._emit_signal(z, TradingDirection.SHORT, 167100.0, t0 + timedelta(minutes=30), 150, True)
        self.assertEqual(z.status, ZoneStatus.EXHAUSTED)
        self.assertEqual(z.touch_count, 3)

    def test_macro_decoupling_override(self):
        """Valida que Vale >= +2.0%, Petro >= +1.5% e Dólar < 0 anulam o veto de compra do S&P 500."""
        macro = MacroAgent()
        basket = BasketAgent()
        sentinel = SentinelAgent()

        orchestrator = Orchestrator(
            macro_agent=macro,
            basket_agent=basket,
            sentinel_agent=sentinel
        )

        now = datetime(2026, 11, 25, 14, 30, 0)

        # Cenário 1: S&P cai (-2.5%), Vale e Petro fracas -> SHORT_ONLY
        macro.update_sp500(price=5900.0, change_pct=-2.50, timestamp=now)
        basket.update_stock("VALE3", 0.5, timestamp=now)
        basket.update_stock("PETR4", 0.2, timestamp=now)
        st1 = orchestrator.run_cycle(current_time=now)
        self.assertEqual(st1.allowed_direction, TradingDirection.SHORT_ONLY)

        # Cenário 2: S&P cai (-2.5%), MAS Vale (+2.8%), Petro (+1.9%) e Dólar (-1.2%) disparam -> DESCOLAMENTO!
        basket.update_stock("VALE3", 2.8, timestamp=now)
        basket.update_stock("PETR4", 1.9, timestamp=now)
        macro.update_dxy(dxy_val=104.0, change_pct=-1.20, timestamp=now)
        basket.update_di("DI1F29", -2.0, timestamp=now)

        st2 = orchestrator.run_cycle(current_time=now)
        self.assertEqual(st2.allowed_direction, TradingDirection.BOTH)
        self.assertTrue(any("DESCOLAMENTO MACRO ATIVO" in v for v in st2.active_vetos))


if __name__ == "__main__":
    unittest.main()
