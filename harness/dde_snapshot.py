"""
harness/dde_snapshot.py
Coletor e normalizador DDE de alta performance para a lista HARNESS_WIN do Profit Pro.
Monitora 10 ativos B3, mapeia as 15 colunas do menu Cotações, mantém buffer circular
dos últimos 20 snapshots e calcula métricas instantâneas de Book e Fluxo com fallback automático.
"""

import ctypes
from ctypes import wintypes
import time
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
import zoneinfo

# Fuso horário oficial de Brasília
TZ_BRASILIA = zoneinfo.ZoneInfo("America/Sao_Paulo")

# Ativos homologados da grade HARNESS_WIN
HARNESS_WIN_ASSETS = [
    "WINZ26",
    "WINFUT",
    "WDOZ26",
    "WDOFUT",
    "DI1F29",
    "DI1F31",
    "ITUB4",
    "PETR4",
    "VALE3",
    "WSPZ26"
]

# 15 Colunas oficiais mapeadas do Profit Pro (menu Cotações)
PROFIT_COLUMNS_CANONICAL = [
    "ultimo",
    "abertura",
    "maximo",
    "minimo",
    "variacao",
    "negocios",
    "quantidade",
    "of_compra",
    "of_venda",
    "voc",
    "vov",
    "agr_compra",
    "agr_venda",
    "saldo_agressao",
    "lote_padrao"
]

# Mapa de sinônimos/mnemônicos aceitos para cada uma das 15 colunas
COLUMN_SYNONYMS: Dict[str, List[str]] = {
    "ultimo": ["ultimo", "último", "ult", "val", "last", "cotacao", "cotação"],
    "abertura": ["abertura", "abe", "open"],
    "maximo": ["maximo", "máximo", "max", "high"],
    "minimo": ["minimo", "mínimo", "min", "low"],
    "variacao": ["variacao", "variação", "var", "varpts"],
    "negocios": ["negocios", "negócios", "neg", "trades", "n_trades"],
    "quantidade": ["quantidade", "qtd", "vol", "volf", "volume"],
    "of_compra": ["of_compra", "of.compra", "ofcompra", "ocp", "melhor_c", "ofe_c_pre", "bid"],
    "of_venda": ["of_venda", "of.venda", "ofvenda", "ovd", "melhor_v", "ofe_v_pre", "ask"],
    "voc": ["voc", "vol_compra", "ofe_c_qtd", "qtd_compra", "bid_qty", "bid_vol"],
    "vov": ["vov", "vol_venda", "ofe_v_qtd", "qtd_venda", "ask_qty", "ask_vol"],
    "agr_compra": ["agr_compra", "agr. compra", "agr.compra", "agrvolc", "agr_c", "aggressor_buy"],
    "agr_venda": ["agr_venda", "agr. venda", "agr.venda", "agrvolv", "agr_v", "aggressor_sell"],
    "saldo_agressao": ["saldo_agressao", "saldo de agressao", "saldo de agressão", "agrsaldo", "saldo_agr", "delta_agr"],
    "lote_padrao": ["lote_padrao", "lote padrão", "lotepadrao", "lote", "lot", "round_lot"]
}

# Inverte o mapa de sinônimos para lookup rápido O(1)
_LOOKUP_SYNONYMS: Dict[str, str] = {}
for canonical, synonyms in COLUMN_SYNONYMS.items():
    for syn in synonyms:
        _LOOKUP_SYNONYMS[syn.lower().replace(".", "").replace(" ", "").replace("_", "")] = canonical


def normalize_column_name(raw_name: str) -> Optional[str]:
    """Converte qualquer variação de rótulo ou código DDE para o nome canônico."""
    if not raw_name:
        return None
    clean = str(raw_name).strip().lower().replace(".", "").replace(" ", "").replace("_", "")
    return _LOOKUP_SYNONYMS.get(clean)


import re

def parse_ptbr_float(val: Any) -> float:
    """
    Converte com segurança valores PT-BR ('165.920,00' -> 165920.0, '1.800' -> 1800.0),
    tratando células vazias, valores herdados e erros DDE sem lançar exceções.
    """
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        if isinstance(val, float) and (val != val or val == float('inf') or val == float('-inf')):
            return 0.0
        return float(val)

    s = str(val).strip()
    if not s:
        return 0.0

    upper = s.upper()
    if upper in ("-", "--", "---", "#N/D", "#VALOR!", "#VALOR", "N/A", "N/D", "NONE", "NULL", "ERR", "ND"):
        return 0.0
    if any(err in upper for err in ["#N/D", "#VALOR", "N/A", "NONE", "NULL", "ERR"]):
        return 0.0

    # Limpar caracteres de formatação monetária e percentual
    s = s.replace('%', '').replace('R$', '').replace('$', '').strip()

    try:
        if ',' in s and '.' in s:
            # Formato brasileiro completo: 165.920,00
            s = s.replace('.', '').replace(',', '.')
            return float(s)
        elif ',' in s:
            # Formato brasileiro com decimais: 14,25 ou -0,35
            s = s.replace(',', '.')
            return float(s)
        elif '.' in s:
            # Se for separador de milhar brasileiro (ex: 1.800 ou 150.000)
            if re.match(r'^[+-]?\d{1,3}(?:\.\d{3})+$', s):
                s = s.replace('.', '')
                return float(s)
            else:
                # Formato decimal padrão: 12.45 ou 5.5
                return float(s)
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def parse_ptbr_int(val: Any) -> int:
    """Converte valor PT-BR para inteiro arredondado com segurança."""
    return int(round(parse_ptbr_float(val)))


@dataclass
class AssetSnapshot:
    """Snapshot normalizado de um ativo individual com as 15 colunas DDE e deltas instantâneos."""
    symbol: str
    timestamp: datetime
    ultimo: float = 0.0
    abertura: float = 0.0
    maximo: float = 0.0
    minimo: float = 0.0
    variacao: float = 0.0
    negocios: int = 0
    quantidade: float = 0.0
    of_compra: float = 0.0
    of_venda: float = 0.0
    voc: float = 0.0
    vov: float = 0.0
    agr_compra: float = 0.0
    agr_venda: float = 0.0
    saldo_agressao: float = 0.0
    lote_padrao: int = 1

    # Deltas calculados em relação ao snapshot anterior no histórico
    delta_voc: float = 0.0
    delta_vov: float = 0.0
    delta_negocios: int = 0
    delta_quantidade: float = 0.0

    raw_values: Dict[str, str] = field(default_factory=dict)

    def is_valid(self) -> bool:
        """Determina se o ativo possui cotação e negócios válidos no pregão atual."""
        return self.ultimo > 0.0 and (self.negocios > 0 or self.quantidade > 0.0 or self.of_compra > 0.0)


@dataclass
class HarnessFullSnapshot:
    """Contém a fotografia completa de todos os 10 ativos da grade HARNESS_WIN em um dado instante."""
    timestamp: datetime
    assets: Dict[str, AssetSnapshot] = field(default_factory=dict)
    active_win_symbol: str = "WINZ26"
    active_wdo_symbol: str = "WDOZ26"


class DdeSnapshotCollector:
    """
    Coletor e normalizador DDE de alta performance.
    - Mantém conexões Win32 thread-safe com 'profitchart|cot'.
    - Opera com buffer circular dos últimos 20 snapshots (`history`).
    - Resolve dinamicamente fallbacks (WINZ26 -> WINFUT; WDOZ26 -> WDOFUT).
    - Suporta injeção de dados direta para testes determinísticos sem depender de Profit aberto.
    """

    # DDE Win32 Constants
    CP_WINUNICODE = 1200
    XTYP_REQUEST = 0x00B0 | 0x2000
    CF_TEXT = 1
    TIMEOUT_MS = 1500

    def __init__(self, service_name: str = "profitchart", topic_name: str = "cot", max_history: int = 20):
        self.service_name = service_name
        self.topic_name = topic_name
        self.max_history = max_history

        # Buffer circular dos últimos 20 snapshots completos
        self.history: deque[HarnessFullSnapshot] = deque(maxlen=max_history)

        # Últimos snapshots individuais conhecidos por ativo
        self.latest_assets: Dict[str, AssetSnapshot] = {}

        # Fallbacks ativos
        self.active_win_symbol: str = "WINZ26"
        self.active_wdo_symbol: str = "WDOZ26"

        self._lock = threading.Lock()
        self.is_connected: bool = False
        self.last_poll_time: Optional[datetime] = None
        self.last_error: str = ""

        # Inicializa estruturas vazias seguras para os 10 ativos
        now = datetime.now(TZ_BRASILIA)
        for sym in HARNESS_WIN_ASSETS:
            self.latest_assets[sym] = AssetSnapshot(symbol=sym, timestamp=now)

    def resolve_active_win(self) -> str:
        """
        Determina se utiliza o contrato específico 'WINZ26' ou o perpétuo 'WINFUT'.
        Fallback automático caso 'WINZ26' esteja vazio, zerado ou vencido.
        """
        snap_winz = self.latest_assets.get("WINZ26")
        snap_winfut = self.latest_assets.get("WINFUT")

        if snap_winz and snap_winz.is_valid():
            self.active_win_symbol = "WINZ26"
        elif snap_winfut and snap_winfut.is_valid():
            self.active_win_symbol = "WINFUT"
        else:
            # Se ambos estiverem sem dados ou pré-mercado, preserva WINZ26 como primário
            self.active_win_symbol = "WINZ26"
        return self.active_win_symbol

    def resolve_active_wdo(self) -> str:
        """
        Determina se utiliza o contrato específico 'WDOZ26' ou o perpétuo 'WDOFUT'.
        Fallback automático caso 'WDOZ26' esteja vazio, zerado ou vencido.
        """
        snap_wdoz = self.latest_assets.get("WDOZ26")
        snap_wdofut = self.latest_assets.get("WDOFUT")

        if snap_wdoz and snap_wdoz.is_valid():
            self.active_wdo_symbol = "WDOZ26"
        elif snap_wdofut and snap_wdofut.is_valid():
            self.active_wdo_symbol = "WDOFUT"
        else:
            self.active_wdo_symbol = "WDOZ26"
        return self.active_wdo_symbol

    def ingest_raw_snapshot(self, raw_data_by_symbol: Dict[str, Dict[str, Any]], timestamp: Optional[datetime] = None) -> HarnessFullSnapshot:
        """
        Ponto central de ingestão de dados (compatível com DDE ao vivo, Mock de testes ou CSV).
        Normaliza os campos das 15 colunas, calcula deltas instantâneos contra o histórico
        e atualiza o buffer circular de 20 posições.
        """
        now = timestamp or datetime.now(TZ_BRASILIA)
        new_assets: Dict[str, AssetSnapshot] = {}

        with self._lock:
            # Processa cada um dos 10 ativos da grade
            for symbol in HARNESS_WIN_ASSETS:
                sym_upper = symbol.upper()
                raw_dict = raw_data_by_symbol.get(sym_upper, {})
                prev_snap = self.latest_assets.get(sym_upper)

                # Dicionário temporário para os valores normalizados
                parsed_vals: Dict[str, Any] = {col: 0.0 for col in PROFIT_COLUMNS_CANONICAL}
                parsed_vals["negocios"] = 0
                parsed_vals["lote_padrao"] = 1

                raw_strings: Dict[str, str] = {}

                # Varre os campos recebidos mapeando pelos sinônimos
                for raw_col, val in raw_dict.items():
                    raw_strings[str(raw_col)] = str(val)
                    canon_col = normalize_column_name(str(raw_col))
                    if canon_col:
                        if canon_col in ("negocios", "lote_padrao"):
                            parsed_vals[canon_col] = parse_ptbr_int(val)
                        else:
                            parsed_vals[canon_col] = parse_ptbr_float(val)

                # Se a cotação estiver zerada no payload atual, preserva os valores anteriores conhecidos
                if parsed_vals["ultimo"] <= 0.0 and prev_snap and prev_snap.ultimo > 0.0:
                    for col in PROFIT_COLUMNS_CANONICAL:
                        if parsed_vals.get(col, 0.0) == 0.0:
                            parsed_vals[col] = getattr(prev_snap, col, 0.0)

                # Cálculo determinístico dos deltas instantâneos em relação ao snapshot anterior
                delta_voc = 0.0
                delta_vov = 0.0
                delta_neg = 0
                delta_qtd = 0.0

                if prev_snap is not None and prev_snap.is_valid():
                    delta_voc = parsed_vals["voc"] - prev_snap.voc
                    delta_vov = parsed_vals["vov"] - prev_snap.vov
                    delta_neg = parsed_vals["negocios"] - prev_snap.negocios
                    delta_qtd = parsed_vals["quantidade"] - prev_snap.quantidade

                snap = AssetSnapshot(
                    symbol=sym_upper,
                    timestamp=now,
                    ultimo=parsed_vals["ultimo"],
                    abertura=parsed_vals["abertura"],
                    maximo=parsed_vals["maximo"],
                    minimo=parsed_vals["minimo"],
                    variacao=parsed_vals["variacao"],
                    negocios=parsed_vals["negocios"],
                    quantidade=parsed_vals["quantidade"],
                    of_compra=parsed_vals["of_compra"],
                    of_venda=parsed_vals["of_venda"],
                    voc=parsed_vals["voc"],
                    vov=parsed_vals["vov"],
                    agr_compra=parsed_vals["agr_compra"],
                    agr_venda=parsed_vals["agr_venda"],
                    saldo_agressao=parsed_vals["saldo_agressao"],
                    lote_padrao=parsed_vals["lote_padrao"],
                    delta_voc=delta_voc,
                    delta_vov=delta_vov,
                    delta_negocios=delta_neg,
                    delta_quantidade=delta_qtd,
                    raw_values=raw_strings
                )

                new_assets[sym_upper] = snap
                self.latest_assets[sym_upper] = snap

            # Atualiza fallbacks automáticos
            active_win = self.resolve_active_win()
            active_wdo = self.resolve_active_wdo()

            full_snap = HarnessFullSnapshot(
                timestamp=now,
                assets=new_assets,
                active_win_symbol=active_win,
                active_wdo_symbol=active_wdo
            )

            # Insere no buffer circular de 20 snapshots
            self.history.append(full_snap)
            self.last_poll_time = now

            return full_snap

    def get_win_book_metrics(self) -> Dict[str, Any]:
        """
        Extrai e computa as métricas de Book L2 do ativo ativo do WIN (WINZ26 ou WINFUT fallback):
        - of_compra, of_venda, spread_pts, voc, vov,
        - imbalance_compra_pct, imbalance_venda_pct, ratio_voc_vov,
        - delta_voc e delta_vov.
        """
        with self._lock:
            active_sym = self.resolve_active_win()
            snap = self.latest_assets.get(active_sym)
            if snap is None:
                snap = AssetSnapshot(symbol=active_sym, timestamp=datetime.now(TZ_BRASILIA))

            of_compra = snap.of_compra
            of_venda = snap.of_venda
            voc = snap.voc
            vov = snap.vov

            # Cálculo do Spread em pontos
            spread_pts = 0.0
            if of_compra > 0.0 and of_venda > 0.0:
                spread_pts = round(abs(of_venda - of_compra), 2)

            # Imbalance percentual do topo do livro (0% a 100%)
            total_vo = voc + vov
            if total_vo > 0.0:
                imbalance_compra_pct = round((voc / total_vo) * 100.0, 2)
                imbalance_venda_pct = round((vov / total_vo) * 100.0, 2)
            else:
                imbalance_compra_pct = 50.0
                imbalance_venda_pct = 50.0

            # Razão entre ordens de compra e venda (VOC / VOV)
            if vov > 0.0:
                ratio_voc_vov = round(voc / vov, 3)
            else:
                ratio_voc_vov = 999.0 if voc > 0.0 else 1.0

            return {
                "active_symbol": active_sym,
                "of_compra": of_compra,
                "of_venda": of_venda,
                "spread_pts": spread_pts,
                "voc": voc,
                "vov": vov,
                "imbalance_compra_pct": imbalance_compra_pct,
                "imbalance_venda_pct": imbalance_venda_pct,
                "ratio_voc_vov": ratio_voc_vov,
                "delta_voc": snap.delta_voc,
                "delta_vov": snap.delta_vov
            }

    def get_latest_asset(self, symbol: str) -> Optional[AssetSnapshot]:
        """Retorna o snapshot mais recente de um ativo específico."""
        with self._lock:
            return self.latest_assets.get(symbol.upper())

    def get_active_win_snapshot(self) -> AssetSnapshot:
        """Retorna o snapshot atual do ativo WIN selecionado (WINZ26 ou WINFUT)."""
        with self._lock:
            sym = self.resolve_active_win()
            return self.latest_assets.get(sym, AssetSnapshot(symbol=sym, timestamp=datetime.now(TZ_BRASILIA)))

    def get_active_wdo_snapshot(self) -> AssetSnapshot:
        """Retorna o snapshot atual do ativo WDO selecionado (WDOZ26 ou WDOFUT)."""
        with self._lock:
            sym = self.resolve_active_wdo()
            return self.latest_assets.get(sym, AssetSnapshot(symbol=sym, timestamp=datetime.now(TZ_BRASILIA)))

    def poll_profit_dde_live(self) -> HarnessFullSnapshot:
        """
        Executa uma rodada completa de leitura síncrona nos 10 ativos da grade HARNESS_WIN
        diretamente via Win32 DDEML (User32.dll) no Profit Pro ('profitchart|cot').
        Não bloqueia a execução em caso de ausência de conexão.
        """
        raw_results: Dict[str, Dict[str, Any]] = {sym: {} for sym in HARNESS_WIN_ASSETS}

        try:
            user32 = ctypes.windll.user32
            WINSTA_ALL = 0x37F
            DESKTOP_ALL = 0x1FF
            hwinsta = user32.OpenWindowStationW("winsta0", False, WINSTA_ALL)
            if hwinsta:
                user32.SetProcessWindowStation(hwinsta)
                hdesk = user32.OpenDesktopW("default", 0, False, DESKTOP_ALL)
                if hdesk:
                    user32.SetThreadDesktop(hdesk)

            PFNCALLBACK = ctypes.WINFUNCTYPE(
                ctypes.c_void_p, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
            )
            cb_func = PFNCALLBACK(lambda *args: 0)
            id_inst = wintypes.DWORD(0)
            res = user32.DdeInitializeW(ctypes.byref(id_inst), cb_func, 0, 0)
            if res != 0:
                self.is_connected = False
                self.last_error = f"DdeInitializeW falhou: {res}"
                return self.ingest_raw_snapshot(raw_results)

            hsz_srv = user32.DdeCreateStringHandleW(id_inst.value, self.service_name, self.CP_WINUNICODE)
            hsz_top = user32.DdeCreateStringHandleW(id_inst.value, self.topic_name, self.CP_WINUNICODE)
            hconv = user32.DdeConnect(id_inst.value, hsz_srv, hsz_top, None)

            if not hconv:
                self.is_connected = False
                self.last_error = f"Profit Pro DDE '{self.service_name}|{self.topic_name}' offline ou aguardando abertura."
                user32.DdeFreeStringHandle(id_inst.value, hsz_srv)
                user32.DdeFreeStringHandle(id_inst.value, hsz_top)
                user32.DdeUninitialize(id_inst.value)
                return self.ingest_raw_snapshot(raw_results)

            self.is_connected = True
            self.last_error = ""

            # Consulta os campos DDE para cada um dos 10 ativos
            fields_to_query = [
                ("ULT", "ultimo"),
                ("ABE", "abertura"),
                ("MAX", "maximo"),
                ("MIN", "minimo"),
                ("VAR", "variacao"),
                ("NEG", "negocios"),
                ("VOL", "quantidade"),
                ("OCP", "of_compra"),
                ("OVD", "of_venda"),
                ("VOC", "voc"),
                ("VOV", "vov"),
                ("AGRVOLC", "agr_compra"),
                ("AGRVOLV", "agr_venda"),
                ("AGRSALDO", "saldo_agressao"),
                ("LOTEPADRAO", "lote_padrao")
            ]

            pdw_res = wintypes.DWORD(0)

            for sym in HARNESS_WIN_ASSETS:
                for dde_tag, canon_col in fields_to_query:
                    item_name = f"{sym}.{dde_tag}"
                    hsz_item = user32.DdeCreateStringHandleW(id_inst.value, item_name, self.CP_WINUNICODE)
                    hdata = user32.DdeClientTransaction(
                        None, 0, hconv, hsz_item, self.CF_TEXT, self.XTYP_REQUEST, self.TIMEOUT_MS, ctypes.byref(pdw_res)
                    )
                    if hdata:
                        size = user32.DdeGetData(hdata, None, 0, 0)
                        if size > 0:
                            buf = ctypes.create_string_buffer(size)
                            user32.DdeGetData(hdata, buf, size, 0)
                            val_str = buf.value.decode('latin-1', errors='replace').strip()
                            raw_results[sym][canon_col] = val_str
                        user32.DdeFreeDataHandle(hdata)
                    user32.DdeFreeStringHandle(id_inst.value, hsz_item)

            user32.DdeDisconnect(hconv)
            user32.DdeFreeStringHandle(id_inst.value, hsz_srv)
            user32.DdeFreeStringHandle(id_inst.value, hsz_top)
            user32.DdeUninitialize(id_inst.value)

        except Exception as e:
            self.is_connected = False
            self.last_error = f"Erro no poll DDE: {e}"

        return self.ingest_raw_snapshot(raw_results)
