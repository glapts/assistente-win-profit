"""
run_orchestrator.py
Serviço Daemon do Comitê Multi-Agente & Orquestrador de Mesa.
Roda em segundo plano, consolida os pareceres dos 3 agentes especialistas
(Macro, Cesta/DI e Sentinela) e atualiza 'data/runtime_state.json' a cada ciclo.
Alimenta os agentes em tempo real via DDE do Profit Pro (PETR4, VALE3, ITUB4, DI1F29, WSPZ26).
"""

import os
import sys
import time
import argparse
from datetime import datetime
from typing import Optional
import ctypes
from ctypes import wintypes

# Garante path do projeto
base_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base_dir)

from core.agents.macro_agent import MacroAgent
from core.agents.basket_agent import BasketAgent
from core.agents.sentinel_agent import SentinelAgent
from core.agents.orchestrator import Orchestrator
from core.harness.contracts import ExecutionMode
from core.smc import DynamicRangeManager, DynamicRangeState, M5CandleBuilder


class ProfitDDEPoller:
    """Poller DDE assíncrono para captura dos percentuais da Cesta e Macro do Profit Pro."""
    def __init__(self, service: str = "profitchart", topic: str = "cot"):
        self.service = service
        self.topic = topic
        self.user32 = ctypes.windll.user32
        self.CP_WINUNICODE = 1200
        self.XTYP_REQUEST = 0x00B0 | 0x2000
        self.CF_TEXT = 1
        self.id_inst = wintypes.DWORD(0)
        self.cb_func = None
        self.initialized = False
        self._init_dde()

    def _init_dde(self):
        try:
            WINSTA_ALL = 0x37F
            DESKTOP_ALL = 0x1FF
            hwinsta = self.user32.OpenWindowStationW("winsta0", False, WINSTA_ALL)
            if hwinsta:
                self.user32.SetProcessWindowStation(hwinsta)
            hdesk = self.user32.OpenDesktopW("default", 0, False, DESKTOP_ALL)
            if hdesk:
                self.user32.SetThreadDesktop(hdesk)

            PFNCALLBACK = ctypes.WINFUNCTYPE(ctypes.c_void_p, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
            self.cb_func = PFNCALLBACK(lambda *args: 0)
            res = self.user32.DdeInitializeW(ctypes.byref(self.id_inst), self.cb_func, 0, 0)
            self.initialized = (res == 0)
        except Exception:
            self.initialized = False

    def query(self, item_name: str) -> Optional[str]:
        if not self.initialized:
            return None
        try:
            hsz_srv = self.user32.DdeCreateStringHandleW(self.id_inst.value, self.service, self.CP_WINUNICODE)
            hsz_top = self.user32.DdeCreateStringHandleW(self.id_inst.value, self.topic, self.CP_WINUNICODE)
            hconv = self.user32.DdeConnect(self.id_inst.value, hsz_srv, hsz_top, None)
            val = None
            if hconv:
                hsz_item = self.user32.DdeCreateStringHandleW(self.id_inst.value, item_name, self.CP_WINUNICODE)
                pdw_res = wintypes.DWORD(0)
                hdata = self.user32.DdeClientTransaction(
                    None, 0, hconv, hsz_item, self.CF_TEXT, self.XTYP_REQUEST, 1000, ctypes.byref(pdw_res)
                )
                if hdata:
                    size = self.user32.DdeGetData(hdata, None, 0, 0)
                    if size > 0:
                        buf = ctypes.create_string_buffer(size)
                        self.user32.DdeGetData(hdata, buf, size, 0)
                        val = buf.value.decode('latin-1', errors='replace').strip()
                    self.user32.DdeFreeDataHandle(hdata)
                self.user32.DdeFreeStringHandle(self.id_inst.value, hsz_item)
                self.user32.DdeDisconnect(hconv)
            self.user32.DdeFreeStringHandle(self.id_inst.value, hsz_srv)
            self.user32.DdeFreeStringHandle(self.id_inst.value, hsz_top)
            return val
        except Exception:
            return None


def poll_profit_feed(poller: ProfitDDEPoller, basket: BasketAgent, macro: MacroAgent) -> Optional[float]:
    """Lê variações percentuais em tempo real, atualiza os agentes e retorna o último preço de WIN."""
    def parse_pct(val_str: Optional[str]) -> Optional[float]:
        if not val_str:
            return None
        try:
            clean = val_str.replace('%', '').replace('+', '').replace('.', '').replace(',', '.').strip()
            return float(clean)
        except ValueError:
            return None

    def parse_price(val_str: Optional[str]) -> Optional[float]:
        if not val_str:
            return None
        try:
            # ex: "178.960,00" ou "178960,00" -> 178960.0
            clean = val_str.replace('.', '').replace(',', '.').strip()
            return float(clean)
        except ValueError:
            return None

    # Mini-Índice B3 (WIN)
    ult_win = None
    for win_sym in ["WINZ26", "WIN", "INDZ26", "IND"]:
        raw_win = poller.query(f"{win_sym}.ULT")
        p = parse_price(raw_win)
        if p is not None and p > 1000.0:
            ult_win = p
            break

    # Blue Chips da Cesta
    for stock in ["VALE3", "PETR4", "ITUB4"]:
        raw = poller.query(f"{stock}.VAR")
        pct = parse_pct(raw)
        if pct is not None:
            basket.update_stock(stock, pct)

    # Curva de Juros DI (DI1F29 / DI1F31)
    raw_di29 = poller.query("DI1F29.VAR")
    pct_di29 = parse_pct(raw_di29)
    if pct_di29 is not None:
        # 1% de variação no DI equivale aprox a 10 bps
        basket.update_di("DI1F29", pct_di29 * 5.0)

    # Macro S&P 500 Futuro
    for sp_sym in ["WSPZ26", "WSP", "ISPZ26", "ISP"]:
        raw_sp = poller.query(f"{sp_sym}.VAR")
        raw_sp_ult = poller.query(f"{sp_sym}.ULT")
        pct_sp = parse_pct(raw_sp)
        ult_sp = parse_price(raw_sp_ult)
        if pct_sp is not None:
            macro.update_sp500(price=ult_sp or 6000.0, change_pct=pct_sp)
            break

    # Dólar Futuro (WDO / DOL)
    for wdo_sym in ["WDOZ26", "WDO", "DOLZ26", "DOL"]:
        raw_wdo = poller.query(f"{wdo_sym}.VAR")
        pct_wdo = parse_pct(raw_wdo)
        if pct_wdo is not None:
            macro.update_dxy(dxy_val=104.0, change_pct=pct_wdo)
            break

    return ult_win


def main():
    parser = argparse.ArgumentParser(description="Daemon do Comitê de Agentes e Orquestrador")
    parser.add_argument("--interval", type=int, default=10, help="Intervalo em segundos entre ciclos (padrão: 10s)")
    parser.add_argument("--mode", type=str, choices=["COPILOT", "FULL_AUTO"], default="COPILOT", help="Modo operacional")
    args = parser.parse_args()

    print("=" * 80)
    print("🧠 INICIANDO COMITÊ MULTI-AGENTE & ORQUESTRADOR DE MESA (ASSÍNCRONO)")
    print("=" * 80)
    print(" Agentes Ativos:")
    print("   1. Macro & Global (S&P 500, Treasuries, DXY, Calendário EUA)")
    print("   2. Cesta IBOV & Arbitragem (PETR4, VALE3, Bancos, Curva DI)")
    print("   3. Sentinela Político (Notícias de Brasília, Risco Fiscal, Black Swan)")
    print(f" Destino de Estado : data/runtime_state.json")
    print(f" Intervalo do Loop : {args.interval}s")
    print(f" Modo Configurado  : {args.mode}")
    print("=" * 80)

    macro = MacroAgent()
    basket = BasketAgent()
    sentinel = SentinelAgent()
    poller = ProfitDDEPoller()

    orchestrator = Orchestrator(
        macro_agent=macro,
        basket_agent=basket,
        sentinel_agent=sentinel,
        execution_mode=ExecutionMode(args.mode.upper())
    )

    dynamic_range_mgr = DynamicRangeManager()
    candle_builder = M5CandleBuilder()

    cycle_count = 0
    try:
        while True:
            cycle_count += 1
            now = datetime.now()
            
            # Atualiza Cesta, Macro e cotação de WIN via DDE
            ult_win = poll_profit_feed(poller, basket, macro)

            # Atualiza agregador M5 e avalia expansão de Dealing Range / Breakers
            if ult_win is not None:
                closed_m5 = candle_builder.update_tick(price=ult_win, timestamp=now)
                if closed_m5:
                    macro_op = macro.evaluate(now)
                    delta_est = 3500.0 if macro_op.bias == "BULLISH" else (-3500.0 if macro_op.bias == "BEARISH" else 0.0)
                    dynamic_range_mgr.on_candle_closed(
                        candle=closed_m5,
                        delta_15m=delta_est,
                        macro_veto_buy=macro_op.veto_buy,
                        macro_veto_sell=macro_op.veto_sell
                    )
            
            state = orchestrator.run_cycle(current_time=now)
            
            status_symbol = "🟢 OPERAÇÃO LIBERADA" if state.trading_enabled else "🔴 OPERAÇÃO BLOQUEADA"
            opinion_summary = f"Dir: {state.allowed_direction.value} | Confiança: {state.confidence_score*100:.0f}%"
            print(f"[{now.strftime('%H:%M:%S')}] Ciclo #{cycle_count:04d} | {status_symbol} | {opinion_summary}")

            # Log informativo do DynamicRangeManager
            niveis_atual = dynamic_range_mgr.cached_niveis
            if niveis_atual:
                dr = niveis_atual.dealing_range
                st_dr = dynamic_range_mgr.state.value
                standby_count = sum(1 for z in niveis_atual.zonas_fvg if getattr(z.status, 'value', str(z.status)) == "STANDBY_DEEP_PULLBACK")
                active_count = len(niveis_atual.zonas_fvg) - standby_count
                color_tag = "\033[1;36m" if st_dr == "EXPANSION_ACTIVE" else ("\033[1;33m" if st_dr == "BREAKER_PROMOTED" else "\033[1;32m")
                print(f"   {color_tag}[DYNAMIC RANGE: {st_dr}]\033[0m DR: Topo {dr.topo_estrutural:.0f} / Fundo {dr.fundo_estrutural:.0f} | 50% Eq: {dr.equilibrium_50:.0f} | Zonas Ativas: {active_count} (Standby: {standby_count})")
            if not state.trading_enabled:
                vetos = getattr(state, "active_vetos", [])
                if vetos:
                    for v in vetos:
                        print(f"   -> Motivo do Bloqueio: {v}")
                elif getattr(state.macro_regime, "lockout_reason", None):
                    print(f"   -> Motivo do Bloqueio: {state.macro_regime.lockout_reason}")
                else:
                    print(f"   -> Motivo do Bloqueio: Operação desabilitada pelas travas do sistema.")
            elif getattr(state, "active_vetos", []):
                for v in state.active_vetos:
                    print(f"   -> Alerta/Restrição: {v}")
            
            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\n[ORQUESTRADOR] Encerrando serviço a pedido do operador.")


if __name__ == "__main__":
    main()
