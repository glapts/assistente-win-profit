"""
simular_operacoes_hoje.py
Simulações hiper-realistas das duas grandes operações institucionais de hoje (13/11/2026):
1. COMPRA INSTITUCIONAL DAS 11:30 (Wall Street Open + Sweep de Mínima + Escada de Lotes)
2. VENDA INSTITUCIONAL DAS 11:38 (Absorção de 806ct no 50% CE da Resistência FVG)

Pode ser executado diretamente no PowerShell:
    python simular_operacoes_hoje.py compra
    python simular_operacoes_hoje.py venda
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


def emitir_apitos(direcao: str = "COMPRA"):
    """Emite os 5 apitos sonoros oficiais do assistente no SuperDOM."""
    try:
        import winsound
        freq = 1300 if direcao == "COMPRA" else 950
        print(f"\n{Fore.CYAN}{Style.BRIGHT}🔔 [ALERTA SONORO B3] Disparando 5 apitos de EXECUÇÃO ({direcao})...{Style.RESET_ALL}")
        for _ in range(5):
            try:
                winsound.Beep(freq, 75)
            except Exception:
                pass
            time.sleep(0.06)
    except Exception:
        pass


def simular_compra():
    """
    Simulação da Operação de COMPRA das 11:30:
    Sweep de Mínima em 173.105, abertura de NY e varredura de lotes institucionais.
    """
    now = datetime.now(TZ_BRASILIA)
    symbol = get_current_win_contract()

    # 1. Tocar os 5 apitos
    emitir_apitos("COMPRA")
    time.sleep(0.2)

    # 2. Configurar o Radar FVG Institucional
    scanner = FGVMTFScanner()
    fvg_suporte = ActiveMTFFVG(
        timeframe=5,
        direction="BULLISH",
        top=173350.0,
        bottom=173150.0,
        ce_50=173250.0,
        formed_time=now - timedelta(minutes=15)
    )
    scanner.active_fvgs[5].append(fvg_suporte)

    fvg_alert = FVGApproachAlert(
        fvg=fvg_suporte,
        current_price=173445.0,
        distance_to_zone=95.0,
        distance_to_ce=195.0,
        is_inside_zone=False,
        action_direction="COMPRA",
        zone_start=173350.0,
        zone_end=173150.0
    )
    fvg_banner = scanner.format_power_shell_alert(fvg_alert, use_color=True)

    # 3. Regimes alinhados com o contexto do dia
    regimes = {
        "240m": "ALTA",
        "60m" : "ALTA",
        "30m" : "ALTA",
        "15m" : "ALTA",
        "10m" : "ALTA",
        "5m"  : "ALTA",
        "2m"  : "ALTA",
        "1m"  : "BAIXA"
    }

    # 4. Dados de Fluxo e Tape Reading com a "Escada Institucional"
    flow_data = {
        "buy_volume": 13495,
        "sell_volume": 8029,
        "delta": +5466,
        "large_trades": [
            {"qty": 522, "price": 173435.0, "side": "BUY"},
            {"qty": 782, "price": 173485.0, "side": "BUY"},
            {"qty": 923, "price": 173570.0, "side": "BUY"}
        ],
        "price_displacement_pts": +85.0,
        "flow_pattern": "Agressão com Continuidade Compradora (DELTA positivo acompanhado de avanço do preço)"
    }

    # 5. Setup Canônico
    setup_compra = SignalSetup(
        timestamp=now,
        setup_name="Compra após Falso Rompimento da Mínima (Sweep 2m)",
        direction=Direction.COMPRA,
        symbol=symbol,
        status=SetupStatus.CONFIRMADO,
        entry_price=173445.0,
        stop_price=173195.0,
        stop_points=250.0,
        target_price=173845.0,
        target_points=400.0,
        risk_reward=1.60,
        timeframe_trigger=2,
        in_trend_direction=True,
        structure_event="Sweep de Mínima (173185): violou 173105 e fechou em 173225",
        obstacles=[
            "PASSAGEM LIVRE: Nenhum obstáculo institucional contrário entre entrada e alvo (400 pts livres até 173.845)"
        ],
        facts_observed=[
            "Preço atual: 173.445",
            "Estrutura: Falso rompimento de fundo no 2m às 11:28 (Captura de Liquidez institucional)",
            "Abertura de Wall Street (11:30 BRT): Algoritmos gringos agredindo massivamente a mercado",
            "Delta de fluxo: +5.466 contratos de pressão compradora",
            "Escada de lotes: 522ct@173435 ➔ 782ct@173485 ➔ 923ct@173570 (Comprador pagando spread)"
        ],
        interpretations=[
            "SINAL DE COMPRA DE ALTA PROBABILIDADE.",
            "Executar imediatamente no SuperDOM na Coluna Azul (173.445).",
            "Alvo projetado de 400 pontos em 173.845 com extensão até 174.200."
        ],
        limitations=["Oscilação padrão de pregão em abertura de NY"],
        invalidation_criteria="Perda da mínima da captura em 173.195"
    )

    alert_text = format_operational_alert(
        setup=setup_compra,
        regimes=regimes,
        source_name="Nelogica ProfitPro (DDE)",
        delay_ms=0.4,
        quality_status="ÍNTEGRO (FLUXO + ESTRUTURA)",
        flow_data=flow_data,
        fvg_radar_banner=fvg_banner
    )

    print(alert_text)
    print(f"\n{Fore.GREEN}{Style.BRIGHT}✅ [SIMULAÇÃO CONCLUÍDA - COMPRA 11:30]{Style.RESET_ALL}")
    print(f"{Fore.WHITE}Dica de Leitura: Observe a escada de preços nas Grandes Execuções (173435 ➔ 173485 ➔ 173570).{Style.RESET_ALL}\n")


def simular_venda():
    """
    Simulação da Operação de VENDA das 11:38 (Lucro do Dia):
    Reteste em FVG 5m, Absorção no topo em 173.700 (806ct BUY) e derretimento até 173.300.
    """
    now = datetime.now(TZ_BRASILIA)
    symbol = get_current_win_contract()

    # 1. Tocar os 5 apitos de venda
    emitir_apitos("VENDA")
    time.sleep(0.2)

    # 2. Configurar o Radar FVG Institucional (Resistência de Venda)
    scanner = FGVMTFScanner()
    fvg_resistencia = ActiveMTFFVG(
        timeframe=5,
        direction="BEARISH",
        top=174235.0,
        bottom=173205.0,
        ce_50=173720.0,
        formed_time=now - timedelta(minutes=20)
    )
    scanner.active_fvgs[5].append(fvg_resistencia)

    fvg_alert = FVGApproachAlert(
        fvg=fvg_resistencia,
        current_price=173700.0,
        distance_to_zone=0.0,
        distance_to_ce=20.0,
        is_inside_zone=True,
        action_direction="VENDA",
        zone_start=173205.0,
        zone_end=174235.0
    )
    fvg_banner = scanner.format_power_shell_alert(fvg_alert, use_color=True)

    # 3. Regimes daquele momento
    regimes = {
        "240m": "ALTA",
        "60m" : "ALTA",
        "30m" : "ALTA",
        "15m" : "ALTA",
        "10m" : "ALTA",
        "5m"  : "ALTA",
        "2m"  : "ALTA",
        "1m"  : "BAIXA"
    }

    # 4. Dados de Fluxo e Tape Reading com Absorção de Topo
    flow_data = {
        "buy_volume": 14741,
        "sell_volume": 18168,
        "delta": -3427,
        "large_trades": [
            {"qty": 123, "price": 173690.0, "side": "SELL"},
            {"qty": 806, "price": 173700.0, "side": "BUY"},
            {"qty": 294, "price": 173700.0, "side": "SELL"}
        ],
        "price_displacement_pts": +165.0,
        "flow_pattern": "Absorção Passiva de Venda no Topo / Exaustão Compradora (Lote de 806ct contido)"
    }

    # 5. Setup Canônico
    setup_venda = SignalSetup(
        timestamp=now,
        setup_name="Venda de Continuidade em Tendência de Baixa (Reteste de FVG 1m)",
        direction=Direction.VENDA,
        symbol=symbol,
        status=SetupStatus.CONFIRMADO,
        entry_price=173700.0,
        stop_price=173950.0,
        stop_points=250.0,
        target_price=173300.0,
        target_points=400.0,
        risk_reward=1.60,
        timeframe_trigger=1,
        in_trend_direction=True,
        structure_event="Retração em FVG de 1m (173480-173720) com toque no 50% CE em 173.720",
        obstacles=[
            "PASSAGEM LIVRE: Nenhum obstáculo institucional contrário mapeado até o alvo de 400 pts (173.300)"
        ],
        facts_observed=[
            "Preço atual: 173.700",
            "Radar FVG: Preço testando exatamente a zona de 50% CE da Resistência Institucional (173.720)",
            "Tape Reading: Delta negativo de -3.427 contratos",
            "Absorção e Exaustão: 806ct tomados na compra em 173.700 sem romper a máxima",
            "Defesa Imediata: Vendedor institucional marretou 294ct no mesmo preço (173.700)"
        ],
        interpretations=[
            "SINAL DE VENDA CONFIRMADO (LUCRO DO DIA).",
            "Executar imediatamente no SuperDOM na Coluna Vermelha (173.700).",
            "Alvo integral de 400 pontos até 173.300."
        ],
        limitations=["Não segurar se romper 173.750"],
        invalidation_criteria="Superação de 173.950"
    )

    alert_text = format_operational_alert(
        setup=setup_venda,
        regimes=regimes,
        source_name="Nelogica ProfitPro (DDE)",
        delay_ms=2.8,
        quality_status="ÍNTEGRO (FLUXO + ESTRUTURA)",
        flow_data=flow_data,
        fvg_radar_banner=fvg_banner
    )

    print(alert_text)
    print(f"\n{Fore.RED}{Style.BRIGHT}✅ [SIMULAÇÃO CONCLUÍDA - VENDA 11:38 (LUCRO DO DIA)]{Style.RESET_ALL}")
    print(f"{Fore.WHITE}Dica de Leitura: Observe a absorção do lote de 806ct BUY seguido de 294ct SELL no mesmo nível (173.700).{Style.RESET_ALL}\n")


if __name__ == "__main__":
    arg = sys.argv[1].lower() if len(sys.argv) > 1 else "todos"
    
    if arg in ("compra", "buy", "1"):
        simular_compra()
    elif arg in ("venda", "sell", "2"):
        simular_venda()
    else:
        print(f"\n{Fore.YELLOW}{Style.BRIGHT}=== EXECUTANDO SIMULAÇÃO DUPLA: COMPRA (11:30) E VENDA (11:38) ==={Style.RESET_ALL}\n")
        simular_compra()
        print("\n" + "=" * 70 + "\n")
        time.sleep(1.0)
        simular_venda()
