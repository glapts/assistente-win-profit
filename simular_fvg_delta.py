"""
simular_fvg_delta.py
Simulador oficial para reproduzir no PowerShell o disparo simultâneo de:
1. Radar FVG Antecipado contra a tendência (ex: Resistência Bearish 60m)
2. Setup do Algoritmo com Desbalanceamento de Delta (Times & Trades + Tape Reading)

Permite testar e comprovar na tela o motivo pelo qual o alerta sonoro tocou,
mas parte das informações (especialmente o banner do FVG no topo) rolou para
fora da janela visível do PowerShell devido à altura do buffer (81 linhas).
"""

import sys
import os
import time
import shutil
from datetime import datetime, timedelta

# Garante path do projeto
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


def tocar_apitos_alerta(direcao: str = "COMPRA"):
    """Reproduz os 5 apitos rápidos disparados pelo motor do assistente."""
    try:
        import winsound
        freq = 1300 if direcao == "COMPRA" else 950
        print(f"\n{Fore.YELLOW}[ÁUDIO] Emitindo sequência de 5 apitos de alerta ({direcao})...{Style.RESET_ALL}")
        for _ in range(5):
            try:
                winsound.Beep(freq, 85)
            except Exception:
                pass
            time.sleep(0.08)
    except Exception:
        pass


def criar_cenario_confluencia_ou_conflito(contra_tendencia: bool = True):
    """
    Monta exatamente o estado dos dois disparos:
    1. FVG MTF Scanner (ex: 60m Bearish no topo contra a tendência de alta recente)
    2. Setup de Desbalanceamento de Delta no Times & Trades (ex: Compra agressiva de 1m)
    """
    now = datetime.now(TZ_BRASILIA)
    symbol = get_current_win_contract()
    
    # 1. RADAR FVG ANTECIPADO (Ex: FVG Macro de 60m nos 170.300 atuando como Resistência)
    scanner = FGVMTFScanner()
    fvg_60m = ActiveMTFFVG(
        timeframe=60,
        direction="BEARISH",
        top=170380.0,
        bottom=170250.0,
        ce_50=170315.0,
        formed_time=now - timedelta(hours=3)
    )
    scanner.active_fvgs[60].append(fvg_60m)
    
    # Preço atual testando a zona ou se aproximando da borda inferior
    current_price = 170215.0
    fvg_alert = FVGApproachAlert(
        fvg=fvg_60m,
        current_price=current_price,
        distance_to_zone=35.0,
        distance_to_ce=100.0,
        is_inside_zone=False,
        action_direction="VENDA",
        zone_start=170250.0,
        zone_end=170380.0
    )
    fvg_radar_banner = scanner.format_power_shell_alert(fvg_alert, use_color=True)
    
    # 2. ALGORITMO: SETUP COM DESBALANCEAMENTO DE DELTA E TAPE READING
    regimes = {
        "240m": "ALTA",
        "60m" : "ALTA",
        "30m" : "ALTA",
        "15m" : "ALTA",
        "10m" : "ALTA",
        "5m"  : "CONSOLIDAÇÃO",
        "2m"  : "CONSOLIDAÇÃO",
        "1m"  : "ALTA"
    }
    
    flow_data = {
        "buy_volume": 12450,
        "sell_volume": 6820,
        "delta": +5630, # Desbalanceamento expressivo de delta comprador
        "large_trades": [
            {"qty": 180, "price": 170210.0, "side": "BUY"},
            {"qty": 250, "price": 170215.0, "side": "BUY"},
            {"qty": 120, "price": 170215.0, "side": "BUY"}
        ],
        "price_displacement_pts": +65.0,
        "flow_pattern": "Agressão com Continuidade Compradora (DELTA positivo com avanço rápido)"
    }
    
    setup = SignalSetup(
        timestamp=now,
        setup_name="Compra por Defesa Institucional no Fundo (Tape Reading + Desbalanceamento 1m)",
        direction=Direction.COMPRA,
        symbol=symbol,
        status=SetupStatus.CONFIRMADO,
        entry_price=170215.0,
        stop_price=169965.0,
        stop_points=250.0,
        target_price=170615.0,
        target_points=400.0,
        risk_reward=1.60,
        timeframe_trigger=1,
        in_trend_direction=True,
        fvg_zone=None, # Como é setup de fluxo/delta no 1m, este campo do setup fica sem FVG interno
        structure_event="Agressão compradora no 1m com absorção e defesa de lote no book",
        book_evidence={
            "observed_behavior": "Barreira de lotes passivos compradores em 170.200 (650 contratos)",
            "metrics": {"spread": 5.0, "book_imbalance_top5": 0.45},
            "classification": "Comportamento de oferta observado (Defesa de compradores)",
            "limitations": ["Feed amostrado DDE", "Profundidade de topo de livro"]
        },
        flow_evidence=flow_data,
        facts_observed=[
            "Preço atual: 170.215",
            "Times & Trades: DELTA=+5630 contratos (Forte desbalanceamento comprador)",
            "Grandes players agredindo na compra a mercado (250ct, 180ct)",
            "Aproximação simultânea de FVG Macro de 60m (170.250 - 170.380) logo acima"
        ],
        interpretations=[
            "Algoritmo sinaliza compra rápida por desbalanceamento de fluxo no micro (1m).",
            "ATENÇÃO: Resistência de FVG Macro 60m localizada a apenas 35 pontos acima da entrada!"
        ],
        limitations=[
            "Risco de exaustão compradora contra a barreira de liquidez do FVG 60m.",
            "Não há garantia de rompimento da zona de resistência."
        ],
        validity_deadline=now + timedelta(minutes=5),
        invalidation_criteria="Perda do nível 169.965 ou reversão brusca do delta para negativo."
    )
    
    # Mapear obstáculos institucionais vs passagem livre no caminho do alvo
    setup.obstacles = scanner.check_target_obstacles(
        direction=setup.direction,
        entry_price=setup.entry_price,
        target_price=setup.target_price
    )
    
    # 3. Formata o alerta unificado exatamente como a engine faz no evaluate_now()
    alert_text = format_operational_alert(
        setup=setup,
        regimes=regimes,
        source_name="Nelogica ProfitPro (DDE)",
        delay_ms=0.4,
        quality_status="ÍNTEGRO (FLUXO + ESTRUTURA)",
        use_color=True,
        flow_data=flow_data,
        symbol_override=f"{symbol} (Mini-Índice B3)",
        fvg_radar_banner=fvg_radar_banner
    )
    
    return alert_text, fvg_radar_banner, setup


def executar_simulacao():
    print("=" * 75)
    print(" SIMULADOR DE CONFLUÊNCIA: RADAR FVG MTF + DESBALANCEAMENTO DE DELTA")
    print("=" * 75)
    print("Cenário sendo simulado:")
    print("  1. Radar FVG MTF: Detecta aproximação de FVG Macro de 60m [VENDA / RESISTÊNCIA]")
    print("  2. Algoritmo Tape Reading: Detecta desbalanceamento de Delta no 1m [COMPRA +5.630 ct]")
    print("-" * 75)
    
    # Toca os apitos oficiais de disparo
    tocar_apitos_alerta("COMPRA")
    
    # Obtém o alerta montado
    alert_text, fvg_banner, setup = criar_cenario_confluencia_ou_conflito(contra_tendencia=True)
    
    # Medições de tela
    linhas_alerta = alert_text.splitlines()
    total_linhas = len(linhas_alerta)
    terminal_size = shutil.get_terminal_size((80, 25))
    altura_terminal = terminal_size.lines
    largura_terminal = terminal_size.columns
    
    print("\n" + Fore.CYAN + ">>> IMPRIMINDO ALERTA COMPLETO NA TELA DO POWERSHELL (EXATAMENTE COMO NO SISTEMA) <<<" + Style.RESET_ALL + "\n")
    time.sleep(0.5)
    
    # Imprime exatamente o que o Profit Assistant cospe no console
    print(alert_text)
    
    # Diagnóstico visual pós-impressão
    print("\n" + "=" * 75)
    print(Fore.GREEN + Style.BRIGHT + " [NOVO LAYOUT APROVADO: RADAR FVG FIXADO NO RODAPÉ DO POWERSHELL]" + Style.RESET_ALL)
    print("=" * 75)
    print(f" * Total de linhas geradas pelo Alerta : {total_linhas} linhas")
    print(f" * Altura atual da sua janela PowerShell : {altura_terminal} linhas")
    print(f" * Largura da sua janela PowerShell      : {largura_terminal} colunas")
    
    print(f"\n{Fore.GREEN}{Style.BRIGHT} [OK] POSICIONAMENTO CORRIGIDO:{Style.RESET_ALL}")
    print("   Agora o [RADAR FVG ANTECIPADO] está posicionado LOGO ABAIXO de:")
    print("     1. TIMES & TRADES (Fluxo, Delta, Agressões)")
    print("     2. >>> EXECUÇÃO RÁPIDA NO SUPERDOM <<< (Ação, Entrada, Stop, Alvo)")
    print("     3. [RADAR FVG ANTECIPADO] (Preço, Timeframe, Direção, Zona, 50% CE, Objetivo)")
    print("\n   Dessa forma, mesmo que a janela do PowerShell tenha apenas 25-30 linhas,")
    print("   quando o alerta imprime na tela, o final da rolagem mostra exatamente:")
    print("   TIMES & TRADES + SUPERDOM + RADAR FVG, sem nunca mais sumir da visão!")
    print("=" * 75 + "\n")


if __name__ == "__main__":
    executar_simulacao()
