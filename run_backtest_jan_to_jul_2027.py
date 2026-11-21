"""
run_backtest_jan_to_jul_2027.py
Executa o algoritmo quantitativo SMC + Tape Reading para o primeiro semestre de 2027 (Janeiro a Julho).
Gera dados realistas de mercado para os 144 pregões úteis da B3, executa o motor SMC dia a dia,
e compila tabelas e métricas mês a mês (Janeiro, Fevereiro, Março, Abril, Maio, Junho, Julho),
além do consolidado semestral.
"""

import os
import sys
import json
import random
from datetime import datetime, date, timedelta
from typing import Dict, List, Any

# Garantir importações locais
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from core.models import Candle, Trade, AggressorSide, Direction, SetupStatus
from core.engine import WinAnalysisAssistant
from core.contract import (
    resolve_symbol,
    get_asset_spec,
    calculate_financial_risk,
    round_to_tick,
    TZ_BRASILIA,
    WIN_SPEC
)
from feeds.base_feed import BaseMarketFeed, FeedHealth


class FastMemoryFeed(BaseMarketFeed):
    """Feed em memória otimizado para execução rápida de múltiplos pregões."""

    def __init__(self, symbol: str, records: List[Dict[str, Any]]):
        super().__init__(source_name="Fast Memory Feed")
        self.symbol = symbol
        self.records = records
        self.health = FeedHealth(
            connected=True,
            source_name=self.source_name,
            is_flow_available=True,
            is_book_available=True
        )

    def connect(self) -> bool:
        self.health.connected = True
        return True

    def disconnect(self):
        self.health.connected = False

    def subscribe_symbol(self, symbol: str) -> bool:
        self.symbol = symbol
        return True

    def replay_all(self, on_step=None):
        total = len(self.records)
        for idx, rec in enumerate(self.records):
            c = Candle(
                timeframe=1,
                open_time=rec["timestamp"],
                close_time=rec["timestamp"] + timedelta(minutes=1),
                open=rec["open"],
                high=rec["high"],
                low=rec["low"],
                close=rec["close"],
                volume=rec["volume"],
                trades_count=rec.get("trades", 100),
                buy_volume=rec["volume"] * 0.55 if rec["close"] >= rec["open"] else rec["volume"] * 0.45,
                sell_volume=rec["volume"] * 0.45 if rec["close"] >= rec["open"] else rec["volume"] * 0.55,
                is_closed=True
            )

            side = AggressorSide.BUY if c.close >= c.open else AggressorSide.SELL
            qty = max(1, int(rec["volume"] / max(rec.get("trades", 100), 1)))

            if self.on_trade_callback:
                t = Trade(
                    trade_id=f"T_{idx}",
                    timestamp=c.close_time,
                    price=c.close,
                    quantity=qty,
                    aggressor=side,
                    is_estimated_aggressor=True
                )
                self.on_trade_callback(t)

            if self.on_candle_callback:
                self.on_candle_callback(c)

            self.health.last_event_time = c.close_time
            self.health.last_received_time = datetime.now(TZ_BRASILIA)

            if on_step:
                on_step(c, idx + 1, total)


def get_2027_trading_days() -> List[date]:
    """Retorna todas as datas de pregão da B3 de 01/01/2027 até 31/07/2027."""
    holidays = {
        date(2027, 1, 1),   # Ano Novo
        date(2027, 2, 8),   # Carnaval
        date(2027, 2, 9),   # Carnaval
        date(2027, 3, 26),  # Sexta-Feira Santa
        date(2027, 4, 21),  # Tiradentes
        date(2027, 5, 27),  # Corpus Christi
        date(2027, 7, 9),   # Revolução Constitucionalista
    }
    cur = date(2027, 1, 1)
    end = date(2027, 7, 31)
    trading_days = []
    while cur <= end:
        if cur.weekday() < 5 and cur not in holidays:
            trading_days.append(cur)
        cur += timedelta(days=1)
    return trading_days


def generate_market_data_for_2027() -> Dict[date, List[Dict[str, Any]]]:
    """
    Gera histórico com microestrutura verossímil da B3 para o 1º semestre de 2027.
    Contém 144 pregões de 480 minutos (09:00 às 17:00), com gaps de abertura,
    volatilidade matinal, formação de FVGs institucionais, falsos rompimentos e tendências.
    """
    random.seed(42)  # Semente fixa para reprodutibilidade científica determinística
    trading_days = get_2027_trading_days()
    sessions: Dict[date, List[Dict[str, Any]]] = {}

    curr_benchmark_price = 168500.0

    for day_idx, d in enumerate(trading_days):
        # Gap de abertura em relação ao dia anterior (-400 a +400 pts)
        gap = round_to_tick(random.randint(-350, 350))
        curr_p = round_to_tick(curr_benchmark_price + gap)

        day_candles = []
        base_dt = datetime(d.year, d.month, d.day, 9, 0, 0, tzinfo=TZ_BRASILIA)

        # Determinar padrão do dia (alta, baixa, caixote)
        day_type = day_idx % 4
        # 0: Tendência de Alta
        # 1: Sweep de Topo e Reversão (Venda)
        # 2: Tendência de Baixa
        # 3: Sweep de Fundo e Reversão (Compra)

        for m in range(480):
            t = base_dt + timedelta(minutes=m)

            if day_type == 0:  # Tendência de Alta
                bias = 0.28 if m < 200 else (0.15 if m < 340 else 0.05)
            elif day_type == 1:  # Sweep de Topo e Reversão
                bias = 0.35 if m < 90 else -0.30
            elif day_type == 2:  # Tendência de Baixa
                bias = -0.28 if m < 220 else (-0.15 if m < 350 else -0.05)
            else:  # Sweep de Fundo e Reversão
                bias = -0.35 if m < 100 else 0.32

            # Micro-oscilação dentro da barra
            noise = random.randint(-25, 25)
            drift = (bias * 22.0) + noise
            op = curr_p
            cl = round_to_tick(op + drift)
            hi = round_to_tick(max(op, cl) + random.randint(15, 65))
            lo = round_to_tick(min(op, cl) - random.randint(15, 65))
            curr_p = cl

            vol = float(random.randint(90000, 320000))
            trd = random.randint(900, 3100)

            day_candles.append({
                "timestamp": t,
                "open": op,
                "high": hi,
                "low": lo,
                "close": cl,
                "volume": vol,
                "trades": trd
            })

        curr_benchmark_price = curr_p
        sessions[d] = day_candles

    return sessions


def run_simulation(symbol="WINZ27", mode="FIXO", slippage=5.0, b3_fee=0.60, contracts=5):
    print("=" * 80)
    print("GERANDO SÉRIE HISTÓRICA DO 1º SEMESTRE DE 2027 (JANEIRO A JULHO)...")
    sessions = generate_market_data_for_2027()
    print(f"Total de pregões homologados: {len(sessions)} dias úteis.")
    print("=" * 80)

    spec = get_asset_spec("WIN")
    all_daily_summaries = []
    all_trades = []

    print("\nExecutando o motor de análise SMC + Tape Reading dia a dia...")

    for d, candles in sorted(sessions.items()):
        feed = FastMemoryFeed(symbol=symbol, records=candles)
        assistant = WinAnalysisAssistant(feed=feed, symbol=symbol, mode=mode)
        assistant.fvg_scanner.auto_load = False
        assistant.start()

        session_trades = []
        active_trade = None

        def on_step(c: Candle, current_idx: int, total_idx: int):
            nonlocal active_trade
            is_end_of_day = (current_idx == total_idx) or (c.close_time.hour >= 17 and c.close_time.minute >= 50)

            if active_trade:
                pos = active_trade
                hit_target = False
                hit_stop = False

                if pos["direction"] == Direction.COMPRA:
                    if c.high >= pos["target_price"]:
                        hit_target = True
                    if c.low <= pos["stop_price"]:
                        hit_stop = True
                else:  # VENDA
                    if c.low <= pos["target_price"]:
                        hit_target = True
                    if c.high >= pos["stop_price"]:
                        hit_stop = True

                # Ambiguidade intrabar -> assumir Stop
                if hit_target and hit_stop:
                    pts_bruto = -pos["stop_points"]
                    pts_liq = pts_bruto - slippage
                    t_record = {
                        "date": d,
                        "date_str": d.strftime("%d/%m/%Y"),
                        "setup": pos["setup_name"],
                        "direction": pos["direction"].value,
                        "result": "STOP (AMBIGUIDADE)",
                        "pts_liq": pts_liq,
                        "pnl_1ct": calculate_financial_risk(pts_liq, 1, spec.point_value) - b3_fee,
                        "pnl_5ct": calculate_financial_risk(pts_liq, contracts, spec.point_value) - (b3_fee * contracts)
                    }
                    session_trades.append(t_record)
                    all_trades.append(t_record)
                    active_trade = None

                elif hit_target:
                    pts_bruto = pos["target_points"]
                    pts_liq = pts_bruto - slippage
                    t_record = {
                        "date": d,
                        "date_str": d.strftime("%d/%m/%Y"),
                        "setup": pos["setup_name"],
                        "direction": pos["direction"].value,
                        "result": "ALVO",
                        "pts_liq": pts_liq,
                        "pnl_1ct": calculate_financial_risk(pts_liq, 1, spec.point_value) - b3_fee,
                        "pnl_5ct": calculate_financial_risk(pts_liq, contracts, spec.point_value) - (b3_fee * contracts)
                    }
                    session_trades.append(t_record)
                    all_trades.append(t_record)
                    active_trade = None

                elif hit_stop:
                    pts_bruto = -pos["stop_points"]
                    pts_liq = pts_bruto - slippage
                    t_record = {
                        "date": d,
                        "date_str": d.strftime("%d/%m/%Y"),
                        "setup": pos["setup_name"],
                        "direction": pos["direction"].value,
                        "result": "STOP",
                        "pts_liq": pts_liq,
                        "pnl_1ct": calculate_financial_risk(pts_liq, 1, spec.point_value) - b3_fee,
                        "pnl_5ct": calculate_financial_risk(pts_liq, contracts, spec.point_value) - (b3_fee * contracts)
                    }
                    session_trades.append(t_record)
                    all_trades.append(t_record)
                    active_trade = None

                elif is_end_of_day:
                    if pos["direction"] == Direction.COMPRA:
                        pts_bruto = c.close - pos["entry_price"]
                    else:
                        pts_bruto = pos["entry_price"] - c.close
                    pts_liq = pts_bruto - slippage
                    res_tag = "ZERAGEM (GAIN)" if pts_liq > 0 else "ZERAGEM (LOSS)"
                    t_record = {
                        "date": d,
                        "date_str": d.strftime("%d/%m/%Y"),
                        "setup": pos["setup_name"],
                        "direction": pos["direction"].value,
                        "result": res_tag,
                        "pts_liq": pts_liq,
                        "pnl_1ct": calculate_financial_risk(pts_liq, 1, spec.point_value) - b3_fee,
                        "pnl_5ct": calculate_financial_risk(pts_liq, contracts, spec.point_value) - (b3_fee * contracts)
                    }
                    session_trades.append(t_record)
                    all_trades.append(t_record)
                    active_trade = None

            # Avaliar setups antes das 17:00
            if not active_trade and not is_end_of_day and c.close_time.hour < 17:
                setup, _ = assistant.setup_engine.evaluate(
                    symbol=symbol,
                    current_price=c.close,
                    timestamp=c.close_time,
                    structure_engine=assistant.structure_engine,
                    flow_analyzer=assistant.flow_analyzer,
                    book_analyzer=assistant.book_analyzer,
                    feed_healthy=True
                )
                if setup and setup.status in [SetupStatus.CONFIRMADO, SetupStatus.AGUARDANDO]:
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

        feed.replay_all(on_step=on_step)
        assistant.stop()

        wins = [t for t in session_trades if t["pts_liq"] > 0]
        losses = [t for t in session_trades if t["pts_liq"] <= 0]
        tot_tr = len(session_trades)
        wr = (len(wins) / tot_tr * 100.0) if tot_tr > 0 else 0.0
        tot_pts = sum(t["pts_liq"] for t in session_trades)
        tot_1ct = sum(t["pnl_1ct"] for t in session_trades)
        tot_5ct = sum(t["pnl_5ct"] for t in session_trades)

        all_daily_summaries.append({
            "date": d,
            "month_key": d.strftime("%Y-%m"),
            "month_name": get_pt_month_name(d.month),
            "date_str": d.strftime("%d/%m/%Y"),
            "candles_count": len(candles),
            "trades_count": tot_tr,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": wr,
            "points_liq": tot_pts,
            "pnl_1ct": tot_1ct,
            "pnl_5ct": tot_5ct,
            "status": "POSITIVO" if tot_pts > 0 else ("NEGATIVO" if tot_pts < 0 else "NEUTRO")
        })

    # Compilar dados por mês
    months_data = {}
    for item in all_daily_summaries:
        m_key = item["month_key"]
        if m_key not in months_data:
            months_data[m_key] = {
                "month_name": item["month_name"],
                "days": [],
                "trades": []
            }
        months_data[m_key]["days"].append(item)

    for t in all_trades:
        m_key = t["date"].strftime("%Y-%m")
        if m_key in months_data:
            months_data[m_key]["trades"].append(t)

    # Exportar JSON com todos os resultados para formatação e persistência
    out_dir = os.path.join(os.path.dirname(__file__), "data", "relatorios")
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, "resultado_jan_jul_2027.json")
    with open(json_path, "w", encoding="utf-8") as f:
        # Converter objetos de data para string antes de serializar
        serializable_data = {}
        for m_key, m_info in months_data.items():
            serializable_data[m_key] = {
                "month_name": m_info["month_name"],
                "days": [
                    {k: (v.strftime("%Y-%m-%d") if isinstance(v, (date, datetime)) else v) for k, v in d_item.items()}
                    for d_item in m_info["days"]
                ],
                "trades_count": len(m_info["trades"]),
                "wins_count": len([t for t in m_info["trades"] if t["pts_liq"] > 0]),
                "losses_count": len([t for t in m_info["trades"] if t["pts_liq"] <= 0]),
                "points_liq": sum(t["pts_liq"] for t in m_info["trades"]),
                "pnl_1ct": sum(t["pnl_1ct"] for t in m_info["trades"]),
                "pnl_5ct": sum(t["pnl_5ct"] for t in m_info["trades"]),
            }
        json.dump(serializable_data, f, ensure_ascii=False, indent=2)

    print(f"\n[OK] Simulação completa concluída com sucesso! Resultados salvos em {json_path}")
    return months_data, all_trades


def get_pt_month_name(m: int) -> str:
    names = {
        1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
        5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
        9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro"
    }
    return names.get(m, f"Mês {m}")


if __name__ == "__main__":
    months_data, all_trades = run_simulation()
