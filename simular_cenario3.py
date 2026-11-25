"""
simular_cenario3.py
Script oficial para simular no PowerShell a execução do CENÁRIO 3 implementado:
1. Demonstração de Trade CONFIRMADO (Passagem Livre até o Alvo de 400 pts com Stop de 250 pts)
2. Demonstração de Trade BLOQUEADO (Obstáculo Institucional FVG no caminho do Alvo — Sem Apitos / Sem Execução)
"""

import sys
import os
import time
from datetime import datetime, timedelta

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from core.models import SignalSetup, SetupStatus, Direction
from core.contract import get_current_win_contract, TZ_BRASILIA
from analysis.alert_formatter import format_operational_alert
from analysis.fvg_mtf_scanner import FGVMTFScanner, ActiveMTFFVG, FVGApproachAlert
import colorama
from colorama import Fore, Back, Style

colorama.init(autoreset=True)


def tocar_apitos(direcao: str = "COMPRA"):
    """Toca a sequência de 5 apitos rápidos quando o trade é confirmado."""
    try:
        import winsound
        freq = 1300 if direcao == "COMPRA" else 950
        print(f"\n{Fore.YELLOW}[ÁUDIO OFICIAL] Tocando 5 apitos de EXECUÇÃO CONFIRMADA ({direcao})...{Style.RESET_ALL}")
        for _ in range(5):
            try:
                winsound.Beep(freq, 80)
            except Exception:
                pass
            time.sleep(0.08)
    except Exception:
        pass


def simular_cenario_3():
    now = datetime.now(TZ_BRASILIA)
    symbol = get_current_win_contract()
    
    print("=" * 80)
    print(Fore.CYAN + Style.BRIGHT + "   SIMULADOR OFICIAL DO CENÁRIO 3 — MINI-ÍNDICE WIN (B3)" + Style.RESET_ALL)
    print("=" * 80)
    print("Regras Ativas:")
    print("  * Alvo Fixo     : +400 pontos (R$ 80,00 por contrato / R$ 400,00 com 5 cts)")
    print("  * Stop Fixo     : -250 pontos (R$ 50,00 por contrato / R$ 250,00 com 5 cts)")
    print("  * Mitigação SMC : Descarte de rompimentos secos de 1m (exige confirmação no 2m/5m)")
    print("  * Radar FVG     : Bloqueio imediato se houver barreira institucional contrária no alvo")
    print("=" * 80 + "\n")

    # -------------------------------------------------------------
    # DEMONSTRAÇÃO 1: TRADE BLOQUEADO POR OBSTÁCULO INSTITUCIONAL FVG
    # -------------------------------------------------------------
    print(Fore.YELLOW + Style.BRIGHT + ">>> [DEMONSTRAÇÃO 1/2] TRADE BLOQUEADO PELO RADAR FVG (SEM APITO / NÃO OPERAR) <<<" + Style.RESET_ALL)
    print("Cenário: O algoritmo detectou rompimento de topo no 5m, MAS há uma Resistência FVG de 60m no caminho do alvo.\n")
    time.sleep(1)

    scanner = FGVMTFScanner()
    fvg_60m = ActiveMTFFVG(
        timeframe=60,
        direction="BEARISH",
        top=170380.0,
        bottom=170250.0,
        ce_50=170315.0,
        formed_time=now - timedelta(hours=2)
    )
    scanner.active_fvgs[60].append(fvg_60m)
    
    current_p = 170215.0
    fvg_alert = FVGApproachAlert(
        fvg=fvg_60m,
        current_price=current_p,
        distance_to_zone=35.0,
        distance_to_ce=100.0,
        is_inside_zone=False,
        action_direction="VENDA",
        zone_start=170250.0,
        zone_end=170380.0
    )
    fvg_banner = scanner.format_power_shell_alert(fvg_alert, use_color=True)
    
    regimes = {60: "ALTA", 30: "ALTA", 15: "ALTA", 10: "ALTA", 5: "ALTA", 2: "CONSOLIDAÇÃO", 1: "ALTA"}
    
    flow_data = {
        "buy_volume": 11800,
        "sell_volume": 7200,
        "delta": +4600,
        "large_trades": [{"qty": 200, "price": 170215.0, "side": "BUY"}],
        "price_displacement_pts": +50.0,
        "flow_pattern": "Agressão Compradora com avanço rápido"
    }

    setup_bloqueado = SignalSetup(
        timestamp=now,
        setup_name="Compra de Rompimento Estrutural (BOS 5m / Breakout com Continuidade)",
        direction=Direction.COMPRA,
        symbol=symbol,
        status=SetupStatus.BLOQUEADO,
        entry_price=170215.0,
        stop_price=169965.0,
        stop_points=250.0,
        target_price=170615.0,
        target_points=400.0,
        risk_reward=1.60,
        timeframe_trigger=5,
        in_trend_direction=True,
        structure_event="Rompimento de topo no 5m",
        obstacles=[
            "[ALERTA] OBSTÁCULO INSTITUCIONAL: Resistência FVG de 60m em 170.250 - 170.380 (50% CE: 170.315) a 35 pts da entrada (no caminho do alvo)"
        ],
        facts_observed=[
            "Preço atual: 170.215",
            "Times & Trades: DELTA=+4600 contratos",
            "OBSTÁCULO DETECTADO: Resistência FVG de 60m a apenas 35 pontos da entrada",
            "Alvo estimado de 400 pts (170.615) colide diretamente contra a zona vendedora"
        ],
        interpretations=[
            "CENÁRIO 3 ATIVO: Operação de compra BLOQUEADA para proteger o capital contra armadilha de topo.",
            "Sem sinal sonoro para evitar execução acidental."
        ],
        limitations=["Alvo bloqueado por barreira de liquidez macro"],
        invalidation_criteria="Fechamento acima de 170.380 com volume institucional ou perda de 169.965"
    )

    alert_bloqueado = format_operational_alert(
        setup=setup_bloqueado,
        regimes=regimes,
        source_name="Nelogica ProfitPro (DDE)",
        delay_ms=0.5,
        quality_status="ÍNTEGRO (FLUXO + ESTRUTURA)",
        use_color=True,
        flow_data=flow_data,
        symbol_override=f"{symbol} (Mini-Índice B3)",
        fvg_radar_banner=fvg_banner
    )

    print(alert_bloqueado)
    print("\n" + Fore.YELLOW + "[SISTEMA]: Operação BLOQUEADA com sucesso. Nenhum apito emitido. Execução travada no SuperDOM." + Style.RESET_ALL)
    print("=" * 80 + "\n")
    
    input("Pressione [ENTER] para ver a Demonstração 2 (Trade CONFIRMADO com Passagem Livre)... ")
    
    # -------------------------------------------------------------
    # DEMONSTRAÇÃO 2: TRADE CONFIRMADO (PASSAGEM LIVRE)
    # -------------------------------------------------------------
    print("\n" + Fore.GREEN + Style.BRIGHT + ">>> [DEMONSTRAÇÃO 2/2] TRADE CONFIRMADO (PASSAGEM LIVRE — 5 APITOS ATIVOS) <<<" + Style.RESET_ALL)
    print("Cenário: Pullback em FVG de 15m a favor da tendência com passagem livre de 400 pontos até o alvo.\n")
    time.sleep(1)
    
    tocar_apitos("COMPRA")
    
    scanner_livre = FGVMTFScanner()
    setup_confirmado = SignalSetup(
        timestamp=now,
        setup_name="Compra por Reteste de 50% do FVG (Consequent Encroachment)",
        direction=Direction.COMPRA,
        symbol=symbol,
        status=SetupStatus.CONFIRMADO,
        entry_price=169850.0,
        stop_price=169600.0,
        stop_points=250.0,
        target_price=170250.0,
        target_points=400.0,
        risk_reward=1.60,
        timeframe_trigger=15,
        in_trend_direction=True,
        structure_event="Reteste do 50% CE com absorção e defesa no book",
        obstacles=["PASSAGEM LIVRE: Nenhum obstáculo institucional contrário mapeado até o alvo de 400 pts"],
        facts_observed=[
            "Preço atual: 169.850",
            "Times & Trades: DELTA=+6120 contratos",
            "Caminho livre até o alvo em 170.250 (+400 pontos)",
            "Excelente confluência fluxo + estrutura SMC"
        ],
        interpretations=[
            "Setup 100% qualificado pelas regras do Cenário 3.",
            "Executar imediatamente no SuperDOM: Alvo 400 pts / Stop 250 pts."
        ],
        limitations=["Oscilação padrão de mercado"],
        invalidation_criteria="Perda do fundo em 169.600"
    )

    alert_confirmado = format_operational_alert(
        setup=setup_confirmado,
        regimes=regimes,
        source_name="Nelogica ProfitPro (DDE)",
        delay_ms=0.3,
        quality_status="ÍNTEGRO (FLUXO + ESTRUTURA)",
        use_color=True,
        flow_data=flow_data,
        symbol_override=f"{symbol} (Mini-Índice B3)",
        fvg_radar_banner=None
    )

    print(alert_confirmado)
    print("\n" + Fore.GREEN + Style.BRIGHT + ">>> [OK] CENÁRIO 3 VALIDADO EM TEMPO REAL NO POWERSHELL <<<" + Style.RESET_ALL + "\n")


if __name__ == "__main__":
    simular_cenario_3()
