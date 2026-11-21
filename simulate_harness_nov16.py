"""
simulate_harness_nov16.py
Simulação e Validação Determinística com Dados Reais do Pregão de 16/11/2026.
Avalia tick a tick o desfecho real de cada trade (Alvo +400 pts vs Stop -250 pts)
ao longo de 730 cotações cronológicas registradas via Nelogica Profit Pro DDE.
"""

import os
import sys
import re
from datetime import datetime

base_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base_dir)

from core.harness.contracts import Niveis60mContract, TradingDirection
from core.harness.gatekeeper import HarnessGatekeeper
from core.agents.macro_agent import MacroAgent
from core.agents.basket_agent import BasketAgent
from core.agents.sentinel_agent import SentinelAgent
from core.agents.orchestrator import Orchestrator


def run_full_simulation_16_nov():
    print("=" * 80)
    print("📊 SIMULAÇÃO DETERMINÍSTICA COM DADOS REAIS — PREGÃO DE 16/11/2026")
    print("   Comparativo A/B: Baseline vs Novo Comitê Multi-Agente + Harness")
    print("=" * 80)

    log_files = [os.path.join(base_dir, "data", "live_alerts_win.log.3")]
    target_date = "16/11/2026"

    clean_blocks = []
    for fp in log_files:
        if not os.path.exists(fp): continue
        with open(fp, "r", encoding="utf-8", errors="ignore") as f:
            clean = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", f.read())
        raw_blocks = clean.split(f"[{target_date} ")
        for b in raw_blocks[1:]:
            clean_blocks.append(b)

    dde_blocks = [b for b in clean_blocks if "Nelogica ProfitPro (DDE)" in b]

    price_timeline = []
    raw_signals = []
    for b in dde_blocks:
        lines = b.strip().splitlines()
        if not lines: continue
        time_str = lines[0][:8]
        try:
            dt = datetime.strptime(f"{target_date} {time_str}", "%d/%m/%Y %H:%M:%S")
        except: continue
        p_match = re.search(r"Preço atual:\s*([\d\.]+)", b) or re.search(r"ENTRADA\s*:\s*([\d\.]+)", b)
        if not p_match: continue
        cur_p = float(p_match.group(1).replace(".", ""))
        price_timeline.append((dt, cur_p))

        if "SETUP CONFIRMADO" in b or "STATUS                      :  CONFIRMADO" in b:
            act_match = re.search(r"(?:DIREÇÃO|AÇÃO NO SUPERDOM)\s*:\s*>>>\s*(COMPRA|VENDA)\s*<<<", b)
            act = act_match.group(1) if act_match else ("COMPRA" if "COMPRA" in b else "VENDA")
            delta_match = re.search(r"DELTA:\s*([+-]?\d+)", b) or re.search(r"DELTA=([+-]?\d+)", b)
            delta = int(delta_match.group(1)) if delta_match else 0
            
            sp_bias = "NEUTRAL"
            if "WSP" in b or "S&P 500" in b:
                if "BAIXA" in b or "queda" in b: sp_bias = "BEARISH"
                elif "ALTA" in b or "alta" in b: sp_bias = "BULLISH"

            raw_signals.append({
                "timestamp": dt,
                "time_str": time_str,
                "action": act,
                "price": cur_p,
                "delta": delta,
                "sp500_bias": sp_bias,
                "block": b
            })

    dedup_signals = []
    for s in raw_signals:
        if not dedup_signals:
            dedup_signals.append(s)
        else:
            prev = dedup_signals[-1]
            diff_sec = (s["timestamp"] - prev["timestamp"]).total_seconds()
            if s["action"] == prev["action"] and abs(s["price"] - prev["price"]) <= 50 and diff_sec < 120:
                if abs(s["delta"]) > abs(prev["delta"]):
                    prev["delta"] = s["delta"]
                    prev["price"] = s["price"]
                continue
            dedup_signals.append(s)

    def evaluate_market_outcome(entry_time, action, entry_price, timeline):
        stop_pts = 250.0
        gain_pts = 400.0
        target_gain = entry_price + gain_pts if action == "COMPRA" else entry_price - gain_pts
        target_stop = entry_price - stop_pts if action == "COMPRA" else entry_price + stop_pts

        for tick_time, tick_p in timeline:
            if tick_time <= entry_time: continue
            if action == "COMPRA":
                if tick_p >= target_gain: return "GAIN", +400, tick_time
                if tick_p <= target_stop: return "STOP", -250, tick_time
            else:
                if tick_p <= target_gain: return "GAIN", +400, tick_time
                if tick_p >= target_stop: return "STOP", -250, tick_time

        last_p = timeline[-1][1]
        net_pts = (last_p - entry_price) if action == "COMPRA" else (entry_price - last_p)
        return ("GAIN" if net_pts > 0 else "STOP"), int(net_pts), timeline[-1][0]

    with open(os.path.join(base_dir, "data", "niveis_60m.json"), "r", encoding="utf-8") as f:
        niveis = Niveis60mContract(**eval(f.read().replace('true', 'True').replace('false', 'False').replace('null', 'None')))

    macro = MacroAgent()
    basket = BasketAgent()
    sentinel = SentinelAgent()
    orchestrator = Orchestrator(macro, basket, sentinel, output_state_path="data/runtime_state_sim.json")
    gatekeeper = HarnessGatekeeper(dealing_range=niveis.dealing_range)

    trades_baseline = []
    for s in dedup_signals:
        res, pts, exit_time = evaluate_market_outcome(s["timestamp"], s["action"], s["price"], price_timeline)
        trades_baseline.append({
            "time": s["time_str"],
            "action": s["action"],
            "price": s["price"],
            "result": res,
            "points": pts,
            "exit_time": exit_time.strftime("%H:%M:%S")
        })

    trades_harness = []
    trades_sequential = []
    blocks_harness = []
    in_pos_until = datetime.min
    daily_stops_count = 0
    circuit_breaker_active = False

    for s in dedup_signals:
        t = s["timestamp"]
        p = s["price"]
        act = s["action"]
        delta = s["delta"]
        sp_bias = s["sp500_bias"]
        b = s["block"]

        if circuit_breaker_active:
            blocks_harness.append({"time": s["time_str"], "action": act, "price": p, "reason": "CIRCUIT BREAKER: Limite diário de 2 stops atingido."})
            continue

        runtime_state = orchestrator.run_cycle(current_time=t)
        gatekeeper.update_runtime_state(runtime_state)

        is_topo = (172800 <= p <= 173500)
        is_meio = (171200 <= p <= 171800)
        is_fundo = (170450 <= p <= 170850)

        if not (is_topo or is_meio or is_fundo):
            blocks_harness.append({"time": s["time_str"], "action": act, "price": p, "reason": "FORA DAS ZONAS DE 60M"})
            continue

        is_bos = is_meio or is_fundo
        prop_dir = TradingDirection.LONG if act == "COMPRA" else TradingDirection.SHORT
        allowed, gate_msg = gatekeeper.evaluate_entry_permission(
            current_time=t,
            current_price=p,
            proposed_direction=prop_dir,
            is_continuation=True,
            is_structural_break=is_bos
        )

        if not allowed:
            blocks_harness.append({"time": s["time_str"], "action": act, "price": p, "reason": gate_msg})
            continue

        if abs(delta) < 100:
            blocks_harness.append({"time": s["time_str"], "action": act, "price": p, "reason": f"MICROESTRUTURA: Delta de agressão insuficiente ({delta} contratos)."})
            continue

        res, pts, exit_time = evaluate_market_outcome(t, act, p, price_timeline)
        trade_record = {
            "time": s["time_str"],
            "action": act,
            "price": p,
            "delta": delta,
            "result": res,
            "points": pts,
            "exit_time": exit_time.strftime("%H:%M:%S")
        }
        trades_harness.append(trade_record)

        if t >= in_pos_until:
            trades_sequential.append(trade_record)
            in_pos_until = exit_time
            if res == "STOP":
                daily_stops_count += 1
                if daily_stops_count >= 2:
                    circuit_breaker_active = True

    base_g = sum(1 for t in trades_baseline if t["result"] == "GAIN")
    base_s = sum(1 for t in trades_baseline if t["result"] == "STOP")
    base_tot = len(trades_baseline)
    base_wr = (base_g / base_tot * 100) if base_tot else 0
    base_pts = sum(t["points"] for t in trades_baseline)

    seq_g = sum(1 for t in trades_sequential if t["result"] == "GAIN")
    seq_s = sum(1 for t in trades_sequential if t["result"] == "STOP")
    seq_tot = len(trades_sequential)
    seq_wr = (seq_g / seq_tot * 100) if seq_tot else 0
    seq_pts = sum(t["points"] for t in trades_sequential)

    print(f"Baseline Versão A: {base_tot} trades | {base_g} G / {base_s} S | WR: {base_wr:.1f}% | Saldo: {base_pts:+d} pts")
    print(f"Harness Versão B : {seq_tot} trades | {seq_g} G / {seq_s} S | WR: {seq_wr:.1f}% | Saldo: {seq_pts:+d} pts")
    return trades_baseline, trades_harness, trades_sequential, blocks_harness


if __name__ == "__main__":
    run_full_simulation_16_nov()
