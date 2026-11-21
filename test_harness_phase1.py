"""
test_harness_phase1.py
Validação e Testes Determinísticos da Fase 1: Estrutura do Harness e Contratos.
Testa:
  1. Carregamento dos Contratos Pydantic (niveis_60m.json e runtime_state.json)
  2. Validação da Regra de Ouro: Premium & Discount (Dealing Range 50% Equilibrium)
  3. Travas Físicas (09h-10h e Abertura de NY)
  4. Circuit Breaker (Limite diário de 2 stops)
  5. Filtro Anti-HFT e Absorção Institucional (>= 100 contratos)
  6. Máquina de Estados FVG e Inversão em iFVG
  7. Modo Copiloto: Geração de Alerta Visual e Gravação de Sinais
"""

import os
import sys
import json
from datetime import datetime

# Garante path do projeto
base_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base_dir)

from core.harness.contracts import (
    ExecutionMode,
    Niveis60mContract,
    RuntimeStateContract,
    TradingDirection,
    PriceRegime,
    ZoneStatus,
    ZoneType
)
from core.harness.gatekeeper import HarnessGatekeeper
from core.harness.microstructure_filter import MicrostructureFilter
from core.harness.state_machine import FVGStateMachine
from core.harness.execution_harness import ExecutionHarness


def test_contracts_loading():
    print("\n--- [TESTE 1] Carregamento e Validação dos Contratos Pydantic ---")
    
    # 1. niveis_60m.json
    with open("data/niveis_60m.json", "r", encoding="utf-8") as f:
        data_niveis = json.load(f)
    niveis = Niveis60mContract(**data_niveis)
    assert niveis.ativo == "WINZ26"
    assert len(niveis.zonas_fvg) == 11
    assert niveis.dealing_range.equilibrium_50 == 171205.0
    print(f" [PASS] niveis_60m.json validado com sucesso ({len(niveis.zonas_fvg)} zonas).")

    # 2. runtime_state.json
    with open("data/runtime_state.json", "r", encoding="utf-8") as f:
        data_state = json.load(f)
    state = RuntimeStateContract(**data_state)
    assert state.execution_mode == ExecutionMode.COPILOT
    assert 0.0 <= state.confidence_score <= 1.0
    print(f" [PASS] runtime_state.json validado com sucesso (Modo: {state.execution_mode.value}, Score: {state.confidence_score}).")
    return niveis, state


def test_gatekeeper_premium_discount(niveis, state):
    print("\n--- [TESTE 2] Regra de Ouro: Premium & Discount (50% Equilibrium) ---")
    state.allowed_direction = TradingDirection.BOTH
    state.trading_enabled = True
    state.macro_regime.event_lockout = False
    gatekeeper = HarnessGatekeeper(dealing_range=niveis.dealing_range, runtime_state=state)
    
    eq = niveis.dealing_range.equilibrium_50 # 171.205
    test_time = datetime(2026, 11, 21, 10, 15, 0) # 10:15 (horário permitido)

    # 1. Preço em Premium: 172.800 (> 171.205)
    regime_high = gatekeeper.get_price_regime(172800)
    assert regime_high == PriceRegime.PREMIUM
    
    # Venda em Premium deve ser AUTORIZADA
    ok_sell_prem, msg = gatekeeper.evaluate_entry_permission(test_time, 172800, TradingDirection.SHORT, is_continuation=True)
    assert ok_sell_prem is True, f"Esperado True, obteve: {msg}"
    print(f" [PASS] Venda em Zona PREMIUM (172.800): AUTORIZADA ({msg[:45]}...)")

    # Compra em Premium deve ser VETADA (comprar topo)
    ok_buy_prem, msg = gatekeeper.evaluate_entry_permission(test_time, 172800, TradingDirection.LONG, is_continuation=True)
    assert ok_buy_prem is False
    print(f" [PASS] Compra em Zona PREMIUM (172.800): BLOQUEADA com sucesso ({msg[:55]}...)")

    # 2. Preço em Discount: 170.100 (< 171.205)
    regime_low = gatekeeper.get_price_regime(170100)
    assert regime_low == PriceRegime.DISCOUNT

    # Compra em Discount deve ser AUTORIZADA
    ok_buy_disc, msg = gatekeeper.evaluate_entry_permission(test_time, 170100, TradingDirection.LONG, is_continuation=True)
    assert ok_buy_disc is True, f"Esperado True, obteve: {msg}"
    print(f" [PASS] Compra em Zona DISCOUNT (170.100): AUTORIZADA ({msg[:45]}...)")

    # Venda em Discount deve ser VETADA (vender fundo)
    ok_sell_disc, msg = gatekeeper.evaluate_entry_permission(test_time, 170100, TradingDirection.SHORT, is_continuation=True)
    assert ok_sell_disc is False
    print(f" [PASS] Venda em Zona DISCOUNT (170.100): BLOQUEADA com sucesso ({msg[:55]}...)")


def test_gatekeeper_time_locks_and_circuit_breaker(niveis, state):
    print("\n--- [TESTE 3] Travas de Horário Rígidas e Circuit Breaker ---")
    gatekeeper = HarnessGatekeeper(dealing_range=niveis.dealing_range, runtime_state=state)

    # 1. Trava das 09:00 às 10:00 (OBSERVATION_ONLY)
    t_09h30 = datetime(2026, 11, 21, 9, 30, 0)
    ok, msg = gatekeeper.evaluate_entry_permission(t_09h30, 170100, TradingDirection.LONG)
    assert ok is False
    assert "OBSERVATION_ONLY" in msg
    print(f" [PASS] Horário 09:30: BLOQUEADO por regra rígida ({msg})")

    # 2. Trava de Abertura de NY (10:30)
    t_10h30 = datetime(2026, 11, 21, 10, 30, 0)
    ok, msg = gatekeeper.evaluate_entry_permission(t_10h30, 170100, TradingDirection.LONG)
    assert ok is False
    assert "ABERTURA NY" in msg
    print(f" [PASS] Horário 10:30 (NY Open): BLOQUEADO por regra rígida ({msg})")

    # 3. Circuit Breaker (2 stops)
    state.circuit_breaker.daily_stops_count = 2
    t_14h00 = datetime(2026, 11, 21, 14, 0, 0)
    ok, msg = gatekeeper.evaluate_entry_permission(t_14h00, 170100, TradingDirection.LONG)
    assert ok is False
    assert "CIRCUIT BREAKER" in msg
    print(f" [PASS] Circuit Breaker com 2 stops: BLOQUEADO ({msg})")
    state.circuit_breaker.daily_stops_count = 0 # restaura


def test_microstructure_anti_hft():
    print("\n--- [TESTE 4] Filtro Anti-HFT e Absorção Institucional ---")
    micro = MicrostructureFilter(min_hft_lot=20, min_institutional_absorption=100)
    now = datetime(2026, 11, 21, 10, 15, 0)

    # 1. Ruído de HFT: Ordens de 5 contratos
    res1 = micro.on_trade(170100, 5, "SELL", now)
    assert res1["filtered"] is True
    assert "HFT_NOISE" in res1["reason"]
    print(" [PASS] Lotes pequenos (<20) descartados como ruído de HFT.")

    # 2. Ordem de lote institucional (40 contratos)
    res2 = micro.on_trade(170100, 40, "SELL", now)
    assert res2["filtered"] is False

    # Verifica absorção com apenas 40 contratos (insuficiente para meta de 100)
    abs_ok, vol, msg = micro.evaluate_absorption(170100, "BUY_DEFENSE")
    assert abs_ok is False
    assert vol == 40
    print(f" [PASS] Absorção parcial (40/100 contratos): Aguarda confirmação ({msg}).")

    # Injeta mais 70 contratos institucionais (total 110)
    micro.on_trade(170100, 70, "SELL", now)
    abs_ok, vol, msg = micro.evaluate_absorption(170100, "BUY_DEFENSE")
    assert abs_ok is True
    assert vol == 110
    print(f" [PASS] Absorção institucional confirmada ({vol} contratos >= 100): {msg}")


def test_fvg_state_machine_and_inversion(niveis):
    print("\n--- [TESTE 5] Máquina de Estados FVG e Inversão em iFVG ---")
    sm = FVGStateMachine(zones=niveis.zonas_fvg)
    now = datetime(2026, 11, 21, 10, 15, 0)

    # Localiza a zona FVG_60M_02_172800 (172.700 a 172.900)
    z2 = sm.zones["FVG_60M_02_172800"]
    assert z2.status == ZoneStatus.UNMITIGATED

    # 1. Preço entra na zona
    events = sm.evaluate_price_tick(172800, now)
    assert z2.status == ZoneStatus.TESTING_CONTINUATION
    assert any(e["type"] == "ZONE_ENTERED" for e in events)
    print(f" [PASS] Preço tocou 172.800: Zona transitou para TESTING_CONTINUATION.")

    # 2. Inversão em iFVG: Um candle de 15m fecha com corpo acima do topo (172.950 > 172.900)
    events_candle = sm.on_candle_closed(timeframe=15, open_p=172750, high_p=173000, low_p=172700, close_p=172950, timestamp=now)
    assert z2.status == ZoneStatus.INVERTED_PENDING_RETEST
    assert any(e["type"] == "ZONE_INVERTED_TO_BULLISH_IFVG" for e in events_candle)
    print(f" [PASS] Candle de 15m fechou acima: Zona invertida para iFVG de ALTA (INVERTED_PENDING_RETEST).")

    # 3. Reteste da zona invertida
    events_retest = sm.evaluate_price_tick(172850, now)
    assert z2.status == ZoneStatus.TRIGGER_IFVG
    print(f" [PASS] Preço retornou para retestar a zona: Status transitou para TRIGGER_IFVG.")


def test_execution_harness_copilot_signal(niveis, state):
    print("\n--- [TESTE 6] ExecutionHarness no Modo COPILOTO (End-to-End) ---")
    harness = ExecutionHarness(
        niveis_contract=niveis,
        runtime_state=state,
        mode=ExecutionMode.COPILOT,
        signals_output_path="data/sinais_copiloto.json"
    )

    t_signal = datetime(2026, 11, 21, 10, 20, 0) # 10:20 (Horário liberado)
    price_entry = 170100 # Zona FVG_60M_10_SWEEP_170100 (Discount)

    # 1. Alimenta o Tape Reading com 120 contratos institucionais na defesa
    harness.on_trade(price=170100, qty=60, aggressor="SELL", timestamp=t_signal)
    harness.on_trade(price=170100, qty=60, aggressor="SELL", timestamp=t_signal)

    # 2. Dispara o tick dentro da zona de sweep
    signal = harness.on_tick(price=price_entry, timestamp=t_signal)

    assert signal is not None, "O sinal deveria ter sido gerado com sucesso!"
    assert signal.direction == TradingDirection.LONG
    assert signal.entry_price == 170100
    assert signal.stop_loss == 169850 # Stop 250 pts
    assert signal.take_profit == 170500 # Alvo 400 pts
    assert signal.rr_ratio == 1.60
    assert signal.execution_mode == ExecutionMode.COPILOT
    assert os.path.exists("data/sinais_copiloto.json")
    print(f" [PASS] Sinal emitido e gravado em data/sinais_copiloto.json (ID: {signal.id}).")


if __name__ == "__main__":
    print("=" * 75)
    print("TESTE DETERMINÍSTICO DE HOMOLOGAÇÃO: FASE 1 — EXECUTION HARNESS")
    print("=" * 75)
    
    niveis, state = test_contracts_loading()
    test_gatekeeper_premium_discount(niveis, state)
    test_gatekeeper_time_locks_and_circuit_breaker(niveis, state)
    test_microstructure_anti_hft()
    test_fvg_state_machine_and_inversion(niveis)
    test_execution_harness_copilot_signal(niveis, state)
    
    print("\n" + "=" * 75)
    print("✅ TODOS OS 6 TESTES DA FASE 1 PASSARAM COM 100% DE SUCESSO!")
    print("=" * 75)
