"""
batch_backtest.py
Módulo de Automação de Exportação e Teste em Lote (Batch Backtest) para o Mini-Índice B3 (WIN) e Mini-Dólar (WDO).
Executa replay histórico em múltiplos dias/arquivos CSV do Profit Pro com métricas institucionais completas:
- Separação e execução independente de cada pregão diário (09:00 às 17:55)
- Desconto conservador de Slippage (1 tick) e taxas oficiais B3 (emolumentos + registro)
- Resolução conservadora de barras com ambiguidade intrabar
- Zeragem compulsória de posições abertas no encerramento do pregão (17:50+)
- Relatório consolidado no terminal, arquivo resumo (.txt) e exportação de todos os trades (.csv)
- Ferramenta interativa de captura contínua via Clipboard e gerador de amostras
"""

import os
import sys
import csv
import time
import argparse
import subprocess
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict

# Garantir import dos módulos do projeto
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from feeds.base_feed import BaseMarketFeed, FeedHealth
from feeds.csv_feed import parse_raw_csv_text, get_windows_clipboard_text
from core.models import Candle, Trade, AggressorSide, Direction, SetupStatus
from core.engine import WinAnalysisAssistant
from core.contract import (
    get_current_win_contract,
    get_current_wdo_contract,
    resolve_symbol,
    get_asset_spec,
    calculate_financial_risk,
    round_to_tick,
    TZ_BRASILIA,
    WIN_SPEC
)


class MemoryReplayFeed(BaseMarketFeed):
    """Feed de replay em memória que alimenta o motor SMC a partir de lista de registros."""

    def __init__(self, symbol: str, records: List[Dict[str, Any]]):
        super().__init__(source_name="Batch Memory Feed")
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

    def replay_all(self, on_step: Optional[Any] = None):
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

            # Simular negócios de fluxo para aquecer o TapeReadingAnalyzer
            side = AggressorSide.BUY if c.close >= c.open else AggressorSide.SELL
            qty = max(1, int(rec["volume"] / max(rec.get("trades", 100), 1)))

            # Gerar 4 micro-ticks por minuto (open, min, max, close) para fluxo realista
            prices_seq = [c.open, c.low if side == AggressorSide.BUY else c.high,
                          c.high if side == AggressorSide.BUY else c.low, c.close]
            for step_i, p in enumerate(prices_seq):
                if self.on_trade_callback:
                    t = Trade(
                        trade_id=f"B_{idx}_{step_i}",
                        timestamp=c.open_time + timedelta(seconds=15 * (step_i + 1)),
                        price=p,
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


class BatchBacktestRunner:
    """Orquestrador do teste em lote de múltiplos pregões."""

    def __init__(
        self,
        symbol: Optional[str] = None,
        mode: str = "FIXO",
        slippage_points: float = 5.0,
        b3_roundtrip_cost: float = 0.60,
        contracts: int = 1
    ):
        self.symbol = resolve_symbol(symbol)
        self.spec = get_asset_spec(self.symbol)
        self.mode = mode.upper()
        self.slippage_points = slippage_points
        self.b3_roundtrip_cost = b3_roundtrip_cost
        self.contracts = contracts

        self.daily_results: List[Dict[str, Any]] = []
        self.all_trades: List[Dict[str, Any]] = []

    def simulate_session(self, session_date: date, candles: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Executa um único pregão diário de ponta a ponta."""
        candles_sorted = sorted(candles, key=lambda x: x["timestamp"])
        feed = MemoryReplayFeed(symbol=self.symbol, records=candles_sorted)
        assistant = WinAnalysisAssistant(feed=feed, symbol=self.symbol, mode=self.mode)
        # Desabilitar persistência em disco dos FVGs durante backtest para máxima velocidade
        assistant.fvg_scanner.auto_load = False
        assistant.start()

        session_trades: List[Dict[str, Any]] = []
        active_trade: Optional[Dict[str, Any]] = None

        def on_step(c: Candle, current_idx: int, total_idx: int):
            nonlocal active_trade

            # 1. Checar se estamos no fim do pregão e precisamos zerar compulsóriamente
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

                # Resolução estritamente conservadora para ambiguidade intrabar
                if hit_target and hit_stop:
                    pts_bruto = -pos["stop_points"]
                    pts_liq = pts_bruto - self.slippage_points
                    dur = int((c.close_time - pos["entry_time"]).total_seconds() / 60)
                    trade_record = {
                        "session_date": session_date.strftime("%d/%m/%Y"),
                        "entry_time": pos["entry_time"].strftime("%H:%M"),
                        "exit_time": c.close_time.strftime("%H:%M"),
                        "setup_name": pos["setup_name"],
                        "direction": pos["direction"].value,
                        "entry_price": pos["entry_price"],
                        "exit_price": pos["stop_price"],
                        "result": "STOP (AMBIGUIDADE)",
                        "points_bruto": pts_bruto,
                        "points_liquido": pts_liq,
                        "pnl_bruto_1ct": calculate_financial_risk(pts_bruto, 1, self.spec.point_value),
                        "pnl_liq_1ct": calculate_financial_risk(pts_liq, 1, self.spec.point_value) - self.b3_roundtrip_cost,
                        "pnl_liq_custom": calculate_financial_risk(pts_liq, self.contracts, self.spec.point_value) - (self.b3_roundtrip_cost * self.contracts),
                        "duration_min": max(1, dur)
                    }
                    session_trades.append(trade_record)
                    self.all_trades.append(trade_record)
                    active_trade = None

                elif hit_target:
                    pts_bruto = pos["target_points"]
                    pts_liq = pts_bruto - self.slippage_points
                    dur = int((c.close_time - pos["entry_time"]).total_seconds() / 60)
                    trade_record = {
                        "session_date": session_date.strftime("%d/%m/%Y"),
                        "entry_time": pos["entry_time"].strftime("%H:%M"),
                        "exit_time": c.close_time.strftime("%H:%M"),
                        "setup_name": pos["setup_name"],
                        "direction": pos["direction"].value,
                        "entry_price": pos["entry_price"],
                        "exit_price": pos["target_price"],
                        "result": "ALVO",
                        "points_bruto": pts_bruto,
                        "points_liquido": pts_liq,
                        "pnl_bruto_1ct": calculate_financial_risk(pts_bruto, 1, self.spec.point_value),
                        "pnl_liq_1ct": calculate_financial_risk(pts_liq, 1, self.spec.point_value) - self.b3_roundtrip_cost,
                        "pnl_liq_custom": calculate_financial_risk(pts_liq, self.contracts, self.spec.point_value) - (self.b3_roundtrip_cost * self.contracts),
                        "duration_min": max(1, dur)
                    }
                    session_trades.append(trade_record)
                    self.all_trades.append(trade_record)
                    active_trade = None

                elif hit_stop:
                    pts_bruto = -pos["stop_points"]
                    pts_liq = pts_bruto - self.slippage_points
                    dur = int((c.close_time - pos["entry_time"]).total_seconds() / 60)
                    trade_record = {
                        "session_date": session_date.strftime("%d/%m/%Y"),
                        "entry_time": pos["entry_time"].strftime("%H:%M"),
                        "exit_time": c.close_time.strftime("%H:%M"),
                        "setup_name": pos["setup_name"],
                        "direction": pos["direction"].value,
                        "entry_price": pos["entry_price"],
                        "exit_price": pos["stop_price"],
                        "result": "STOP",
                        "points_bruto": pts_bruto,
                        "points_liquido": pts_liq,
                        "pnl_bruto_1ct": calculate_financial_risk(pts_bruto, 1, self.spec.point_value),
                        "pnl_liq_1ct": calculate_financial_risk(pts_liq, 1, self.spec.point_value) - self.b3_roundtrip_cost,
                        "pnl_liq_custom": calculate_financial_risk(pts_liq, self.contracts, self.spec.point_value) - (self.b3_roundtrip_cost * self.contracts),
                        "duration_min": max(1, dur)
                    }
                    session_trades.append(trade_record)
                    self.all_trades.append(trade_record)
                    active_trade = None

                elif is_end_of_day:
                    # Zeragem compulsória no leilão / fechamento
                    if pos["direction"] == Direction.COMPRA:
                        pts_bruto = c.close - pos["entry_price"]
                    else:
                        pts_bruto = pos["entry_price"] - c.close
                    pts_liq = pts_bruto - self.slippage_points
                    dur = int((c.close_time - pos["entry_time"]).total_seconds() / 60)
                    res_tag = "ZERAGEM (GAIN)" if pts_liq > 0 else "ZERAGEM (LOSS)"
                    trade_record = {
                        "session_date": session_date.strftime("%d/%m/%Y"),
                        "entry_time": pos["entry_time"].strftime("%H:%M"),
                        "exit_time": c.close_time.strftime("%H:%M"),
                        "setup_name": pos["setup_name"],
                        "direction": pos["direction"].value,
                        "entry_price": pos["entry_price"],
                        "exit_price": c.close,
                        "result": res_tag,
                        "points_bruto": pts_bruto,
                        "points_liquido": pts_liq,
                        "pnl_bruto_1ct": calculate_financial_risk(pts_bruto, 1, self.spec.point_value),
                        "pnl_liq_1ct": calculate_financial_risk(pts_liq, 1, self.spec.point_value) - self.b3_roundtrip_cost,
                        "pnl_liq_custom": calculate_financial_risk(pts_liq, self.contracts, self.spec.point_value) - (self.b3_roundtrip_cost * self.contracts),
                        "duration_min": max(1, dur)
                    }
                    session_trades.append(trade_record)
                    self.all_trades.append(trade_record)
                    active_trade = None

            # 2. Se não estiver posicionado e antes das 17:00, avaliar setups SMC
            if not active_trade and not is_end_of_day and c.close_time.hour < 17:
                setup, status_msg = assistant.setup_engine.evaluate(
                    symbol=self.symbol,
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

        # Consolidar métricas do dia
        wins = [t for t in session_trades if t["points_liquido"] > 0]
        losses = [t for t in session_trades if t["points_liquido"] <= 0]
        tot_trades = len(session_trades)
        wr = (len(wins) / tot_trades * 100.0) if tot_trades > 0 else 0.0
        tot_pts_liq = sum(t["points_liquido"] for t in session_trades)
        tot_liq_1ct = sum(t["pnl_liq_1ct"] for t in session_trades)
        tot_liq_custom = sum(t["pnl_liq_custom"] for t in session_trades)

        session_summary = {
            "date": session_date,
            "date_str": session_date.strftime("%d/%m/%Y"),
            "candles_count": len(candles_sorted),
            "trades_count": tot_trades,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": wr,
            "points_liq": tot_pts_liq,
            "pnl_liq_1ct": tot_liq_1ct,
            "pnl_liq_custom": tot_liq_custom,
            "status": "POSITIVO" if tot_pts_liq > 0 else ("NEGATIVO" if tot_pts_liq < 0 else "NEUTRO")
        }
        self.daily_results.append(session_summary)
        return session_summary

    def run_all_sessions(self, sessions_map: Dict[date, List[Dict[str, Any]]]):
        """Executa todos os dias ordenados cronologicamente."""
        sorted_dates = sorted(sessions_map.keys())
        print(f"\nIniciando execução em lote de {len(sorted_dates)} pregões do ativo {self.symbol}...")
        print(f"Modo: {self.mode} | Slippage: {self.slippage_points} pts | Taxa B3: R$ {self.b3_roundtrip_cost:.2f} / trade")
        print("-" * 75)

        for idx, d in enumerate(sorted_dates, 1):
            candles = sessions_map[d]
            summary = self.simulate_session(d, candles)
            color_badge = "🟢" if summary["status"] == "POSITIVO" else ("🔴" if summary["status"] == "NEGATIVO" else "⚪")
            print(f"[{idx:02d}/{len(sorted_dates):02d}] {summary['date_str']} | {summary['candles_count']:3d} barras | Trades: {summary['trades_count']:2d} | WR: {summary['win_rate']:5.1f}% | Saldo: {summary['points_liq']:+6.0f} pts | R$ {summary['pnl_liq_1ct']:+8.2f} {color_badge}")

    def generate_report(self) -> str:
        """Gera o relatório quantitativo consolidado formatado."""
        if not self.daily_results:
            return "Nenhuma sessão processada."

        tot_sessions = len(self.daily_results)
        positive_days = len([d for d in self.daily_results if d["status"] == "POSITIVO"])
        negative_days = len([d for d in self.daily_results if d["status"] == "NEGATIVO"])
        neutral_days = len([d for d in self.daily_results if d["status"] == "NEUTRO"])
        pct_profitable_days = (positive_days / tot_sessions * 100.0) if tot_sessions > 0 else 0.0

        all_trades = self.all_trades
        tot_trades = len(all_trades)
        wins = [t for t in all_trades if t["points_liquido"] > 0]
        losses = [t for t in all_trades if t["points_liquido"] <= 0]
        global_wr = (len(wins) / tot_trades * 100.0) if tot_trades > 0 else 0.0

        tot_pts_bruto = sum(t["points_bruto"] for t in all_trades)
        tot_pts_liq = sum(t["points_liquido"] for t in all_trades)
        tot_pnl_1ct = sum(t["pnl_liq_1ct"] for t in all_trades)
        tot_pnl_custom = sum(t["pnl_liq_custom"] for t in all_trades)

        gross_profit_reais = sum(t["pnl_liq_1ct"] for t in wins)
        gross_loss_reais = abs(sum(t["pnl_liq_1ct"] for t in losses))
        profit_factor = (gross_profit_reais / gross_loss_reais) if gross_loss_reais > 0 else 999.0

        avg_win_pts = (sum(t["points_liquido"] for t in wins) / len(wins)) if wins else 0.0
        avg_loss_pts = (abs(sum(t["points_liquido"] for t in losses)) / len(losses)) if losses else 0.0
        payoff = (avg_win_pts / avg_loss_pts) if avg_loss_pts > 0 else 0.0
        ev_pts = (tot_pts_liq / tot_trades) if tot_trades > 0 else 0.0
        ev_reais = (tot_pnl_1ct / tot_trades) if tot_trades > 0 else 0.0

        # Cálculo do Max Drawdown da curva de capital (líquido 1 ct)
        equity = 0.0
        peak = 0.0
        max_dd_reais = 0.0
        for t in all_trades:
            equity += t["pnl_liq_1ct"]
            if equity > peak:
                peak = equity
            dd = peak - equity
            if dd > max_dd_reais:
                max_dd_reais = dd

        # Estatísticas por Setup
        setups_stat: Dict[str, Dict[str, Any]] = {}
        for t in all_trades:
            s_name = t["setup_name"]
            if s_name not in setups_stat:
                setups_stat[s_name] = {"trades": 0, "wins": 0, "losses": 0, "pts": 0.0, "pnl": 0.0}
            st = setups_stat[s_name]
            st["trades"] += 1
            if t["points_liquido"] > 0:
                st["wins"] += 1
            else:
                st["losses"] += 1
            st["pts"] += t["points_liquido"]
            st["pnl"] += t["pnl_liq_1ct"]

        lines = []
        lines.append("=" * 80)
        lines.append("  RELATÓRIO DE REPLAY EM LOTE & BACKTEST MULTI-SESSÕES (SMC + TAPE READING)")
        lines.append(f"  Ativo: {self.symbol} ({self.spec.name}) | Modo: {self.mode}")
        lines.append(f"  Custos Computados: Slippage {self.slippage_points} pts/trade + Taxas B3 R$ {self.b3_roundtrip_cost:.2f}/trade")
        lines.append("=" * 80)
        lines.append("")
        lines.append("1. RESUMO EXECUTIVO DIÁRIO:")
        lines.append("-" * 80)
        lines.append(f"{'Data':^10} | {'Barras':^6} | {'Trades':^6} | {'Vitórias':^8} | {'Derrotas':^8} | {'WR %':^6} | {'Saldo Pts':^10} | {'Líq. 1ct':^12}")
        lines.append("-" * 80)
        for d in self.daily_results:
            tag = "+" if d["points_liq"] > 0 else ""
            lines.append(f"{d['date_str']:^10} | {d['candles_count']:^6} | {d['trades_count']:^6} | {d['wins']:^8} | {d['losses']:^8} | {d['win_rate']:5.1f}% | {tag}{d['points_liq']:>8.0f} pts | R$ {d['pnl_liq_1ct']:>9.2f}")
        lines.append("-" * 80)
        lines.append("")

        lines.append("2. MÉTRICAS CONSOLIDADAS DE PERFORMANCE:")
        lines.append("-" * 80)
        lines.append(f"Total de Pregões Testados     : {tot_sessions} dias ({positive_days} Positivos | {negative_days} Negativos | {neutral_days} Neutros)")
        lines.append(f"Taxa de Dias Lucrativos        : {pct_profitable_days:.1f}%")
        lines.append(f"Total de Operações Disparadas  : {tot_trades} trades ({len(wins)} Alvos / {len(losses)} Stops)")
        lines.append(f"Média de Trades por Pregão    : {(tot_trades / tot_sessions):.1f} trades/dia")
        lines.append(f"Taxa de Acerto Global (WinRate): {global_wr:.1f}% (Breakeven R:R 1.6 é 38.5%)")
        lines.append(f"Saldo Total em Pontos (Bruto)  : {tot_pts_bruto:+,.0f} pontos")
        lines.append(f"Saldo Total em Pontos (Líquido): {tot_pts_liq:+,.0f} pontos (com {self.slippage_points} pts de derrapagem)")
        lines.append(f"Resultado Líquido (1 contrato) : R$ {tot_pnl_1ct:+,.2f}")
        lines.append(f"Resultado Líquido ({self.contracts:2d} contratos): R$ {tot_pnl_custom:+,.2f}")
        lines.append(f"Fator de Lucro (Profit Factor) : {profit_factor:.2f}")
        lines.append(f"Relação Payoff (Gain / Loss)   : {payoff:.2f}")
        lines.append(f"Expectativa Matemática / Trade : {ev_pts:+.1f} pontos | R$ {ev_reais:+.2f} por trade")
        lines.append(f"Drawdown Máximo Estimado       : R$ {max_dd_reais:,.2f} ({max_dd_reais / (self.spec.point_value):,.0f} pts)")
        lines.append("-" * 80)
        lines.append("")

        lines.append("3. DETALHAMENTO DE PERFORMANCE POR SETUP SMC:")
        lines.append("-" * 80)
        lines.append(f"{'Setup SMC':<38} | {'Trades':^6} | {'WR %':^6} | {'Saldo Pts':^10} | {'Líq. 1ct':^12}")
        lines.append("-" * 80)
        for s_name, st in sorted(setups_stat.items(), key=lambda x: x[1]["pts"], reverse=True):
            s_wr = (st["wins"] / st["trades"] * 100.0) if st["trades"] > 0 else 0.0
            tag = "+" if st["pts"] > 0 else ""
            lines.append(f"{s_name[:38]:<38} | {st['trades']:^6} | {s_wr:5.1f}% | {tag}{st['pts']:>8.0f} pts | R$ {st['pnl']:>9.2f}")
        lines.append("-" * 80)

        # 4. RESUMO MÊS A MÊS (CONSOLIDAÇÃO MENSAL)
        months_stat = defaultdict(lambda: {"days": 0, "trades": 0, "wins": 0, "losses": 0, "pts": 0.0, "pnl_1ct": 0.0, "pnl_5ct": 0.0})
        month_names = {
            1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril", 5: "Maio", 6: "Junho",
            7: "Julho", 8: "Agosto", 9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro"
        }
        for d in self.daily_results:
            m_key = (d["date"].year, d["date"].month)
            months_stat[m_key]["days"] += 1
            months_stat[m_key]["trades"] += d["trades_count"]
            months_stat[m_key]["wins"] += d["wins"]
            months_stat[m_key]["losses"] += d["losses"]
            months_stat[m_key]["pts"] += d["points_liq"]
            months_stat[m_key]["pnl_1ct"] += d["pnl_liq_1ct"]
            months_stat[m_key]["pnl_5ct"] += (d["points_liq"] * self.spec.point_value * 5) - (self.b3_roundtrip_cost * 5 * d["trades_count"])

        lines.append("")
        lines.append("4. RESUMO CONSOLIDADO MÊS A MÊS:")
        lines.append("-" * 95)
        lines.append(f"{'Mês / Ano':<16} | {'Pregões':^7} | {'Trades':^6} | {'Gains':^6} | {'Stops':^6} | {'WR %':^6} | {'Saldo Pts':^11} | {'Líq. 1ct':^13} | {'Líq. 5cts'}")
        lines.append("-" * 95)
        for (y, m), mst in sorted(months_stat.items()):
            m_wr = (mst["wins"] / mst["trades"] * 100.0) if mst["trades"] > 0 else 0.0
            tag = "+" if mst["pts"] > 0 else ""
            m_label = f"{month_names.get(m, str(m))} / {y}"
            lines.append(f"{m_label:<16} | {mst['days']:^7} | {mst['trades']:^6} | {mst['wins']:^6} | {mst['losses']:^6} | {m_wr:5.1f}% | {tag}{mst['pts']:>9.0f} pts | R$ {mst['pnl_1ct']:>10.2f} | R$ {mst['pnl_5ct']:>10.2f}")
        lines.append("-" * 95)
        lines.append("=" * 95)

        return "\n".join(lines)

    def export_to_files(self, output_dir: str = "data/relatorios") -> Tuple[str, str]:
        """Salva resumo em .txt e base de trades em .csv."""
        os.makedirs(output_dir, exist_ok=True)
        ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        txt_path = os.path.join(output_dir, f"relatorio_lote_{ts_str}.txt")
        csv_path = os.path.join(output_dir, f"trades_lote_{ts_str}.csv")

        # 1. Salvar relatório resumo
        report_text = self.generate_report()
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(report_text)

        # 2. Salvar histórico individual de trades
        fieldnames = [
            "session_date", "entry_time", "exit_time", "setup_name", "direction",
            "entry_price", "exit_price", "result", "points_bruto", "points_liquido",
            "pnl_bruto_1ct", "pnl_liq_1ct", "pnl_liq_custom", "duration_min"
        ]
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
            writer.writeheader()
            for t in self.all_trades:
                writer.writerow(t)

        return txt_path, csv_path


# ==============================================================================
# UTILITÁRIOS DE INGESTÃO, CLIPBOARD E GERAÇÃO DE SESSÕES HISTÓRICAS
# ==============================================================================

# Feriados Nacionais e B3 (fixos e móveis)
B3_FIXED_HOLIDAYS = {
    (1, 1),    # Confraternização Universal
    (4, 21),   # Tiradentes
    (5, 1),    # Dia do Trabalho
    (9, 7),    # Independência do Brasil
    (10, 12),  # Nossa Senhora Aparecida
    (11, 2),   # Finados (Mercado B3 Fechado)
    (11, 15),  # Proclamação da República
    (11, 20),  # Dia da Consciência Negra
    (12, 24),  # Véspera de Natal (Sem pregão)
    (12, 25),  # Natal
    (12, 31),  # Último dia útil do ano (Sem pregão)
}


def is_b3_holiday(d: date) -> bool:
    """Verifica se a data é feriado oficial no Brasil com pregão fechado na B3."""
    if (d.month, d.day) in B3_FIXED_HOLIDAYS:
        return True
    # Feriados móveis 2026
    if d.year == 2026 and d in {date(2026, 2, 16), date(2026, 2, 17), date(2026, 4, 3), date(2026, 6, 4)}:
        return True
    # Feriados móveis 2027
    if d.year == 2027 and d in {date(2027, 2, 8), date(2027, 2, 9), date(2027, 3, 26), date(2027, 5, 27)}:
        return True
    return False


def load_and_group_csv_files(file_path: Optional[str] = None, dir_path: Optional[str] = None) -> Dict[date, List[Dict[str, Any]]]:
    """Carrega arquivos CSV e agrupa todos os candles de 1m por data de pregão."""
    sessions_map: Dict[date, List[Dict[str, Any]]] = {}
    files_to_read = []

    if file_path and os.path.exists(file_path):
        if os.path.isdir(file_path):
            for root, _, files in os.walk(file_path):
                for f in files:
                    if f.lower().endswith((".csv", ".txt")):
                        files_to_read.append(os.path.join(root, f))
        else:
            files_to_read.append(file_path)
    elif dir_path and os.path.exists(dir_path):
        for root, _, files in os.walk(dir_path):
            for f in files:
                if f.lower().endswith((".csv", ".txt")):
                    files_to_read.append(os.path.join(root, f))

    if not files_to_read:
        return sessions_map

    for fp in files_to_read:
        try:
            with open(fp, "r", encoding="utf-8-sig", errors="replace") as f:
                content = f.read()
            records = parse_raw_csv_text(content)
            for r in records:
                d = r["timestamp"].date()
                if d not in sessions_map:
                    sessions_map[d] = []
                sessions_map[d].append(r)
        except Exception as e:
            print(f"[AVISO] Erro ao ler arquivo {fp}: {e}")

    # Ordenar candles dentro de cada dia
    for d in sessions_map:
        sessions_map[d].sort(key=lambda x: x["timestamp"])

    return sessions_map


def interactive_clipboard_collector(output_dir: str = "data/historico"):
    """
    Coletor interativo via Clipboard: o usuário copia o gráfico no Profit Pro
    e o script salva automaticamente em arquivos individuais por data.
    """
    os.makedirs(output_dir, exist_ok=True)
    print("\n" + "=" * 70)
    print("COLETOR INTELIGENTE DE PREGÕES VIA CLIPBOARD (PROFIT PRO)")
    print("=" * 70)
    print("Como usar:")
    print(" 1. Abra o Profit Pro em qualquer dia no gráfico de 1 Minuto.")
    print(" 2. Clique com botão direito no gráfico -> Exportar -> Copiar estudos para o Excel.")
    print(" 3. O script detecta automaticamente a data e salva na pasta:")
    print(f"    {os.path.abspath(output_dir)}")
    print(" 4. Repita para quantos dias desejar!")
    print(" 5. Pressione [ENTER] quando terminar para rodar o teste em lote.")
    print("=" * 70 + "\n")

    captured_days = set()

    while True:
        prompt = input("Pressione [C] + ENTER para capturar agora (ou [ENTER] para finalizar e testar): ").strip().upper()
        if prompt != "C":
            break

        clip_text = get_windows_clipboard_text()
        if not clip_text or len(clip_text.strip()) == 0:
            print("  [!] Área de Transferência vazia! Copie os estudos no Profit primeiro.\n")
            continue

        records = parse_raw_csv_text(clip_text)
        if not records:
            print("  [!] Não foi possível reconhecer o padrão de candles do Profit no Clipboard.\n")
            continue

        # Agrupar datas presentes no clipboard
        dates_in_clip = set(r["timestamp"].date() for r in records)
        for d in dates_in_clip:
            day_records = [r for r in records if r["timestamp"].date() == d]
            day_records.sort(key=lambda x: x["timestamp"])
            fname = f"WIN_{d.strftime('%Y_%m_%d')}.csv"
            save_path = os.path.join(output_dir, fname)

            with open(save_path, "w", encoding="utf-8") as f:
                f.write("Data;Hora;Abertura;Máxima;Mínima;Fechamento;Volume;Quantidade\n")
                for r in day_records:
                    t = r["timestamp"]
                    f.write(f"{t.strftime('%d/%m/%Y')};{t.strftime('%H:%M:%S')};{r['open']:.0f};{r['high']:.0f};{r['low']:.0f};{r['close']:.0f};{r['volume']:.0f};{r['trades']}\n")

            captured_days.add(d)
            print(f"  [OK] Pregão de {d.strftime('%d/%m/%Y')} salvo com sucesso: {fname} ({len(day_records)} candles)!")
        print("")

    print(f"\nColeta finalizada! Total de dias capturados nesta sessão: {len(captured_days)}.")


def generate_sample_sessions(num_days: int = 5, output_dir: str = "data/historico") -> Dict[date, List[Dict[str, Any]]]:
    """
    Gera dias sintéticos com dinâmica B3 realista (gaps, tendências, sweeps de liquidez e FVGs)
    para validação imediata do algoritmo em lote.
    """
    import random
    os.makedirs(output_dir, exist_ok=True)
    random.seed(1234)

    sessions_map: Dict[date, List[Dict[str, Any]]] = {}
    base_date = datetime(2026, 11, 2, 9, 0, 0, tzinfo=TZ_BRASILIA)

    print(f"\nGerando {num_days} pregões de amostra realistas em {output_dir}...")

    current_dt = base_date
    generated_days = 0

    while generated_days < num_days:
        session_d = current_dt.date()
        if current_dt.weekday() < 5 and not is_b3_holiday(session_d):  # Segunda a Sexta e NÃO feriado B3
            base_price = 170000.0 + (generated_days * 350.0) + random.randint(-400, 400)
            base_price = round_to_tick(base_price)

            day_records = []
            curr_p = base_price

            # 480 minutos de pregão (09:00 até 17:00)
            for m in range(480):
                t = current_dt + timedelta(minutes=m)
                # Alternância de micro-tendências com sweep e consolidação
                if m < 45:  # Abertura volátil
                    trend = 0.35 if (generated_days % 2 == 0) else -0.35
                elif m < 180:  # Tendência matinal
                    trend = 0.20 if (m % 60 < 35) else -0.25
                elif m < 300:  # Almoço / consolidação
                    trend = 0.05 if (m % 20 < 10) else -0.05
                else:  # Tarde institucional
                    trend = -0.30 if (generated_days % 2 == 0) else 0.30

                # Deslocamento
                drift = (trend * 25.0) + random.randint(-20, 20)
                op = curr_p
                cl = round_to_tick(op + drift)
                hi = round_to_tick(max(op, cl) + random.randint(10, 60))
                lo = round_to_tick(min(op, cl) - random.randint(10, 60))
                curr_p = cl

                day_records.append({
                    "timestamp": t,
                    "open": op,
                    "high": hi,
                    "low": lo,
                    "close": cl,
                    "volume": float(random.randint(80000, 350000)),
                    "trades": random.randint(800, 3500)
                })

            sessions_map[session_d] = day_records

            # Salvar CSV para reutilização futura
            fname = f"WIN_SAMPLE_{session_d.strftime('%Y_%m_%d')}.csv"
            save_path = os.path.join(output_dir, fname)
            with open(save_path, "w", encoding="utf-8") as f:
                f.write("Data;Hora;Abertura;Máxima;Mínima;Fechamento;Volume;Quantidade\n")
                for r in day_records:
                    t = r["timestamp"]
                    f.write(f"{t.strftime('%d/%m/%Y')};{t.strftime('%H:%M:%S')};{r['open']:.0f};{r['high']:.0f};{r['low']:.0f};{r['close']:.0f};{r['volume']:.0f};{r['trades']}\n")

            generated_days += 1

        current_dt += timedelta(days=1)

    print(f"[OK] {num_days} pregões gerados e salvos com sucesso na pasta de histórico!\n")
    return sessions_map


# ==============================================================================
# PONTO DE ENTRADA CLI
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(description="Automação de Exportação e Teste em Lote (Batch Backtest) — Mini-Índice B3")
    parser.add_argument("--dir", type=str, default="data/historico", help="Pasta contendo os arquivos CSV de histórico (padrão: data/historico)")
    parser.add_argument("--file", type=str, default=None, help="Caminho de um arquivo CSV específico ou multi-dias do Profit Pro")
    parser.add_argument("--mode", choices=["FIXO", "ESTRUTURAL"], default="FIXO", help="Modo de Stop e Alvo (FIXO ou ESTRUTURAL)")
    parser.add_argument("--symbol", type=str, default=None, help="Ticker do contrato ou ativo (ex: WIN, WDO, WINZ26, WDOZ26)")
    parser.add_argument("--contracts", type=int, default=5, help="Quantidade de contratos para projeção financeira secundária (padrão: 5)")
    parser.add_argument("--slippage", type=float, default=5.0, help="Derrapagem em pontos por operação (padrão: 5.0 pts / 1 tick)")
    parser.add_argument("--collect-clipboard", action="store_true", help="Abre o coletor contínuo de pregões a partir da Área de Transferência")
    parser.add_argument("--generate-samples", type=int, default=0, help="Gera N dias de amostra sintética realista e executa o teste")

    args = parser.parse_args()

    # Modo 1: Coleta interativa de Clipboard
    if args.collect_clipboard:
        interactive_clipboard_collector(output_dir=args.dir)

    # Modo 2: Geração de amostras sob demanda
    if args.generate_samples > 0:
        sessions_map = generate_sample_sessions(num_days=args.generate_samples, output_dir=args.dir)
    else:
        # Carregar arquivos da pasta ou do arquivo especificado
        sessions_map = load_and_group_csv_files(file_path=args.file, dir_path=args.dir)

    # Se a pasta estiver vazia e nenhum arquivo fornecido, sugerir geração de amostras
    if not sessions_map:
        print("\n" + "=" * 70)
        print("NENHUM DADO HISTÓRICO ENCONTRADO!")
        print("=" * 70)
        print(f"A pasta '{os.path.abspath(args.dir)}' não contém arquivos CSV do Profit.")
        print("\nVocê tem 3 opções simples:")
        print(" 1. Gerar 5 dias de amostras para testar o script agora mesmo:")
        print("    python batch_backtest.py --generate-samples 5")
        print("\n 2. Copiar dados do Profit Pro para o Excel e capturar automaticamente:")
        print("    python batch_backtest.py --collect-clipboard")
        print("\n 3. Exportar um CSV de múltiplos dias no Profit Pro e rodar:")
        print("    python batch_backtest.py --file 'caminho/do/seu_arquivo.csv'")
        print("=" * 70 + "\n")
        return

    # Executar Backtest em Lote
    runner = BatchBacktestRunner(
        symbol=args.symbol,
        mode=args.mode,
        slippage_points=args.slippage,
        contracts=args.contracts
    )
    runner.run_all_sessions(sessions_map)

    # Exibir Relatório Completo
    report_text = runner.generate_report()
    print("\n" + report_text)

    # Salvar Arquivos
    txt_path, csv_path = runner.export_to_files()
    print(f"\n[OK] Relatório executivo salvo em : {txt_path}")
    print(f"[OK] Planilha detalhada de trades : {csv_path}\n")


if __name__ == "__main__":
    main()
