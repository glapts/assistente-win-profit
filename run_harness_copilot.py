"""
run_harness_copilot.py
Execução Oficial do Execution Harness no Modo Copiloto (Assistido).
Conecta-se ao Profit Pro via DDE/RTD ou executa em modo monitoramento ativo.
Carrega e monitora os contratos:
  - data/niveis_60m.json (Zonas FVG e Dealing Range 50%)
  - data/runtime_state.json (Estado do Orquestrador e Circuit Breakers, com hot-reload Fail-Closed)
"""

import os
import sys
import time
import json
import argparse
from datetime import datetime

# Garante path do projeto
base_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base_dir)

from core.harness.contracts import (
    ExecutionMode,
    Niveis60mContract,
    RuntimeStateContract
)
from core.harness.execution_harness import ExecutionHarness
from feeds.dde_feed import ProfitDDEFeed
from core.contract import get_current_win_contract, resolve_symbol


def load_contracts():
    niveis_path = os.path.join(base_dir, "data", "niveis_60m.json")
    state_path = os.path.join(base_dir, "data", "runtime_state.json")

    if not os.path.exists(niveis_path):
        print(f"[ERRO] Arquivo de níveis não encontrado em: {niveis_path}")
        sys.exit(1)

    if not os.path.exists(state_path):
        print(f"[ERRO] Arquivo de estado não encontrado em: {state_path}")
        sys.exit(1)

    with open(niveis_path, "r", encoding="utf-8") as f:
        niveis_data = json.load(f)
    niveis = Niveis60mContract(**niveis_data)

    with open(state_path, "r", encoding="utf-8") as f:
        state_data = json.load(f)
    state = RuntimeStateContract(**state_data)

    return niveis, state


def main():
    parser = argparse.ArgumentParser(description="Execution Harness - Modo Copiloto Assistido (WIN B3)")
    parser.add_argument("--symbol", type=str, default=None, help="Ticker do contrato (ex: WIN, WINZ26)")
    parser.add_argument("--mode", type=str, choices=["COPILOT", "FULL_AUTO"], default="COPILOT", help="Modo operacional")
    args = parser.parse_args()

    niveis, state = load_contracts()
    exec_mode = ExecutionMode(args.mode.upper())
    state.execution_mode = exec_mode

    symbol = resolve_symbol(args.symbol or niveis.ativo)
    state_path = os.path.join(base_dir, "data", "runtime_state.json")

    print("=" * 80)
    print(f"🚀 INICIANDO EXECUTION HARNESS — {exec_mode.value} (MINI-ÍNDICE B3)")
    print("=" * 80)
    print(f" Ativo Monitorado   : {symbol}")
    print(f" Dealing Range 60m  : Topo {niveis.dealing_range.topo_estrutural:.0f} | Fundo {niveis.dealing_range.fundo_estrutural:.0f}")
    print(f" 50% Equilibrium    : {niveis.dealing_range.equilibrium_50:.0f} (Regra Premium & Discount Ativa)")
    print(f" Zonas Mapeadas     : {len(niveis.zonas_fvg)} zonas de FVG/iFVG")
    print(f" Circuit Breaker    : Max {state.circuit_breaker.max_daily_stops} stops diários")
    print(f" Trava de Horário   : 09:00 - 10:00 (OBSERVATION_ONLY) | 10:28 - 10:35 (NY Open)")
    print(f" Modo Operacional   : {exec_mode.value}")
    if exec_mode == ExecutionMode.COPILOT:
        print("  -> Alertas sonoros e visuais habilitados. Ordens confirmadas pelo trader.")
    else:
        print("  -> MODO CONSULTIVO / STUB SEGURO (Sem envio de ordens reais).")
    print("=" * 80)

    harness = ExecutionHarness(
        niveis_contract=niveis,
        runtime_state=state,
        mode=exec_mode
    )

    feed = ProfitDDEFeed()

    # Callbacks do feed
    def on_trade_event(trade):
        aggr = trade.aggressor.value if hasattr(trade.aggressor, 'value') else str(trade.aggressor)
        harness.on_trade(trade.price, trade.quantity, aggr, trade.timestamp)
        harness.on_tick(trade.price, trade.timestamp)

    def on_candle_event(candle):
        ts = getattr(candle, "close_time", getattr(candle, "timestamp", datetime.now()))
        harness.on_candle_closed(candle.timeframe, candle.open, candle.high, candle.low, candle.close, ts)

    feed.set_callbacks(
        on_trade=on_trade_event,
        on_candle=on_candle_event
    )

    print(f"\n[FEED] Conectando ao Nelogica Profit Pro via DDE para {symbol}...")
    try:
        feed.connect()
        feed.subscribe_symbol(symbol)
        print("[FEED] Conexão iniciada! Monitorando fluxo institucional em tempo real...")
        print("[HARNESS] Aguardando preço atingir zonas de 60m com confirmação de fluxo...\n")
        
        last_state_check = 0.0
        last_version_seen = state.state_version
        niveis_path = os.path.join(base_dir, "data", "niveis_60m.json")
        last_niveis_mtime = os.path.getmtime(niveis_path) if os.path.exists(niveis_path) else 0.0

        while True:
            t_now = time.time()
            if t_now - last_state_check >= 1.0:
                last_state_check = t_now
                # 1. Hot-reload de niveis_60m.json em tempo real (sem reiniciar o processo)
                try:
                    if os.path.exists(niveis_path):
                        mtime_now = os.path.getmtime(niveis_path)
                        if mtime_now > last_niveis_mtime:
                            last_niveis_mtime = mtime_now
                            with open(niveis_path, "r", encoding="utf-8") as f:
                                fresh_niveis_data = json.load(f)
                            fresh_niveis = Niveis60mContract(**fresh_niveis_data)
                            harness.niveis = fresh_niveis
                            harness.state_machine.update_zones(fresh_niveis.zonas_fvg)
                            harness.gatekeeper.update_dealing_range(fresh_niveis.dealing_range)
                            print(f"[HARNESS SYNC] 🔄 Zonas SMC atualizadas em tempo real! Total: {len(fresh_niveis.zonas_fvg)} zonas ativas.")
                except Exception as ex_niveis:
                    pass

                # 2. Hot-reload de runtime_state com Fail-Closed imediato
                try:
                    if os.path.exists(state_path):
                        with open(state_path, "r", encoding="utf-8") as f:
                            fresh_data = json.load(f)
                        fresh_state = RuntimeStateContract(**fresh_data)
                        fresh_state.execution_mode = exec_mode
                        
                        if fresh_state.state_version != last_version_seen:
                            last_version_seen = fresh_state.state_version
                            print(f"[HARNESS SYNC] Novo runtime_state v{fresh_state.state_version} aplicado. Trading={fresh_state.trading_enabled}, CB={fresh_state.circuit_breaker.lockout_active}")

                        harness.gatekeeper.update_runtime_state(fresh_state)
                    else:
                        harness.gatekeeper.update_runtime_state(None)
                except Exception as ex:
                    # Em caso de falha de leitura ou JSON temporariamente inconsistente, aplica Fail-Closed
                    harness.gatekeeper.update_runtime_state(None)

            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\n[HARNESS] Encerrando monitoramento a pedido do operador.")
        feed.disconnect()
    except Exception as e:
        print(f"\n[HARNESS AVISO] Conexão DDE encerrada: {e}")
        feed.disconnect()


if __name__ == "__main__":
    main()
