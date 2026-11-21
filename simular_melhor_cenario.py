"""
simular_melhor_cenario.py
Simulador Mestre de Alta Precisão — Cenários Ideais de Compra e Venda na B3.
Desenvolvido para treinamento visual e execução em tempo real no SuperDOM com Tape Reading e SMC.

Como executar no PowerShell:
    python simular_melhor_cenario.py compra
    python simular_melhor_cenario.py venda
    python simular_melhor_cenario.py
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
    """Dispara a sequência oficial de 5 apitos operacionais no SuperDOM."""
    try:
        import winsound
        freq = 1300 if direcao == "COMPRA" else 950
        print(f"\n{Fore.CYAN}{Style.BRIGHT}🔔 [ALERTA SONORO SUPERDOM] 5 Apitos de Execução ({direcao})...{Style.RESET_ALL}")
        for _ in range(5):
            try:
                winsound.Beep(freq, 70)
            except Exception:
                pass
            time.sleep(0.05)
    except Exception:
        pass


def exibir_guia_didatico(direcao: str):
    """Exibe o passo a passo de como o trader deve ler e atuar em tempo real no pregão."""
    b_blue = Fore.CYAN + Style.BRIGHT
    b_green = Fore.GREEN + Style.BRIGHT
    b_red = Fore.RED + Style.BRIGHT
    b_yellow = Fore.YELLOW + Style.BRIGHT
    b_white = Fore.WHITE + Style.BRIGHT
    rst = Style.RESET_ALL

    print("=" * 80)
    if direcao == "COMPRA":
        print(f"{b_green}🧠 GUIA MESTRE DE LEITURA EM TEMPO REAL: COMO BATER COMPRA NO PREGÃO AO VIVO{rst}")
        print("=" * 80)
        print(f"""
{b_yellow}1. LOCALIZAÇÃO ESTRUTURAL (SMC DISCOUNT):{rst}
   • O preço deve estar no terço inferior do range (fundo do dia) ou testando o suporte/50% CE de um FVG.
   • Nunca compre mercado esticado no topo. Espere o preço chegar na zona barata (Discount).

{b_yellow}2. O GATILHO DE TAPE READING (A ARMADILHA DOS VENDEDORES):{rst}
   • {b_red}Etapa 1 (Absorção de Fundo):{rst} Você vê no Times & Trades um lote expressivo de venda a mercado 
     ex: {b_red}540ct@173150 (SELL){rst}, mas o preço NÃO cai (deslocamento zerado ou de apenas 5 pontos).
     ➔ Diagnóstico: Institucionais colocaram um muro passivo de compra e absorveram a venda.
   • {b_green}Etapa 2 (Agressão em Escada Compradora):{rst} Imediatamente após a absorção, entram ordens de compra
     a mercado pagando spread para cima: {b_green}780ct@173160 (BUY) ➔ 1.120ct@173200 (BUY){rst}.
   • {b_blue}Etapa 3 (Delta Positivo Expressivo):{rst} O Delta salta para {b_green}+9.400 contratos{rst} com deslocamento rápido de alta.

{b_yellow}3. AÇÃO NO SUPERDOM (1 CLIQUE):{rst}
   • 👉 {b_green}Onde clicar:{rst} Coluna AZUL (Compra) no preço de confirmação ({b_white}173.200{rst}).
   • 👉 {b_red}Stop Loss:{rst} Colado 1 tick abaixo do lote que absorveu ({b_white}172.950{rst} — 250 pontos).
   • 👉 {b_green}Alvo Técnico:{rst} Rompimento de liquidez do topo ou próximo FVG ({b_white}173.600{rst} — 400 pontos).
""")
    else:
        print(f"{b_red}🧠 GUIA MESTRE DE LEITURA EM TEMPO REAL: COMO BATER VENDA NO PREGÃO AO VIVO{rst}")
        print("=" * 80)
        print(f"""
{b_yellow}1. LOCALIZAÇÃO ESTRUTURAL (SMC PREMIUM):{rst}
   • O preço deve estar no terço superior do range (topo do dia) ou testando a resistência/50% CE de um FVG.
   • Nunca venda mercado esticado no fundo. Espere o preço chegar na zona cara (Premium).

{b_yellow}2. O GATILHO DE TAPE READING (A ARMADILHA DOS COMPRADORES):{rst}
   • {b_green}Etapa 1 (Absorção de Topo):{rst} A manada ou compradores eufóricos tomam um lote massivo a mercado 
     ex: {b_green}890ct@173800 (BUY){rst}, mas o preço NÃO avança 1 tick acima (deslocamento travado).
     ➔ Diagnóstico: Um grande player institucional colocou um "iceberg" de venda e engoliu toda a compra.
   • {b_red}Etapa 2 (Contra-Ataque Imediato):{rst} No mesmo nível, o vendedor bate a mercado {b_red}420ct@173800 (SELL){rst}
     e em seguida marreta para baixo {b_red}1.250ct@173750 (SELL){rst} limpando as ordens de compra penduradas.
   • {b_red}Etapa 3 (Delta Negativo Expressivo):{rst} O Delta desaba para {b_red}-11.300 contratos{rst} com deslocamento de baixa.

{b_yellow}3. AÇÃO NO SUPERDOM (1 CLIQUE):{rst}
   • 👉 {b_red}Onde clicar:{rst} Coluna VERMELHA (Venda) no preço de confirmação ({b_white}173.750{rst}).
   • 👉 {b_red}Stop Loss:{rst} Colado 1 tick acima do lote absorvido ({b_white}174.000{rst} — 250 pontos).
   • 👉 {b_green}Alvo Técnico:{rst} Busca do fundo prévio ou FVG inferior ({b_white}173.350{rst} — 400 pontos).
""")
    print("=" * 80 + "\n")


def simular_cenario_compra():
    """Simulação do Cenário Perfeito de Compra (Absorção no Fundo + Escada Institucional)."""
    now = datetime.now(TZ_BRASILIA)
    symbol = get_current_win_contract()

    emitir_apitos("COMPRA")
    time.sleep(0.15)

    # 1. Configurar Radar FVG de Suporte
    scanner = FGVMTFScanner()
    fvg_suporte = ActiveMTFFVG(
        timeframe=15,
        direction="BULLISH",
        top=173300.0,
        bottom=173100.0,
        ce_50=173200.0,
        formed_time=now - timedelta(minutes=30)
    )
    scanner.active_fvgs[15].append(fvg_suporte)

    fvg_alert = FVGApproachAlert(
        fvg=fvg_suporte,
        current_price=173200.0,
        distance_to_zone=0.0,
        distance_to_ce=0.0,
        is_inside_zone=True,
        action_direction="COMPRA",
        zone_start=173300.0,
        zone_end=173100.0
    )
    fvg_banner = scanner.format_power_shell_alert(fvg_alert, use_color=True)

    # 2. Matriz de Tendência Multi-Timeframe
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

    # 3. Métricas Determinísticas de Tape Reading
    flow_data = {
        "buy_volume": 15200,
        "sell_volume": 5800,
        "delta": +9400,
        "large_trades": [
            {"qty": 540, "price": 173150.0, "side": "SELL"},  # Venda absorvida no fundo
            {"qty": 780, "price": 173160.0, "side": "BUY"},   # Resposta compradora
            {"qty": 1120, "price": 173200.0, "side": "BUY"}   # Escada compradora varrendo spread
        ],
        "price_displacement_pts": +95.0,
        "flow_pattern": "Absorção Compradora de Fundo (540ct contidos) seguida de Agressão em Escada Institucional"
    }

    # 4. Setup Estrutural
    setup_compra = SignalSetup(
        timestamp=now,
        setup_name="Compra por Defesa Institucional no Fundo (Tape Reading + Reteste 50% CE FVG 15m)",
        direction=Direction.COMPRA,
        symbol=symbol,
        status=SetupStatus.CONFIRMADO,
        entry_price=173200.0,
        stop_price=172950.0,
        stop_points=250.0,
        target_price=173600.0,
        target_points=400.0,
        risk_reward=1.60,
        timeframe_trigger=2,
        in_trend_direction=True,
        structure_event="Toque milimétrico no 50% CE do FVG de 15m (173.200) com absorção de venda",
        obstacles=[
            "PASSAGEM TOTALMENTE LIVRE: Nenhum obstáculo institucional contrário até o alvo (400 pts livres até 173.600)"
        ],
        facts_observed=[
            "Preço atual: 173.200 (Região SMC Discount — Fundo da Sessão)",
            "Radar FVG: Preço testando exatamente o centro de equilíbrio (50% CE: 173.200) do gap de 15m",
            "Tape Reading: Vendedores agrediram 540 contratos a mercado em 173.150 e o preço NÃO caiu (Absorção de Fundo)",
            "Contra-ataque Institucional: Compradores entraram com 780ct@173160 e 1.120ct@173200 pagando spread",
            "DELTA: +9.400 contratos de pressão compradora líquida (Delta violentamente positivo e ascendente)",
            "Deslocamento: Reação imediata de +95 pontos na janela de 60 segundos"
        ],
        interpretations=[
            "CENÁRIO PERFEITO DE COMPRA (GABARITO INSTITUCIONAL SMC + TAPE READING).",
            "Executar imediatamente no SuperDOM na Coluna Azul (173.200).",
            "Alvo integral de 400 pontos em 173.600 com possibilidade de extensão de alvo até 174.000."
        ],
        limitations=["Oscilação padrão de pregão em teste de FVG macro"],
        invalidation_criteria="Perda do suporte institucional em 172.950"
    )

    alert_text = format_operational_alert(
        setup=setup_compra,
        regimes=regimes,
        source_name="Nelogica ProfitPro (DDE)",
        delay_ms=0.3,
        quality_status="ÍNTEGRO (FLUXO + ESTRUTURA)",
        flow_data=flow_data,
        fvg_radar_banner=fvg_banner
    )

    print(alert_text)
    exibir_guia_didatico("COMPRA")


def simular_cenario_venda():
    """Simulação do Cenário Perfeito de Venda (Muro de Absorção no Topo + Contra-Ataque Vendedor)."""
    now = datetime.now(TZ_BRASILIA)
    symbol = get_current_win_contract()

    emitir_apitos("VENDA")
    time.sleep(0.15)

    # 1. Configurar Radar FVG de Resistência
    scanner = FGVMTFScanner()
    fvg_resistencia = ActiveMTFFVG(
        timeframe=15,
        direction="BEARISH",
        top=174300.0,
        bottom=173700.0,
        ce_50=173800.0,
        formed_time=now - timedelta(minutes=40)
    )
    scanner.active_fvgs[15].append(fvg_resistencia)

    fvg_alert = FVGApproachAlert(
        fvg=fvg_resistencia,
        current_price=173750.0,
        distance_to_zone=0.0,
        distance_to_ce=50.0,
        is_inside_zone=True,
        action_direction="VENDA",
        zone_start=173700.0,
        zone_end=174300.0
    )
    fvg_banner = scanner.format_power_shell_alert(fvg_alert, use_color=True)

    # 2. Matriz de Tendência Multi-Timeframe
    regimes = {
        "240m": "BAIXA",
        "60m" : "BAIXA",
        "30m" : "BAIXA",
        "15m" : "BAIXA",
        "10m" : "BAIXA",
        "5m"  : "BAIXA",
        "2m"  : "BAIXA",
        "1m"  : "BAIXA"
    }

    # 3. Métricas Determinísticas de Tape Reading
    flow_data = {
        "buy_volume": 7200,
        "sell_volume": 18500,
        "delta": -11300,
        "large_trades": [
            {"qty": 890, "price": 173800.0, "side": "BUY"},   # Compra absorvida no topo
            {"qty": 420, "price": 173800.0, "side": "SELL"},  # Defesa imediata no mesmo preço
            {"qty": 1250, "price": 173750.0, "side": "SELL"}  # Marretada vendedora varrendo ofertas
        ],
        "price_displacement_pts": -110.0,
        "flow_pattern": "Absorção Vendedora de Topo (890ct contidos) seguida de Exaustão Compradora e Agressão Vendedora"
    }

    # 4. Setup Estrutural
    setup_venda = SignalSetup(
        timestamp=now,
        setup_name="Venda por Defesa Institucional no Topo (Tape Reading + Reteste 50% CE FVG 15m)",
        direction=Direction.VENDA,
        symbol=symbol,
        status=SetupStatus.CONFIRMADO,
        entry_price=173750.0,
        stop_price=174000.0,
        stop_points=250.0,
        target_price=173350.0,
        target_points=400.0,
        risk_reward=1.60,
        timeframe_trigger=2,
        in_trend_direction=True,
        structure_event="Reteste na zona de 50% CE da Resistência de 15m (173.800) com absorção de topo",
        obstacles=[
            "PASSAGEM TOTALMENTE LIVRE: Nenhum obstáculo institucional contrário até o alvo (400 pts livres até 173.350)"
        ],
        facts_observed=[
            "Preço atual: 173.750 (Região SMC Premium — Topo da Sessão)",
            "Radar FVG: Preço testando a zona de rejeição e 50% CE da Resistência Institucional (173.800)",
            "Tape Reading: Compradores eufóricos tomaram 890 contratos a mercado em 173.800 e o preço NÃO subiu (Absorção de Topo)",
            "Defesa Institucional: Vendedor bateu 420ct no mesmo preço (173.800) e despejou 1.250ct@173750 limpando o Book",
            "DELTA: -11.300 contratos de pressão vendedora líquida (Delta fortemente negativo e afundando)",
            "Deslocamento: Queda imediata de -110 pontos nos últimos 60 segundos"
        ],
        interpretations=[
            "CENÁRIO PERFEITO DE VENDA (GABARITO INSTITUCIONAL SMC + TAPE READING).",
            "Executar imediatamente no SuperDOM na Coluna Vermelha (173.750).",
            "Alvo integral de 400 pontos em 173.350 com busca de liquidez nos fundos do dia."
        ],
        limitations=["Não manter operação se o preço romper e fechar acima de 173.850"],
        invalidation_criteria="Superação da barreira absorvida em 174.000"
    )

    alert_text = format_operational_alert(
        setup=setup_venda,
        regimes=regimes,
        source_name="Nelogica ProfitPro (DDE)",
        delay_ms=0.4,
        quality_status="ÍNTEGRO (FLUXO + ESTRUTURA)",
        flow_data=flow_data,
        fvg_radar_banner=fvg_banner
    )

    print(alert_text)
    exibir_guia_didatico("VENDA")


def main():
    arg = sys.argv[1].lower() if len(sys.argv) > 1 else "todos"

    if arg in ("compra", "buy", "c", "1"):
        simular_cenario_compra()
    elif arg in ("venda", "sell", "v", "2"):
        simular_cenario_venda()
    else:
        print(f"\n{Fore.MAGENTA}{Style.BRIGHT}======================================================================{Style.RESET_ALL}")
        print(f"{Fore.MAGENTA}{Style.BRIGHT}   EXIBIÇÃO DOS DOIS MELHORES CENÁRIOS INSTITUCIONAIS (COMPRA & VENDA)  {Style.RESET_ALL}")
        print(f"{Fore.MAGENTA}{Style.BRIGHT}======================================================================{Style.RESET_ALL}\n")
        simular_cenario_compra()
        print("\n" + f"{Fore.CYAN}{Style.BRIGHT}Pressione Enter para visualizar o Cenário Perfeito de Venda...{Style.RESET_ALL}")
        try:
            input()
        except Exception:
            time.sleep(1.5)
        simular_cenario_venda()


if __name__ == "__main__":
    main()
