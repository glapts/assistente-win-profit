"""
testar_visual_melhorias.py
Script interativo para demonstrar na tela do PowerShell exatamente o que mudou
quando o sinal é disparado com as Melhorias A, B e C ativas.
"""

import sys
import os
import time
from datetime import datetime

# Garantir path raiz
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

import colorama
from colorama import Fore, Back, Style

colorama.init(autoreset=True)

from core.models import SignalSetup, SetupStatus, Direction
from core.contract import TZ_BRASILIA
from analysis.alert_formatter import format_operational_alert

def main():
    now = datetime.now(TZ_BRASILIA)

    print(Fore.CYAN + Style.BRIGHT + "=" * 76)
    print(Fore.WHITE + Style.BRIGHT + "  🔍 DEMONSTRAÇÃO VISUAL DAS MELHORIAS NO POWERSHELL (RADAR FVG + FLUXO)  ")
    print(Fore.CYAN + Style.BRIGHT + "=" * 76 + "\n")

    # =========================================================================
    # CENÁRIO: Rompimento Institucional das 10:17:16 (Dado Real de Hoje - WINZ26)
    # Entrada: 174.070 | Stop: 173.920 | Alvo: 174.470 | FVG 5m em 174.180 - 174.250
    # Times & Trades: Delta +18.796 ct | Deslocamento +60 pts
    # =========================================================================

    flow_real = {
        "buy_volume": 33682,
        "sell_volume": 14886,
        "delta": 18796,
        "price_displacement_pts": 60.0,
        "flow_pattern": "Agressão com Continuidade Compradora (Delta positivo acompanhado de avanço do preço)",
        "large_trades": [
            {"side": "BUY", "qty": 350, "price": 174070},
            {"side": "BUY", "qty": 200, "price": 174070},
            {"side": "BUY", "qty": 150, "price": 174065}
        ]
    }

    regimes_demo = {
        60: "ALTA",
        30: "ALTA",
        15: "ALTA",
        10: "ALTA",
        5: "ALTA",
        2: "ALTA",
        1: "ALTA"
    }

    # -------------------------------------------------------------------------
    # 1. COMO ERA ANTES (BLOQUEIO TOTAL DO RADAR FVG)
    # -------------------------------------------------------------------------
    print(Fore.YELLOW + Style.BRIGHT + "🔴 1. COMO APARECIA ANTES (OPERAÇÃO BLOQUEADA PELO FVG INTRADAY):")
    print(Fore.YELLOW + "   O trader perdia +635 pontos porque o Radar FVG bloqueava a execução no DOM.\n")

    setup_antigo = SignalSetup(
        timestamp=now,
        symbol="WINZ26",
        direction=Direction.COMPRA,
        setup_name="Rompimento Institucional com Sweet Spot",
        status=SetupStatus.BLOQUEADO,
        entry_price=174070.0,
        stop_price=173920.0,
        stop_points=150.0,
        target_price=174470.0,
        target_points=400.0,
        risk_reward=2.67,
        timeframe_trigger=2,
        in_trend_direction=True,
        obstacles=[
            "[ALERTA] OBSTÁCULO INSTITUCIONAL: Resistência FVG de 5m em 174.180 - 174.250 (50% CE: 174.215) a 110 pts da entrada (no caminho do alvo)"
        ],
        interpretations=[
            "Contexto de forte alta institucional com expansão de volume."
        ]
    )

    alerta_antigo = format_operational_alert(
        setup=setup_antigo,
        regimes=regimes_demo,
        flow_data=flow_real,
        use_color=True
    )
    print(alerta_antigo)

    print("\n" + "=" * 76 + "\n")
    input(Fore.CYAN + Style.BRIGHT + "👉 Pressione [ENTER] para ver COMO FICA AGORA com as Melhorias A, B e C...")

    # -------------------------------------------------------------------------
    # 2. COMO FICA AGORA (FLOW OVERRIDE + ALVO 1 PARCIAL + ALVO 2 FINAL)
    # -------------------------------------------------------------------------
    print("\n" + Fore.GREEN + Style.BRIGHT + "🟢 2. COMO FICA AGORA (MELHORIAS A, B e C — OPÇÃO 2 SMC ATIVA):")
    print(Fore.GREEN + "   * Melhoria A: Delta institucional >= +3.000 ct no Sweet Spot (+50 a +180 pts) ativa o FLOW OVERRIDE.")
    print(Fore.GREEN + "   * Melhoria B: Cria o ALVO 1 (Parcial na borda do FVG @ 174.180) para garantir lucro.")
    print(Fore.GREEN + "   * Melhoria C: Proteção SMC ativa (deslocamentos > 180 pts em Zona Premium são vetados).")
    print(Fore.GREEN + "   * Box de 1-Clique no SuperDOM liberado imediatamente!\n")

    setup_novo = SignalSetup(
        timestamp=now,
        symbol="WINZ26",
        direction=Direction.COMPRA,
        setup_name="Rompimento Institucional com Sweet Spot",
        status=SetupStatus.CONFIRMADO,
        entry_price=174070.0,
        stop_price=173920.0,
        stop_points=150.0,
        target_price=174470.0,
        target_points=400.0,
        risk_reward=2.67,
        timeframe_trigger=2,
        in_trend_direction=True,
        partial_target_price=174180.0,
        partial_target_points=110.0,
        obstacles=[
            "[ALERTA] OBSTÁCULO INSTITUCIONAL: Resistência FVG de 5m em 174.180 - 174.250 (50% CE: 174.215) a 110 pts da entrada (no caminho do alvo)"
        ],
        interpretations=[
            "Contexto de forte alta institucional com expansão de volume.",
            "⚡ FLOW OVERRIDE ATIVO: Delta institucional (+18796) e deslocamento (+60 pts) superam barreira intraday, convertendo FVG em Inversion FVG (iFVG)."
        ]
    )

    alerta_novo = format_operational_alert(
        setup=setup_novo,
        regimes=regimes_demo,
        flow_data=flow_real,
        use_color=True
    )
    print(alerta_novo)

    # Simular o apito sonoro de confirmação
    try:
        import winsound
        print(Fore.YELLOW + "\n🔊 Tocando sequência sonora de 5 apitos (CONFIRMAÇÃO DE ENTRADA)...")
        for _ in range(5):
            winsound.Beep(1200, 100)
            time.sleep(0.05)
    except Exception:
        pass

    print(Fore.CYAN + Style.BRIGHT + "\n" + "=" * 76)
    print(Fore.GREEN + Style.BRIGHT + "  ✅ DEMONSTRAÇÃO CONCLUÍDA COM SUCESSO!")
    print(Fore.CYAN + Style.BRIGHT + "=" * 76)

if __name__ == "__main__":
    main()
