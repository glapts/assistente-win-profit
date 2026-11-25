"""
record_stop.py
Utilitário rápido para registrar stops ou resetar o Circuit Breaker do sistema.
Uso:
  python record_stop.py              # Registra +1 stop no dia
  python record_stop.py --reset      # Zera os stops e reativa as operações
"""

import os
import sys
import json
import argparse
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CB_FILE = os.path.join(BASE_DIR, "data", "circuit_breaker.json")
RUNTIME_FILE = os.path.join(BASE_DIR, "data", "runtime_state.json")

def main():
    parser = argparse.ArgumentParser(description="Gerenciador do Circuit Breaker")
    parser.add_argument("--reset", action="store_true", help="Reseta os stops diários para 0")
    parser.add_argument("--stops", type=int, default=None, help="Define o número exato de stops")
    args = parser.parse_args()

    os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)

    cb_data = {"daily_stops_count": 0, "max_daily_stops": 2, "lockout_active": False}
    if os.path.exists(CB_FILE):
        try:
            with open(CB_FILE, "r", encoding="utf-8") as f:
                cb_data = json.load(f)
        except Exception:
            pass

    max_stops = cb_data.get("max_daily_stops", 2)

    if args.reset:
        count = 0
        lockout = False
        msg = "CIRCUIT BREAKER RESETADO: Stops zerados pelo operador."
    elif args.stops is not None:
        count = args.stops
        lockout = count >= max_stops
        msg = f"Stops definidos manualmente para {count}/{max_stops}."
    else:
        count = cb_data.get("daily_stops_count", 0) + 1
        lockout = count >= max_stops
        msg = f"Stop registrado pelo operador! Total hoje: {count}/{max_stops}."

    cb_data["daily_stops_count"] = count
    cb_data["max_daily_stops"] = max_stops
    cb_data["lockout_active"] = lockout
    cb_data["reason"] = msg
    cb_data["updated_at"] = datetime.now().isoformat()

    with open(CB_FILE, "w", encoding="utf-8") as f:
        json.dump(cb_data, f, indent=2, ensure_ascii=False)

    # Atualiza runtime_state.json de imediato
    if os.path.exists(RUNTIME_FILE):
        try:
            with open(RUNTIME_FILE, "r", encoding="utf-8") as f:
                rt = json.load(f)
            rt["circuit_breaker"] = {
                "daily_stops_count": count,
                "max_daily_stops": max_stops,
                "lockout_active": lockout
            }
            if lockout:
                rt["trading_enabled"] = False
                vetos = rt.get("active_vetos", [])
                cb_veto = f"CIRCUIT BREAKER: Limite diário de stops atingido ({count}/{max_stops})."
                if not any("CIRCUIT BREAKER" in v for v in vetos):
                    vetos.append(cb_veto)
                rt["active_vetos"] = vetos
            else:
                # Se resetou e não há outros bloqueios rígidos
                rt["active_vetos"] = [v for v in rt.get("active_vetos", []) if "CIRCUIT BREAKER" not in v]
                rt["trading_enabled"] = True

            rt["state_version"] = rt.get("state_version", 0) + 1
            with open(RUNTIME_FILE, "w", encoding="utf-8") as f:
                json.dump(rt, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[AVISO] Falha ao sincronizar runtime_state: {e}")

    # Exibição visual
    color = "\033[91m" if lockout else "\033[92m"
    bold = "\033[1m"
    reset = "\033[0m"

    print(f"\n{bold}{'=' * 65}{reset}")
    if lockout:
        print(f"{bold}{color}🛑 [CIRCUIT BREAKER ATIVADO — OPERAÇÃO BLOQUEADA]{reset}")
        print(f" {bold}Stops Hoje   :{reset} {color}{count}/{max_stops}{reset}")
        print(f" {bold}Status       :{reset} {color}LOCKOUT ATIVO — Nenhuma nova ordem permitida hoje.{reset}")
        print(f" {bold}Preservação  :{reset} Disciplina mantida. Capital protegido para amanhã.")
    else:
        print(f"{bold}{color}🟢 [CIRCUIT BREAKER ATUALIZADO]{reset}")
        print(f" {bold}Stops Hoje   :{reset} {count}/{max_stops}")
        print(f" {bold}Status       :{reset} {color}OPERAÇÕES LIBERADAS (Modo Copiloto ativo){reset}")
    print(f"{bold}{'=' * 65}{reset}\n")

if __name__ == "__main__":
    main()
