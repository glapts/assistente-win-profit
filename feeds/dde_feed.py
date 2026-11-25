"""
feeds/dde_feed.py
Conector nativo DDE (Dynamic Data Exchange) para o Nelogica Profit Pro.
Lê as cotações em tempo real do serviço 'profitchart' e tópico 'cot'.
Arquitetura thread-safe: DdeInitialize e DdeConnect executados na mesma thread de polling.
"""

import ctypes
from ctypes import wintypes
import time
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict

from feeds.base_feed import BaseMarketFeed, FeedHealth
from core.models import Candle, Trade, AggressorSide
from core.contract import TZ_BRASILIA, round_to_tick


# DDE Constants
CP_WINUNICODE = 1200
XTYP_REQUEST = 0x00B0 | 0x2000
CF_TEXT = 1
TIMEOUT_MS = 2000

PFNCALLBACK = ctypes.WINFUNCTYPE(
    ctypes.c_void_p, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
)


class ProfitDDEFeed(BaseMarketFeed):
    """
    Feed oficial DDE do Nelogica Profit Pro.
    Garante que a inicialização e o loop DDEML residam na mesma thread Win32.
    """

    def __init__(self, service_name: str = "profitchart", topic_name: str = "cot"):
        super().__init__(source_name="Nelogica ProfitPro (DDE)")
        self.service_name = service_name
        self.topic_name = topic_name
        
        self.symbol: Optional[str] = None
        self.running: bool = False
        self.worker_thread: Optional[threading.Thread] = None
        
        # Windows API
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32
        
        # Valores em cache
        self.last_price: float = 0.0
        self.last_open: float = 0.0
        self.last_high: float = 0.0
        self.last_low: float = 0.0

    def connect(self) -> bool:
        """Marca conexão como pronta para a thread."""
        self.health.connected = True
        return True

    def subscribe_symbol(self, symbol: str) -> bool:
        self.symbol = symbol.upper()
        if not self.running:
            self.running = True
            self.worker_thread = threading.Thread(target=self._worker_thread_run, daemon=True)
            self.worker_thread.start()
        return True

    def _worker_thread_run(self):
        """Thread dedicada que mantém a instância DDE ativa no Windows."""
        # Anexar à desktop interativa
        WINSTA_ALL = 0x37F
        DESKTOP_ALL = 0x1FF
        hwinsta = self.user32.OpenWindowStationW("winsta0", False, WINSTA_ALL)
        if hwinsta:
            self.user32.SetProcessWindowStation(hwinsta)
            hdesk = self.user32.OpenDesktopW("default", 0, False, DESKTOP_ALL)
            if hdesk:
                self.user32.SetThreadDesktop(hdesk)

        def dde_cb(*args):
            return 0

        cb_func = PFNCALLBACK(dde_cb)
        id_inst = wintypes.DWORD(0)
        res = self.user32.DdeInitializeW(ctypes.byref(id_inst), cb_func, 0, 0)
        if res != 0:
            self.health.connected = False
            self.health.error_message = f"DdeInitializeW falhou na thread: {res}"
            return

        hsz_srv = self.user32.DdeCreateStringHandleW(id_inst.value, self.service_name, CP_WINUNICODE)
        hsz_top = self.user32.DdeCreateStringHandleW(id_inst.value, self.topic_name, CP_WINUNICODE)

        # Tentar conectar ao DDE com resiliência a inicialização do Profit Pro
        hconv = None
        while self.running and not hconv:
            hconv = self.user32.DdeConnect(id_inst.value, hsz_srv, hsz_top, None)
            if not hconv:
                err = self.user32.DdeGetLastError(id_inst.value)
                self.health.connected = False
                self.health.error_message = (
                    f"Aguardando transmissão DDE do Profit Pro ('{self.service_name}|{self.topic_name}')..."
                )
                time.sleep(1.5)
            else:
                self.health.connected = True
                self.health.error_message = ""

        if not self.running or not hconv:
            self.user32.DdeFreeStringHandle(id_inst.value, hsz_srv)
            self.user32.DdeFreeStringHandle(id_inst.value, hsz_top)
            self.user32.DdeUninitialize(id_inst.value)
            return

        def query_item(item_name: str) -> Optional[str]:
            hsz_item = self.user32.DdeCreateStringHandleW(id_inst.value, item_name, CP_WINUNICODE)
            pdw_res = wintypes.DWORD(0)
            hdata = self.user32.DdeClientTransaction(
                None, 0, hconv, hsz_item, CF_TEXT, XTYP_REQUEST, TIMEOUT_MS, ctypes.byref(pdw_res)
            )
            val = None
            if hdata:
                size = self.user32.DdeGetData(hdata, None, 0, 0)
                if size > 0:
                    buf = ctypes.create_string_buffer(size)
                    self.user32.DdeGetData(hdata, buf, size, 0)
                    val = buf.value.decode('latin-1', errors='replace').strip()
                self.user32.DdeFreeDataHandle(hdata)
            self.user32.DdeFreeStringHandle(id_inst.value, hsz_item)
            return val

        # Estado de agregação minuto a minuto e Tape Reading incremental
        active_1m_candle: Optional[Candle] = None
        current_minute_tag: Optional[int] = None
        last_vol_c: float = 0.0
        last_vol_v: float = 0.0

        # Loop contínuo de polling na mesma thread
        while self.running:
            try:
                t0 = time.perf_counter()
                now = datetime.now(TZ_BRASILIA)

                val_str = query_item(f"{self.symbol}.ULT")
                t1 = time.perf_counter()
                self.health.latency_ms = (t1 - t0) * 1000.0
                self.health.last_received_time = now

                if val_str:
                    try:
                        clean_val = val_str.replace('.', '').replace(',', '.')
                        price = float(clean_val)
                        self.last_price = price
                        self.health.last_event_time = now
                        self.health.error_message = ""

                        # Ler métricas de sessão do Profit Pro
                        raw_abe = query_item(f"{self.symbol}.ABE")
                        raw_max = query_item(f"{self.symbol}.MAX")
                        raw_min = query_item(f"{self.symbol}.MIN")
                        raw_neg = query_item(f"{self.symbol}.NEG")
                        raw_agr_c = query_item(f"{self.symbol}.AGRVOLC")
                        raw_agr_v = query_item(f"{self.symbol}.AGRVOLV")

                        open_p = float(raw_abe.replace('.', '').replace(',', '.')) if raw_abe else price
                        high_p = float(raw_max.replace('.', '').replace(',', '.')) if raw_max else price
                        low_p = float(raw_min.replace('.', '').replace(',', '.')) if raw_min else price
                        trades_count = int(float(raw_neg.replace('.', '').replace(',', '.'))) if raw_neg else 0
                        vol_c = float(raw_agr_c.replace('.', '').replace(',', '.')) if raw_agr_c else 0.0
                        vol_v = float(raw_agr_v.replace('.', '').replace(',', '.')) if raw_agr_v else 0.0

                        self.last_open = open_p
                        self.last_high = high_p
                        self.last_low = low_p

                        # Delta e Tape Reading incremental (sem distorção de acumulação diária)
                        delta_c = 0.0
                        delta_v = 0.0
                        if last_vol_c > 0 and vol_c >= last_vol_c:
                            delta_c = vol_c - last_vol_c
                        if last_vol_v > 0 and vol_v >= last_vol_v:
                            delta_v = vol_v - last_vol_v
                        last_vol_c = vol_c
                        last_vol_v = vol_v

                        if delta_c > 0 or delta_v > 0:
                            self.health.is_flow_available = True
                            if self.on_trade_callback:
                                if delta_c > 0:
                                    self.on_trade_callback(Trade("DDE_BUY", now, price, int(delta_c), AggressorSide.BUY))
                                if delta_v > 0:
                                    self.on_trade_callback(Trade("DDE_SELL", now, price, int(delta_v), AggressorSide.SELL))

                        # Agregação determinística de candles de 1m alinhada ao relógio
                        min_tag = (now.hour * 60) + now.minute
                        if current_minute_tag is None:
                            current_minute_tag = min_tag
                            active_1m_candle = Candle(
                                timeframe=1,
                                open_time=now,
                                close_time=now,
                                open=price,
                                high=price,
                                low=price,
                                close=price,
                                volume=delta_c + delta_v,
                                trades_count=1,
                                buy_volume=delta_c,
                                sell_volume=delta_v,
                                is_closed=False
                            )
                        elif min_tag != current_minute_tag:
                            # O minuto anterior acabou de encerrar -> fechar e despachar barra de 1m (apenas sessão regular >= 09:00)
                            if active_1m_candle is not None:
                                active_1m_candle.is_closed = True
                                active_1m_candle.close_time = now
                                if self.on_candle_callback and active_1m_candle.open_time.hour >= 9:
                                    self.on_candle_callback(active_1m_candle)

                            # Abrir novo candle de 1m para o minuto atual
                            current_minute_tag = min_tag
                            active_1m_candle = Candle(
                                timeframe=1,
                                open_time=now,
                                close_time=now,
                                open=price,
                                high=price,
                                low=price,
                                close=price,
                                volume=delta_c + delta_v,
                                trades_count=1,
                                buy_volume=delta_c,
                                sell_volume=delta_v,
                                is_closed=False
                            )
                        else:
                            # Atualizar candle intrabar de 1m
                            if active_1m_candle is not None:
                                active_1m_candle.high = max(active_1m_candle.high, price)
                                active_1m_candle.low = min(active_1m_candle.low, price)
                                active_1m_candle.close = price
                                active_1m_candle.close_time = now
                                active_1m_candle.volume += (delta_c + delta_v)
                                active_1m_candle.buy_volume += delta_c
                                active_1m_candle.sell_volume += delta_v
                                active_1m_candle.trades_count += 1

                    except ValueError:
                        pass
                else:
                    self.health.error_message = (
                        "Aguardando transmissão do ativo pelo Profit Pro."
                    )

            except Exception as e:
                self.health.error_message = f"Erro no poll DDE: {e}"

            time.sleep(1.0)

        # Encerramento na thread
        self.user32.DdeDisconnect(hconv)
        self.user32.DdeFreeStringHandle(id_inst.value, hsz_srv)
        self.user32.DdeFreeStringHandle(id_inst.value, hsz_top)
        self.user32.DdeUninitialize(id_inst.value)
        self.health.connected = False

    def _query_item(self, item_name: str, timeout_ms: int = 400) -> Optional[str]:
        """Consulta síncrona sob demanda para ferramentas como scan-dde."""
        WINSTA_ALL = 0x37F
        DESKTOP_ALL = 0x1FF
        hwinsta = self.user32.OpenWindowStationW("winsta0", False, WINSTA_ALL)
        if hwinsta:
            self.user32.SetProcessWindowStation(hwinsta)
            hdesk = self.user32.OpenDesktopW("default", 0, False, DESKTOP_ALL)
            if hdesk:
                self.user32.SetThreadDesktop(hdesk)

        # Se chamada fora da thread, cria contexto rápido
        id_inst = wintypes.DWORD(0)
        cb_func = PFNCALLBACK(lambda *args: 0)
        self.user32.DdeInitializeW(ctypes.byref(id_inst), cb_func, 0, 0)
        hsz_srv = self.user32.DdeCreateStringHandleW(id_inst.value, self.service_name, CP_WINUNICODE)
        hsz_top = self.user32.DdeCreateStringHandleW(id_inst.value, self.topic_name, CP_WINUNICODE)
        hconv = self.user32.DdeConnect(id_inst.value, hsz_srv, hsz_top, None)
        val = None
        if hconv:
            hsz_item = self.user32.DdeCreateStringHandleW(id_inst.value, item_name, CP_WINUNICODE)
            pdw_res = wintypes.DWORD(0)
            hdata = self.user32.DdeClientTransaction(
                None, 0, hconv, hsz_item, CF_TEXT, XTYP_REQUEST, timeout_ms, ctypes.byref(pdw_res)
            )
            if hdata:
                size = self.user32.DdeGetData(hdata, None, 0, 0)
                if size > 0:
                    buf = ctypes.create_string_buffer(size)
                    self.user32.DdeGetData(hdata, buf, size, 0)
                    val = buf.value.decode('latin-1', errors='replace').strip()
                self.user32.DdeFreeDataHandle(hdata)
            self.user32.DdeFreeStringHandle(id_inst.value, hsz_item)
            self.user32.DdeDisconnect(hconv)
        self.user32.DdeFreeStringHandle(id_inst.value, hsz_srv)
        self.user32.DdeFreeStringHandle(id_inst.value, hsz_top)
        self.user32.DdeUninitialize(id_inst.value)
        return val

    def disconnect(self):
        self.running = False
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=2.0)
        self.health.connected = False
