"""
simular_liberado.py
Demonstração instantânea no PowerShell de quando uma OPERAÇÃO É LIBERADA / CONFIRMADA:
- 5 apitos rápidos oficiais de execução
- Status: CONFIRMADO
- Ação no SuperDOM: >>> COMPRA <<< (Verde Brilhante)
- Alvo: 400 pontos | Stop: 250 pontos
- Obstáculos: PASSAGEM LIVRE (Verde)
- Bloco de Execução Rápida no SuperDOM no rodapé
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


def tocar_apitos_confirmados(direcao: str = "COMPRA"):
    """Emite a sequência sonora de 5 apitos de entrada confirmada."""
    try:
        import winsound
        freq = 1300 if direcao == "COMPRA" else 950
        print(f"\n{Fore.GREEN}{Style.BRIGHT}[ÁUDIO OFICIAL B3] Emitindo 5 apitos de OPERAÇÃO LIBERADA ({direcao})...{Style.RESET_ALL}")
        for _ in range(5):
            try:
                winsound.Beep(freq, 80)
            except Exception:
                pass
            time.sleep(0.08)
    except Exception:
        pass


def executar_exemplo_liberado():
    now = datetime.now(TZ_BRASILIA)
    symbol = get_current_win_contract()
    
    # 1. Toca o alerta sonoro imediatamente
    tocar_apitos_confirmados("COMPRA")
    time.sleep(0.3)
    
    # 2. Monta o Radar FVG a favor do movimento (Zona de Suporte Institucional no fundo)
    scanner = FGVMTFScanner()
    fvg_suporte = ActiveMTFFVG(
        timeframe=15,
        direction="BULLISH",
        top=170200.0,
        bottom=170100.0,
        ce_50=170150.0,
        formed_time=now - timedelta(minutes=45)
    )
    scanner.active_fvgs[15].append(fvg_suporte)
    
    fvg_alert = FVGApproachAlert(
        fvg=fvg_suporte,
        current_price=170215.0,
        distance_to_zone=15.0,
        distance_to_ce=65.0,
        is_inside_zone=False,
        action_direction="COMPRA",
        zone_start=170200.0,
        zone_end=170100.0
    )
    fvg_banner = scanner.format_power_shell_alert(fvg_alert, use_color=True)
    
    regimes = {
        "240m": "ALTA",
        "60m" : "ALTA",
        "30m" : "ALTA",
        "15m" : "ALTA",
        "10m" : "ALTA",
        "5m"  : "ALTA",
        "2m"  : "ALTA",
        "1m"  : "ALTA"
    }
    
    flow_data = {
        "buy_volume": 14200,
        "sell_volume": 5800,
        "delta": +8400,
        "large_trades": [
            {"qty": 350, "price": 170215.0, "side": "BUY"},
            {"qty": 200, "price": 170210.0, "side": "BUY"},
            {"qty": 180, "price": 170215.0, "side": "BUY"}
        ],
        "price_displacement_pts": +75.0,
        "flow_pattern": "Agressão Compradora Institucional com Absorção Passiva no Suporte"
    }

    setup_liberado = SignalSetup(
        timestamp=now,
        setup_name="Compra por Defesa Institucional no Fundo (Tape Reading + Reteste de Suporte)",
        direction=Direction.COMPRA,
        symbol=symbol,
        status=SetupStatus.CONFIRMADO,
        entry_price=170215.0,
        stop_price=169965.0,
        stop_points=250.0,
        target_price=170615.0,
        target_points=400.0,
        risk_reward=1.60,
        timeframe_trigger=5,
        in_trend_direction=True,
        structure_event="Defesa compradora no suporte de 15m com absorção e agressão",
        obstacles=[
            "PASSAGEM LIVRE: Nenhum obstáculo institucional contrário mapeado até o alvo de 400 pts"
        ],
        facts_observed=[
            "Preço atual: 170.215",
            "Times & Trades: DELTA=+8400 contratos (Forte domínio institucional comprador)",
            "Grandes players agredindo na compra a mercado (350ct, 200ct)",
            "Suporte FVG de 15m em 170.150 atuando como piso da operação",
            "Caminho totalmente livre até o alvo em 170.615 (+400 pontos)"
        ],
        interpretations=[
            "CENÁRIO 3: OPERAÇÃO 100% LIBERADA E CONFIRMADA.",
            "Executar imediatamente no SuperDOM: Compra a mercado ou apregoada em 170.215."
        ],
        limitations=["Oscilação padrão de mercado"],
        invalidation_criteria="Perda do nível de suporte em 169.965"
    )

    alert_text = format_operational_alert(
        setup=setup_liberado,
        regimes=regimes,
        source_name="Nelogica ProfitPro (DDE)",
        delay_ms=0.3,
        quality_status="ÍNTEGRO (FLUXO + ESTRUTURA)",
        use_color=True,
        flow_data=flow_data,
        symbol_override=f"{symbol} (Mini-Índice B3)",
        fvg_radar_banner=fvg_banner
    )

    print(alert_text)
    print("\n" + "=" * 75)
    print(Fore.GREEN + Style.BRIGHT + ">>> [SUCESSO] OPERAÇÃO LIBERADA COM PASSAGEM LIVRE (CENÁRIO 3) <<<" + Style.RESET_ALL)
    print("=" * 75 + "\n")


if __name__ == "__main__":
    executar_exemplo_liberado()
