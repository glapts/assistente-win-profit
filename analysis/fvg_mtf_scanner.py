"""
analysis/fvg_mtf_scanner.py
Scanner determinístico Multi-Timeframe (MTF) de Fair Value Gaps (FVGs) Antigos Não Liquidados
e Sistema de Alerta Antecipado no Terminal PowerShell para o Mini-Índice (WIN) na B3.
Monitora simultaneamente os tempos gráficos de: 10m, 15m, 30m, 60m e 240m (4 horas).

Regras de Negócio e Visualização em conformidade com:
- fvg_mtf_antigravity_spec.md
- SPEC_MELHORIAS_FVG_PERFORMANCE.md
"""

from typing import List, Dict, Optional, Tuple, Any, Set
from dataclasses import dataclass, field
from datetime import datetime
import json
import os
import hashlib

from core.models import Candle, FairValueGap, Direction
from core.contract import TZ_BRASILIA, WIN_SPEC


def formatar_preco(valor: float, decimals: int = 0) -> str:
    """
    Formata níveis de preço no padrão brasileiro com precisão decimal configurável.
    """
    if valor is None:
        return "N/D"
    if decimals == 0:
        return f"{int(round(valor)):,}".replace(",", ".")
    return f"{valor:,.{decimals}f}".replace(".", "X").replace(",", ".").replace("X", ",")


def formatar_preco_win(valor: float) -> str:
    """Compatibilidade retroativa com a especificação fvg_mtf_antigravity_spec.md."""
    return formatar_preco(valor, decimals=0)


def generate_fvg_id(timeframe: int, direction: str, top: float, bottom: float, formed_time: Any) -> str:
    """
    Melhoria 1: Gera um identificador determinístico único para o FVG.
    Baseado em hash SHA-256 estável dos parâmetros imutáveis de formação.
    """
    if hasattr(formed_time, "isoformat"):
        formed_str = formed_time.isoformat()
    elif formed_time:
        formed_str = str(formed_time)
    else:
        formed_str = "NONE"
    
    dir_str = str(direction).upper()
    raw = f"{timeframe}_{dir_str}_{top:.2f}_{bottom:.2f}_{formed_str}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class ActiveMTFFVG:
    """
    Representa um FVG histórico mantido em memória até ser totalmente liquidado.
    Melhoria 1: Inclui identificador determinístico único fvg_id.
    """
    timeframe: int               # 5, 10, 15, 30, 60, 240
    direction: str               # "BULLISH" ou "BEARISH"
    top: float                   # Limite superior da zona
    bottom: float                # Limite inferior da zona
    ce_50: float                 # Consequent Encroachment (50%) = (top + bottom) / 2.0
    formed_time: datetime        # Data/hora de formação
    start_bar: int = 0
    end_bar: int = 0
    is_liquidated: bool = False  # True quando rompido por completo
    tested_count: int = 0        # Número de toques/testes já realizados
    fvg_id: str = ""             # Identificador determinístico único (Melhoria 1)

    def __post_init__(self):
        if not self.fvg_id:
            self.fvg_id = generate_fvg_id(
                self.timeframe, self.direction, self.top, self.bottom, self.formed_time
            )

    @property
    def size(self) -> float:
        return abs(self.top - self.bottom)


@dataclass
class FVGApproachAlert:
    """
    Dados de aproximação do preço a um FVG ativo para emissão de Alerta Antecipado.
    Melhoria 2: Inclui is_ce_imminent para proximidade fina (1 a 2 ticks) do 50% CE.
    """
    fvg: ActiveMTFFVG
    current_price: float
    distance_to_zone: float      # Distância em pontos até o início da zona
    distance_to_ce: float        # Distância em pontos até o Ponto de 50% (CE)
    is_inside_zone: bool         # Se o preço já tocou o início da zona mas não liquidou
    action_direction: str        # "VENDA" ou "COMPRA"
    zone_start: float            # Início da zona no sentido do movimento
    zone_end: float              # Fim da zona no sentido do movimento
    target_points_min: int = 200 # Objetivo estimado mínimo (200 pts)
    target_points_max: int = 300 # Objetivo estimado máximo (300 pts)
    is_ce_imminent: bool = False # Melhoria 2: True quando distância ao 50% CE <= 2 ticks (10 pts no WIN)


class FGVMTFScanner:
    """
    Rastreador Multi-Timeframe de FVGs Antigos Não Liquidados.
    Monitora 240m (4h), 60m, 30m, 15m, 10m e 5m com segregação ativa e deduplicação O(1).
    """

    # Melhoria 3: Timeframe 240m garantido como membro pleno com precedência macro
    MONITORED_TIMEFRAMES = [240, 60, 30, 15, 10, 5]

    # Códigos ANSI nativos para PowerShell / Windows Terminal
    ANSI_RESET = "\033[0m"
    ANSI_YELLOW_BOLD = "\033[1;93m"  # Destaque do rótulo Ponto de 50% (CE) e Iminência
    ANSI_RED_BOLD = "\033[1;91m"     # Sinal de VENDA / Resistência
    ANSI_GREEN_BOLD = "\033[1;92m"   # Sinal de COMPRA / Suporte
    ANSI_CYAN_BOLD = "\033[1;96m"
    ANSI_WHITE_BOLD = "\033[1;97m"

    def __init__(
        self,
        min_fvg_size: float = 10.0,
        default_approach_radius: float = 150.0,
        asset_spec=None,
        auto_load: bool = False
    ):
        self.min_fvg_size = min_fvg_size
        self.default_approach_radius = default_approach_radius
        self.spec = asset_spec or WIN_SPEC
        self.auto_load = auto_load
        
        # Histórico de candles recentes por timeframe para detecção de FVGs de 3 barras
        self.candles_history: Dict[int, List[Candle]] = {
            tf: [] for tf in self.MONITORED_TIMEFRAMES
        }
        
        # Melhoria 4: Segregação ativa de coleções
        # self.active_fvgs: Apenas FVGs abertos e vigentes
        self.active_fvgs: Dict[int, List[ActiveMTFFVG]] = {
            tf: [] for tf in self.MONITORED_TIMEFRAMES
        }
        # self.liquidated_archive: Arquivo histórico de zonas invalidadas/liquidadas
        self.liquidated_archive: Dict[int, List[ActiveMTFFVG]] = {
            tf: [] for tf in self.MONITORED_TIMEFRAMES
        }
        
        # Melhoria 1: Índice O(1) de mapeamento por fvg_id
        self._fvg_by_id: Dict[str, ActiveMTFFVG] = {}

        self.last_price: float = 0.0
        # Carregar FVGs ativos preservados de sessões anteriores se auto_load estiver ativo
        if self.auto_load:
            self.load_from_disk()

    def register_candle(self, candle: Candle):
        """
        Recebe um candle fechado em qualquer timeframe e:
        1. Atualiza histórico local do timeframe.
        2. Avalia formação de novos FVGs (fórmula clássica SMC de 3 candles intacta).
        3. Avalia liquidação de FVGs existentes e transfere para liquidated_archive.
        """
        if not candle.is_closed:
            return

        tf = candle.timeframe
        self.last_price = candle.close

        # 1. Avaliar liquidação de FVGs abertos com os extremos da barra
        self._check_liquidation_with_candle(candle)

        if tf in self.MONITORED_TIMEFRAMES:
            self.candles_history[tf].append(candle)
            # Avaliar formação de novo FVG
            self._detect_new_fvg(tf)

    def register_price_tick(self, price: float):
        """Atualiza o preço corrente e verifica liquidações em tempo real."""
        if price <= 0:
            return
        self.last_price = price
        self._check_liquidation_with_price(price)

    def _detect_new_fvg(self, tf: int):
        """
        Aplica a fórmula canônica SMC de FVG sobre os 3 últimos candles fechados:
        c1 = [idx-2], c2 = [idx-1], c3 = [idx].
        - FVG de Alta: c3.low > c1.high e (c3.low - c1.high) >= min_fvg_size
        - FVG de Baixa: c3.high < c1.low e (c1.low - c3.high) >= min_fvg_size
        Melhoria 1: Deduplicação estrita via fvg_id e hash determinístico.
        """
        candles = self.candles_history[tf]
        if len(candles) < 3:
            return

        c1 = candles[-3]
        c2 = candles[-2]
        c3 = candles[-1]

        min_sz = self.min_fvg_size

        # FVG de Alta (Bullish / Suporte)
        if c3.low > c1.high and (c3.low - c1.high) >= min_sz:
            top_val = c3.low
            bottom_val = c1.high
            ce_val = (top_val + bottom_val) / 2.0
            cand_id = generate_fvg_id(tf, "BULLISH", top_val, bottom_val, c3.close_time)

            # Melhoria 1: Deduplicação estrita O(1) via hash determinístico + proximidade de tick
            if cand_id not in self._fvg_by_id:
                already_exists = any(
                    abs(f.top - top_val) < 1.0 and abs(f.bottom - bottom_val) < 1.0
                    for f in self.active_fvgs[tf]
                )
                if not already_exists:
                    fvg = ActiveMTFFVG(
                        timeframe=tf,
                        direction="BULLISH",
                        top=top_val,
                        bottom=bottom_val,
                        ce_50=ce_val,
                        formed_time=c3.close_time,
                        start_bar=len(candles) - 3,
                        end_bar=len(candles) - 1,
                        is_liquidated=False,
                        fvg_id=cand_id
                    )
                    self.active_fvgs[tf].append(fvg)
                    self._fvg_by_id[cand_id] = fvg
                    self.save_to_disk()

        # FVG de Baixa (Bearish / Resistência)
        elif c3.high < c1.low and (c1.low - c3.high) >= min_sz:
            top_val = c1.low
            bottom_val = c3.high
            ce_val = (top_val + bottom_val) / 2.0
            cand_id = generate_fvg_id(tf, "BEARISH", top_val, bottom_val, c3.close_time)

            # Melhoria 1: Deduplicação estrita O(1) via hash determinístico + proximidade de tick
            if cand_id not in self._fvg_by_id:
                already_exists = any(
                    abs(f.top - top_val) < 1.0 and abs(f.bottom - bottom_val) < 1.0
                    for f in self.active_fvgs[tf]
                )
                if not already_exists:
                    fvg = ActiveMTFFVG(
                        timeframe=tf,
                        direction="BEARISH",
                        top=top_val,
                        bottom=bottom_val,
                        ce_50=ce_val,
                        formed_time=c3.close_time,
                        start_bar=len(candles) - 3,
                        end_bar=len(candles) - 1,
                        is_liquidated=False,
                        fvg_id=cand_id
                    )
                    self.active_fvgs[tf].append(fvg)
                    self._fvg_by_id[cand_id] = fvg
                    self.save_to_disk()

    def _get_storage_path(self) -> str:
        sym = getattr(self.spec, 'symbol_base', 'win').lower()
        if getattr(sys, 'frozen', False):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        data_dir = os.path.join(base_dir, 'data')
        os.makedirs(data_dir, exist_ok=True)
        return os.path.join(data_dir, f"active_fvgs_{sym}.json")

    def save_to_disk(self):
        """
        Persiste os FVGs ativos e arquivados em disco.
        Retrocompatível: Mantém a estrutura de dicionário indexado por timeframe.
        """
        if not getattr(self, 'auto_load', False):
            return
        try:
            path = self._get_storage_path()
            data = {}
            for tf in self.MONITORED_TIMEFRAMES:
                all_fvgs = self.active_fvgs.get(tf, []) + self.liquidated_archive.get(tf, [])
                data[str(tf)] = [
                    {
                        "fvg_id": f.fvg_id,
                        "timeframe": f.timeframe,
                        "direction": f.direction,
                        "top": f.top,
                        "bottom": f.bottom,
                        "ce_50": f.ce_50,
                        "formed_time": f.formed_time.isoformat() if f.formed_time else None,
                        "is_liquidated": f.is_liquidated,
                        "tested_count": f.tested_count
                    }
                    for f in all_fvgs
                ]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def load_from_disk(self):
        """
        Restaura FVGs ativos e arquivados preservados em disco com deduplicação O(1).
        Melhoria 4: Segrega automaticamente entre active_fvgs e liquidated_archive.
        """
        try:
            path = self._get_storage_path()
            if not os.path.exists(path):
                return
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for tf_str, items in data.items():
                tf = int(tf_str)
                if tf in self.MONITORED_TIMEFRAMES:
                    for item in items:
                        formed_dt = datetime.fromisoformat(item["formed_time"]) if item.get("formed_time") else datetime.now(TZ_BRASILIA)
                        top_v = float(item["top"])
                        bot_v = float(item["bottom"])
                        ce_v = float(item.get("ce_50", (top_v + bot_v) / 2.0))
                        dir_v = item["direction"]
                        cand_id = item.get("fvg_id") or generate_fvg_id(tf, dir_v, top_v, bot_v, formed_dt)

                        if cand_id in self._fvg_by_id:
                            continue

                        # Checagem de segurança de proximidade
                        already = any(abs(x.top - top_v) < 1.0 and abs(x.bottom - bot_v) < 1.0 for x in self.active_fvgs[tf]) or \
                                  any(abs(x.top - top_v) < 1.0 and abs(x.bottom - bot_v) < 1.0 for x in self.liquidated_archive[tf])
                        if already:
                            continue

                        is_liq = item.get("is_liquidated", False)
                        fvg = ActiveMTFFVG(
                            timeframe=item["timeframe"],
                            direction=dir_v,
                            top=top_v,
                            bottom=bot_v,
                            ce_50=ce_v,
                            formed_time=formed_dt,
                            is_liquidated=is_liq,
                            tested_count=item.get("tested_count", 0),
                            fvg_id=cand_id
                        )
                        self._fvg_by_id[cand_id] = fvg
                        if is_liq:
                            self.liquidated_archive[tf].append(fvg)
                        else:
                            self.active_fvgs[tf].append(fvg)
        except Exception:
            pass

    def _check_liquidation_with_candle(self, candle: Candle):
        """
        Regra de Liquidação (Seção 3 da especificação):
        - FVG de Baixa (Venda/Resistência): completamente rompido para cima -> fechamento (candle.close > fvg.top)
        - FVG de Alta (Compra/Suporte): completamente rompido para baixo -> fechamento (candle.close < fvg.bottom)
        Apenas candles fechados de timeframe relevante (>= 5m ou >= fvg.timeframe) liquidam a zona.
        Melhoria 4: Transfere imediatamente o FVG liquidado de active_fvgs para liquidated_archive.
        """
        changed = False
        for tf in self.MONITORED_TIMEFRAMES:
            active_list = self.active_fvgs.get(tf, [])
            still_active = []
            for fvg in active_list:
                is_liquidated = False
                if candle.timeframe >= min(5, fvg.timeframe):
                    if fvg.direction == "BEARISH" and candle.close > fvg.top:
                        is_liquidated = True
                    elif fvg.direction == "BULLISH" and candle.close < fvg.bottom:
                        is_liquidated = True

                if is_liquidated:
                    fvg.is_liquidated = True
                    self.liquidated_archive[tf].append(fvg)
                    changed = True
                else:
                    still_active.append(fvg)
            self.active_fvgs[tf] = still_active

        if changed:
            self.save_to_disk()

    def _check_liquidation_with_price(self, price: float):
        """
        Verifica se o preço atual ultrapassou amplamente a zona além da margem de rompimento (4 ticks).
        Melhoria 4: Transfere imediatamente o FVG liquidado de active_fvgs para liquidated_archive.
        """
        thresh = getattr(self.spec, 'tick_size', 5.0) * 4
        changed = False
        for tf in self.MONITORED_TIMEFRAMES:
            active_list = self.active_fvgs.get(tf, [])
            still_active = []
            for fvg in active_list:
                is_liquidated = False
                if fvg.direction == "BEARISH" and price > (fvg.top + thresh):
                    is_liquidated = True
                elif fvg.direction == "BULLISH" and price < (fvg.bottom - thresh):
                    is_liquidated = True

                if is_liquidated:
                    fvg.is_liquidated = True
                    self.liquidated_archive[tf].append(fvg)
                    changed = True
                else:
                    still_active.append(fvg)
            self.active_fvgs[tf] = still_active

        if changed:
            self.save_to_disk()

    def sync_from_engine(self, structure_engine):
        """
        Sincroniza os FVGs e candles já existentes no MultiTimeframeMarketEngine.
        Garante que qualquer histórico prévio nos analyzers alimente o scanner.
        Melhoria 1 e 4: Deduplicação O(1) e segregação active vs liquidated.
        """
        changed = False
        for tf in self.MONITORED_TIMEFRAMES:
            if tf in structure_engine.analyzers:
                analyzer = structure_engine.analyzers[tf]
                # Carregar candles
                for c in analyzer.candles:
                    if c not in self.candles_history[tf]:
                        self.candles_history[tf].append(c)
                # Carregar FVGs
                for f in analyzer.fvgs:
                    ce_val = (f.top + f.bottom) / 2.0
                    cand_id = generate_fvg_id(tf, f.direction, f.top, f.bottom, f.timestamp)

                    matched = self._fvg_by_id.get(cand_id)
                    if not matched:
                        for x in self.active_fvgs[tf]:
                            if abs(x.top - f.top) < 1.0 and abs(x.bottom - f.bottom) < 1.0:
                                matched = x
                                break
                        if not matched:
                            for x in self.liquidated_archive[tf]:
                                if abs(x.top - f.top) < 1.0 and abs(x.bottom - f.bottom) < 1.0:
                                    matched = x
                                    break

                    if not matched:
                        new_fvg = ActiveMTFFVG(
                            timeframe=tf,
                            direction=f.direction,
                            top=f.top,
                            bottom=f.bottom,
                            ce_50=ce_val,
                            formed_time=f.timestamp,
                            start_bar=f.start_bar,
                            end_bar=f.end_bar,
                            is_liquidated=f.is_invalidated,
                            fvg_id=cand_id
                        )
                        self._fvg_by_id[cand_id] = new_fvg
                        if f.is_invalidated:
                            self.liquidated_archive[tf].append(new_fvg)
                        else:
                            self.active_fvgs[tf].append(new_fvg)
                        changed = True
                    else:
                        if matched.is_liquidated != f.is_invalidated:
                            matched.is_liquidated = f.is_invalidated
                            if f.is_invalidated:
                                if matched in self.active_fvgs[tf]:
                                    self.active_fvgs[tf].remove(matched)
                                if matched not in self.liquidated_archive[tf]:
                                    self.liquidated_archive[tf].append(matched)
                            else:
                                if matched in self.liquidated_archive[tf]:
                                    self.liquidated_archive[tf].remove(matched)
                                if matched not in self.active_fvgs[tf]:
                                    self.active_fvgs[tf].append(matched)
                            changed = True

        if changed:
            self.save_to_disk()

    def get_unliquidated_fvgs(self, timeframe: Optional[int] = None) -> List[ActiveMTFFVG]:
        """
        Retorna lista de FVGs que continuam abertos (não liquidados).
        Melhoria 4: O(1) de filtragem pois active_fvgs contém apenas zonas ativas.
        """
        timeframes = [timeframe] if timeframe else self.MONITORED_TIMEFRAMES
        result = []
        for tf in timeframes:
            if tf in self.active_fvgs:
                for f in self.active_fvgs[tf]:
                    if not f.is_liquidated:
                        result.append(f)
        return result

    def scan_approach_alerts(
        self,
        current_price: float,
        approach_radius: Optional[float] = None
    ) -> List[FVGApproachAlert]:
        """
        Calcula a distância do preço atual até todos os FVGs abertos e identifica
        quando o Mini Índice entra no raio de aproximação (ex: 150 pontos).
        Melhoria 2: Calcula is_ce_imminent quando a distância ao 50% CE <= 2 ticks.
        Melhoria 3: Ordenação prioritária macro sobre micro (240m > 60m > 30m > ...).
        Melhoria 4: Itera exclusivamente sobre self.active_fvgs.
        """
        radius = approach_radius or self.default_approach_radius
        alerts: List[FVGApproachAlert] = []

        if current_price <= 0:
            return alerts

        # Avaliar todos os FVGs não liquidados (itera apenas sobre zonas ativas)
        unliquidated = self.get_unliquidated_fvgs()
        tick_sz = getattr(self.spec, 'tick_size', 5.0)
        ce_imminent_threshold = tick_sz * 2  # 2 ticks (10 pts no WIN)

        for fvg in unliquidated:
            ce_val = fvg.ce_50

            # --- CASO 1: FVG DE BAIXA (Resistência / VENDA) ---
            # Preço subindo em direção à zona que fica acima
            # Início da Zona = fvg.bottom | Fim da Zona = fvg.top
            if fvg.direction == "BEARISH":
                zone_start = fvg.bottom
                zone_end = fvg.top

                if current_price <= zone_start:
                    dist_zone = zone_start - current_price
                    dist_ce = ce_val - current_price
                    # Preço aproximando-se da zona por baixo
                    if 0 <= dist_zone <= radius:
                        is_ce_imminent = (dist_ce <= ce_imminent_threshold)
                        alerts.append(FVGApproachAlert(
                            fvg=fvg,
                            current_price=current_price,
                            distance_to_zone=dist_zone,
                            distance_to_ce=dist_ce,
                            is_inside_zone=False,
                            action_direction="VENDA",
                            zone_start=zone_start,
                            zone_end=zone_end,
                            is_ce_imminent=is_ce_imminent
                        ))
                elif zone_start < current_price <= zone_end:
                    # Preço já penetrou na zona testando o 50% CE
                    dist_ce = abs(ce_val - current_price)
                    if dist_ce <= radius:
                        is_ce_imminent = (dist_ce <= ce_imminent_threshold)
                        alerts.append(FVGApproachAlert(
                            fvg=fvg,
                            current_price=current_price,
                            distance_to_zone=0.0,
                            distance_to_ce=dist_ce,
                            is_inside_zone=True,
                            action_direction="VENDA",
                            zone_start=zone_start,
                            zone_end=zone_end,
                            is_ce_imminent=is_ce_imminent
                        ))

            # --- CASO 2: FVG DE ALTA (Suporte / COMPRA) ---
            # Preço caindo em direção à zona que fica abaixo
            # Início da Zona = fvg.top | Fim da Zona = fvg.bottom
            elif fvg.direction == "BULLISH":
                zone_start = fvg.top
                zone_end = fvg.bottom

                if current_price >= zone_start:
                    dist_zone = current_price - zone_start
                    dist_ce = current_price - ce_val
                    # Preço aproximando-se da zona por cima
                    if 0 <= dist_zone <= radius:
                        is_ce_imminent = (dist_ce <= ce_imminent_threshold)
                        alerts.append(FVGApproachAlert(
                            fvg=fvg,
                            current_price=current_price,
                            distance_to_zone=dist_zone,
                            distance_to_ce=dist_ce,
                            is_inside_zone=False,
                            action_direction="COMPRA",
                            zone_start=zone_start,
                            zone_end=zone_end,
                            is_ce_imminent=is_ce_imminent
                        ))
                elif zone_end <= current_price < zone_start:
                    # Preço já penetrou na zona testando o 50% CE
                    dist_ce = abs(current_price - ce_val)
                    if dist_ce <= radius:
                        is_ce_imminent = (dist_ce <= ce_imminent_threshold)
                        alerts.append(FVGApproachAlert(
                            fvg=fvg,
                            current_price=current_price,
                            distance_to_zone=0.0,
                            distance_to_ce=dist_ce,
                            is_inside_zone=True,
                            action_direction="COMPRA",
                            zone_start=zone_start,
                            zone_end=zone_end,
                            is_ce_imminent=is_ce_imminent
                        ))

        # Melhoria 3: Ordenar por proximidade (menor distância à zona) e precedência macro sobre micro
        # (240 > 60 > 30 > 15 > 10 > 5)
        alerts.sort(key=lambda a: (a.distance_to_zone, -a.fvg.timeframe))
        return alerts

    def format_power_shell_alert(self, alert: FVGApproachAlert, use_color: bool = True) -> str:
        """
        Formata o Alerta Antecipado no PowerShell rigorosamente conforme especificações:
        - Pontuação de Preço com separador de milhar por ponto (170.000).
        - Rótulo 'Ponto de 50% (CE)' em destaque (Amarelo Brilhante \033[1;93m).
        - Sinal de VENDA em VERMELHO BRILHANTE (\033[1;91m).
        - Sinal de COMPRA em VERDE BRILHANTE (\033[1;92m).
        - Melhoria 2: Tag piscante/destacada ao lado do 50% CE quando is_ce_imminent é True.
        - Melhoria 3: Tag [ZONA INSTITUCIONAL MACRO - 4 HORAS] quando FVG for de 240m.
        - Reset de Cor (\033[0m).
        """
        is_sell = (alert.action_direction == "VENDA")
        
        c_reset = self.ANSI_RESET if use_color else ""
        c_ce_label = self.ANSI_YELLOW_BOLD if use_color else ""
        c_action = self.ANSI_RED_BOLD if is_sell else self.ANSI_GREEN_BOLD
        c_price = (self.ANSI_RED_BOLD if is_sell else self.ANSI_GREEN_BOLD) if use_color else ""
        c_action_text = (c_action if use_color else "")

        dec = getattr(self.spec, "decimals", 0)
        unit_lbl = "pts" if getattr(self.spec, "symbol_base", "WIN") in ("WIN", "WDO") else "reais"
        target_unit = "pontos" if getattr(self.spec, "symbol_base", "WIN") in ("WIN", "WDO") else "reais"

        price_str = formatar_preco(alert.current_price, dec)
        zone_start_str = formatar_preco(alert.zone_start, dec)
        zone_end_str = formatar_preco(alert.zone_end, dec)
        ce_str = formatar_preco(alert.fvg.ce_50, dec)
        
        dist_pts_str = f"{alert.distance_to_zone:.{dec}f}" if dec > 0 else f"{int(round(alert.distance_to_zone))}"
        ce_dist_str = f"{alert.distance_to_ce:.{dec}f}" if dec > 0 else f"{int(round(alert.distance_to_ce))}"

        if alert.is_inside_zone:
            dist_desc = f"(Testando Zona | Faltam {ce_dist_str} {unit_lbl} p/ 50% CE)"
        else:
            dist_desc = f"(Faltam {dist_pts_str} {unit_lbl})"

        action_label = "[VENDA - RESISTÊNCIA]" if is_sell else "[COMPRA - SUPORTE]"
        operation_tag = f"({alert.action_direction})"
        asset_name_upper = getattr(self.spec, "name", "Mini-Índice B3").upper()

        # Melhoria 2: Tag destacada de iminência do 50% CE (<= 2 ticks)
        imminent_tag = ""
        if alert.is_ce_imminent:
            c_imm = self.ANSI_YELLOW_BOLD if use_color else ""
            imminent_tag = f" {c_imm}[IMINÊNCIA DE TOQUE NO 50% CE - PREPARAR CLIQUE]{c_reset}"

        # Melhoria 3: Tag de Zona Institucional Macro no cabeçalho para 240 minutos (4 Horas)
        macro_tag = " [ZONA INSTITUCIONAL MACRO - 4 HORAS]" if alert.fvg.timeframe == 240 else ""
        header_title = f"[RADAR FVG ANTECIPADO]{macro_tag} - {asset_name_upper} SE APROXIMANDO DE ZONA DE LIQUIDEZ"

        tf_label = f"{alert.fvg.timeframe} Minutos"
        if alert.fvg.timeframe == 240:
            tf_label = "240 Minutos (4 Horas)"

        lines = [
            "======================================================================",
            header_title,
            "======================================================================",
            f" Preço Atual       : {price_str}",
            f" Timeframe do FVG  : {tf_label} (Aberto / Não Liquidado)",
            f" Direção / Ação    : {c_action_text}{action_label}{c_reset}",
            f" Início da Zona    : {zone_start_str} {dist_desc}",
            f" {c_ce_label}Ponto de 50% (CE){c_reset} : {c_price}{ce_str} {operation_tag}{c_reset}{imminent_tag}",
            f" Fim da Zona       : {zone_end_str}",
            f" Objetivo Estimado : Reversão de {self.spec.default_stop_points:.{dec}f} a {self.spec.default_target_points:.{dec}f} {target_unit}",
            "======================================================================"
        ]

        return "\n".join(lines)

    def get_target_obstacles_info(
        self,
        direction: Any,
        entry_price: float,
        target_price: float
    ) -> List[Dict[str, Any]]:
        """
        Retorna a lista estruturada de obstáculos institucionais (FVGs contrários não liquidados)
        que interceptam o trajeto entre o preço de entrada e o preço do alvo.
        Identifica se é macro (timeframe >= 60), o preço da borda inicial de toque, 50% CE e distância.
        """
        dir_str = getattr(direction, 'value', str(direction)).upper()
        unliquidated = self.get_unliquidated_fvgs()
        obstacles: List[Dict[str, Any]] = []

        if dir_str == "COMPRA":
            # Entrada abaixo do alvo (preço subindo rumo ao gain)
            # Obstáculo: FVG Bearish (Resistência)
            for f in unliquidated:
                if f.direction == "BEARISH":
                    if (entry_price <= f.bottom <= target_price) or (entry_price <= f.ce_50 <= target_price) or (f.bottom <= entry_price <= f.top):
                        dist = max(0.0, f.bottom - entry_price)
                        obstacles.append({
                            'fvg': f,
                            'timeframe': f.timeframe,
                            'is_macro': f.timeframe >= 60,
                            'edge_price': f.bottom,
                            'ce_50': f.ce_50,
                            'distance': dist,
                            'direction': f.direction
                        })
        elif dir_str == "VENDA":
            # Entrada acima do alvo (preço descendo rumo ao gain)
            # Obstáculo: FVG Bullish (Suporte)
            for f in unliquidated:
                if f.direction == "BULLISH":
                    if (target_price <= f.top <= entry_price) or (target_price <= f.ce_50 <= entry_price) or (f.bottom <= entry_price <= f.top):
                        dist = max(0.0, entry_price - f.top)
                        obstacles.append({
                            'fvg': f,
                            'timeframe': f.timeframe,
                            'is_macro': f.timeframe >= 60,
                            'edge_price': f.top,
                            'ce_50': f.ce_50,
                            'distance': dist,
                            'direction': f.direction
                        })

        return obstacles

    def get_closest_obstacle_info(
        self,
        direction: Any,
        entry_price: float,
        target_price: float
    ) -> Optional[Dict[str, Any]]:
        """
        Retorna o obstáculo institucional mais próximo da entrada.
        Ordena pela menor distância em relação à entrada e, em caso de empate, maior timeframe.
        """
        obs_list = self.get_target_obstacles_info(direction, entry_price, target_price)
        if not obs_list:
            return None
        obs_list.sort(key=lambda c: (c['distance'], -c['timeframe']))
        return obs_list[0]

    def check_target_obstacles(
        self,
        direction: Any,
        entry_price: float,
        target_price: float
    ) -> List[str]:
        """
        Mapeia se o caminho entre a Entrada e o Alvo possui Obstáculos Institucionais
        (FVGs não liquidados em direção contrária) ou se há Passagem Livre.
        Melhoria 4: Consulta apenas zonas ativas não liquidadas.
        """
        obs_info_list = self.get_target_obstacles_info(direction, entry_price, target_price)
        dec = getattr(self.spec, "decimals", 0)
        unit = "pts" if getattr(self.spec, "symbol_base", "WIN") in ("WIN", "WDO") else "reais"

        if not obs_info_list:
            diff_pts = abs(target_price - entry_price)
            diff_str = f"{diff_pts:.{dec}f}" if dec > 0 else f"{int(round(diff_pts))}"
            tgt_str = formatar_preco(target_price, dec)
            return [f"PASSAGEM LIVRE: Nenhum obstáculo institucional (FVG MTF contrário) entre entrada e alvo ({diff_str} {unit} livres até {tgt_str})"]

        obstacles: List[str] = []
        for obs in obs_info_list:
            f = obs['fvg']
            dist = obs['distance']
            dist_str = f"{dist:.{dec}f}" if dec > 0 else f"{int(round(dist))}"
            bottom_str = formatar_preco(f.bottom, dec)
            top_str = formatar_preco(f.top, dec)
            ce_str = formatar_preco(f.ce_50, dec)
            tf_str = f"{f.timeframe}m (4h)" if f.timeframe == 240 else f"{f.timeframe}m"
            side_type = "Resistência" if f.direction == "BEARISH" else "Suporte"
            macro_tag = " [MACRO]" if obs['is_macro'] else ""
            obstacles.append(
                f"[ALERTA] OBSTÁCULO INSTITUCIONAL{macro_tag}: {side_type} FVG de {tf_str} em {bottom_str} - {top_str} "
                f"(50% CE: {ce_str}) a {dist_str} {unit} da entrada (no caminho do alvo)"
            )

        return obstacles
