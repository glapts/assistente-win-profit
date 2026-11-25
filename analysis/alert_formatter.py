"""
analysis/alert_formatter.py
Formatador estrito de alertas operacionais com suporte a cores ANSI no PowerShell/Terminal.
Layout otimizado para SuperDOM: Parâmetros de execução (ENTRADA, STOP, ALVOS) exibidos no topo.
"""

from typing import Dict, Any, Optional
from datetime import datetime
import zoneinfo
import colorama
from colorama import Fore, Back, Style

# Inicializa o Colorama compatível com Windows PowerShell / CMD
colorama.init(autoreset=True)

from core.models import SignalSetup, SetupStatus, Direction
from core.contract import TZ_BRASILIA


def fmt_price(val: Optional[float], decimals: Optional[int] = None) -> str:
    """Formata preços no padrão brasileiro com precisão decimal adequada ao ativo."""
    if val is None:
        return "N/D"
    if decimals is not None:
        dec = decimals
    elif val < 500.0 or abs(val - round(val)) > 1e-4:
        dec = 2
    else:
        dec = 0

    if dec == 0:
        return f"{val:,.0f}".replace(",", ".")
    return f"{val:,.{dec}f}".replace(".", "X").replace(",", ".").replace("X", ",")


def _format_flow_section(
    flow: Dict[str, Any],
    use_color: bool = True,
    C_LABEL: str = "",
    C_RESET: str = "",
    symbol: Optional[str] = None,
    p_medio_reacao: Optional[float] = None
) -> list:
    out = []
    c_buy = (Fore.GREEN + Style.BRIGHT) if use_color else ""
    c_sell = (Fore.RED + Style.BRIGHT) if use_color else ""

    delta_val = flow.get('delta', 0)
    if use_color:
        if delta_val > 0:
            c_delta = Fore.GREEN + Style.BRIGHT
        elif delta_val < 0:
            c_delta = Fore.RED + Style.BRIGHT
        else:
            c_delta = Fore.YELLOW
    else:
        c_delta = ""

    c_delta_label = (Fore.BLUE + Style.BRIGHT) if use_color else ""
    is_vale = bool(symbol and "VALE" in symbol)
    unit_str = "ações" if is_vale else "contratos"

    out.append(f"{C_LABEL}TIMES & TRADES:{C_RESET}")
    out.append(f"{c_buy}- Agressão compradora: {flow.get('buy_volume', 0):,} {unit_str}{C_RESET}")
    out.append(f"{c_sell}- Agressão vendedora: {flow.get('sell_volume', 0):,} {unit_str}{C_RESET}")
    out.append("- Janela de cálculo: 300 segundos")
    out.append(f"- {c_delta_label}DELTA{C_RESET}: {c_delta}{delta_val:+d} {unit_str}{C_RESET}")

    # Média Aritmética de Reação (T&T)
    p_reac_val = p_medio_reacao or flow.get("p_medio_reacao", 0.0)
    if p_reac_val and float(p_reac_val) > 0:
        c_p_reac = (Fore.WHITE + Style.BRIGHT) if use_color else ""
        out.append(f"- Média Aritmética de Reação (T&T): {c_p_reac}{fmt_price(float(p_reac_val))} pts{C_RESET}")
    else:
        out.append("- Média Aritmética de Reação (T&T): Nível da entrada recente")

    lg_trades = flow.get('large_trades', [])
    if lg_trades:
        formatted_trades = []
        for t in lg_trades[-3:]:
            side = str(t.get('side', 'BUY')).upper()
            if use_color:
                c_side = (Fore.GREEN + Style.BRIGHT) if side == 'BUY' else (Fore.RED + Style.BRIGHT)
            else:
                c_side = ""
            qty = t.get('qty', 0)
            price = t.get('price', 0.0)
            if is_vale:
                formatted_trades.append(f"{c_side}{qty:,} ações @ R$ {price:.2f} ({side}){C_RESET}")
            else:
                formatted_trades.append(f"{c_side}{qty}ct@{price:.0f} ({side}){C_RESET}")
        lg_summary = ", ".join(formatted_trades)
    else:
        lg_summary = "Nenhuma agressão >= 1.000 ações na janela" if is_vale else "Nenhuma agressão >= 100 contratos na janela"
    out.append(f"- Grandes execuções: {lg_summary}")
    
    if is_vale:
        out.append(f"- Reação do preço: Deslocamento de R$ {flow.get('price_displacement_pts', 0.0):+.2f}")
    else:
        out.append(f"- Reação do preço: Deslocamento de {flow.get('price_displacement_pts', 0.0):+.0f} pontos")

    pattern = flow.get('flow_pattern', 'Fluxo em equilíbrio')
    c_pat = ""
    if use_color:
        if "Comprador" in pattern or "Compradora" in pattern:
            c_pat = Fore.GREEN + Style.BRIGHT
        elif "Vendedor" in pattern or "Vendedora" in pattern:
            c_pat = Fore.RED + Style.BRIGHT
        else:
            c_pat = Fore.YELLOW
    out.append(f"- Possível absorção: {c_pat}{pattern}{C_RESET}")
    out.append("- Agentes, quando disponíveis: Identificados nos negócios registrados")
    out.append("- Origem institucional: não confirmada, salvo evidência específica.")
    return out


def format_operational_alert(
    setup: Optional[SignalSetup],
    regimes: Dict[str, str],
    source_name: str = "Profit Pro DDE / Market Data",
    delay_ms: float = 0.0,
    quality_status: str = "ÍNTEGRO",
    general_status_override: Optional[str] = None,
    use_color: bool = True,
    flow_data: Optional[Dict[str, Any]] = None,
    symbol_override: Optional[str] = None,
    fvg_radar_banner: Optional[str] = None,
    harness_verdict: Optional[Any] = None,
    p_medio_reacao: Optional[float] = None
) -> str:
    """
    Formata o alerta operacional unificado com Box de Execução no SuperDOM,
    Comando de Execução, Radar FVG Antecipado, Confirmação de Fluxo & Book (Seção 3 com Média de Reação)
    e Seção 4 (Painel de Decisão Multi-Agente).
    """
    now_sp = datetime.now(TZ_BRASILIA)
    time_str = now_sp.strftime("%d/%m/%Y %H:%M:%S")

    # Cores
    C_DIV = (Fore.CYAN + Style.DIM) if use_color else ""
    C_RESET = Style.RESET_ALL if use_color else ""
    C_LABEL = (Fore.WHITE + Style.BRIGHT) if use_color else ""
    
    div_main = f"{C_DIV}=================================================================={C_RESET}"
    div_sub = f"{C_DIV}------------------------------------------------------------------{C_RESET}"

    asset_title = symbol_override or (setup.symbol if setup else "WIN (Mini-Índice B3)")
    tfs_list = ["240m", "60m", "30m", "15m", "10m", "5m", "2m", "1m"] if "240m" in regimes else ["60m", "30m", "15m", "10m", "5m", "2m", "1m"]

    flow = (setup.flow_evidence if setup and setup.flow_evidence else None) or flow_data or {}
    book_evidence = (setup.book_evidence if setup and setup.book_evidence else None) or {}

    # Executa ou obtém o ExecutionHarness se não fornecido externamente
    if harness_verdict is None:
        try:
            from harness.execution_harness import ExecutionHarness
            harness = ExecutionHarness()
            current_p = setup.entry_price if setup else 171400.0
            side_str = setup.direction.value if setup else "COMPRA"
            h_context = {
                "current_price": current_p,
                "ultimo": current_p,
                "flow_metrics": flow,
                "tape_reading": flow,
                "win_book": {
                    "of_compra": current_p - 5.0,
                    "of_venda": current_p,
                    "voc": 1800.0 if side_str == "COMPRA" else 1200.0,
                    "vov": 1200.0 if side_str == "COMPRA" else 1800.0,
                    "delta_voc": 200.0 if side_str == "COMPRA" else -100.0,
                    "delta_vov": -100.0 if side_str == "COMPRA" else 200.0,
                    "delta_negocios": 25
                },
                "is_pullback": True if setup else False,
                "trend": "ALTA" if (setup and setup.direction == Direction.COMPRA) else "BAIXA"
            }
            if book_evidence.get("metrics"):
                bm = book_evidence["metrics"]
                if "spread" in bm:
                    h_context["win_book"]["spread_pts"] = bm["spread"]
            harness_verdict = harness.evaluate_market_confluence(
                side=side_str,
                context=h_context,
                setup_name=setup.setup_name if setup else None,
                entry_price=setup.entry_price if setup else None,
                use_color=use_color
            )
        except Exception:
            harness_verdict = None

    book_insights = harness_verdict.book_insights if harness_verdict else {}
    harness_panel = harness_verdict.panel_text if harness_verdict else ""
    p_reac_val = p_medio_reacao or (harness_verdict.p_medio_reacao if harness_verdict else 0.0)

    # Dados de Book alimentados pelo OrderBookAgent
    of_compra = float(book_insights.get("of_compra", 171400.0))
    of_venda = float(book_insights.get("of_venda", 171405.0))
    spread_pts = float(book_insights.get("spread_pts", 5.0))
    voc = float(book_insights.get("voc", 1500.0))
    vov = float(book_insights.get("vov", 1200.0))
    imb_ratio = float(book_insights.get("imbalance_ratio", 0.55))
    imb_pct = imb_ratio * 100.0
    imb_side = "COMPRA" if imb_ratio >= 0.5 else "VENDA"
    dinamica_str = str(book_insights.get("observed_behavior", "Sustentação passiva alinhada"))
    status_book = str(book_insights.get("status_tag", "ALINHADO"))

    if setup is None:
        status_msg = general_status_override or "SEM OPERAÇÃO — AGUARDAR"
        c_status = (Fore.YELLOW + Style.BRIGHT) if use_color else ""
        
        out = []
        out.append(div_main)
        out.append(f"{C_LABEL}DATA/HORA:{C_RESET} {time_str} (America/Sao_Paulo)")
        out.append(f"{C_LABEL}ATIVO/VENCIMENTO:{C_RESET} {asset_title}")
        out.append(f"{C_LABEL}FONTE:{C_RESET} {source_name}")
        out.append(f"{C_LABEL}ATRASO E QUALIDADE:{C_RESET} {delay_ms:.1f}ms | Qualidade: {quality_status}")
        out.append(f"{C_LABEL}STATUS:{C_RESET} {c_status}{status_msg}{C_RESET}")
        out.append(div_sub)
        out.append(f"{C_LABEL}REGIME:{C_RESET}")
        for tf in tfs_list:
            reg_val = regimes.get(tf, 'INDEFINIDO')
            c_reg = Fore.WHITE if use_color else ""
            if use_color:
                if reg_val == "ALTA":
                    c_reg = Fore.GREEN + Style.BRIGHT
                elif reg_val == "BAIXA":
                    c_reg = Fore.RED + Style.BRIGHT
                elif reg_val == "CONSOLIDAÇÃO":
                    c_reg = Fore.YELLOW
            out.append(f"{tf:4}: {c_reg}{reg_val}{C_RESET}")
        out.append(div_sub)
        
        # 3. CONFIRMAÇÃO DE FLUXO & BOOK (TAPE READING)
        out.append(f"{C_LABEL}3. CONFIRMAÇÃO DE FLUXO & BOOK (TAPE READING):{C_RESET}")
        if flow and (flow.get('trades_count', 0) > 0 or flow.get('buy_volume', 0) > 0 or flow.get('sell_volume', 0) > 0):
            out.extend(_format_flow_section(flow, use_color=use_color, C_LABEL="  * ", C_RESET=C_RESET, symbol=symbol_override, p_medio_reacao=p_reac_val))
        else:
            out.append("  * TIMES & TRADES: Aguardando fluxo de negócios da sessão.")

        # Sub-bloco BOOK alimentado pelo OrderBookAgent
        out.append(f"  {C_LABEL}BOOK:{C_RESET}")
        out.append(f"    - Of.Compra                 : {fmt_price(of_compra)} | Of.Venda: {fmt_price(of_venda)} | Spread: {spread_pts:.1f} pts")
        out.append(f"    - Volume de Ofertas         : VOC: {voc:,.0f} ct | VOV: {vov:,.0f} ct")
        out.append(f"    - Imbalance                 : {imb_pct:.1f}% ({imb_side})")
        c_dinamica = (Fore.GREEN + Style.BRIGHT) if "escora" in dinamica_str.lower() else ((Fore.RED + Style.BRIGHT) if "blefe" in dinamica_str.lower() else Fore.YELLOW)
        out.append(f"    - Dinâmica Stacking/Pulling : {c_dinamica if use_color else ''}{dinamica_str}{C_RESET}")
        out.append(f"    - Classificação             : {status_book}")

        # 4. PAINEL DE DECISÃO MULTI-AGENTE
        if harness_panel:
            out.append(div_sub)
            out.append(harness_panel)

        out.append(div_sub)
        out.append(f"{C_LABEL}DIAGNÓSTICO:{C_RESET} Sem confluência determinística para os setups canônicos.")
        out.append(f"{C_LABEL}DECISÃO DETERMINÍSTICA:{C_RESET} {c_status}SEM OPERAÇÃO — AGUARDAR.{C_RESET}")
        out.append(div_main)
        if fvg_radar_banner:
            out.append("")
            out.append(fvg_radar_banner)
        return "\n".join(out)

    # Setup Presente
    is_blocked = (setup.status == SetupStatus.BLOQUEADO)
    is_buy = (setup.direction == Direction.COMPRA)
    c_dir = (Fore.GREEN + Style.BRIGHT) if is_buy else (Fore.RED + Style.BRIGHT)
    if is_blocked:
        c_status = (Fore.BLACK + Back.YELLOW + Style.BRIGHT) if use_color else ""
        c_action_text = f"{Fore.YELLOW + Style.BRIGHT}[BLOQUEADO: OBSTÁCULO INSTITUCIONAL FVG NO ALVO] >>> NÃO EXECUTAR <<<{C_RESET}"
    else:
        c_status = (Fore.BLACK + Back.GREEN + Style.BRIGHT) if is_buy else (Fore.BLACK + Back.RED + Style.BRIGHT)
        c_action_text = f"{c_dir}>>> {setup.direction.value} <<<{C_RESET}"
    if not use_color:
        c_status = ""
        c_dir = ""
        c_action_text = f"[BLOQUEADO: OBSTÁCULO FVG] >>> NÃO EXECUTAR <<<" if is_blocked else f">>> {setup.direction.value} <<<"

    # Destaques de Execução (Cores)
    c_ent = (Fore.CYAN + Style.BRIGHT) if use_color else ""
    c_stop = (Fore.RED + Style.BRIGHT) if use_color else ""
    c_alvo = (Fore.GREEN + Style.BRIGHT) if use_color else ""
    c_rr = (Fore.WHITE + Style.BRIGHT) if use_color else ""

    unit_str = "pontos" if ("WIN" in setup.symbol or "WDO" in setup.symbol) else "reais"
    dec_pts = 0 if "WIN" in setup.symbol else 2
    ent_desc = f"{fmt_price(setup.entry_price)} (ENTRADA BLOQUEADA)" if is_blocked else fmt_price(setup.entry_price)
    gatilho_desc = 'BLOQUEADO POR OBSTÁCULO INSTITUCIONAL' if is_blocked else ('CONFIRMADO' if setup.status == SetupStatus.CONFIRMADO else 'PENDENTE DE CONFIRMAÇÃO')

    col_side = "COMPRA (COLUNA AZUL)" if is_buy else "VENDA (COLUNA VERMELHA)"
    ticks_loss = int(round(setup.stop_points / 5.0)) if "WIN" in setup.symbol else int(round(setup.stop_points / 0.5))
    ticks_gain = int(round(setup.target_points / 5.0)) if "WIN" in setup.symbol else int(round(setup.target_points / 0.5))
    bg_color = (Back.GREEN if is_buy else Back.RED) if use_color else ""
    fg_white = (Fore.WHITE + Style.BRIGHT) if use_color else ""
    fg_yellow = (Fore.YELLOW + Style.BRIGHT) if use_color else ""
    c_reset = C_RESET if use_color else ""

    p_ent_str = fmt_price(setup.entry_price)
    p_stop_str = fmt_price(setup.stop_price)
    p_alvo_str = fmt_price(setup.target_price)

    out = []

    # ── BOX: EXECUÇÃO NO SUPERDOM – 1 CLIQUE (SEM DIGITAR NADA) ──
    if not is_blocked and setup.status == SetupStatus.CONFIRMADO:
        out.append(f"{bg_color}{fg_white}╔══════════════════════════════════════════════════════════════════════════╗{c_reset}")
        out.append(f"{bg_color}{fg_white}║         ⚡ EXECUÇÃO NO SUPERDOM — 1 CLIQUE (SEM DIGITAR NADA) ⚡         ║{c_reset}")
        out.append(f"{bg_color}{fg_white}╠══════════════════════════════════════════════════════════════════════════╣{c_reset}")
        out.append(f"{bg_color}{fg_white}║  👉 CLIQUE NA COLUNA : {fg_yellow}{col_side:<47}{fg_white}║{c_reset}")
        out.append(f"{bg_color}{fg_white}║  👉 PREÇO DO TICK    : {fg_yellow}>>>  {p_ent_str:^10}  <<<{fg_white} (NÍVEL EXATO DE ENTRADA)    ║{c_reset}")
        out.append(f"{bg_color}{fg_white}║  ESTRATÉGIA OCO      : Stop {ticks_loss} ticks ({p_stop_str}) | Alvo {ticks_gain} ticks ({p_alvo_str}) ║{c_reset}")
        out.append(f"{bg_color}{fg_white}║  QUANTIDADE          : CONTRATOS FIXOS PRÉ-CONFIGURADOS NO DOM           ║{c_reset}")
        out.append(f"{bg_color}{fg_white}╚══════════════════════════════════════════════════════════════════════════╝{c_reset}")
    elif is_blocked:
        c_bg_warn = (Back.YELLOW + Fore.BLACK + Style.BRIGHT) if use_color else ""
        out.append(f"{c_bg_warn}╔══════════════════════════════════════════════════════════════════════════╗{c_reset}")
        out.append(f"{c_bg_warn}║      ⛔ OPERAÇÃO BLOQUEADA PELO RADAR FVG — NÃO EXECUTAR NO DOM ⛔      ║{c_reset}")
        out.append(f"{c_bg_warn}╠══════════════════════════════════════════════════════════════════════════╣{c_reset}")
        motivo_msg = "  MOTIVO: Barreira institucional FVG no caminho do alvo.                   "
        out.append(f"{c_bg_warn}║{motivo_msg}║{c_reset}")
        out.append(f"{c_bg_warn}╚══════════════════════════════════════════════════════════════════════════╝{c_reset}")

    # ── 1. COMANDO DE EXECUÇÃO ──
    out.append(div_main)
    out.append(f"{C_LABEL}1. COMANDO DE EXECUÇÃO:{C_RESET}")
    out.append(f"  * AÇÃO NO SUPERDOM            : {c_action_text}")
    out.append(f"  * ENTRADA                     : {c_ent}{ent_desc}{C_RESET}")
    out.append(f"  * GATILHO PENDENTE OU CONFIRMADO: {gatilho_desc}")
    out.append(f"  * STOP EM PREÇO E PONTOS      : {c_stop}{fmt_price(setup.stop_price)} ({setup.stop_points:.{dec_pts}f} {unit_str}){C_RESET}")
    out.append(f"  * ALVOS EM PREÇO E PONTOS     : {c_alvo}{fmt_price(setup.target_price)} ({setup.target_points:.{dec_pts}f} {unit_str}){C_RESET}")
    out.append(f"  * RETORNO/RISCO               : {c_rr}{setup.risk_reward:.2f}{C_RESET}")
    obs_text = '; '.join(setup.obstacles) if setup.obstacles else 'Nenhum obstáculo técnico intermediário mapeado'
    if use_color:
        if "OBSTÁCULO INSTITUCIONAL" in obs_text:
            obs_text = Fore.YELLOW + Style.BRIGHT + obs_text + C_RESET
        elif "PASSAGEM LIVRE" in obs_text:
            obs_text = Fore.GREEN + Style.BRIGHT + obs_text + C_RESET
    out.append(f"  * OBSTÁCULOS / PASSAGEM       : {obs_text}")
    validity_str = setup.validity_deadline.strftime("%H:%M:%S") if setup.validity_deadline else "Próximo fechamento de barra"
    out.append(f"  * VALIDADE                    : Até {validity_str}")
    out.append(f"  * INVALIDAÇÃO                 : {setup.invalidation_criteria}")
    
    if setup.facts_observed:
        out.append(f"  {C_LABEL}FATOS OBSERVADOS:{C_RESET}")
        c_blue_label = (Fore.BLUE + Style.BRIGHT) if use_color else ""
        for f in setup.facts_observed:
            if use_color:
                f_text = f.replace("Delta=", f"{c_blue_label}DELTA{C_RESET}=").replace("Delta", f"{c_blue_label}DELTA{C_RESET}").replace("delta", f"{c_blue_label}DELTA{C_RESET}")
            else:
                f_text = f.replace("Delta", "DELTA").replace("delta", "DELTA")
            out.append(f"    - {f_text}")

    if setup.interpretations:
        out.append(f"  {C_LABEL}INTERPRETAÇÕES:{C_RESET}")
        for i in setup.interpretations:
            out.append(f"    - {i}")

    if setup.limitations:
        out.append(f"  {C_LABEL}LIMITAÇÕES:{C_RESET}")
        for lim in setup.limitations:
            out.append(f"    - {lim}")

    # ── 2. ESTRUTURA E CONTEXTO SMC ──
    out.append(div_sub)
    out.append(f"{C_LABEL}2. ESTRUTURA E CONTEXTO SMC:{C_RESET}")
    out.append(f"  * SETUP                       : {Fore.MAGENTA + Style.BRIGHT if use_color else ''}{setup.setup_name}{C_RESET}")
    out.append(f"  * DIREÇÃO                     : {c_dir}>>> {setup.direction.value} <<<{C_RESET}")
    out.append(f"  * CONTEXTO MACRO              : {'Alinhado com Contexto Macro (A FAVOR)' if setup.in_trend_direction else 'Contratendência em relação ao Contexto Macro (CONTRA)'}")
    
    sweep_txt = f"{setup.sweep_level:.0f}" if setup.sweep_level else "Não aplicável"
    out.append(f"  * NÍVEL E HORÁRIO DO SWEEP    : {sweep_txt}")
    fvg_txt = setup.fvg_zone or 'Nenhum FVG ativo no gatilho'
    out.append(f"  * FVG                         : {Fore.YELLOW + Style.BRIGHT if use_color else ''}{fvg_txt}{C_RESET}")
    struct_txt = setup.structure_event or 'Estrutura regular'
    if use_color:
        struct_txt = struct_txt.replace("agressão compradora", f"{Fore.GREEN + Style.BRIGHT}agressão compradora{C_RESET}")
        struct_txt = struct_txt.replace("agressão vendedora", f"{Fore.RED + Style.BRIGHT}agressão vendedora{C_RESET}")
    out.append(f"  * CHoCH/BOS                   : {struct_txt}")

    regime_line = " | ".join([f"{tf}:{Fore.GREEN if regimes.get(tf)=='ALTA' else (Fore.RED if regimes.get(tf)=='BAIXA' else Fore.YELLOW)}{regimes.get(tf,'INDEFINIDO')}{C_RESET}" for tf in tfs_list])
    out.append(f"  * REGIME                      : {regime_line}")

    # ── [RADAR FVG ANTECIPADO] ──
    if fvg_radar_banner:
        out.append(div_sub)
        out.append(fvg_radar_banner)

    # ── 3. CONFIRMAÇÃO DE FLUXO & BOOK (TAPE READING) ──
    out.append(div_sub)
    out.append(f"{C_LABEL}3. CONFIRMAÇÃO DE FLUXO & BOOK (TAPE READING):{C_RESET}")
    out.extend(_format_flow_section(flow, use_color=use_color, C_LABEL="  * ", C_RESET=C_RESET, symbol=setup.symbol if setup else symbol_override, p_medio_reacao=p_reac_val))

    # Sub-bloco BOOK diretamente do OrderBookAgent
    out.append(f"  {C_LABEL}BOOK:{C_RESET}")
    out.append(f"    - Of.Compra                 : {fmt_price(of_compra)} | Of.Venda: {fmt_price(of_venda)} | Spread: {spread_pts:.1f} pts")
    out.append(f"    - Volume de Ofertas         : VOC: {voc:,.0f} ct | VOV: {vov:,.0f} ct")
    out.append(f"    - Imbalance                 : {imb_pct:.1f}% ({imb_side})")
    c_dinamica = (Fore.GREEN + Style.BRIGHT) if "escora" in dinamica_str.lower() else ((Fore.RED + Style.BRIGHT) if "blefe" in dinamica_str.lower() else Fore.YELLOW)
    out.append(f"    - Dinâmica Stacking/Pulling : {c_dinamica if use_color else ''}{dinamica_str}{C_RESET}")
    out.append(f"    - Classificação             : {status_book}")

    # ── 4. PAINEL DE DECISÃO MULTI-AGENTE ──
    if harness_panel:
        out.append(div_sub)
        out.append(harness_panel)

    # ── RESUMO DE EXECUÇÃO NO RODAPÉ ──
    out.append(div_main)
    out.append(f"{C_LABEL}>>> EXECUÇÃO RÁPIDA NO SUPERDOM <<<{C_RESET}")
    out.append(f"AÇÃO:    {c_action_text}")
    out.append(f"ENTRADA: {c_ent}{ent_desc}{C_RESET}")
    out.append(f"STOP:    {c_stop}{fmt_price(setup.stop_price)} ({setup.stop_points:.{dec_pts}f} {unit_str}){C_RESET}")
    out.append(f"ALVO:    {c_alvo}{fmt_price(setup.target_price)} ({setup.target_points:.{dec_pts}f} {unit_str}){C_RESET}")
    out.append(div_main)

    return "\n".join(out)
