"""
tests/test_fail_safe_hardening.py
Suíte de testes de regressão automatizados para validação de segurança e Fail-Safe (Fase 2).
Cobre:
  1. Fail-Closed no Gatekeeper (runtime ausente, expirado, inválido)
  2. Circuit Breakers e Event Lockouts
  3. Governança e invariantes matemáticas em TradeSignal (LONG e SHORT)
  4. TTL e frescor de dados em AgentOpinion
  5. Persistência da máquina de estados e tolerância a reinício
  6. Consumo seguro de zonas (reversão em caso de falha de persistência)
  7. Versionamento atômico do Orquestrador
"""

import os
import tempfile
import unittest
from datetime import datetime, timedelta

from core.harness.contracts import (
    DealingRange,
    TradingDirection,
    PriceRegime,
    ZoneType,
    ZoneStatus,
    PrimarySetup,
    FVGZone,
    Niveis60mContract,
    CircuitBreakerState,
    MacroRegimeState,
    BasketRegimeState,
    RuntimeStateContract,
    TradeSignal,
    ExecutionMode
)
from core.harness.gatekeeper import HarnessGatekeeper
from core.harness.state_machine import FVGStateMachine
from core.harness.execution_harness import ExecutionHarness
from core.agents.base_agent import AgentOpinion
from core.agents.macro_agent import MacroAgent
from core.agents.basket_agent import BasketAgent
from core.agents.sentinel_agent import SentinelAgent
from core.agents.orchestrator import Orchestrator


class TestFailSafeHardening(unittest.TestCase):
    def setUp(self):
        self.dr = DealingRange(
            topo_estrutural=171000.0,
            fundo_estrutural=169000.0,
            equilibrium_50=170000.0
        )
        self.valid_runtime = RuntimeStateContract(
            timestamp=datetime.now().isoformat(),
            state_version=1,
            ttl_seconds=120.0,
            data_quality="INTEGRITY_OK",
            trading_enabled=True,
            allowed_direction=TradingDirection.BOTH,
            confidence_score=0.85,
            circuit_breaker=CircuitBreakerState(daily_stops_count=0, max_daily_stops=2, lockout_active=False),
            macro_regime=MacroRegimeState(),
            basket_regime=BasketRegimeState()
        )

    # -------------------------------------------------------------
    # ITEM 1: Fail-Closed no Gatekeeper
    # -------------------------------------------------------------
    def test_gatekeeper_fail_closed_when_runtime_state_is_none(self):
        """Se runtime_state for None, o Gatekeeper deve bloquear 100% dos sinais (Fail-Closed)."""
        gk = HarnessGatekeeper(dealing_range=self.dr, runtime_state=None)
        allowed, reason = gk.evaluate_entry_permission(
            current_time=datetime(2026, 11, 21, 10, 15),
            current_price=169500.0,
            proposed_direction=TradingDirection.LONG
        )
        self.assertFalse(allowed)
        self.assertIn("FAIL-CLOSED", reason)
        self.assertIn("ausente", reason)

    def test_gatekeeper_fail_closed_when_runtime_state_is_expired(self):
        """Se o timestamp do runtime_state tiver ultrapassado o TTL, bloqueia como NO_TRADE."""
        expired_time = datetime.now() - timedelta(seconds=300)
        expired_state = RuntimeStateContract(
            timestamp=expired_time.isoformat(),
            ttl_seconds=120.0,
            trading_enabled=True,
            confidence_score=0.85
        )
        gk = HarnessGatekeeper(dealing_range=self.dr, runtime_state=expired_state)
        allowed, reason = gk.evaluate_entry_permission(
            current_time=datetime.now(),
            current_price=169500.0,
            proposed_direction=TradingDirection.LONG
        )
        self.assertFalse(allowed)
        self.assertIn("FAIL-CLOSED", reason)
        self.assertIn("expirado", reason)

    def test_gatekeeper_blocks_when_circuit_breaker_active(self):
        """Circuit Breaker ativo deve vetar imediatamente qualquer entrada."""
        self.valid_runtime.circuit_breaker.lockout_active = True
        gk = HarnessGatekeeper(dealing_range=self.dr, runtime_state=self.valid_runtime)
        allowed, reason = gk.evaluate_entry_permission(
            current_time=datetime.now().replace(hour=10, minute=15),
            current_price=169500.0,
            proposed_direction=TradingDirection.LONG
        )
        self.assertFalse(allowed)
        self.assertIn("CIRCUIT BREAKER", reason)

    def test_gatekeeper_blocks_when_event_lockout(self):
        """Bloqueio de eventos macro (Payroll/FOMC) deve vetar operações."""
        self.valid_runtime.macro_regime.event_lockout = True
        self.valid_runtime.macro_regime.lockout_reason = "Payroll em divulgação"
        gk = HarnessGatekeeper(dealing_range=self.dr, runtime_state=self.valid_runtime)
        allowed, reason = gk.evaluate_entry_permission(
            current_time=datetime.now().replace(hour=10, minute=15),
            current_price=169500.0,
            proposed_direction=TradingDirection.LONG
        )
        self.assertFalse(allowed)
        self.assertIn("EVENT LOCKOUT", reason)

    def test_gatekeeper_enforces_direction_lockout(self):
        """Se o Orquestrador permitir apenas LONG, entradas SHORT devem ser vetadas."""
        self.valid_runtime.allowed_direction = TradingDirection.LONG_ONLY
        gk = HarnessGatekeeper(dealing_range=self.dr, runtime_state=self.valid_runtime)
        allowed, reason = gk.evaluate_entry_permission(
            current_time=datetime.now().replace(hour=10, minute=15),
            current_price=170500.0,
            proposed_direction=TradingDirection.SHORT
        )
        self.assertFalse(allowed)
        self.assertIn("BLOQUEIO DE DIREÇÃO", reason)

    # -------------------------------------------------------------
    # ITEM 2: TTL e Pareceres dos Agentes
    # -------------------------------------------------------------
    def test_agent_opinion_expiration(self):
        """Opinião antiga deve ser detectada como expirada pelo método is_expired."""
        now = datetime.now()
        op_old = AgentOpinion(
            agent_name="Test",
            bias="BULLISH",
            confidence=0.8,
            timestamp=now - timedelta(seconds=200),
            ttl_seconds=120.0
        )
        self.assertTrue(op_old.is_expired(now))

        op_fresh = AgentOpinion(
            agent_name="Test",
            bias="BULLISH",
            confidence=0.8,
            timestamp=now - timedelta(seconds=30),
            ttl_seconds=120.0
        )
        self.assertFalse(op_fresh.is_expired(now))

    # -------------------------------------------------------------
    # ITEM 4: Invariantes de Domínio em TradeSignal
    # -------------------------------------------------------------
    def test_trade_signal_valid_invariants(self):
        """Sinal válido de COMPRA e VENDA deve instanciar com sucesso."""
        sig_buy = TradeSignal(
            id="SIG_001",
            timestamp=datetime.now().isoformat(),
            ativo="WINZ26",
            direction=TradingDirection.LONG,
            entry_price=170000.0,
            stop_loss=169750.0,
            take_profit=170400.0,
            risk_points=250.0,
            gain_points=400.0,
            rr_ratio=1.60,
            zone_id="Z1",
            setup_name="TEST",
            regime=PriceRegime.DISCOUNT,
            confidence_score=0.85,
            execution_mode=ExecutionMode.COPILOT,
            institutional_volume_detected=150,
            explanation="Validação Long"
        )
        self.assertEqual(sig_buy.direction, TradingDirection.LONG)

        sig_sell = TradeSignal(
            id="SIG_002",
            timestamp=datetime.now().isoformat(),
            ativo="WINZ26",
            direction=TradingDirection.SHORT,
            entry_price=170000.0,
            stop_loss=170250.0,
            take_profit=169600.0,
            risk_points=250.0,
            gain_points=400.0,
            rr_ratio=1.60,
            zone_id="Z2",
            setup_name="TEST",
            regime=PriceRegime.PREMIUM,
            confidence_score=0.85,
            execution_mode=ExecutionMode.COPILOT,
            institutional_volume_detected=150,
            explanation="Validação Short"
        )
        self.assertEqual(sig_sell.direction, TradingDirection.SHORT)

    def test_trade_signal_rejects_inverted_stops_and_targets(self):
        """Deve rejeitar sinais com stop e alvo invertidos."""
        # LONG com stop acima da entrada
        with self.assertRaises(ValueError):
            TradeSignal(
                id="SIG_ERR1",
                timestamp=datetime.now().isoformat(),
                ativo="WINZ26",
                direction=TradingDirection.LONG,
                entry_price=170000.0,
                stop_loss=170300.0,  # INVÁLIDO
                take_profit=170400.0,
                risk_points=250.0,
                gain_points=400.0,
                rr_ratio=1.60,
                zone_id="Z1",
                setup_name="TEST",
                regime=PriceRegime.DISCOUNT,
                confidence_score=0.85,
                execution_mode=ExecutionMode.COPILOT,
                institutional_volume_detected=150,
                explanation="Erro"
            )

        # SHORT com take profit acima da entrada
        with self.assertRaises(ValueError):
            TradeSignal(
                id="SIG_ERR2",
                timestamp=datetime.now().isoformat(),
                ativo="WINZ26",
                direction=TradingDirection.SHORT,
                entry_price=170000.0,
                stop_loss=170250.0,
                take_profit=170500.0,  # INVÁLIDO
                risk_points=250.0,
                gain_points=400.0,
                rr_ratio=1.60,
                zone_id="Z2",
                setup_name="TEST",
                regime=PriceRegime.PREMIUM,
                confidence_score=0.85,
                execution_mode=ExecutionMode.COPILOT,
                institutional_volume_detected=150,
                explanation="Erro"
            )

    def test_trade_signal_rejects_invalid_direction_types(self):
        """Deve rejeitar direções agregadas (BOTH, NONE) para um sinal individual."""
        with self.assertRaises(ValueError):
            TradeSignal(
                id="SIG_ERR3",
                timestamp=datetime.now().isoformat(),
                ativo="WINZ26",
                direction=TradingDirection.BOTH,  # INVÁLIDO
                entry_price=170000.0,
                stop_loss=169750.0,
                take_profit=170400.0,
                risk_points=250.0,
                gain_points=400.0,
                rr_ratio=1.60,
                zone_id="Z1",
                setup_name="TEST",
                regime=PriceRegime.DISCOUNT,
                confidence_score=0.85,
                execution_mode=ExecutionMode.COPILOT,
                institutional_volume_detected=150,
                explanation="Erro"
            )

    def test_trade_signal_rejects_out_of_bounds_confidence(self):
        """Deve rejeitar confidence_score fora do intervalo [0.0, 1.0]."""
        with self.assertRaises(ValueError):
            TradeSignal(
                id="SIG_ERR4",
                timestamp=datetime.now().isoformat(),
                ativo="WINZ26",
                direction=TradingDirection.LONG,
                entry_price=170000.0,
                stop_loss=169750.0,
                take_profit=170400.0,
                risk_points=250.0,
                gain_points=400.0,
                rr_ratio=1.60,
                zone_id="Z1",
                setup_name="TEST",
                regime=PriceRegime.DISCOUNT,
                confidence_score=1.50,  # INVÁLIDO
                execution_mode=ExecutionMode.COPILOT,
                institutional_volume_detected=150,
                explanation="Erro"
            )

    # -------------------------------------------------------------
    # ITEM 6: Persistência da Máquina de Estados (Restart)
    # -------------------------------------------------------------
    def test_state_machine_session_persistence_across_restart(self):
        """Zonas marcadas como EXHAUSTED devem sobreviver a reinício do processo."""
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as tf:
            session_file = tf.name

        try:
            zone1 = FVGZone(
                id="FVG_1",
                tipo_original=ZoneType.BEARISH,
                top=170500.0,
                ce_50=170400.0,
                bottom=170300.0,
                setup_primario=PrimarySetup.CONTINUATION_SELL,
                status=ZoneStatus.UNMITIGATED
            )
            zone2 = FVGZone(
                id="FVG_2",
                tipo_original=ZoneType.BULLISH,
                top=169500.0,
                ce_50=169400.0,
                bottom=169300.0,
                setup_primario=PrimarySetup.CONTINUATION_BUY,
                status=ZoneStatus.UNMITIGATED
            )

            # Instância 1: Consome a zona 1 e salva
            sm1 = FVGStateMachine([zone1, zone2], session_storage_path=session_file)
            sm1.zones["FVG_1"].status = ZoneStatus.EXHAUSTED
            sm1.save_session()

            # Instância 2 (Simulando Restart do Processo)
            # Cria do zero com status UNMITIGATED, mas carrega o arquivo de sessão
            zone1_new = FVGZone(
                id="FVG_1",
                tipo_original=ZoneType.BEARISH,
                top=170500.0,
                ce_50=170400.0,
                bottom=170300.0,
                setup_primario=PrimarySetup.CONTINUATION_SELL,
                status=ZoneStatus.UNMITIGATED
            )
            zone2_new = FVGZone(
                id="FVG_2",
                tipo_original=ZoneType.BULLISH,
                top=169500.0,
                ce_50=169400.0,
                bottom=169300.0,
                setup_primario=PrimarySetup.CONTINUATION_BUY,
                status=ZoneStatus.UNMITIGATED
            )
            sm2 = FVGStateMachine([zone1_new, zone2_new], session_storage_path=session_file)

            # Verifica se FVG_1 foi restaurada como EXHAUSTED
            self.assertEqual(sm2.zones["FVG_1"].status, ZoneStatus.EXHAUSTED)
            self.assertEqual(sm2.zones["FVG_2"].status, ZoneStatus.UNMITIGATED)
            # FVG_1 não deve constar nas zonas ativas
            active_ids = [z.id for z in sm2.get_active_zones()]
            self.assertNotIn("FVG_1", active_ids)
            self.assertIn("FVG_2", active_ids)

        finally:
            if os.path.exists(session_file):
                os.remove(session_file)

    # -------------------------------------------------------------
    # ITEM 7: Prevenção de Consumo Prematuro de Zonas
    # -------------------------------------------------------------
    def test_safe_zone_emission_reverts_on_failure(self):
        """Se a persistência de sinais falhar, a zona não deve virar EXHAUSTED."""
        zone = FVGZone(
            id="FVG_SAFE",
            tipo_original=ZoneType.BEARISH,
            top=170500.0,
            ce_50=170400.0,
            bottom=170300.0,
            setup_primario=PrimarySetup.CONTINUATION_SELL,
            status=ZoneStatus.TESTING_CONTINUATION
        )
        contract = Niveis60mContract(
            data_referencia="2026-11-21",
            dealing_range=self.dr,
            zonas_fvg=[zone]
        )
        # Caminho inválido proposital para forçar falha de persistência
        invalid_path = "Z:\\caminho_inexistente_com_erro\\sinais.json"
        harness = ExecutionHarness(
            niveis_contract=contract,
            runtime_state=self.valid_runtime,
            signals_output_path=invalid_path
        )

        with self.assertRaises(Exception):
            harness._emit_signal(
                zone=zone,
                direction=TradingDirection.SHORT,
                entry_price=170400.0,
                timestamp=datetime.now(),
                institutional_volume=200,
                is_continuation=True
            )

        # A zona DEVE ter revertido seu status para TESTING_CONTINUATION (não queimou!)
        self.assertEqual(zone.status, ZoneStatus.TESTING_CONTINUATION)

    # -------------------------------------------------------------
    # ITEM 5: Versionamento e Gravação Atômica do Orquestrador
    # -------------------------------------------------------------
    def test_orchestrator_versioning(self):
        """Orquestrador deve incrementar state_version a cada ciclo e gravar atomicamente."""
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as tf:
            state_file = tf.name

        try:
            orc = Orchestrator(output_state_path=state_file)
            s1 = orc.run_cycle(datetime(2026, 11, 21, 10, 0))
            self.assertEqual(s1.state_version, 1)

            s2 = orc.run_cycle(datetime(2026, 11, 21, 10, 1))
            self.assertEqual(s2.state_version, 2)

            # Verifica leitura em disco
            import json
            with open(state_file, "r", encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual(saved["state_version"], 2)
            self.assertEqual(saved["data_quality"], "INTEGRITY_OK")

        finally:
            if os.path.exists(state_file):
                os.remove(state_file)


if __name__ == "__main__":
    unittest.main()
