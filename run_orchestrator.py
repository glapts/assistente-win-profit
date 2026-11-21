"""
run_orchestrator.py
Serviço Daemon do Comitê Multi-Agente & Orquestrador de Mesa.
Roda em segundo plano, consolida os pareceres dos 3 agentes especialistas
(Macro, Cesta/DI e Sentinela) e atualiza 'data/runtime_state.json' a cada ciclo.
"""

import os
import sys
import time
import argparse
from datetime import datetime

# Garante path do projeto
base_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base_dir)

from core.agents.macro_agent import MacroAgent
from core.agents.basket_agent import BasketAgent
from core.agents.sentinel_agent import SentinelAgent
from core.agents.orchestrator import Orchestrator
from core.harness.contracts import ExecutionMode


def main():
    parser = argparse.ArgumentParser(description="Daemon do Comitê de Agentes e Orquestrador")
    parser.add_argument("--interval", type=int, default=10, help="Intervalo em segundos entre ciclos (padrão: 10s)")
    parser.add_argument("--mode", type=str, choices=["COPILOT", "FULL_AUTO"], default="COPILOT", help="Modo operacional")
    args = parser.parse_args()

    print("=" * 80)
    print("🧠 INICIANDO COMITÊ MULTI-AGENTE & ORQUESTRADOR DE MESA (ASSÍNCRONO)")
    print("=" * 80)
    print(" Agentes Ativos:")
    print("   1. Macro & Global (S&P 500, Treasuries, DXY, Calendário EUA)")
    print("   2. Cesta IBOV & Arbitragem (PETR4, VALE3, Bancos, Curva DI)")
    print("   3. Sentinela Político (Notícias de Brasília, Risco Fiscal, Black Swan)")
    print(f" Destino de Estado : data/runtime_state.json")
    print(f" Intervalo do Loop : {args.interval}s")
    print(f" Modo Configurado  : {args.mode}")
    print("=" * 80)

    macro = MacroAgent()
    basket = BasketAgent()
    sentinel = SentinelAgent()

    orchestrator = Orchestrator(
        macro_agent=macro,
        basket_agent=basket,
        sentinel_agent=sentinel,
        execution_mode=ExecutionMode(args.mode.upper())
    )

    cycle_count = 0
    try:
        while True:
            cycle_count += 1
            now = datetime.now()
            state = orchestrator.run_cycle(current_time=now)
            
            status_symbol = "🟢 OPERAÇÃO LIBERADA" if state.trading_enabled else "🔴 OPERAÇÃO BLOQUEADA"
            print(f"[{now.strftime('%H:%M:%S')}] Ciclo #{cycle_count:04d} | {status_symbol} | Dir: {state.allowed_direction.value} | Confiança: {state.confidence_score*100:.0f}%")
            
            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\n[ORQUESTRADOR] Encerrando serviço a pedido do operador.")


if __name__ == "__main__":
    main()
