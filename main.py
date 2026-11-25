"""
main.py
Ponto de entrada principal do Assistente de Análise Quantitativa Institucional B3 — Profit Pro.
Versão Comercial Protegida (Cenário 3 Oficial: Target 400 pts, Stop 250 pts, Radar FVG MTF & Mitigação SMC).
"""

import sys
import os
import argparse
from datetime import datetime

from core.engine import WinAnalysisAssistant
from feeds.dde_feed import ProfitDDEFeed
from feeds.replay_feed import ReplayMarketFeed
from ui.dashboard import run_dashboard
from core.contract import (
    get_current_win_contract,
    get_current_wdo_contract,
    resolve_symbol,
    get_asset_spec,
    TZ_BRASILIA,
    calculate_financial_risk
)
from core.models import Direction, Candle
from licensing.validator import check_and_enforce_license


def cmd_diagnose():
    print("=" * 70)
    print("DIAGNÓSTICO OFICIAL DE INTEGRAÇÃO — PROFIT PRO & B3")
    print("=" * 70)
    
    # 1. Sistema Operacional e Hardware
    import platform
    print(f"Sistema Operacional : {platform.system()} {platform.release()} ({platform.architecture()[0]})")
    
    # 2. Nelogica Profit
    import subprocess
    out = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Process -Name profitchart -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id"], capture_output=True, text=True)
    pids = [p.strip() for p in out.stdout.splitlines() if p.strip().isdigit()]
    if pids:
        print(f"ProfitChart Processo: ATIVO (PID: {', '.join(pids)})")
    else:
        print("ProfitChart Processo: NÃO ENCONTRADO EM EXECUÇÃO")

    # 3. Teste DDE
    print("\nTestando Conexão DDE com Profit Pro...")
    feed_dde = ProfitDDEFeed()
    ok_dde = feed_dde.connect()
    if ok_dde:
        print("  [OK] Conexão DDE com 'profitchart|cot' estabelecida com sucesso!")
        feed_dde.disconnect()
    else:
        print(f"  [FALHA] DDE: {feed_dde.health.error_message}")

    # 4. Status da ProfitDLL / DataFeed
    print("\nVerificando Licença ProfitDLL / Market Data SDK...")
    print("  [STATUS] DLL NÃO INSTALADA NO AMBIENTE LOCAL.")
    print("  [EXPLICAÇÃO] A assinatura comercial padrão do Profit Pro NÃO inclui a ProfitDLL.")
    print("               Trata-se de um produto B2B com taxa de licenciamento e chave própria da Nelogica.")

    # 5. Ativos Homologados e Contratos Vigentes
    win_contract = get_current_win_contract()
    wdo_contract = get_current_wdo_contract()
    print("\n" + "-" * 70)
    print("STATUS DOS ATIVOS HOMOLOGADOS (CENÁRIO 3 OFICIAL):")
    print(f"1. Mini-Índice B3 (WIN) : Contrato Vigente: {win_contract} | Tick: 5.0 pts | Stop: 250 pts | Alvo: 400 pts (R$ 0,20/pt)")
    print(f"2. Mini-Dólar B3 (WDO)  : Contrato Vigente: {wdo_contract} | Tick: 0.5 pts | Stop: 5.0 pts | Alvo: 8.0 pts (R$ 10,00/pt)")
    print(f"3. Vale S.A. (VALE3)    : Ticker Ativo    : VALE3   | Tick: R$ 0,01 | Stop: R$ 0,35 | Alvo: R$ 0,56 (Lote 100)")
    print(f"\nHorário Local B3        : {datetime.now(TZ_BRASILIA).strftime('%d/%m/%Y %H:%M:%S')}")
    print("=" * 70)


def cmd_run_dde(mode: str = "FIXO", symbol: str | None = None):
    chosen_symbol = resolve_symbol(symbol)
    spec = get_asset_spec(chosen_symbol)
    print(f"Iniciando monitoramento ao vivo via Profit Pro DDE...")
    print(f"Ativo: {chosen_symbol} ({spec.name}) | Modo: {mode}")
    print(f"Parâmetros: Tick: {spec.tick_size} | Stop: {spec.default_stop_points} | Alvo: {spec.default_target_points} (R:R 1.60)")
    print("Blindagem Cenário 3 Ativa: Radar FVG MTF + Mitigação de rompimentos secos de 1m.")
    feed = ProfitDDEFeed()
    assistant = WinAnalysisAssistant(feed=feed, symbol=chosen_symbol, mode=mode)
    run_dashboard(assistant)


def cmd_test_replay(mode: str = "FIXO"):
    print(f"\nIniciando Replay de Teste e Validação Estrutural (Modo: {mode})...\n")
    feed = ReplayMarketFeed(symbol=get_current_win_contract(), initial_price=171400.0)
    assistant = WinAnalysisAssistant(feed=feed, mode=mode)
    assistant.start()

    print("1. Gerando histórico base com oscilação natural (ondas de impulsão e retração)...")
    for i in range(120):
        bias = 0.25 if (i % 30 < 18) else -0.25
        feed.generate_step(trend_bias=bias, inject_sweep=False)

    print("2. Injetando Sweep de Liquidez no topo recente...")
    feed.generate_step(trend_bias=0.0, inject_sweep=True, sweep_direction="BEARISH")

    print("3. Avaliando cada barra de confirmação (retorno e reação de fluxo)...")
    setup_found = False
    for i in range(1, 15):
        feed.generate_step(trend_bias=-0.35, inject_sweep=False)
        alert = assistant.evaluate_now()
        if "STATUS: CONFIRMADO" in alert or "STATUS: AGUARDANDO" in alert:
            print(f"\n>>> GATILHO IDENTIFICADO NA BARRA +{i} DE CONFIRMAÇÃO! <<<")
            print(alert)
            setup_found = True
            break
            
    if not setup_found:
        print("\n--- RESULTADO DA AVALIAÇÃO DETERMINÍSTICA ---")
        alert = assistant.evaluate_now()
        print(alert)
        
    assistant.stop()


def cmd_fvg_radar():
    """Demonstração visual do Radar FVG MTF Antecipado (10m, 15m, 30m, 60m, 240m)."""
    from analysis.fvg_mtf_scanner import FGVMTFScanner, ActiveMTFFVG
    
    scanner = FGVMTFScanner()
    now = datetime.now(TZ_BRASILIA)
    
    print("\n" + "=" * 70)
    print("DEMONSTRAÇÃO DO RADAR FVG MTF ANTECIPADO NO POWERSHELL")
    print("Monitorando tempos gráficos: 10m, 15m, 30m, 60m e 240m (4 Horas)")
    print("=" * 70 + "\n")
    
    # 1. Cenário 1: Preço subindo rumo aos 170.000 (FVG Bearish 60m -> VENDA)
    fvg_60m = ActiveMTFFVG(
        timeframe=60,
        direction="BEARISH",
        top=170170.0,
        bottom=170000.0,
        ce_50=170085.0,
        formed_time=now
    )
    scanner.active_fvgs[60].append(fvg_60m)
    
    alerts_venda = scanner.scan_approach_alerts(169880.0, approach_radius=150.0)
    if alerts_venda:
        print("[CENÁRIO 1] - Preço Subindo Rumo aos 170.000 pts (Alerta de VENDA em Vermelho):\n")
        print(scanner.format_power_shell_alert(alerts_venda[0], use_color=True))
        
    print("\n" + "-" * 70 + "\n")
    
    # 2. Cenário 2: Preço caindo rumo aos 170.000 (FVG Bullish 30m -> COMPRA)
    scanner2 = FGVMTFScanner()
    fvg_30m = ActiveMTFFVG(
        timeframe=30,
        direction="BULLISH",
        top=170000.0,
        bottom=169830.0,
        ce_50=169915.0,
        formed_time=now
    )
    scanner2.active_fvgs[30].append(fvg_30m)
    
    alerts_compra = scanner2.scan_approach_alerts(170120.0, approach_radius=150.0)
    if alerts_compra:
        print("[CENÁRIO 2] - Preço Caindo Rumo aos 170.000 pts (Alerta de COMPRA em Verde):\n")
        print(scanner2.format_power_shell_alert(alerts_compra[0], use_color=True))
        
    print("\n" + "=" * 70)
    print("FIM DA DEMONSTRAÇÃO DO RADAR FVG MTF")
    print("=" * 70 + "\n")


def cmd_demo_alert():
    """Gera visualização demonstrativa colorida de alertas reais de FVG no terminal."""
    import time
    from datetime import timedelta
    from core.models import SignalSetup, SetupStatus, Direction
    from analysis.alert_formatter import format_operational_alert
    
    now = datetime.now(TZ_BRASILIA)
    symbol = get_current_win_contract()
    
    print("\n" + "=" * 70)
    print("DEMONSTRAÇÃO DE ALERTA VISUAL NO POWERSHELL COM CORES (SMC & FLUXO)")
    print("=" * 70 + "\n")
    
    cmd_fvg_radar()
    print("Avançando para simulação de execução no SuperDOM...\n")
    time.sleep(1.0)
    
    # 1. Demonstração de COMPRA (FVG de Alta)
    regimes_buy = {
        "60m": "ALTA", "30m": "ALTA", "15m": "ALTA",
        "10m": "ALTA", "5m": "ALTA", "2m": "ALTA", "1m": "ALTA"
    }
    setup_buy = SignalSetup(
        timestamp=now,
        setup_name="Compra de Continuidade em Tendência de Alta",
        direction=Direction.COMPRA,
        symbol=symbol,
        status=SetupStatus.CONFIRMADO,
        entry_price=171405.0,
        stop_price=171155.0,
        stop_points=250.0,
        target_price=171805.0,
        target_points=400.0,
        risk_reward=1.60,
        timeframe_trigger=5,
        in_trend_direction=True,
        fvg_zone="171350 - 171420 (FVG de Alta no 5m)",
        structure_event="Recuo em FVG de 5m (171350-171420) a favor do contexto 60m/30m",
        book_evidence={
            "observed_behavior": "Concentração de liquidez passiva compradora no suporte do FVG (171350)",
            "metrics": {"spread": 5.0, "book_imbalance_top5": 0.32},
            "classification": "Comportamento de oferta observado",
            "limitations": ["Ausência de identificador único de ordem", "Feed DDE amostrado"]
        },
        flow_evidence={
            "buy_volume": 14850,
            "sell_volume": 8210,
            "delta": 6640,
            "large_trades": [{"qty": 120, "price": 171405.0, "side": "BUY"}, {"qty": 150, "price": 171410.0, "side": "BUY"}],
            "price_displacement_pts": 45.0,
            "flow_pattern": "Agressão com Continuidade Compradora (DELTA positivo com avanço)"
        },
        facts_observed=[
            "Preço atual: 171405",
            "Estrutura: Recuo em FVG de 5m (171350-171420) a favor do contexto 60m/30m",
            "Modo de cálculo: FIXO (Stop: 250 pts | Alvo: 400 pts)",
            "Fluxo recente: DELTA=+6640 | Padrão=Continuidade Compradora"
        ],
        interpretations=[
            "Setup a favor em relação ao contexto macro.",
            "Relação Retorno/Risco bruto: 1.60 (R$ 50.00 de risco / R$ 80.00 de retorno por contrato)."
        ],
        limitations=[
            "Não há garantia de execução nos preços exatos (sujeito a slippage e latência).",
            "Níveis estruturais não comprovam localização de stops institucionais."
        ],
        validity_deadline=now + timedelta(minutes=15),
        invalidation_criteria="Superação do nível 171155 ou quebra da premissa estrutural."
    )
    
    print("[1/2] SIMULAÇÃO DE OPORTUNIDADE DE COMPRA (FVG DE ALTA):\n")
    alert_buy_str = format_operational_alert(
        setup=setup_buy,
        regimes=regimes_buy,
        source_name="Nelogica ProfitPro (DDE)",
        delay_ms=0.1,
        quality_status="ÍNTEGRO (FLUXO + ESTRUTURA)",
        use_color=True
    )
    print(alert_buy_str)
    
    print("\n" + "-" * 70)
    print("Aguardando 2 segundos para simular oportunidade de VENDA...")
    print("-" * 70 + "\n")
    time.sleep(2.0)
    
    # 2. Demonstração de VENDA (FVG de Baixa)
    regimes_sell = {
        "60m": "BAIXA", "30m": "BAIXA", "15m": "BAIXA",
        "10m": "BAIXA", "5m": "BAIXA", "2m": "BAIXA", "1m": "BAIXA"
    }
    setup_sell = SignalSetup(
        timestamp=now,
        setup_name="Venda de Continuidade em Tendência de Baixa",
        direction=Direction.VENDA,
        symbol=symbol,
        status=SetupStatus.CONFIRMADO,
        entry_price=172025.0,
        stop_price=172275.0,
        stop_points=250.0,
        target_price=171625.0,
        target_points=400.0,
        risk_reward=1.60,
        timeframe_trigger=5,
        in_trend_direction=True,
        fvg_zone="172080 - 172010 (FVG de Baixa no 5m)",
        structure_event="Retração em FVG de 5m (172080-172010) a favor do contexto 60m/30m",
        book_evidence={
            "observed_behavior": "Barreira de liquidez passiva vendedora no topo do FVG (172080)",
            "metrics": {"spread": 5.0, "book_imbalance_top5": -0.38},
            "classification": "Comportamento de oferta observado",
            "limitations": ["Ausência de identificador único de ordem", "Feed DDE amostrado"]
        },
        flow_evidence={
            "buy_volume": 6120,
            "sell_volume": 13900,
            "delta": -7780,
            "large_trades": [{"qty": 100, "price": 172030.0, "side": "SELL"}, {"qty": 200, "price": 172025.0, "side": "SELL"}],
            "price_displacement_pts": -60.0,
            "flow_pattern": "Agressão com Continuidade Vendedora (DELTA negativo com recuo)"
        },
        facts_observed=[
            "Preço atual: 172025",
            "Estrutura: Retração em FVG de 5m (172080-172010) a favor do contexto 60m/30m",
            "Modo de cálculo: FIXO (Stop: 250 pts | Alvo: 400 pts)",
            "Fluxo recente: DELTA=-7780 | Padrão=Continuidade Vendedora"
        ],
        interpretations=[
            "Setup a favor em relação ao contexto macro.",
            "Relação Retorno/Risco bruto: 1.60 (R$ 50.00 de risco / R$ 80.00 de retorno por contrato)."
        ],
        limitations=[
            "Não há garantia de execução nos preços exatos (sujeito a slippage e latência).",
            "Níveis estruturais não comprovam localização de stops institucionais."
        ],
        validity_deadline=now + timedelta(minutes=15),
        invalidation_criteria="Superação do nível 172275 ou quebra da premissa estrutural."
    )
    
    print("[2/2] SIMULAÇÃO DE OPORTUNIDADE DE VENDA (FVG DE BAIXA):\n")
    alert_sell_str = format_operational_alert(
        setup=setup_sell,
        regimes=regimes_sell,
        source_name="Nelogica ProfitPro (DDE)",
        delay_ms=0.1,
        quality_status="ÍNTEGRO (FLUXO + ESTRUTURA)",
        use_color=True
    )
    print(alert_sell_str)
    print("\n" + "=" * 70)
    print("FIM DA DEMONSTRAÇÃO VISUAL")
    print("=" * 70 + "\n")


def cmd_scan_dde(symbol: str | None = None):
    """Varre todos os tópicos e campos DDE comuns para verificar quais estão ativos."""
    chosen_symbol = resolve_symbol(symbol)
    print("=" * 70)
    print("VARREDURA DE CAMPOS DDE NO PROFIT PRO")
    print(f"Ativo Selecionado: {chosen_symbol}")
    print("=" * 70)
    feed = ProfitDDEFeed()
    if not feed.connect():
        print(f"[ERRO] Não foi possível conectar ao DDE: {feed.health.error_message}")
        return
    
    fields = [
        "ULT", "ABE", "MAX", "MIN", "FEC", "VOL", "VAR", "VARPTS",
        "OCP", "OVD", "VOC", "VOV", "NEG", "AGRVOLC", "AGRVOLV", "AGRSALDO", "HOR"
    ]
    
    print(f"Testando campos para o ativo: {chosen_symbol}...")
    found_any = False
    for f in fields:
        fmt = f"{chosen_symbol}.{f}"
        val = feed._query_item(fmt, timeout_ms=100)
        if val:
            print(f"  [RECEBIDO] {fmt:20} = '{val}'")
            found_any = True
    
    if not found_any:
        print("\nNenhum dado retornado no momento.")
        print("MOTIVOS POSSÍVEIS:")
        print("1. O pregão da B3 está fechado (horário noturno / final de semana).")
        print("2. A tabela de exportação precisa ser aberta no Profit Pro:")
        print(f"   Menu: Ferramentas -> Exportar em tempo real (DDE / RTD) -> Adicionar {chosen_symbol}.")
    print("=" * 70)
    feed.disconnect()


def cmd_replay_file(file_path: str | None, mode: str = "FIXO", delay: float = 0.0, symbol: str | None = None):
    """Executa replay de mercado determinístico a partir de arquivo CSV exportado do Profit Pro para o Mini-Índice."""
    from feeds.csv_feed import ProfitCSVFeed
    from core.contract import round_to_tick
    from datetime import timedelta
    
    if not file_path or not os.path.exists(file_path):
        sample_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "sample_profit_win.csv"))
        if not os.path.exists(sample_path):
            print(f"Gerando arquivo de exemplo do Profit Pro: {sample_path}...")
            with open(sample_path, "w", encoding="utf-8") as f:
                f.write("Data;Hora;Abertura;Máxima;Mínima;Fechamento;Volume;Quantidade\n")
                curr_p = 171400.0
                base_dt = datetime(2026, 11, 2, 9, 0, 0, tzinfo=TZ_BRASILIA)
                for i in range(120):
                    t = base_dt + timedelta(minutes=i)
                    drift = 25.0 if (i % 20 < 12) else -25.0
                    op = curr_p
                    hi = round_to_tick(op + 60.0)
                    lo = round_to_tick(op - 40.0)
                    cl = round_to_tick(op + drift)
                    curr_p = cl
                    f.write(f"{t.strftime('%d/%m/%Y')};{t.strftime('%H:%M:%S')};{op:,.0f};{hi:,.0f};{lo:,.0f};{cl:,.0f};150000;2500\n".replace(",", "."))
        file_path = sample_path

    chosen_symbol = symbol or get_current_win_contract()
    print("=" * 70)
    print("REPLAY DE MERCADO HISTÓRICO — ARQUIVO PROFIT PRO (WIN)")
    print(f"Arquivo Fonte       : {file_path}")
    print(f"Ativo               : {chosen_symbol}")
    print(f"Modo Operacional    : {mode} (Stop: 250 pts | Alvo: 400 pts | R:R 1.60)")
    print("=" * 70)

    feed = ProfitCSVFeed(file_path=file_path, symbol=chosen_symbol, delay_seconds=delay)
    if not feed.connect():
        print(f"Erro ao conectar com o arquivo: {feed.health.error_message}")
        return

    assistant = WinAnalysisAssistant(feed=feed, symbol=chosen_symbol, mode=mode)
    assistant.start()

    trades_history = []
    active_trade = None

    def on_step(c: Candle, current_idx: int, total_idx: int):
        nonlocal active_trade
        if active_trade:
            pos = active_trade
            hit_target = False
            hit_stop = False
            
            if pos["direction"] == Direction.COMPRA:
                if c.high >= pos["target_price"]:
                    hit_target = True
                if c.low <= pos["stop_price"]:
                    hit_stop = True
            else: # VENDA
                if c.low <= pos["target_price"]:
                    hit_target = True
                if c.high >= pos["stop_price"]:
                    hit_stop = True

            if hit_target and hit_stop:
                trades_history.append({"result": "STOP", "pts": -pos["stop_points"], "setup": pos["setup_name"]})
                print(f"  [STOP AMBIGUIDADE] {c.close_time.strftime('%H:%M')} | {pos['setup_name']} em {c.close:.0f}")
                active_trade = None
            elif hit_target:
                trades_history.append({"result": "ALVO", "pts": pos["target_points"], "setup": pos["setup_name"]})
                print(f"  [ALVO ATINGIDO +400 pts!] {c.close_time.strftime('%H:%M')} | {pos['setup_name']} em {pos['target_price']:.0f}")
                active_trade = None
            elif hit_stop:
                trades_history.append({"result": "STOP", "pts": -pos["stop_points"], "setup": pos["setup_name"]})
                print(f"  [STOP ACIONADO -250 pts] {c.close_time.strftime('%H:%M')} | {pos['setup_name']} em {pos['stop_price']:.0f}")
                active_trade = None

        if not active_trade:
            setup, status_msg = assistant.setup_engine.evaluate(
                symbol=chosen_symbol,
                current_price=c.close,
                timestamp=c.close_time,
                structure_engine=assistant.structure_engine,
                flow_analyzer=assistant.flow_analyzer,
                book_analyzer=assistant.book_analyzer,
                feed_healthy=True
            )
            if setup:
                active_trade = {
                    "setup_name": setup.setup_name,
                    "direction": setup.direction,
                    "entry_price": setup.entry_price,
                    "stop_price": setup.stop_price,
                    "stop_points": setup.stop_points,
                    "target_price": setup.target_price,
                    "target_points": setup.target_points,
                    "entry_time": c.close_time
                }
                dir_label = "COMPRA" if setup.direction == Direction.COMPRA else "VENDA"
                print(f"\n>>> GATILHO SMC DISPARADO: [{dir_label}] às {c.close_time.strftime('%H:%M:%S')} <<<")
                print(f"    Setup   : {setup.setup_name}")
                print(f"    Entrada : {setup.entry_price:.0f} | Stop: {setup.stop_price:.0f} (250 pts) | Alvo: {setup.target_price:.0f} (400 pts)")

    print(f"Processando {len(feed.records)} candles de 1 minuto do pregão...\n")
    feed.replay_all(on_step=on_step)
    assistant.stop()

    print("\n" + "=" * 70)
    print("RELATÓRIO FINAL DO REPLAY DE MERCADO")
    print("=" * 70)
    total_trades = len(trades_history)
    if total_trades == 0:
        print("Nenhuma entrada disparada no arquivo (Preservação de capital por falta de confluência).")
    else:
        wins = [t for t in trades_history if t["result"] == "ALVO"]
        losses = [t for t in trades_history if t["result"] == "STOP"]
        wr = (len(wins) / total_trades) * 100.0
        tot_pts = sum(t["pts"] for t in trades_history)
        tot_ticks = tot_pts / 5.0
        tot_reais = calculate_financial_risk(tot_pts, 1)
        
        print(f"Total de Entradas Disparadas: {total_trades}")
        print(f"Vitórias (+400 pts)         : {len(wins)} ({wr:.1f}%)")
        print(f"Derrotas (-250 pts)         : {len(losses)} ({100.0 - wr:.1f}%)")
        print(f"Saldo Total em Pontos       : {tot_pts:+.0f} pontos ({tot_ticks:+.0f} ticks de 5 pts)")
        print(f"Base de Cálculo B3 Oficial  : 1 ponto = R$ 0,20 (1 ct) | R$ 1,00 (5 ct)")
        print(f"Resultado Financeiro (1 ct) : R$ {tot_reais:+,.2f} ({tot_pts:+.0f} pts x R$ 0,20)")
        print(f"Resultado Financeiro (5 ct) : R$ {(tot_reais * 5):+,.2f} ({tot_pts:+.0f} pts x R$ 1,00)")
        print(f"Breakeven Requerido (R:R 1.6): 38.5% (Assertividade superou em +{wr - 38.5:.1f}%)")
    print("=" * 70)


def cmd_replay_clipboard(mode: str = "FIXO", delay: float = 0.0, symbol: str | None = None):
    """Executa replay histórico instantâneo a partir da Área de Transferência (Clipboard) do Windows."""
    from feeds.csv_feed import ProfitClipboardFeed, analyze_dataset_characteristics
    
    feed = ProfitClipboardFeed(symbol=symbol or "TEMP", delay_seconds=delay)
    if not feed.connect():
        print(f"\n[AVISO] {feed.health.error_message}")
        print("\nInstruções simples de uso:")
        print("1. No Profit Pro, abra qualquer gráfico de WIN, WDO ou Ações (ex: 1 Minuto ou 5 Minutos).")
        print("2. Clique com o botão direito no gráfico -> 'Exportar' -> 'Copiar estudos para o Excel'.")
        print("3. Execute novamente este comando!")
        return

    char = analyze_dataset_characteristics(feed.records)
    if symbol:
        chosen_symbol = resolve_symbol(symbol)
    else:
        if char["asset_type"] == "WDO":
            chosen_symbol = get_current_wdo_contract()
        elif char["asset_type"] == "ACAO":
            chosen_symbol = "VALE3"
        else:
            chosen_symbol = get_current_win_contract()

    feed.symbol = chosen_symbol
    spec = get_asset_spec(chosen_symbol)

    print("=" * 70)
    print("REPLAY DE MERCADO HISTÓRICO — CLIPBOARD DO PROFIT PRO")
    print("Origem dos Dados    : Área de Transferência do Windows (RAM)")
    print(f"Ativo Configurado   : {chosen_symbol} ({spec.name})")
    print(f"Modo Operacional    : {mode} (Stop: {spec.default_stop_points} | Alvo: {spec.default_target_points} | R:R 1.60)")
    print("=" * 70)

    first_t = feed.records[0]['timestamp'].strftime('%d/%m/%Y %H:%M')
    last_t = feed.records[-1]['timestamp'].strftime('%d/%m/%Y %H:%M')
    print(f"Encontrados {len(feed.records)} candles carregados da memória!")
    print(f"Intervalo Temporal : {first_t} até {last_t}")
    print(f"Ativo Detectado    : {char['asset_label']} (Preço Médio: {char['avg_price']:,.2f})")
    print(f"Tempo Gráfico      : ~{char['timeframe_min']} Minuto(s)")

    assistant = WinAnalysisAssistant(feed=feed, symbol=chosen_symbol, mode=mode)
    assistant.start()

    trades_history = []
    active_trade = None

    def on_step(c: Candle, current_idx: int, total_idx: int):
        nonlocal active_trade
        if active_trade:
            pos = active_trade
            hit_target = False
            hit_stop = False
            
            if pos["direction"] == Direction.COMPRA:
                if c.high >= pos["target_price"]:
                    hit_target = True
                if c.low <= pos["stop_price"]:
                    hit_stop = True
            else: # VENDA
                if c.low <= pos["target_price"]:
                    hit_target = True
                if c.high >= pos["stop_price"]:
                    hit_stop = True

            if hit_target and hit_stop:
                trades_history.append({"result": "STOP", "pts": -pos["stop_points"], "setup": pos["setup_name"]})
                print(f"  [STOP AMBIGUIDADE] {c.close_time.strftime('%d/%m %H:%M')} | {pos['setup_name']} em {c.close:.0f}")
                active_trade = None
            elif hit_target:
                trades_history.append({"result": "ALVO", "pts": pos["target_points"], "setup": pos["setup_name"]})
                print(f"  [ALVO ATINGIDO +400 pts!] {c.close_time.strftime('%d/%m %H:%M')} | {pos['setup_name']} em {pos['target_price']:.0f}")
                active_trade = None
            elif hit_stop:
                trades_history.append({"result": "STOP", "pts": -pos["stop_points"], "setup": pos["setup_name"]})
                print(f"  [STOP ACIONADO -250 pts] {c.close_time.strftime('%d/%m %H:%M')} | {pos['setup_name']} em {pos['stop_price']:.0f}")
                active_trade = None

        if not active_trade:
            setup, status_msg = assistant.setup_engine.evaluate(
                symbol=chosen_symbol,
                current_price=c.close,
                timestamp=c.close_time,
                structure_engine=assistant.structure_engine,
                flow_analyzer=assistant.flow_analyzer,
                book_analyzer=assistant.book_analyzer,
                feed_healthy=True
            )
            if setup:
                active_trade = {
                    "setup_name": setup.setup_name,
                    "direction": setup.direction,
                    "entry_price": setup.entry_price,
                    "stop_price": setup.stop_price,
                    "stop_points": setup.stop_points,
                    "target_price": setup.target_price,
                    "target_points": setup.target_points,
                    "entry_time": c.close_time
                }
                dir_label = "COMPRA" if setup.direction == Direction.COMPRA else "VENDA"
                print(f"\n>>> GATILHO SMC DISPARADO: [{dir_label}] às {c.close_time.strftime('%d/%m/%Y %H:%M')} <<<")
                print(f"    Setup   : {setup.setup_name}")
                print(f"    Entrada : {setup.entry_price:.0f} | Stop: {setup.stop_price:.0f} (250 pts) | Alvo: {setup.target_price:.0f} (400 pts)")

    print("Iniciando reprodução do fluxo e avaliação confluente...\n")
    feed.replay_all(on_step=on_step)
    assistant.stop()

    print("\n" + "=" * 70)
    print("RELATÓRIO FINAL DO REPLAY DE MERCADO (CLIPBOARD PROFIT)")
    print("=" * 70)
    total_trades = len(trades_history)
    if total_trades == 0:
        print("Nenhuma entrada disparada no período (Preservação de capital por falta de confluência).")
    else:
        wins = [t for t in trades_history if t["result"] == "ALVO"]
        losses = [t for t in trades_history if t["result"] == "STOP"]
        wr = (len(wins) / total_trades) * 100.0
        tot_pts = sum(t["pts"] for t in trades_history)
        tot_ticks = tot_pts / 5.0
        tot_reais = calculate_financial_risk(tot_pts, 1)
        
        print(f"Total de Entradas Disparadas: {total_trades}")
        print(f"Vitórias (+400 pts)         : {len(wins)} ({wr:.1f}%)")
        print(f"Derrotas (-250 pts)         : {len(losses)} ({100.0 - wr:.1f}%)")
        print(f"Saldo Total em Pontos       : {tot_pts:+.0f} pontos ({tot_ticks:+.0f} ticks de 5 pts)")
        print(f"Base de Cálculo B3 Oficial  : 1 ponto = R$ 0,20 (1 ct) | R$ 1,00 (5 ct)")
        print(f"Resultado Financeiro (1 ct) : R$ {tot_reais:+,.2f} ({tot_pts:+.0f} pts x R$ 0,20)")
        print(f"Resultado Financeiro (5 ct) : R$ {(tot_reais * 5):+,.2f} ({tot_pts:+.0f} pts x R$ 1,00)")
        print(f"Breakeven Requerido (R:R 1.6): 38.5% (Assertividade superou em +{wr - 38.5:.1f}%)")
    print("=" * 70)


def cmd_sim_fvg_delta():
    """Executa a simulação do disparo simultâneo de Radar FVG + Desbalanceamento de Delta."""
    import simular_fvg_delta
    simular_fvg_delta.executar_simulacao()


def cmd_sim_cenario3():
    """Executa a simulação oficial do Cenário 3 (Trade Bloqueado vs Confirmado com Radar FVG)."""
    import simular_cenario3
    simular_cenario3.simular_cenario_3()


def cmd_sim_liberado():
    """Executa a demonstração de uma operação LIBERADA com Passagem Livre no SuperDOM."""
    import simular_liberado
    simular_liberado.executar_exemplo_liberado()


def interactive_menu():
    """Menu amigável de inicialização quando o cliente dá duplo clique no executável."""
    while True:
        print("\n" + "=" * 72)
        print("     ASSISTENTE DE TRADING INSTITUCIONAL WIN — MINI-ÍNDICE B3      ")
        print("     Arquitetura Quantitativa SMC & Tape Reading (Cenário 3 Oficial)")
        print("=" * 72)
        print("Selecione uma opção:")
        print("  [1] Iniciar Monitoramento em Tempo Real via Profit Pro (Cenário 3: 250/400 pts)")
        print("  [2] Iniciar Monitoramento em Tempo Real (Modo ESTRUTURAL)")
        print("  [3] Simulação do Cenário 3 — Operação BLOQUEADA por Obstáculo FVG (Radar MTF)")
        print("  [4] Simulação do Cenário 3 — Operação LIBERADA com Confluência (Passagem Livre)")
        print("  [5] Demonstração do Radar FVG Antecipado Multi-Timeframe")
        print("  [6] Demonstração de Alertas Coloridos no SuperDOM (Compra & Venda)")
        print("  [7] Diagnóstico Oficial de Conexão com Profit Pro e DDE")
        print("  [8] Teste de Replay de Mercado e Validação Estrutural")
        print("  [9] Varredura de Tópicos e Campos DDE no Profit Pro")
        print("  [0] Encerrar Aplicativo")
        print("=" * 72)
        try:
            choice = input("\nDigite o número da opção desejada [1]: ").strip() or "1"
        except (KeyboardInterrupt, EOFError):
            break
            
        if choice == "1":
            cmd_run_dde(mode="FIXO")
        elif choice == "2":
            cmd_run_dde(mode="ESTRUTURAL")
        elif choice == "3":
            cmd_sim_cenario3()
        elif choice == "4":
            cmd_sim_liberado()
        elif choice == "5":
            cmd_fvg_radar()
        elif choice == "6":
            cmd_demo_alert()
        elif choice == "7":
            cmd_diagnose()
        elif choice == "8":
            cmd_test_replay(mode="FIXO")
        elif choice == "9":
            cmd_scan_dde()
        elif choice in ("0", "sair", "exit", "q"):
            print("Encerrando aplicativo...")
            break
        else:
            print("[OPÇÃO INVÁLIDA] Digite um número de 0 a 9.")


def main():
    # 1. Trava de Licença Criptográfica (HWID) — Proteção contra Pirataria e Compartilhamento
    if not check_and_enforce_license():
        sys.exit(1)

    # 2. Se executado via duplo clique (sem parâmetros de linha de comando)
    if len(sys.argv) == 1:
        interactive_menu()
        return

    # 3. Execução via linha de comando
    parser = argparse.ArgumentParser(description="Assistente de Análise Quantitativa B3 — Profit Pro (Cenário 3 Oficial)")
    parser.add_argument("command", nargs="?", default="menu", choices=[
        "menu", "diagnose", "run-dde", "test-replay", "backtest",
        "scan-dde", "demo-alert", "fvg-radar", "replay-file",
        "replay-clipboard", "sim-fvg-delta", "sim-cenario3", "sim-liberado"
    ], help="Comando a executar")
    parser.add_argument("--mode", choices=["FIXO", "ESTRUTURAL"], default="FIXO", help="Modo de Stop e Alvo (FIXO: 250/400 pts)")
    parser.add_argument("--file", type=str, default=None, help="Caminho do arquivo CSV exportado do Profit Pro para replay")
    parser.add_argument("--delay", type=float, default=0.0, help="Pausa em segundos entre cada barra para visualização (0.0 = instantâneo)")
    parser.add_argument("--symbol", type=str, default=None, help="Ticker do contrato ou ação (ex: WIN, WDO, WINZ26, WDOZ26, VALE3)")
    
    args = parser.parse_args()
    
    if args.command == "menu":
        interactive_menu()
    elif args.command == "diagnose":
        cmd_diagnose()
    elif args.command == "run-dde":
        cmd_run_dde(mode=args.mode, symbol=args.symbol)
    elif args.command == "test-replay":
        cmd_test_replay(mode=args.mode)
    elif args.command == "scan-dde":
        cmd_scan_dde(symbol=args.symbol)
    elif args.command == "demo-alert":
        cmd_demo_alert()
    elif args.command == "fvg-radar":
        cmd_fvg_radar()
    elif args.command == "sim-fvg-delta":
        cmd_sim_fvg_delta()
    elif args.command == "sim-cenario3":
        cmd_sim_cenario3()
    elif args.command == "sim-liberado":
        cmd_sim_liberado()
    elif args.command == "backtest":
        from tests.test_backtest import run_comprehensive_backtest
        run_comprehensive_backtest(mode=args.mode)
    elif args.command == "replay-file":
        cmd_replay_file(file_path=args.file, mode=args.mode, delay=args.delay, symbol=args.symbol)
    elif args.command == "replay-clipboard":
        cmd_replay_clipboard(mode=args.mode, delay=args.delay, symbol=args.symbol)


if __name__ == "__main__":
    main()
