"""
feeds/csv_feed.py
Feed de Replay Histórico a partir de arquivos exportados ou Área de Transferência (Clipboard) do Nelogica Profit Pro.
Permite reproduzir candles reais de 1m ou períodos superiores sem alterar os algoritmos de trade.
Suporta Mini-Índice (WIN), Mini-Dólar (WDO) e Ações (VALE3).
"""

import os
import re
import csv
import time
import subprocess
from datetime import datetime, timedelta
from typing import List, Optional, Callable, Dict, Any

from feeds.base_feed import BaseMarketFeed, FeedHealth
from core.models import Candle, Trade, AggressorSide
from core.contract import TZ_BRASILIA, round_to_tick


def parse_brazilian_number(val_str: str) -> float:
    """Converte números formatados no padrão brasileiro (ex: 170.350,00 ou 5.470,50 ou 62,05) para float."""
    if not val_str:
        return 0.0
    s = val_str.strip().replace("R$", "").replace(" ", "")
    if "." in s and "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_profit_datetime(date_str: str, time_str: str = "") -> datetime:
    """
    Converte strings de data e hora do Profit Pro para datetime com fuso de Brasília.
    Aceita combinações como '30/10/2026 17:30', '30/10/2026' + '17:30:00', etc.
    """
    d_clean = date_str.strip()
    t_clean = time_str.strip()

    if " " in d_clean:
        parts = d_clean.split(" ", 1)
        d_clean = parts[0]
        if not t_clean:
            t_clean = parts[1]

    d_parts = re.split(r'[/.-]', d_clean)
    if len(d_parts) == 3:
        if len(d_parts[0]) == 4:  # YYYY-MM-DD
            year, month, day = int(d_parts[0]), int(d_parts[1]), int(d_parts[2])
        else:  # DD/MM/YYYY
            day, month = int(d_parts[0]), int(d_parts[1])
            year = int(d_parts[2])
            if year < 100:
                year += 2000
    else:
        now = datetime.now(TZ_BRASILIA)
        year, month, day = now.year, now.month, now.day

    t_parts = t_clean.split(":") if t_clean else []
    hour = int(t_parts[0]) if len(t_parts) > 0 and t_parts[0].isdigit() else 9
    minute = int(t_parts[1]) if len(t_parts) > 1 and t_parts[1].isdigit() else 0
    second = int(t_parts[2]) if len(t_parts) > 2 and t_parts[2].isdigit() else 0

    return datetime(year, month, day, hour, minute, second, tzinfo=TZ_BRASILIA)


def parse_raw_csv_text(raw_text: str) -> List[Dict[str, Any]]:
    """
    Identifica delimitador e colunas de texto exportado ou copiado do Profit Pro.
    Ordena cronologicamente os dados (do mais antigo ao mais recente).
    """
    loaded = []
    if not raw_text or not raw_text.strip():
        return loaded

    sample = raw_text[:4096]
    delim = "\t" if "\t" in sample else (";" if ";" in sample else ",")
    lines = raw_text.splitlines()
    reader = csv.reader(lines, delimiter=delim)

    headers = None
    col_map = {}

    for row in reader:
        if not row or not any(row):
            continue

        if headers is None:
            row_lower = [c.strip().lower() for c in row]
            if any("abertura" in c or "fechamento" in c or "data" in c for c in row_lower):
                headers = row_lower
                for idx, h in enumerate(headers):
                    if "data" in h:
                        col_map["data"] = idx
                    elif "hora" in h:
                        col_map["hora"] = idx
                    elif "abertura" in h:
                        col_map["open"] = idx
                    elif "máxima" in h or "maxima" in h:
                        col_map["high"] = idx
                    elif "mínima" in h or "minima" in h:
                        col_map["low"] = idx
                    elif "fechamento" in h or "último" in h or "ultimo" in h:
                        col_map["close"] = idx
                    elif "volume" in h:
                        col_map["volume"] = idx
                    elif "negócios" in h or "negocios" in h or "quantidade" in h or "trades" in h:
                        col_map["trades"] = idx
                continue
            # Detecção de exportação bruta sem cabeçalho do Profit Pro:
            # Padrão 1: ATIVO;DATA;HORA;ABERTURA;MÁXIMA;MÍNIMA;FECHAMENTO;VOLUME;QUANTIDADE
            elif len(row) >= 7 and ("/" in row[1] or "-" in row[1]) and (":" in row[2]):
                headers = ["ativo", "data", "hora", "abertura", "maxima", "minima", "fechamento", "volume", "trades"]
                col_map = {
                    "data": 1,
                    "hora": 2,
                    "open": 3,
                    "high": 4,
                    "low": 5,
                    "close": 6,
                    "volume": 7 if len(row) > 7 else -1,
                    "trades": 8 if len(row) > 8 else -1
                }
            # Padrão 2: DATA;HORA;ABERTURA;MÁXIMA;MÍNIMA;FECHAMENTO;VOLUME;QUANTIDADE
            elif len(row) >= 6 and ("/" in row[0] or "-" in row[0]) and (":" in row[1]):
                headers = ["data", "hora", "abertura", "maxima", "minima", "fechamento", "volume", "trades"]
                col_map = {
                    "data": 0,
                    "hora": 1,
                    "open": 2,
                    "high": 3,
                    "low": 4,
                    "close": 5,
                    "volume": 6 if len(row) > 6 else -1,
                    "trades": 7 if len(row) > 7 else -1
                }
            else:
                continue

        try:
            d_str = row[col_map.get("data", 0)] if "data" in col_map else ""
            t_str = row[col_map.get("hora", 1)] if "hora" in col_map else ""

            dt = parse_profit_datetime(d_str, t_str)
            open_p = parse_brazilian_number(row[col_map["open"]]) if "open" in col_map else 0.0
            high_p = parse_brazilian_number(row[col_map["high"]]) if "high" in col_map else open_p
            low_p = parse_brazilian_number(row[col_map["low"]]) if "low" in col_map else open_p
            close_p = parse_brazilian_number(row[col_map["close"]]) if "close" in col_map else open_p
            volume = parse_brazilian_number(row[col_map["volume"]]) if "volume" in col_map and col_map["volume"] < len(row) else 1000.0
            trades = int(parse_brazilian_number(row[col_map["trades"]])) if "trades" in col_map and col_map["trades"] < len(row) else 100

            if open_p > 0:
                loaded.append({
                    "timestamp": dt,
                    "open": round_to_tick(open_p),
                    "high": round_to_tick(high_p),
                    "low": round_to_tick(low_p),
                    "close": round_to_tick(close_p),
                    "volume": volume if volume > 0 else 1000.0,
                    "trades": trades if trades > 0 else 100
                })
        except Exception:
            continue

    loaded.sort(key=lambda x: x["timestamp"])
    return loaded


def get_windows_clipboard_text() -> str:
    """Obtém o conteúdo textual atual da Área de Transferência do Windows via PowerShell."""
    cmd = "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; Get-Clipboard"
    res = subprocess.run(
        ["powershell", "-NoProfile", "-Command", cmd],
        capture_output=True,
        text=True,
        encoding="latin-1",
        errors="replace"
    )
    return res.stdout or ""


def analyze_dataset_characteristics(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analisa os registros para identificar o ativo copiado e o tempo gráfico médio."""
    if not records:
        return {"asset_type": "UNKNOWN", "asset_label": "Desconhecido", "avg_price": 0.0, "timeframe_min": 1}

    sample_records = records[:min(50, len(records))]
    avg_price = sum(r["close"] for r in sample_records) / len(sample_records)

    if avg_price > 50000:
        asset_type = "WIN"
        asset_label = "Mini-Índice Futuro (WIN)"
    elif 1000 <= avg_price <= 15000:
        asset_type = "WDO"
        asset_label = "Mini-Dólar Futuro (WDO)"
    else:
        asset_type = "ACAO"
        asset_label = "Ações / Equities (ex: VALE3 / PETR4)"

    intervals = []
    for i in range(min(30, len(records) - 1)):
        diff = (records[i + 1]["timestamp"] - records[i]["timestamp"]).total_seconds() / 60.0
        if 0 < diff <= 120:
            intervals.append(diff)

    tf_min = 1
    if intervals:
        intervals.sort()
        median_diff = intervals[len(intervals) // 2]
        tf_min = int(round(median_diff))
        if tf_min < 1:
            tf_min = 1

    return {
        "asset_type": asset_type,
        "asset_label": asset_label,
        "avg_price": avg_price,
        "timeframe_min": tf_min
    }


class ProfitClipboardFeed(BaseMarketFeed):
    """
    Feed de Replay Histórico direto da memória RAM (Área de Transferência do Windows).
    Permite rodar o replay instantaneamente após clicar em 'Copiar estudos para o Excel' no Profit.
    """

    def __init__(self, symbol: str = "WINZ26", delay_seconds: float = 0.0):
        super().__init__(source_name="Profit Pro Clipboard Replay (Memória RAM)")
        self.symbol = symbol
        self.delay_seconds = delay_seconds
        self.records: List[Dict[str, Any]] = []
        self.is_connected = False

        self.health = FeedHealth(
            connected=False,
            source_name=self.source_name,
            latency_ms=0.0,
            is_flow_available=True,
            is_book_available=True
        )

    def connect(self) -> bool:
        clip_text = get_windows_clipboard_text()
        if not clip_text or len(clip_text.strip()) == 0:
            self.health.error_message = "Área de Transferência vazia. Clique em 'Copiar estudos para o Excel' no Profit Pro primeiro."
            return False

        self.records = parse_raw_csv_text(clip_text)
        if not self.records:
            self.health.error_message = "Nenhum registro de candle válido encontrado no Clipboard."
            return False

        self.is_connected = True
        self.health.connected = True
        self.health.error_message = ""
        return True

    def disconnect(self):
        self.is_connected = False
        self.health.connected = False

    def subscribe_symbol(self, symbol: str) -> bool:
        self.symbol = symbol
        return True

    def replay_all(self, on_step: Optional[Callable[[Candle, int, int], None]] = None):
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
                trades_count=rec["trades"],
                buy_volume=rec["volume"] * 0.55 if rec["close"] >= rec["open"] else rec["volume"] * 0.45,
                sell_volume=rec["volume"] * 0.45 if rec["close"] >= rec["open"] else rec["volume"] * 0.55,
                is_closed=True
            )

            if self.on_trade_callback:
                side = AggressorSide.BUY if c.close >= c.open else AggressorSide.SELL
                t = Trade(
                    trade_id=f"CLIP_{idx}",
                    timestamp=c.close_time,
                    price=c.close,
                    quantity=int(rec["volume"] / max(rec["trades"], 1)),
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

            if self.delay_seconds > 0:
                time.sleep(self.delay_seconds)


class ProfitCSVFeed(BaseMarketFeed):
    """
    Lê e reproduz cronologicamente arquivos de dados exportados do Profit Pro (CSV ou TXT).
    Gera candles de 1m e negócios associados, alimentando o motor SMC e fluxo.
    """

    def __init__(self, file_path: str, symbol: str = "WINZ26", delay_seconds: float = 0.0):
        super().__init__(source_name=f"Profit Pro CSV Replay ({os.path.basename(file_path)})")
        self.file_path = file_path
        self.symbol = symbol
        self.delay_seconds = delay_seconds
        self.records: List[Dict[str, Any]] = []
        self.current_index = 0
        self.is_connected = False

        self.health = FeedHealth(
            connected=False,
            source_name=self.source_name,
            latency_ms=0.0,
            is_flow_available=True,
            is_book_available=True
        )

    def connect(self) -> bool:
        if not os.path.exists(self.file_path):
            self.health.error_message = f"Arquivo não encontrado: {self.file_path}"
            return False

        with open(self.file_path, "r", encoding="utf-8-sig", errors="replace") as f:
            content = f.read()

        self.records = parse_raw_csv_text(content)
        if not self.records:
            self.health.error_message = f"Nenhum registro válido encontrado em: {self.file_path}"
            return False

        self.is_connected = True
        self.health.connected = True
        self.health.error_message = ""
        return True

    def disconnect(self):
        self.is_connected = False
        self.health.connected = False

    def subscribe_symbol(self, symbol: str) -> bool:
        self.symbol = symbol
        return True

    def replay_all(self, on_step: Optional[Callable[[Candle, int, int], None]] = None):
        """
        Executa todos os candles do arquivo CSV, despachando para os callbacks.
        """
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
                trades_count=rec["trades"],
                buy_volume=rec["volume"] * 0.55 if rec["close"] >= rec["open"] else rec["volume"] * 0.45,
                sell_volume=rec["volume"] * 0.45 if rec["close"] >= rec["open"] else rec["volume"] * 0.55,
                is_closed=True
            )

            if self.on_trade_callback:
                side = AggressorSide.BUY if c.close >= c.open else AggressorSide.SELL
                t = Trade(
                    trade_id=f"CSV_{idx}",
                    timestamp=c.close_time,
                    price=c.close,
                    quantity=int(rec["volume"] / max(rec["trades"], 1)),
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

            if self.delay_seconds > 0:
                time.sleep(self.delay_seconds)
