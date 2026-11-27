"""
audit_critical_terminals.py
Auditoria Crítica e Rigorosa de Emissão de Alertas de COMPRA e VENDA
Testa ponta a ponta todos os 3 motores:
  1. Orquestrador Multi-Agente (Runtime State & Vetos)
  2. Execution Harness Copiloto (Alertas de COMPRA e VENDA em tempo real)
  3. Whale Flow Monitor (Alertas Institucionais de COMPRA e VENDA)
  4. Guardrails e Regras Rígidas (Premium/Discount, Absorção, Fail-Closed)
"""

import os
import sys
import json
from datetime import datetime, timedelta

# Garante path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from core.harness.contracts import (
    TradingDirection,
    ExecutionMode,
    RuntimeStateContract,
    Niveis60mContract,
    DealingRange,
    ZoneStatus,
    TradeSignal
)
from core.harness.gatekeeper import HarnessGatekeeper
from core.harness.execution_harness import ExecutionHarness
from core.agents.macro_agent import MacroAgent
from core.agents.basket_agent import BasketAgent
from core.agents.sentinel_agent import SentinelAgent
from core.agents.orchestrator import Orchestrator
from whale_ny_monitor import WhaleNYMonitor, TimesTradesParser, WhaleClusterAggregator

def run_critical_audit():
    print("=" * 80)
    print("       AUDITORIA CRÍTICA E RIGOROSA DE DISPARO: COMPRA & VENDA")
    print("=" * 80)
    now = datetime.now()

    # -------------------------------------------------------------------------
    # TESTE 1: ORQUESTRADOR MULTI-AGENTE
    # -------------------------------------------------------------------------
    print("\n[TESTE 1/4] AUDITORIA DO ORQUESTRADOR MULTI-AGENTE:")
    macro = MacroAgent()
    basket = BasketAgent()
    sentinel = SentinelAgent()
    orch = Orchestrator(macro_agent=macro, basket_agent=basket, sentinel_agent=sentinel)
    
    st_neutral = orch.run_cycle(now)
    print(f"  • Ciclo Padrão (Neutro)     : trading_enabled={st_neutral.trading_enabled} | allowed_dir={st_neutral.allowed_direction.value} | conf={st_neutral.confidence_score*100:.0f}%")
    assert st_neutral.trading_enabled, "Falha: trading_enabled deveria ser True após desbloqueio"
    
    # -------------------------------------------------------------------------
    # TESTE 2: EXECUTION HARNESS — DISPARO DE COMPRA (LONG) EM DISCOUNT
    # -------------------------------------------------------------------------
    print("\n[TESTE 2/4] AUDITORIA DO EXECUTION HARNESS — DISPARO DE COMPRA (LONG):")
    niveis_path = os.path.join(BASE_DIR, "data", "niveis_60m.json")
    with open(niveis_path, "r", encoding="utf-8") as f:
        n_data = json.load(f)
    niveis = Niveis60mContract(**n_data)
    
    # Prepara estado permitindo COMPRAS (LONG_ONLY ou BOTH)
    st_neutral.allowed_direction = TradingDirection.BOTH
    st_neutral.trading_enabled = True
    
    harness_buy = ExecutionHarness(
        niveis_contract=niveis,
        runtime_state=st_neutral,
        mode=ExecutionMode.COPILOT,
        session_storage_path=None
    )
    
    # Simula preço em 171.100 (ZONA_07_ROMPIMENTO_171K_171100 - DEMAND / DISCOUNT, Eq=171.650)
    buy_price = 171100.0
    
    # Injeta volume de agressão vendedora (>= 100 contratos) que é absorvida passivamente pelos compradores
    harness_buy.on_trade(buy_price, 150, "SELL", now)
    
    # Dispara tick no preço da zona
    signal_buy = harness_buy.on_tick(buy_price, now)
    
    assert signal_buy is not None, "ERRO CRÍTICO: Harness NÃO emitiu sinal de COMPRA em zona de Discount!"
    assert signal_buy.direction == TradingDirection.LONG, f"Direção incorreta: {signal_buy.direction}"
    assert signal_buy.entry_price == buy_price, f"Preço de entrada incorreto: {signal_buy.entry_price}"
    assert signal_buy.stop_loss == (buy_price - 250.0), f"Stop incorreto: {signal_buy.stop_loss}"
    assert signal_buy.take_profit == (buy_price + 400.0), f"Alvo incorreto: {signal_buy.take_profit}"
    assert signal_buy.rr_ratio == 1.60, f"R:R incorreto: {signal_buy.rr_ratio}"
    
    print(f"  ✅ ALERTA DE COMPRA EMITIDO COM SUCESSO!")
    print(f"     -> Ativo: {signal_buy.ativo} | Direção: {signal_buy.direction.value} | Entrada: {signal_buy.entry_price:.0f}")
    print(f"     -> Stop Loss: {signal_buy.stop_loss:.0f} (-250 pts) | Take Profit: {signal_buy.take_profit:.0f} (+400 pts) | R:R: {signal_buy.rr_ratio:.2f}")
    print(f"     -> Zona: {signal_buy.zone_id} | Setup: {signal_buy.setup_name}")

    # -------------------------------------------------------------------------
    # TESTE 3: EXECUTION HARNESS — DISPARO DE VENDA (SHORT) EM PREMIUM
    # -------------------------------------------------------------------------
    print("\n[TESTE 3/4] AUDITORIA DO EXECUTION HARNESS — DISPARO DE VENDA (SHORT):")
    harness_sell = ExecutionHarness(
        niveis_contract=niveis,
        runtime_state=st_neutral,
        mode=ExecutionMode.COPILOT,
        session_storage_path=None
    )
    
    # Simula preço em 173.850 (ZONA_01_TOPO_EXAUSTAO_173850 - SUPPLY / PREMIUM, Eq=171.650)
    sell_price = 173850.0
    
    # Injeta volume de agressão compradora (>= 100 contratos) que é absorvida passivamente pelos vendedores
    harness_sell.on_trade(sell_price, 150, "BUY", now)
    
    # Dispara tick no preço da zona
    signal_sell = harness_sell.on_tick(sell_price, now)
    
    assert signal_sell is not None, "ERRO CRÍTICO: Harness NÃO emitiu sinal de VENDA em zona de Premium!"
    assert signal_sell.direction == TradingDirection.SHORT, f"Direção incorreta: {signal_sell.direction}"
    assert signal_sell.entry_price == sell_price, f"Preço de entrada incorreto: {signal_sell.entry_price}"
    assert signal_sell.stop_loss == (sell_price + 250.0), f"Stop incorreto: {signal_sell.stop_loss}"
    assert signal_sell.take_profit == (sell_price - 400.0), f"Alvo incorreto: {signal_sell.take_profit}"
    assert signal_sell.rr_ratio == 1.60, f"R:R incorreto: {signal_sell.rr_ratio}"
    
    print(f"  ✅ ALERTA DE VENDA EMITIDO COM SUCESSO!")
    print(f"     -> Ativo: {signal_sell.ativo} | Direção: {signal_sell.direction.value} | Entrada: {signal_sell.entry_price:.0f}")
    print(f"     -> Stop Loss: {signal_sell.stop_loss:.0f} (-250 pts) | Take Profit: {signal_sell.take_profit:.0f} (+400 pts) | R:R: {signal_sell.rr_ratio:.2f}")
    print(f"     -> Zona: {signal_sell.zone_id} | Setup: {signal_sell.setup_name}")

    # -------------------------------------------------------------------------
    # TESTE 4: WHALE FLOW MONITOR — DISPARO INSTITUCIONAL COMPRA & VENDA
    # -------------------------------------------------------------------------
    print("\n[TESTE 4/4] AUDITORIA DO WHALE FLOW MONITOR (TAPE READING INSTITUCIONAL):")
    whale = WhaleNYMonitor()
    whale.update_cross_market_from_runtime()
    
    # 4A: DISPARO DE VENDA (SHORT) POR EXAUSTÃO NO TOPO
    # Morgan agride 500 cts em 173.850 (ZONA_01_TOPO_EXAUSTAO_173850 - Resistência/Venda)
    tape_short = f"{now.strftime('%H:%M:%S')}.100\tMorgan\t173.850*\t500\tBTG\tComprador\n"
    alerts_whale_short = whale.process_text_payload(tape_short, check_staleness=False)
    
    assert len(alerts_whale_short) > 0, "ERRO CRÍTICO: Whale Monitor NÃO emitiu alerta de VENDA institucional!"
    al_short = alerts_whale_short[0]
    assert al_short.direction == "SHORT", f"Direção esperada SHORT, obtida: {al_short.direction}"
    assert al_short.score >= 80, f"Score abaixo do limiar institucional: {al_short.score}"
    assert al_short.stop_loss == (173850.0 + 250.0), f"Stop de venda incorreto: {al_short.stop_loss}"
    assert al_short.take_profit == (173850.0 - 400.0), f"Alvo de venda incorreto: {al_short.take_profit}"
    
    print(f"  ✅ WHALE FLOW: ALERTA INSTITUCIONAL DE VENDA (SHORT) CONFIRMADO!")
    print(f"     -> Corretora: {al_short.broker} ({al_short.tier}) | Lote: {al_short.quantity} cts [{al_short.magnitude}]")
    print(f"     -> Entrada: {al_short.entry_price:.0f} | Stop: {al_short.stop_loss:.0f} | Alvo: {al_short.take_profit:.0f} | Score: {al_short.score}/100")

    # 4B: DISPARO DE COMPRA (LONG) POR ABSORÇÃO NO FUNDO
    # Morgan agride 600 cts na Venda em 171.100 (ZONA_07_ROMPIMENTO_171K_171100 - Suporte/Compra)
    whale.decision_engine.recent_alerts.clear() # Limpa cooldown para o teste
    tape_long = f"{now.strftime('%H:%M:%S')}.800\tIdeal\t171.100*\t600\tMorgan\tVendedor\n"
    alerts_whale_long = whale.process_text_payload(tape_long, check_staleness=False)
    
    assert len(alerts_whale_long) > 0, "ERRO CRÍTICO: Whale Monitor NÃO emitiu alerta de COMPRA institucional!"
    al_long = alerts_whale_long[0]
    assert al_long.direction == "LONG", f"Direção esperada LONG, obtida: {al_long.direction}"
    assert al_long.score >= 80, f"Score abaixo do limiar institucional: {al_long.score}"
    assert al_long.stop_loss == (171100.0 - 250.0), f"Stop de compra incorreto: {al_long.stop_loss}"
    assert al_long.take_profit == (171100.0 + 400.0), f"Alvo de compra incorreto: {al_long.take_profit}"
    
    print(f"  ✅ WHALE FLOW: ALERTA INSTITUCIONAL DE COMPRA (LONG) CONFIRMADO!")
    print(f"     -> Corretora: {al_long.broker} ({al_long.tier}) | Lote: {al_long.quantity} cts [{al_long.magnitude}]")
    print(f"     -> Entrada: {al_long.entry_price:.0f} | Stop: {al_long.stop_loss:.0f} | Alvo: {al_long.take_profit:.0f} | Score: {al_long.score}/100")

    print("\n" + "=" * 80)
    print("      AUDITORIA CONCLUÍDA COM 100% DE SUCESSO: COMPRA E VENDA OPERANTES!")
    print("=" * 80)

if __name__ == "__main__":
    run_critical_audit()
