"""
run_scalper_glaucio.py
========================================================================================
EXECUTOR INTERATIVO POWERSHELL: Módulo ScalperGlaucio
Monitora o Mini-Índice B3 em tempo real (via DDE do Profit Pro) ou em modo Replay.
========================================================================================
Uso:
  python run_scalper_glaucio.py --replay --date 2026-11-23
  python run_scalper_glaucio.py --live
========================================================================================
"""

import sys
import os
import argparse
import time
import json
from datetime import datetime, date, time as dt_time

base_dir = os.path.dirname(os.path.abspath(__file__))
if base_dir not in sys.path:
    sys.path.insert(0, base_dir)

from core.smc.scalper_glaucio import (
    ScalperGlaucio,
    ScalperSignal,
    ANSI_RESET,
    ANSI_BOLD,
    ANSI_GREEN,
    ANSI_RED,
    ANSI_CYAN,
    ANSI_YELLOW
)
from core.contract import get_current_win_contract, resolve_symbol


def save_signal_to_json(sig: ScalperSignal):
    """Persiste os sinais para auditoria e histórico."""
    out_dir = os.path.join(base_dir, "data")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "sinais_scalper_glaucio.json")

    signals = []
    if os.path.exists(out_path):
        try:
            with open(out_path, "r", encoding="utf-8") as f:
                signals = json.load(f)
        except Exception:
            signals = []

    record = {
        "timestamp": sig.timestamp.isoformat(),
        "signal_type": sig.signal_type,
        "direction": sig.direction,
        "candle_ids": sig.candle_ids,
        "trigger_candle_id": sig.trigger_candle_id,
        "ce_50": sig.ce_50,
        "target_price": sig.target_price,
        "stop_price": sig.stop_price,
        "gap_size": sig.gap_size,
        "trend_day": sig.trend_day,
        "description": sig.description,
        "candle_times": sig.candle_times,
        "trigger_candle_time": sig.trigger_candle_time
    }
    signals.append(record)

    # Gravação atômica
    tmp_path = out_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(signals, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, out_path)


def run_replay(target_date_str: str, file_path: str):
    """Executa replay sobre arquivo Excel do Profit Pro."""
    import openpyxl

    target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
    print(f"\n{ANSI_CYAN}{'='*88}{ANSI_RESET}")
    print(f"{ANSI_BOLD}[ScalperGlaucio] - INICIANDO MODO REPLAY HISTÓRICO: {target_date.strftime('%d/%m/%Y')}{ANSI_RESET}")
    print(f"{ANSI_CYAN}Arquivo base: {file_path}{ANSI_RESET}")
    print(f"{ANSI_CYAN}{'='*88}{ANSI_RESET}\n")

    if not os.path.exists(file_path):
        print(f"{ANSI_RED}[ERRO] Arquivo não encontrado: {file_path}{ANSI_RESET}")
        return

    wb = openpyxl.load_workbook(file_path, read_only=True)
    sheet = wb.active

    candles = []
    for r in sheet.iter_rows(values_only=True):
        if r[0] and isinstance(r[0], datetime) and r[0].date() == target_date:
            candles.append({
                "time": r[0],
                "open": float(r[1]),
                "high": float(r[2]),
                "low": float(r[3]),
                "close": float(r[4])
            })

    candles.sort(key=lambda x: x["time"])
    print(f"[REPLAY] {len(candles)} candles de 1m carregados para {target_date.strftime('%d/%m/%Y')}.\n")

    scalper = ScalperGlaucio(
        min_gap_pts=5.0,
        target_pts=100.0,
        stop_pts=150.0,
        filter_trend=True,
        beep_on_signal=False, # Sem beep no replay em lote
        on_signal_callback=save_signal_to_json
    )

    total_signals = 0
    for c in candles:
        sigs = scalper.on_candle_closed(
            timestamp=c["time"],
            open_price=c["open"],
            high_price=c["high"],
            low_price=c["low"],
            close_price=c["close"],
            volume=100.0
        )
        total_signals += len(sigs)

    print(f"{ANSI_CYAN}{'='*88}{ANSI_RESET}")
    print(f"{ANSI_BOLD}[REPLAY CONCLUÍDO] Total de Sinais Emitidos: {total_signals}{ANSI_RESET}")
    print(f"{ANSI_CYAN}{'='*88}{ANSI_RESET}\n")


def run_live(symbol: str, open_time_str: str = "09:03"):
    """Executa ao vivo conectando-se ao Profit Pro via DDE com poller dedicado de baixa latência (< 50ms)."""
    from feeds.dde_feed import ProfitDDEFeed

    # Parse do horário de abertura para sincronização determinística de barras
    parsed_open = None
    try:
        parts = [int(p) for p in open_time_str.split(":")]
        parsed_open = dt_time(parts[0], parts[1])
    except Exception:
        parsed_open = dt_time(9, 3)

    print(f"\n{ANSI_GREEN}{'='*88}{ANSI_RESET}")
    print(f"{ANSI_BOLD}[ScalperGlaucio] - MODO LIVE ATIVO: NELOGICA PROFIT PRO (POLLER LEVE DEDICADO){ANSI_RESET}")
    print(f"{ANSI_GREEN}Ativo: {symbol} | Gaps >= 5 pts | Alvo: +100 pts | Stop: -150 pts | Abertura: {parsed_open.strftime('%H:%M')}{ANSI_RESET}")
    print(f"{ANSI_GREEN}{'='*88}{ANSI_RESET}\n")

    scalper = ScalperGlaucio(
        min_gap_pts=5.0,
        target_pts=100.0,
        stop_pts=150.0,
        filter_trend=True,
        beep_on_signal=True,
        on_signal_callback=save_signal_to_json,
        market_open_time=parsed_open
    )

    feed = ProfitDDEFeed(
        lightweight_mode=True,
        market_open_time=parsed_open
    )

    def on_candle_event(candle):
        tf = str(candle.timeframe).lower()
        if tf in ("1", "1m"):
            ts = getattr(candle, "close_time", getattr(candle, "timestamp", datetime.now()))
            scalper.on_candle_closed(
                timestamp=ts,
                open_price=candle.open,
                high_price=candle.high,
                low_price=candle.low,
                close_price=candle.close,
                volume=candle.volume
            )

    feed.set_callbacks(on_candle=on_candle_event)

    try:
        feed.connect()
        feed.subscribe_symbol(symbol)
        print(f"[ScalperGlaucio] Conexão DDE estabelecida com sucesso. Poller leve ativo (< 50ms). Aguardando barras...\n")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[ScalperGlaucio] Encerrando monitoramento...")
    finally:
        feed.disconnect()


def main():
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="Módulo ScalperGlaucio - SMC 1 Minuto no WIN B3")
    parser.add_argument("--live", action="store_true", help="Executa conectado ao vivo no Profit via DDE")
    parser.add_argument("--replay", action="store_true", help="Executa replay de arquivo histórico")
    parser.add_argument("--date", type=str, default="2026-11-23", help="Data do replay (YYYY-MM-DD)")
    parser.add_argument("--file", type=str, default="C:/Users/glaci/Downloads/1.imagens/winz26_ohlcv_atual.xlsx", help="Caminho do arquivo Excel")
    parser.add_argument("--symbol", type=str, default=None, help="Ticker do contrato (ex: WINZ26)")
    parser.add_argument("--open-time", type=str, default="09:03", help="Horário da primeira barra negociada pós-leilão (padrão 09:03)")

    args = parser.parse_args()
    symbol = resolve_symbol(args.symbol)

    if args.replay or not args.live:
        run_replay(args.date, args.file)
    else:
        run_live(symbol, args.open_time)


if __name__ == "__main__":
    main()
