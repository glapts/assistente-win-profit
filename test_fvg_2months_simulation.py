"""
test_fvg_2months_simulation.py
Simulação quantitativa determinística dos últimos 2 meses de pregão (Setembro e Outubro/Novembro de 2026).
Avalia as reversões em FVGs identificados nos tempos gráficos de 10m, 15m, 30m, 60m e 240m.
Métricas testadas:
- Stop Loss: 250 pontos
- Alvo 1: 200 pontos
- Alvo 2: 300 pontos
"""

import sys
import os
import random
from datetime import datetime, timedelta

# Importar módulos do assistente
from feeds.replay_feed import ReplayMarketFeed
from core.engine import WinAnalysisAssistant
from core.models import Direction
from analysis.fvg_mtf_scanner import formatar_preco_win

def run_simulation():
    random.seed(42)

    # 44 sessões úteis (aproximadamente 2 meses)
    start_date = datetime(2026, 9, 1, 9, 0, 0)
    num_sessions = 44

    trades_log = []

    for session_idx in range(num_sessions):
        # Determinar data da sessão útil
        session_date = start_date + timedelta(days=int(session_idx * 1.45))
        while session_date.weekday() >= 5:
            session_date += timedelta(days=1)
            
        base_price = 168500.0 + (session_idx % 8) * 450.0 + random.randint(-150, 150)
        
        feed = ReplayMarketFeed(symbol="WINZ26", initial_price=base_price)
        feed.current_time = session_date
        assistant = WinAnalysisAssistant(feed=feed)
        assistant.start()
        
        active_trade = None
        
        # Simular 360 minutos de pregão (09:00 até 15:00)
        for m in range(360):
            # Alternância de ondas de tendência e contra-tendência que geram FVGs
            bias = 0.28 if (m % 90 < 45) else -0.28
            inject_sweep = (m in [60, 150, 240])
            sweep_dir = "BEARISH" if bias > 0 else "BULLISH"
            
            c_list = feed.generate_step(trend_bias=bias, inject_sweep=inject_sweep, sweep_direction=sweep_dir)
            c = c_list[0]
            curr_p = c.close
            
            # 1. Se estiver posicionado em trade de FVG, monitorar evolução
            if active_trade:
                pos = active_trade
                
                if pos["direction"] == Direction.COMPRA:
                    pos["mae"] = max(pos["mae"], pos["entry_price"] - c.low)
                    pos["mfe"] = max(pos["mfe"], c.high - pos["entry_price"])
                    
                    if c.high >= pos["entry_price"] + 200.0:
                        pos["gain_200"] = True
                    if c.high >= pos["entry_price"] + 300.0:
                        pos["gain_300"] = True
                    if c.low <= pos["stop_price"]:
                        pos["stopped"] = True
                else: # VENDA
                    pos["mae"] = max(pos["mae"], c.high - pos["entry_price"])
                    pos["mfe"] = max(pos["mfe"], pos["entry_price"] - c.low)
                    
                    if c.low <= pos["entry_price"] - 200.0:
                        pos["gain_200"] = True
                    if c.low <= pos["entry_price"] - 300.0:
                        pos["gain_300"] = True
                    if c.high >= pos["stop_price"]:
                        pos["stopped"] = True
                        
                # Fechamento do trade se atingiu stop, ou gain 300, ou fim da sessão
                if pos["stopped"] or pos["gain_300"] or m == 359:
                    pos["closed_time"] = c.close_time
                    pos["hit_target_200"] = pos["gain_200"] and not (pos["stopped"] and pos["mfe"] < 200.0)
                    pos["hit_target_300"] = pos["gain_300"] and not (pos["stopped"] and pos["mfe"] < 300.0)
                    trades_log.append(pos)
                    active_trade = None
                    
            # 2. Se não estiver posicionado, avaliar aproximação e toque em FVGs abertos
            if not active_trade:
                alerts = assistant.fvg_scanner.scan_approach_alerts(curr_p, approach_radius=150.0)
                if alerts:
                    # Selecionar FVGs relevantes (mínimo de 30 pontos de tamanho)
                    valid_alerts = [a for a in alerts if a.fvg.size >= 30.0]
                    if valid_alerts:
                        al = valid_alerts[0]
                        # Disparo quando toca na zona ou atinge o 50% CE
                        is_touch = (al.distance_to_zone <= 15.0 or al.is_inside_zone)
                        if is_touch and (c.close_time.hour < 15):
                            trade_dir = Direction.VENDA if al.action_direction == "VENDA" else Direction.COMPRA
                            stop_pts = 250.0
                            stop_p = (curr_p + stop_pts) if trade_dir == Direction.VENDA else (curr_p - stop_pts)
                            
                            active_trade = {
                                "trade_id": len(trades_log) + 1,
                                "date": c.close_time.strftime("%d/%m/%Y"),
                                "time": c.close_time.strftime("%H:%M"),
                                "timeframe": al.fvg.timeframe,
                                "direction": trade_dir,
                                "fvg_type": al.fvg.direction,
                                "fvg_size": al.fvg.size,
                                "entry_price": curr_p,
                                "ce_50": al.fvg.ce_50,
                                "stop_price": stop_p,
                                "stop_pts": stop_pts,
                                "gain_200": False,
                                "gain_300": False,
                                "stopped": False,
                                "mae": 0.0,
                                "mfe": 0.0
                            }

        assistant.stop()

    return trades_log

if __name__ == "__main__":
    trades = run_simulation()
    print(f"Total de operações identificadas e executadas: {len(trades)}")
    
    hits_200 = sum(1 for t in trades if t["hit_target_200"])
    hits_300 = sum(1 for t in trades if t["hit_target_300"])
    total = len(trades)
    
    wr_200 = (hits_200 / total) * 100.0 if total > 0 else 0
    wr_300 = (hits_300 / total) * 100.0 if total > 0 else 0
    
    print(f"Taxa de Acerto para Gain de 200 pts: {wr_200:.1f}% ({hits_200}/{total})")
    print(f"Taxa de Acerto para Gain de 300 pts: {wr_300:.1f}% ({hits_300}/{total})")
    print("\nDesempenho por Timeframe:")
    for tf in [240, 60, 30, 15, 10]:
        sub = [t for t in trades if t["timeframe"] == tf]
        if sub:
            h2 = sum(1 for t in sub if t["hit_target_200"])
            h3 = sum(1 for t in sub if t["hit_target_300"])
            mae_avg = sum(t["mae"] for t in sub) / len(sub)
            mfe_avg = sum(t["mfe"] for t in sub) / len(sub)
            print(f"  {tf}m ({len(sub)} trades): Gain 200pts = {(h2/len(sub))*100:.1f}% | Gain 300pts = {(h3/len(sub))*100:.1f}% | MAE médio = {mae_avg:.0f} pts | MFE médio = {mfe_avg:.0f} pts")
    
    print("\nTabela de Trades (Primeiros 20 trades detalhados):")
    print("-" * 120)
    print(f"{'#':<3} | {'Data':<10} | {'Hora':<5} | {'TF':<4} | {'Direção':<6} | {'Entrada':<7} | {'50% CE':<7} | {'Stop':<7} | {'MAE':<6} | {'MFE':<6} | {'Alvo 200':<10} | {'Alvo 300':<10}")
    print("-" * 120)
    for t in trades[:20]:
        r200 = "GAIN (+200)" if t["hit_target_200"] else "STOP (-250)"
        r300 = "GAIN (+300)" if t["hit_target_300"] else "STOP (-250)"
        print(f"{t['trade_id']:<3} | {t['date']:<10} | {t['time']:<5} | {t['timeframe']:>2}m  | {t['direction'].value:<6} | {formatar_preco_win(t['entry_price']):<7} | {formatar_preco_win(t['ce_50']):<7} | {formatar_preco_win(t['stop_price']):<7} | {t['mae']:>4.0f} pt | {t['mfe']:>4.0f} pt | {r200:<10} | {r300:<10}")
    print("-" * 120)
