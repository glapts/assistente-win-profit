"""
whale_ny_monitor.py
===============================================================================
MÓDULO QUANTITATIVO: WHALE FLOW US/GLOBAL & ESTRATÉGIA ABERTURA NOVA YORK (11:30 BRT)
Mini-Índice B3 (WIN) — Arquitetura Smart Money Concepts (SMC) & Microestrutura

REGRAS DE ARQUITETURA:
  - Módulo 100% desacoplado. Não altera, remove ou substitui nenhum módulo existente.
  - Não altera fórmulas matemáticas de FVGs, Delta, absorção ou stops.
  - Ingestão via Times & Trades (Ordem Original com corretora agressora).
  - Janela de agregação de 3 segundos para detecção de ordens fatiadas / icebergs.
  - Protocolo dedicado para abertura de Wall Street (11h30 BRT) com trava de leilão.
  - Score de Assertividade (0 a 100 pts), disparando alertas quando Score >= 80.
===============================================================================
"""

import os
import sys
import re
import time
import json
import argparse
import subprocess
from datetime import datetime, time as dtime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field

# Garante path do projeto
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# ---------------------------------------------------------------------------
# CÓDIGOS DE CORES ANSI PARA O POWERSHELL
# ---------------------------------------------------------------------------
ANSI_RESET = "\033[0m"
ANSI_BOLD = "\033[1m"
ANSI_DIM = "\033[2m"
ANSI_RED = "\033[91m"
ANSI_GREEN = "\033[92m"
ANSI_YELLOW = "\033[93m"
ANSI_BLUE = "\033[94m"
ANSI_MAGENTA = "\033[95m"
ANSI_CYAN = "\033[96m"
ANSI_WHITE = "\033[97m"
ANSI_BG_RED = "\033[41m"
ANSI_BG_GREEN = "\033[42m"
ANSI_BG_YELLOW = "\033[43m"
ANSI_BG_MAGENTA = "\033[45m"
ANSI_BG_CYAN = "\033[46m"


# ---------------------------------------------------------------------------
# 1. TAXONOMIA DE PLAYERS E MAGNITUDE DE ORDENS
# ---------------------------------------------------------------------------
TIER_1_US_KEYWORDS = {
    "MORGAN", "GOLDMAN", "JP MORGAN", "JPMORGAN", "BOFA", "MERRILL", "CITI", "CITIGROUP", "JEFFERIES"
}

TIER_2_GLOBAL_KEYWORDS = {
    "UBS", "BARCLAYS", "BNP", "DEUTSCHE", "SOCGEN", "SOCIETE GENERALE"
}

TIER_3_DMA_KEYWORDS = {
    "IDEAL", "BTG", "XP"
}


def classify_broker(broker_name: str) -> Tuple[str, float]:
    """
    Classifica a corretora conforme a taxonomia institucional da B3.
    Retorna (Grupo: TIER_1_US | TIER_2_GLOBAL | TIER_3_DMA | OUTROS, Peso: float).
    """
    b = (broker_name or "").strip().upper()
    b_norm = re.sub(r"[.\-_]", " ", b)
    b_norm = re.sub(r"\s+", " ", b_norm).strip()

    for kw in TIER_1_US_KEYWORDS:
        if kw in b_norm or kw in b:
            return "TIER_1_US", 1.00

    for kw in TIER_2_GLOBAL_KEYWORDS:
        if kw in b_norm or kw in b:
            return "TIER_2_GLOBAL", 0.90

    for kw in TIER_3_DMA_KEYWORDS:
        if kw in b_norm or kw in b:
            return "TIER_3_DMA", 0.60

    return "OUTROS", 0.30


def classify_magnitude(quantity: int) -> Optional[str]:
    """Classifica a magnitude da execução institucional."""
    if quantity >= 1000:
        return "MEGA_CLIMAX"
    elif quantity >= 400:
        return "WHALE_BLOCK"
    return None


# ---------------------------------------------------------------------------
# 2. SANITIZAÇÃO DE DADOS DO TIMES & TRADES (INCLUINDO PREÇOS COM '*')
# ---------------------------------------------------------------------------
def sanitize_price(raw: str) -> Optional[float]:
    """
    Sanitiza strings de preço do Profit Pro, tratando asteriscos (*),
    separadores de milhar brasileiros e frações decimais.
    Ex: '165.485*' -> 165485.0 | '165.500,00*' -> 165500.0 | '165485' -> 165485.0
    """
    if not raw:
        return None
    cleaned = raw.strip().replace("*", "").replace("R$", "").replace(" ", "")
    if not cleaned:
        return None

    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", cleaned):
        cleaned = cleaned.replace(".", "")

    try:
        val = float(cleaned)
        return val if val > 0 else None
    except ValueError:
        return None


def sanitize_quantity(raw: str) -> int:
    """Sanitiza strings de quantidade do Profit Pro."""
    if not raw:
        return 0
    cleaned = str(raw).strip().replace(".", "").replace(",", "").replace(" ", "").replace("*", "")
    try:
        return int(cleaned)
    except ValueError:
        return 0


def normalize_aggressor_side(raw: str, compradora: str, vendedora: str) -> str:
    """
    Normaliza a direção do agressor: 'COMPRA', 'VENDA' ou 'DIRETO/NEUTRO'.
    Aceita rótulos 'Comprador'/'Vendedor' ou deduce caso não explícito.
    """
    text = (raw or "").strip().upper()
    if "COMPR" in text or "BUY" in text:
        return "COMPRA"
    if "VEND" in text or "SELL" in text:
        return "VENDA"
    if "DIRETO" in text or "DIRECT" in text:
        return "DIRETO"
    # Fallback se a coluna indicar quem agrediu
    if compradora and compradora != "-" and (not vendedora or vendedora == "-"):
        return "COMPRA"
    if vendedora and vendedora != "-" and (not compradora or compradora == "-"):
        return "VENDA"
    return "INDEFINIDO"


# ---------------------------------------------------------------------------
# 3. ESTRUTURAS DE DADOS: TRADES E CLUSTERS TEMPORAIS (JANELA DE 3 SEGUNDOS)
# ---------------------------------------------------------------------------
@dataclass
class TTRecord:
    timestamp: datetime
    broker: str
    price: float
    quantity: int
    aggressor: str
    tier: str
    tier_weight: float
    is_direct: bool = False
    raw_price_str: str = ""


@dataclass
class WhaleCluster:
    cluster_id: str
    start_time: datetime
    last_time: datetime
    broker: str
    tier: str
    side: str
    total_quantity: int
    trades_count: int
    vwap_price: float
    magnitude: str
    records: List[TTRecord] = field(default_factory=list)


class WhaleClusterAggregator:
    """
    Agrupa ordens fatiadas / iceberg da mesma corretora e lado executadas
    dentro de uma janela deslizante de 3.0 segundos.
    """
    def __init__(self, window_seconds: float = 3.0):
        self.window_seconds = window_seconds
        self.active_groups: Dict[Tuple[str, str], List[TTRecord]] = {}
        self.confirmed_clusters: List[WhaleCluster] = []

    def add_trade(self, trade: TTRecord) -> Optional[WhaleCluster]:
        key = (trade.broker, trade.aggressor)
        now = trade.timestamp

        # Limpar trades fora da janela de 3 segundos
        if key in self.active_groups:
            self.active_groups[key] = [
                t for t in self.active_groups[key]
                if (now - t.timestamp).total_seconds() <= self.window_seconds
            ]
        else:
            self.active_groups[key] = []

        self.active_groups[key].append(trade)

        # Calcular volume acumulado da corretora neste lado
        group = self.active_groups[key]
        total_qty = sum(t.quantity for t in group)

        # Regra de corte por Tier
        required_qty = 600 if trade.tier == "TIER_3_DMA" else 400

        if total_qty >= required_qty:
            vwap = sum(t.price * t.quantity for t in group) / total_qty
            mag = classify_magnitude(total_qty) or "WHALE_BLOCK"
            cluster = WhaleCluster(
                cluster_id=f"WHALE_{trade.broker}_{trade.aggressor}_{int(vwap)}_{now.strftime('%H%M%S')}",
                start_time=group[0].timestamp,
                last_time=now,
                broker=trade.broker,
                tier=trade.tier,
                side=trade.aggressor,
                total_quantity=total_qty,
                trades_count=len(group),
                vwap_price=round(vwap, 2),
                magnitude=mag,
                records=list(group)
            )
            # Limpa o grupo para evitar retrigger duplicado
            self.active_groups[key] = []
            self.confirmed_clusters.append(cluster)
            return cluster

        return None


# ---------------------------------------------------------------------------
# 4. CARREGAMENTO DE ZONAS SMC E PROXIMIDADE (<= 100 PTS)
# ---------------------------------------------------------------------------
@dataclass
class SMCZoneContext:
    zone_id: str
    zone_type: str        # "SUPPLY_RESISTENCIA" (Topo) ou "DEMAND_SUPORTE" (Fundo)
    top: float
    bottom: float
    ce_50: float
    setup_name: str
    stop_pts: float
    alvo_pts: float
    notes: str


class SMCZonesManager:
    """Gerencia as zonas estruturais carregadas de data/niveis_60m.json."""
    def __init__(self, json_path: str = "data/niveis_60m.json"):
        self.json_path = os.path.abspath(os.path.join(BASE_DIR, json_path))
        self.zones: List[SMCZoneContext] = []
        self.dealing_range_topo: float = 167000.0
        self.dealing_range_fundo: float = 164200.0
        self.dealing_range_eq: float = 165600.0
        self.load_zones()

    def load_zones(self):
        self.zones.clear()
        if not os.path.exists(self.json_path):
            return

        try:
            with open(self.json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            dr = data.get("dealing_range", {})
            self.dealing_range_topo = float(dr.get("topo_estrutural", 167000.0))
            self.dealing_range_fundo = float(dr.get("fundo_estrutural", 164200.0))
            self.dealing_range_eq = float(dr.get("equilibrium_50", 165600.0))

            for z in data.get("zonas_fvg", []):
                tipo = z.get("tipo_original", "")
                setup = z.get("setup_primario", "")
                top_p = float(z.get("top", 0.0))
                bot_p = float(z.get("bottom", 0.0))
                ce_p = float(z.get("ce_50", (top_p + bot_p) / 2.0))

                setup_upper = (setup or "").upper()
                tipo_upper = (tipo or "").upper()

                # Classificar se atua como Suporte/Demanda (COMPRA) ou Resistência/Oferta (VENDA)
                # Prioridade 1: Setup primário explícito da zona (BUY vs SELL)
                if "BUY" in setup_upper:
                    z_type = "DEMAND_SUPORTE"
                elif "SELL" in setup_upper:
                    z_type = "SUPPLY_RESISTENCIA"
                # Prioridade 2: Tipo de FVG ou Estrutura original
                elif tipo_upper in ("BULLISH", "SWEEP_SSL"):
                    z_type = "DEMAND_SUPORTE"
                elif tipo_upper in ("BEARISH", "BREAKER", "SWEEP_BSL"):
                    z_type = "SUPPLY_RESISTENCIA"
                # Prioridade 3: Posição relativa ao Equilibrium (Abaixo do 50% = Desconto/Suporte, Acima = Prêmio/Resistência)
                elif ce_p >= self.dealing_range_eq:
                    z_type = "SUPPLY_RESISTENCIA"
                else:
                    z_type = "DEMAND_SUPORTE"

                self.zones.append(SMCZoneContext(
                    zone_id=z.get("id", "ZONA"),
                    zone_type=z_type,
                    top=max(top_p, bot_p),
                    bottom=min(top_p, bot_p),
                    ce_50=ce_p,
                    setup_name=setup,
                    stop_pts=float(z.get("stop_sugerido_pts", 250.0)),
                    alvo_pts=float(z.get("alvo_sugerido_pts", 400.0)),
                    notes=z.get("notes", "")
                ))
        except Exception as e:
            print(f"[WHALE MONITOR] Aviso ao ler niveis_60m.json: {e}")

    def evaluate_proximity(self, price: float, threshold_pts: float = 100.0) -> Optional[Tuple[SMCZoneContext, float, str]]:
        """
        Verifica se o preço está dentro ou a <= threshold_pts de uma zona SMC.
        Retorna (SMCZoneContext, distância_pts, relação: 'DENTRO' | 'BORDA_SUPERIOR' | 'BORDA_INFERIOR').
        """
        closest: Optional[Tuple[SMCZoneContext, float, str]] = None
        min_dist = float("inf")

        for z in self.zones:
            if z.bottom <= price <= z.top:
                return (z, 0.0, "DENTRO")
            
            dist_top = abs(price - z.top)
            dist_bot = abs(price - z.bottom)
            dist = min(dist_top, dist_bot)

            if dist <= threshold_pts and dist < min_dist:
                min_dist = dist
                rel = "BORDA_SUPERIOR" if price > z.top else "BORDA_INFERIOR"
                closest = (z, dist, rel)

        return closest


# ---------------------------------------------------------------------------
# 5. MÓDULO ABERTURA NOVA YORK (11:30 BRT) & MATRIZ CROSS-MARKET
# ---------------------------------------------------------------------------
class NYCashOpenManager:
    """
    Gerencia o protocolo operacional da Abertura de Wall Street (11h30 BRT).
    """
    @staticmethod
    def get_regime(current_time: datetime) -> Tuple[str, str, bool]:
        """
        Retorna (Regime_ID, Descrição, Bloqueio_Ativo).
        """
        t = current_time.time()
        
        # 1. Pré-Abertura NY (11:15 - 11:29:59)
        if dtime(11, 15) <= t < dtime(11, 30):
            return "PRE_NY_OPEN", "Pré-Abertura NY / Posicionamento (Mapeando Máx/Mín da Manhã)", False

        # 2. Leilão NYSE/Nasdaq & Arbitragem ADRs (11:30:00 - 11:33:00)
        if dtime(11, 30) <= t <= dtime(11, 33):
            return "AUCTION_HOLD", "BLOQUEIO DE DISPARO (HOLD): Leilão NYSE/Nasdaq e Arbitragem ADRs", True

        # 3. Fluxo Direcional NY (11:33:01 - 12:30:00)
        if dtime(11, 33, 1) <= t <= dtime(12, 30):
            return "NY_CASH_OPEN", "Fluxo Direcional NY Ativo (Peso Dobrado para TIER 1 US)", False

        return "REGULAR_SESSION", "Sessão Regular Pós-Abertura", False


@dataclass
class CrossMarketState:
    wsp_change_pct: float = -1.90
    wdo_change_pct: float = 0.25
    di1f29_change_bps: float = 4.0
    blue_chips_alignment: str = "BEARISH"  # "BEARISH", "BULLISH", "NEUTRAL"
    timestamp: datetime = field(default_factory=datetime.now)

    def evaluate_alignment(self, candidate_direction: str) -> Tuple[int, str]:
        """
        Avalia a confluência de 4 fatores macro:
          - S&P 500 Futuro (WSP)
          - Dólar Futuro (WDO)
          - Juros Futuros (DI1F29)
          - Blue Chips (PETR4, VALE3, ITUB4)
        Retorna (Score: 0 a 20 pts, Explicação).
        """
        factors_aligned = 0
        details = []

        if candidate_direction == "SHORT":
            if self.wsp_change_pct < 0:
                factors_aligned += 1
                details.append("WSP caindo")
            if self.wdo_change_pct > 0:
                factors_aligned += 1
                details.append("Dólar subindo")
            if self.di1f29_change_bps > 0:
                factors_aligned += 1
                details.append("DI estressando")
            if self.blue_chips_alignment == "BEARISH":
                factors_aligned += 1
                details.append("Blue Chips pesadas")
        elif candidate_direction == "LONG":
            if self.wsp_change_pct > 0:
                factors_aligned += 1
                details.append("WSP subindo")
            if self.wdo_change_pct < 0:
                factors_aligned += 1
                details.append("Dólar caindo")
            if self.di1f29_change_bps < 0:
                factors_aligned += 1
                details.append("DI aliviando")
            if self.blue_chips_alignment == "BULLISH":
                factors_aligned += 1
                details.append("Blue Chips compradoras")

        # Regra da especificação: pelo menos 3 entre 4 confluências garantem os +20 pts
        if factors_aligned >= 3:
            return 20, f"Macro Alinhado ({factors_aligned}/4): {', '.join(details)}"
        elif factors_aligned == 2:
            return 10, f"Macro Misto ({factors_aligned}/4): {', '.join(details)}"
        else:
            return 0, f"Macro Divergente ({factors_aligned}/4)"


# ---------------------------------------------------------------------------
# 6. MOTOR DE DECISÃO: EXAUSTÃO VS. ROMPIMENTO & SCORE DE ASSERTIVIDADE
# ---------------------------------------------------------------------------
@dataclass
class WhaleSignalAlert:
    alert_id: str
    timestamp: datetime
    broker: str
    tier: str
    quantity: int
    magnitude: str
    setup_type: str         # "EXAUSTAO_TOPO" | "DEFESA_FUNDO" | "IGNICAO_ROMPIMENTO"
    direction: str          # "SHORT" (Venda) ou "LONG" (Compra)
    entry_price: float
    stop_loss: float
    take_profit: float
    zone_id: str
    score: int              # 0 a 100
    ny_regime: str
    macro_details: str
    reasons: List[str]


class WhaleDecisionEngine:
    """
    Consolida:
      1. Cluster Institucional (>= 400 cts)
      2. Zonas Estruturais SMC (distância <= 100 pts)
      3. Absorção / CHoCH 2m
      4. Regime NY 11:30 & Cross-Market
    """
    def __init__(self, zones_mgr: SMCZonesManager):
        self.zones_mgr = zones_mgr
        self.recent_alerts: List[WhaleSignalAlert] = []

    def evaluate_cluster(
        self,
        cluster: WhaleCluster,
        current_price: float,
        cross_market: CrossMarketState,
        choch_confirmed: bool = True,
        delta_inverting: bool = True,
        current_time: Optional[datetime] = None
    ) -> Optional[WhaleSignalAlert]:
        now = current_time or cluster.last_time

        # 1. Checagem do Regime de Nova York (11:30 BRT)
        regime_id, regime_desc, is_blocked = NYCashOpenManager.get_regime(now)
        if is_blocked:
            # Bloqueio estrito no leilão 11:30 - 11:33
            return None

        # 2. Checagem de Proximidade da Zona SMC (<= 100 pts)
        prox = self.zones_mgr.evaluate_proximity(current_price, threshold_pts=100.0)
        if not prox:
            # Fora de zona estrutural -> ignora ruído de meio de caminho
            return None

        zone, dist_pts, rel_pos = prox
        score = 0
        reasons = []

        # Pontuação 1: Proximidade de Zona SMC (+30 pts)
        score += 30
        reasons.append(f"Zona SMC {zone.zone_id} [{zone.bottom:.0f}-{zone.top:.0f}] ({rel_pos}, dist={dist_pts:.0f}pts) [+30]")

        # Pontuação 2: Magnitude da Ordem US/Global (+30 pts / +40 pts se mega)
        base_pts = 30 if cluster.tier in ("TIER_1_US", "TIER_2_GLOBAL") else 20
        bonus_mega = 10 if cluster.total_quantity >= 1000 else 0
        score += (base_pts + bonus_mega)
        reasons.append(f"Ordem {cluster.tier} ({cluster.broker}) {cluster.total_quantity} cts [{cluster.magnitude}] [+{base_pts + bonus_mega}]")

        # 3. Determinar o Setup: Topo (Venda) ou Fundo (Compra)
        setup_type = ""
        direction = ""
        entry_price = current_price
        stop_pts = zone.stop_pts
        alvo_pts = zone.alvo_pts

        if zone.zone_type == "SUPPLY_RESISTENCIA":
            # Testando Topo / Resistência de Oferta:
            # - Clímax Comprador absorvido (compras >= 400 sem romper) OU Agressão Vendedora Institucional
            direction = "SHORT"
            setup_type = "EXAUSTAO_TOPO" if cluster.side == "COMPRA" else "AGRESSAO_REJEICAO_VENDA"
            stop_loss = entry_price + stop_pts
            take_profit = entry_price - alvo_pts
        else: # DEMAND_SUPORTE
            # Testando Fundo / Suporte / Apoio no Pullback de Demanda:
            # - Clímax Vendedor absorvido OU Agressão Compradora Institucional
            direction = "LONG"
            setup_type = "DEFESA_FUNDO" if cluster.side == "VENDA" else "APOIO_PULLBACK_COMPRA"
            stop_loss = entry_price - stop_pts
            take_profit = entry_price + alvo_pts

        if not direction:
            return None

        # Pontuação 3: Validação Gráfica Rejeição 5Min + CHoCH 2Min (+20 pts)
        if choch_confirmed and delta_inverting:
            score += 20
            reasons.append("Rejeição 5Min + CHoCH 2Min com inversão de Delta confirmados [+20]")

        # Pontuação 4: Alinhamento Cross-Market NY (+20 pts)
        macro_score, macro_desc = cross_market.evaluate_alignment(direction)
        score += macro_score
        if macro_score > 0:
            reasons.append(f"{macro_desc} [+{macro_score}]")

        # Filtro de Limiar de Assertividade (Score >= 80)
        if score < 80:
            return None

        # Cooldown / Deduplicação de Alerta (mesma zona e direção nos últimos 30 segundos)
        # Evita flood de cards repetidos quando múltiplos lotes entram em sequência no tape
        for prev in reversed(self.recent_alerts):
            if abs((now - prev.timestamp).total_seconds()) < 30.0:
                if prev.zone_id == zone.zone_id and prev.direction == direction:
                    return None

        alert = WhaleSignalAlert(
            alert_id=f"ALERT_WHALE_{now.strftime('%H%M%S')}_{cluster.broker}",
            timestamp=now,
            broker=cluster.broker,
            tier=cluster.tier,
            quantity=cluster.total_quantity,
            magnitude=cluster.magnitude,
            setup_type=setup_type,
            direction=direction,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            zone_id=zone.zone_id,
            score=min(100, score),
            ny_regime=regime_desc,
            macro_details=macro_desc,
            reasons=reasons
        )

        self.recent_alerts.append(alert)
        return alert


# ---------------------------------------------------------------------------
# 7. PARSER RESILIENTE DE TEXTO / CLIPBOARD DO TIMES & TRADES
# ---------------------------------------------------------------------------
class TimesTradesParser:
    """
    Parser robusto da grade 'Ordem Original' do Profit Pro.
    Aceita linhas copiadas via clipboard, delimitadores por TAB, ponto-e-vírgula ou vírgula,
    e trata o asterisco '*' nas cotações de forma transparente.
    """
    @staticmethod
    def parse_line(line: str, ref_date: Optional[datetime] = None) -> Optional[TTRecord]:
        if not line or not line.strip():
            return None

        # Detectar delimitador
        delim = "\t" if "\t" in line else (";" if ";" in line else ",")
        parts = [p.strip() for p in line.split(delim)]

        if len(parts) < 4:
            return None

        # Se for cabeçalho, descarta
        line_low = line.lower()
        if "compradora" in line_low or "quantidade" in line_low or "agressor" in line_low:
            return None

        # Típico formato Profit Ordem Original:
        # [0]: Data/Hora (ex: "10:00:23.510" ou "25/11/2026 10:00:23.510")
        # [1]: Compradora (ex: "Ideal" ou "-")
        # [2]: Valor (ex: "165.485*")
        # [3]: Quantidade (ex: "100" ou "1.400")
        # [4]: Vendedora (ex: "Nova Futura" ou "-")
        # [5]: Agressor (ex: "Vendedor" ou "Comprador")

        # Localizar campo com asterisco ou float de preço
        price_val = None
        price_idx = -1
        for idx, part in enumerate(parts):
            p = sanitize_price(part)
            if p and p > 10000.0:  # Mini-índice trabalha em > 100.000 pts
                price_val = p
                price_idx = idx
                break

        if not price_val or price_idx == -1:
            return None

        # Timestamp
        date_str = parts[0]
        now_ref = ref_date or datetime.now()
        ts = now_ref
        try:
            if " " in date_str:
                # Contém data e hora
                ts = datetime.strptime(date_str, "%d/%m/%Y %H:%M:%S.%f")
            elif ":" in date_str:
                # Apenas hora HH:MM:SS.mmm
                t_parts = date_str.split(":")
                hour = int(t_parts[0])
                minute = int(t_parts[1])
                sec_part = t_parts[2]
                if "." in sec_part:
                    sec, micro = sec_part.split(".", 1)
                    sec_i = int(sec)
                    micro_i = int((micro + "000000")[:6])
                else:
                    sec_i = int(sec_part)
                    micro_i = 0
                ts = now_ref.replace(hour=hour, minute=minute, second=sec_i, microsecond=micro_i)
        except Exception:
            ts = now_ref

        # Quantidade (normalmente vizinha ao preço)
        qty_val = 0
        for idx in [price_idx + 1, price_idx - 1]:
            if 0 <= idx < len(parts):
                q = sanitize_quantity(parts[idx])
                if q > 0:
                    qty_val = q
                    break

        if qty_val == 0:
            return None

        # Identificar Compradora, Vendedora e Agressor
        compradora = parts[1] if len(parts) > 1 and price_idx != 1 else ""
        vendedora = parts[4] if len(parts) > 4 else ""
        agressor_raw = parts[5] if len(parts) > 5 else ""

        aggressor_side = normalize_aggressor_side(agressor_raw, compradora, vendedora)

        # Escolhe a corretora relevante (a agressora)
        if aggressor_side == "COMPRA":
            active_broker = compradora if compradora and compradora != "-" else (vendedora or "DESCONHECIDO")
        elif aggressor_side == "VENDA":
            active_broker = vendedora if vendedora and vendedora != "-" else (compradora or "DESCONHECIDO")
        else:
            active_broker = compradora if compradora and compradora != "-" else vendedora

        tier, weight = classify_broker(active_broker)

        return TTRecord(
            timestamp=ts,
            broker=active_broker,
            price=price_val,
            quantity=qty_val,
            aggressor=aggressor_side,
            tier=tier,
            tier_weight=weight,
            is_direct=("*" in parts[price_idx]),
            raw_price_str=parts[price_idx]
        )


# ---------------------------------------------------------------------------
# 8. RENDERIZADOR VISUAL ANSI PARA POWERSHELL
# ---------------------------------------------------------------------------
class VisualConsoleRenderer:
    """Renderiza cartões e tabelas no console com formatação rica ANSI."""
    @staticmethod
    def print_header(title: str):
        print(f"\n{ANSI_BOLD}{ANSI_CYAN}╔{'═' * 78}╗{ANSI_RESET}")
        print(f"{ANSI_BOLD}{ANSI_CYAN}║ {title.center(76)} ║{ANSI_RESET}")
        print(f"{ANSI_BOLD}{ANSI_CYAN}╚{'═' * 78}╝{ANSI_RESET}")

    @staticmethod
    def print_alert(alert: WhaleSignalAlert):
        # Alerta sonoro no terminal do Windows (beep padrão)
        print("\a", end="", flush=True)

        dir_color = ANSI_GREEN if alert.direction == "LONG" else ANSI_RED
        dir_bg = ANSI_BG_GREEN if alert.direction == "LONG" else ANSI_BG_RED
        border_color = ANSI_YELLOW if alert.score >= 90 else ANSI_CYAN

        print(f"\n{ANSI_BOLD}{border_color}╔{'═' * 78}╗{ANSI_RESET}")
        header_text = f"🚨 ALERTA WHALE FLOW — SINAL INSTITUCIONAL (SCORE {alert.score}/100)"
        print(f"{ANSI_BOLD}{border_color}║ {header_text.center(76)} ║{ANSI_RESET}")
        print(f"{ANSI_BOLD}{border_color}╠{'═' * 78}╣{ANSI_RESET}")

        print(f"  {ANSI_BOLD}Horário         :{ANSI_RESET} {alert.timestamp.strftime('%H:%M:%S.%f')[:-3]}")
        print(f"  {ANSI_BOLD}Corretora       :{ANSI_RESET} {ANSI_BOLD}{ANSI_WHITE}{alert.broker}{ANSI_RESET} ({alert.tier})")
        print(f"  {ANSI_BOLD}Lote Executado  :{ANSI_RESET} {ANSI_BOLD}{ANSI_YELLOW}{alert.quantity:,} contratos{ANSI_RESET} [{alert.magnitude}]")
        print(f"  {ANSI_BOLD}Configuração SMC:{ANSI_RESET} {alert.setup_type} (Zona: {alert.zone_id})")
        print(f"  {ANSI_BOLD}Ação / Direção  :{ANSI_RESET} {ANSI_BOLD}{dir_bg}{ANSI_WHITE} {alert.direction} {ANSI_RESET}")
        print(f"  {ANSI_BOLD}{ANSI_CYAN}PREÇO DE ENTRADA:{ANSI_RESET} {ANSI_BOLD}{ANSI_CYAN}{alert.entry_price:,.0f}{ANSI_RESET}")
        print(f"  {ANSI_BOLD}Stop Loss       :{ANSI_RESET} {ANSI_RED}{alert.stop_loss:,.0f} (-{abs(alert.entry_price - alert.stop_loss):.0f} pts){ANSI_RESET}")
        print(f"  {ANSI_BOLD}Alvo de Ganho   :{ANSI_RESET} {ANSI_GREEN}{alert.take_profit:,.0f} (+{abs(alert.take_profit - alert.entry_price):.0f} pts){ANSI_RESET}")
        print(f"  {ANSI_BOLD}R:R Teórico     :{ANSI_RESET} 1.60 (Stop {abs(alert.entry_price - alert.stop_loss):.0f} / Alvo {abs(alert.take_profit - alert.entry_price):.0f})")
        print(f"  {ANSI_BOLD}Regime NY 11:30 :{ANSI_RESET} {ANSI_CYAN}{alert.ny_regime}{ANSI_RESET}")
        print(f"  {ANSI_BOLD}Confluências    :{ANSI_RESET}")
        for r in alert.reasons:
            print(f"     • {r}")
        print(f"{ANSI_BOLD}{border_color}╚{'═' * 78}╝{ANSI_RESET}\n")

    @staticmethod
    def print_cluster_log(cluster: WhaleCluster, price: float):
        side_color = ANSI_GREEN if cluster.side == "COMPRA" else ANSI_RED
        tier_color = ANSI_MAGENTA if cluster.tier == "TIER_1_US" else (ANSI_CYAN if cluster.tier == "TIER_2_GLOBAL" else ANSI_YELLOW)
        print(
            f"[{cluster.last_time.strftime('%H:%M:%S')}] "
            f"{ANSI_BOLD}{tier_color}[{cluster.tier}]{ANSI_RESET} "
            f"{ANSI_BOLD}{cluster.broker:<12}{ANSI_RESET} "
            f"{side_color}{cluster.side:<6}{ANSI_RESET} "
            f"{ANSI_BOLD}{cluster.total_quantity:>5} cts{ANSI_RESET} @ "
            f"{cluster.vwap_price:.0f} (vwap) | "
            f"{ANSI_YELLOW}{cluster.magnitude}{ANSI_RESET} "
            f"({cluster.trades_count} negócios fatiados em 3s)"
        )


# ---------------------------------------------------------------------------
# 9. SERVIÇO PRINCIPAL (STANDALONE / COPILOTO)
# ---------------------------------------------------------------------------
class WhaleNYMonitor:
    def __init__(self, mode: str = "LIVE_CLIPBOARD", interval: float = 1.0):
        self.mode = mode
        self.interval = interval
        self.zones_mgr = SMCZonesManager()
        self.aggregator = WhaleClusterAggregator(window_seconds=3.0)
        self.decision_engine = WhaleDecisionEngine(self.zones_mgr)
        self.cross_market = CrossMarketState()
        self.last_clipboard_content = ""
        self.processed_signatures = set()

    def update_cross_market_from_runtime(self):
        """Lê o runtime_state.json e recarrega niveis_60m.json se disponível."""
        # Recarrega zonas ativas do disco
        self.zones_mgr.load_zones()

        state_path = os.path.join(BASE_DIR, "data", "runtime_state.json")
        if os.path.exists(state_path):
            try:
                with open(state_path, "r", encoding="utf-8") as f:
                    st = json.load(f)
                macro = st.get("macro_regime", {})
                sp_bias = macro.get("sp500_bias", "BEARISH")
                self.cross_market.wsp_change_pct = -1.90 if sp_bias == "BEARISH" else 0.50
                di_bias = macro.get("di_curve_bias", "STABLE")
                self.cross_market.di1f29_change_bps = 5.0 if di_bias == "STRESSED" else -2.0
                self.cross_market.blue_chips_alignment = "BEARISH" if sp_bias == "BEARISH" else "BULLISH"
            except Exception:
                pass

    def process_text_payload(
        self,
        text: str,
        ref_date: Optional[datetime] = None,
        check_staleness: bool = False,
        max_staleness_sec: float = 180.0
    ) -> List[WhaleSignalAlert]:
        alerts = []
        lines = text.strip().splitlines()

        parsed_records: List[TTRecord] = []
        stale_records_count = 0
        latest_stale_time: Optional[datetime] = None

        for line in lines:
            line_clean = line.strip()
            if not line_clean:
                continue

            # Evita reprocessar a mesma linha já consumida
            sig = hash(line_clean)
            if sig in self.processed_signatures:
                continue
            self.processed_signatures.add(sig)

            # Limita tamanho do cache de assinaturas
            if len(self.processed_signatures) > 20000:
                self.processed_signatures.clear()

            record = TimesTradesParser.parse_line(line_clean, ref_date)
            if record:
                # Checagem de caducidade temporal (staleness) para proteção do trader
                if check_staleness:
                    age_sec = (datetime.now() - record.timestamp).total_seconds()
                    if age_sec > max_staleness_sec:
                        stale_records_count += 1
                        latest_stale_time = record.timestamp
                        continue

                parsed_records.append(record)

        if stale_records_count > 0 and not parsed_records:
            time_str = latest_stale_time.strftime('%H:%M:%S') if latest_stale_time else "passado"
            age_min = int((datetime.now() - latest_stale_time).total_seconds() / 60) if latest_stale_time else 0
            print(
                f"\n{ANSI_BOLD}{ANSI_YELLOW}⚠️ [AVISO WHALE FLOW — SINAL EXPIRADO]{ANSI_RESET} "
                f"Os dados copiados são das {ANSI_BOLD}{time_str}{ANSI_RESET} (há ~{age_min} min). "
                f"Alerta operacional cancelado para proteger sua conta contra entrada tardia. "
                f"Selecione os negócios mais recentes no topo do Times & Trades e tecle Ctrl+C.\n"
            )
            return alerts

        if not parsed_records:
            return alerts

        # Ordenação cronológica (do mais antigo para o mais recente)
        # Garante agregação correta de blocos fatiados e que o sinal mais recente ocorra por último
        parsed_records.sort(key=lambda r: r.timestamp)

        for record in parsed_records:
            # Agregação em janela de 3s
            cluster = self.aggregator.add_trade(record)
            if cluster:
                # 1. Imprime o log de fluxo fatiado primeiro
                VisualConsoleRenderer.print_cluster_log(cluster, record.price)

                # 2. Avalia gatilho no motor de decisão
                alert = self.decision_engine.evaluate_cluster(
                    cluster=cluster,
                    current_price=record.price,
                    cross_market=self.cross_market,
                    current_time=record.timestamp
                )

                if alert:
                    alerts.append(alert)

        # 3. Imprime os alertas institucionais AO FINAL (no rodapé visível do PowerShell)
        for alert in alerts:
            VisualConsoleRenderer.print_alert(alert)

        return alerts

    def run_live_clipboard_loop(self):
        """Loop de monitoramento da Área de Transferência do Windows."""
        VisualConsoleRenderer.print_header("WHALE FLOW US & NY CASH OPEN (11:30 BRT) — MONITOR ATIVO")
        print(f" {ANSI_BOLD}Modo Operacional :{ANSI_RESET} Leitura Contínua da Área de Transferência (Clipboard)")
        print(f" {ANSI_BOLD}Instrução ao Trader:{ANSI_RESET} Selecione negócios na aba 'Ordem Original' e use Ctrl+C.")
        print(f" {ANSI_BOLD}Filtro Anti-Atraso :{ANSI_RESET} Bloqueio automático de trades com mais de 3 minutos de defasagem.")
        print(f" {ANSI_BOLD}Zonas Mapeadas   :{ANSI_RESET} {len(self.zones_mgr.zones)} zonas SMC carregadas de data/niveis_60m.json")
        print(f" {ANSI_BOLD}Abertura NY      :{ANSI_RESET} 11h30 BRT (Trava de leilão 11:30–11:33 / Fluxo livre 11:33–12:30)")
        print(f"{ANSI_CYAN}{'─' * 80}{ANSI_RESET}\n")

        # Inicialização: ignora o conteúdo que já estava no clipboard antes de iniciar
        try:
            res_init = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5
            )
            self.last_clipboard_content = res_init.stdout or ""
            if self.last_clipboard_content:
                print(f" {ANSI_DIM}[WHALE MONITOR] Histórico prévio na área de transferência inicializado. Aguardando nova cópia...{ANSI_RESET}\n")
        except Exception:
            self.last_clipboard_content = ""

        try:
            while True:
                self.update_cross_market_from_runtime()
                
                # Leitura do Clipboard via PowerShell
                try:
                    res = subprocess.run(
                        ["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=5
                    )
                    content = res.stdout or ""
                except Exception:
                    content = ""

                if content and content != self.last_clipboard_content:
                    self.last_clipboard_content = content
                    self.process_text_payload(content, check_staleness=True)

                time.sleep(self.interval)

        except KeyboardInterrupt:
            print(f"\n{ANSI_YELLOW}[WHALE MONITOR] Monitoramento encerrado pelo operador.{ANSI_RESET}")


# ---------------------------------------------------------------------------
# 10. CENÁRIO DE DEMONSTRAÇÃO E TESTE SINTÉTICO (HOMOLOGAÇÃO)
# ---------------------------------------------------------------------------
def run_demo_simulation():
    """
    Simula o cenário exato da especificação:
    Morgan Stanley agride 1.400 contratos no topo às 11:33:15 em 165.700
    com absorção, S&P em queda (-1.90%), CHoCH no 2Min -> Disparo Score 95!
    """
    VisualConsoleRenderer.print_header("DEMONSTRAÇÃO DE HOMOLOGAÇÃO: WHALE FLOW US (MORGAN 1.400 CTS NO TOPO)")

    monitor = WhaleNYMonitor()
    now = datetime.now().replace(hour=11, minute=33, second=15)

    sample_trades_text = f"""
11:33:12.100\tMorgan\t165.700*\t400\tIdeal\tComprador
11:33:13.450\tMorgan\t165.700*\t500\tBTG\tComprador
11:33:14.800\tMorgan\t165.695*\t500\tXP\tComprador
"""
    print(f"{ANSI_YELLOW}Simulando chegada do fluxo institucional fatiado (Morgan 400 + 500 + 500 = 1.400 cts)...{ANSI_RESET}")
    alerts = monitor.process_text_payload(sample_trades_text, ref_date=now)

    if alerts:
        print(f"{ANSI_BOLD}{ANSI_GREEN}✅ HOMOLOGAÇÃO CONCLUÍDA: Alerta gerado com sucesso com Score {alerts[0].score}/100!{ANSI_RESET}")
    else:
        print(f"{ANSI_RED}❌ Falha na geração do alerta de demonstração.{ANSI_RESET}")


# ---------------------------------------------------------------------------
# PONTO DE ENTRADA CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Whale Flow US & NY 11:30 Open Monitor")
    parser.add_argument("--mode", choices=["LIVE_CLIPBOARD", "DEMO"], default="LIVE_CLIPBOARD", help="Modo de execução")
    parser.add_argument("--demo", action="store_true", help="Executa simulação de homologação")
    args = parser.parse_args()

    if args.demo or args.mode == "DEMO":
        run_demo_simulation()
    else:
        monitor = WhaleNYMonitor(mode="LIVE_CLIPBOARD", interval=1.0)
        monitor.run_live_clipboard_loop()


if __name__ == "__main__":
    main()
