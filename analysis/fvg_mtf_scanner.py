"""
analysis/fvg_mtf_scanner.py
Scanner determinístico Multi-Timeframe (MTF) de Fair Value Gaps (FVGs) Antigos Não Liquidados
e Sistema de Alerta Antecipado no Terminal PowerShell para o Mini-Índice (WIN) na B3.
Monitora simultaneamente os tempos gráficos de: 10m, 15m, 30m, 60m e 240m (4 horas).

Regras de Negócio e Visualização em conformidade com: fvg_mtf_antigravity_spec.md
"""

from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime
import json
import os

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


@dataclass
class ActiveMTFFVG:
    """Representa um FVG histórico mantido em memória até ser totalmente liquidado."""
    timeframe: int               # 10, 15, 30, 60, 240
    direction: str               # "BULLISH" ou "BEARISH"
    top: float                   # Limite superior da zona
    bottom: float                # Limite inferior da zona
    ce_50: float                 # Consequent Encroachment (50%) = (top + bottom) / 2.0
    formed_time: datetime        # Data/hora de formação
    start_bar: int = 0
    end_bar: int = 0
    is_liquidated: bool = False  # True quando rompido por completo
    tested_count: int = 0        # Número de toques/testes já realizados

    @property
    def size(self) -> float:
        return abs(self.top - self.bottom)


@dataclass
class FVGApproachAlert:
    """Dados de aproximação do preço a um FVG ativo para emissão de Alerta Antecipado."""
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


class FGVMTFScanner:
    """
    Rastreador Multi-Timeframe de FVGs Antigos Não Liquidados.
    Monitora 5m, 10m, 15m, 30m, 60m e 240m e calcula alertas antecipados.
    """

    MONITORED_TIMEFRAMES = [5, 10, 15, 30, 60, 240]

    # Códigos ANSI nativos para PowerShell / Windows Terminal
    ANSI_RESET = "\033[0m"
    ANSI_YELLOW_BOLD = "\033[1;93m"  # Destaque do rótulo Ponto de 50% (CE)
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
        
        # Lista de FVGs ativos em memória por timeframe
        self.active_fvgs: Dict[int, List[ActiveMTFFVG]] = {
            tf: [] for tf in self.MONITORED_TIMEFRAMES
        }
        
        self.last_price: float = 0.0
        # Carregar FVGs ativos preservados de sessões anteriores se auto_load estiver ativo
        if self.auto_load:
            self.load_from_disk()

    def register_candle(self, candle: Candle):
        """
        Recebe um candle fechado em qualquer timeframe e:
        1. Atualiza histórico local do timeframe.
        2. Avalia formação de novos FVGs (fórmula clássica SMC de 3 candles).
        3. Avalia liquidação de FVGs existentes no mesmo timeframe e timeframes superiores.
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
            
            # Evitar duplicações
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
                    is_liquidated=False
                )
                self.active_fvgs[tf].append(fvg)
                self.save_to_disk()

        # FVG de Baixa (Bearish / Resistência)
        elif c3.high < c1.low and (c1.low - c3.high) >= min_sz:
            top_val = c1.low
            bottom_val = c3.high
            ce_val = (top_val + bottom_val) / 2.0
            
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
                    is_liquidated=False
                )
                self.active_fvgs[tf].append(fvg)
                self.save_to_disk()

    def _get_storage_path(self) -> str:
        sym = getattr(self.spec, 'symbol_base', 'win').lower()
        data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data'))
        os.makedirs(data_dir, exist_ok=True)
        return os.path.join(data_dir, f"active_fvgs_{sym}.json")

    def save_to_disk(self):
        """Persiste os FVGs ativos em disco para manter a memória entre sessões/reinicializações."""
        if not getattr(self, 'auto_load', False):
            return
        try:
            path = self._get_storage_path()
            data = {}
            for tf, fvg_list in self.active_fvgs.items():
                data[str(tf)] = [
                    {
                        "timeframe": f.timeframe,
                        "direction": f.direction,
                        "top": f.top,
                        "bottom": f.bottom,
                        "ce_50": f.ce_50,
                        "formed_time": f.formed_time.isoformat() if f.formed_time else None,
                        "is_liquidated": f.is_liquidated,
                        "tested_count": f.tested_count
                    }
                    for f in fvg_list
                ]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def load_from_disk(self):
        """Restaura FVGs ativos preservados em disco."""
        try:
            path = self._get_storage_path()
            if not os.path.exists(path):
                return
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for tf_str, items in data.items():
                tf = int(tf_str)
                if tf in self.active_fvgs:
                    for item in items:
                        formed_dt = datetime.fromisoformat(item["formed_time"]) if item.get("formed_time") else datetime.now(TZ_BRASILIA)
                        already = any(abs(x.top - item["top"]) < 1.0 and abs(x.bottom - item["bottom"]) < 1.0 for x in self.active_fvgs[tf])
                        if not already:
                            self.active_fvgs[tf].append(
                                ActiveMTFFVG(
                                    timeframe=item["timeframe"],
                                    direction=item["direction"],
                                    top=item["top"],
                                    bottom=item["bottom"],
                                    ce_50=item["ce_50"],
                                    formed_time=formed_dt,
                                    is_liquidated=item.get("is_liquidated", False),
                                    tested_count=item.get("tested_count", 0)
                                )
                            )
        except Exception:
            pass

    def _check_liquidation_with_candle(self, candle: Candle):
        """
        Regra de Liquidação (Seção 3 da especificação):
        - FVG de Baixa (Venda/Resistência): completamente rompido para cima -> fechamento (candle.close > fvg.top)
        - FVG de Alta (Compra/Suporte): completamente rompido para baixo -> fechamento (candle.close < fvg.bottom)
        Apenas candles fechados de timeframe relevante (>= 5m ou >= fvg.timeframe) liquidam a zona.
        Pavio de teste (candle.high / candle.low) apenas testa a zona / 50% CE, sem liquidá-la.
        """
        changed = False
        for tf, fvg_list in self.active_fvgs.items():
            for fvg in fvg_list:
                if fvg.is_liquidated:
                    continue
                if candle.timeframe >= min(5, fvg.timeframe):
                    if fvg.direction == "BEARISH" and candle.close > fvg.top:
                        fvg.is_liquidated = True
                        changed = True
                    elif fvg.direction == "BULLISH" and candle.close < fvg.bottom:
                        fvg.is_liquidated = True
                        changed = True
        if changed:
            self.save_to_disk()

    def _check_liquidation_with_price(self, price: float):
        """
        Verifica se o preço atual ultrapassou amplamente a zona além da margem de rompimento.
        Requer avanço de pelo menos 4 ticks além do extremo para considerar rompimento definitivo em tempo real.
        """
        thresh = getattr(self.spec, 'tick_size', 5.0) * 4
        changed = False
        for tf, fvg_list in self.active_fvgs.items():
            for fvg in fvg_list:
                if fvg.is_liquidated:
                    continue
                if fvg.direction == "BEARISH" and price > (fvg.top + thresh):
                    fvg.is_liquidated = True
                    changed = True
                elif fvg.direction == "BULLISH" and price < (fvg.bottom - thresh):
                    fvg.is_liquidated = True
                    changed = True
        if changed:
            self.save_to_disk()

    def sync_from_engine(self, structure_engine):
        """
        Sincroniza os FVGs e candles já existentes no MultiTimeframeMarketEngine.
        Garante que qualquer histórico prévio nos analyzers alimente o scanner.
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
                    matched = None
                    for x in self.active_fvgs[tf]:
                        if abs(x.top - f.top) < 1.0 and abs(x.bottom - f.bottom) < 1.0:
                            matched = x
                            break
                    if not matched:
                        self.active_fvgs[tf].append(
                            ActiveMTFFVG(
                                timeframe=tf,
                                direction=f.direction,
                                top=f.top,
                                bottom=f.bottom,
                                ce_50=ce_val,
                                formed_time=f.timestamp,
                                start_bar=f.start_bar,
                                end_bar=f.end_bar,
                                is_liquidated=f.is_invalidated
                            )
                        )
                        changed = True
                    else:
                        if matched.is_liquidated != f.is_invalidated:
                            matched.is_liquidated = f.is_invalidated
                            changed = True
        if changed:
            self.save_to_disk()

    def get_unliquidated_fvgs(self, timeframe: Optional[int] = None) -> List[ActiveMTFFVG]:
        """Retorna lista de FVGs que continuam abertos (não liquidados)."""
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
        quando o Mini Índice entra no raio de aproximação (ex: 100 a 150 pontos antes
        de tocar na zona ou no nível de 50%).
        """
        radius = approach_radius or self.default_approach_radius
        alerts: List[FVGApproachAlert] = []

        if current_price <= 0:
            return alerts

        # Avaliar todos os FVGs não liquidados
        unliquidated = self.get_unliquidated_fvgs()

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
                        alerts.append(FVGApproachAlert(
                            fvg=fvg,
                            current_price=current_price,
                            distance_to_zone=dist_zone,
                            distance_to_ce=dist_ce,
                            is_inside_zone=False,
                            action_direction="VENDA",
                            zone_start=zone_start,
                            zone_end=zone_end
                        ))
                elif zone_start < current_price <= zone_end:
                    # Preço já penetrou na zona testando o 50% CE
                    dist_ce = abs(ce_val - current_price)
                    if dist_ce <= radius:
                        alerts.append(FVGApproachAlert(
                            fvg=fvg,
                            current_price=current_price,
                            distance_to_zone=0.0,
                            distance_to_ce=dist_ce,
                            is_inside_zone=True,
                            action_direction="VENDA",
                            zone_start=zone_start,
                            zone_end=zone_end
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
                        alerts.append(FVGApproachAlert(
                            fvg=fvg,
                            current_price=current_price,
                            distance_to_zone=dist_zone,
                            distance_to_ce=dist_ce,
                            is_inside_zone=False,
                            action_direction="COMPRA",
                            zone_start=zone_start,
                            zone_end=zone_end
                        ))
                elif zone_end <= current_price < zone_start:
                    # Preço já penetrou na zona testando o 50% CE
                    dist_ce = abs(current_price - ce_val)
                    if dist_ce <= radius:
                        alerts.append(FVGApproachAlert(
                            fvg=fvg,
                            current_price=current_price,
                            distance_to_zone=0.0,
                            distance_to_ce=dist_ce,
                            is_inside_zone=True,
                            action_direction="COMPRA",
                            zone_start=zone_start,
                            zone_end=zone_end
                        ))

        # Ordenar por proximidade (menor distância à zona) e precedência de timeframe (macro > micro)
        alerts.sort(key=lambda a: (a.distance_to_zone, -a.fvg.timeframe))
        return alerts

    def format_power_shell_alert(self, alert: FVGApproachAlert, use_color: bool = True) -> str:
        """
        Formata o Alerta Antecipado no PowerShell rigorosamente conforme Seção 4.3 da especificação:
        - Pontuação de Preço com separador de milhar por ponto (170.000).
        - Rótulo 'Ponto de 50% (CE)' em destaque (Amarelo Brilhante \033[1;93m).
        - Sinal de VENDA em VERMELHO BRILHANTE (\033[1;91m).
        - Sinal de COMPRA em VERDE BRILHANTE (\033[1;92m).
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

        lines = [
            "======================================================================",
            f"[RADAR FVG ANTECIPADO] - {asset_name_upper} SE APROXIMANDO DE ZONA DE LIQUIDEZ",
            "======================================================================",
            f" Preço Atual       : {price_str}",
            f" Timeframe do FVG  : {alert.fvg.timeframe} Minutos (Aberto / Não Liquidado)",
            f" Direção / Ação    : {c_action_text}{action_label}{c_reset}",
            f" Início da Zona    : {zone_start_str} {dist_desc}",
            f" {c_ce_label}Ponto de 50% (CE){c_reset} : {c_price}{ce_str} {operation_tag}{c_reset}",
            f" Fim da Zona       : {zone_end_str}",
            f" Objetivo Estimado : Reversão de {self.spec.default_stop_points:.{dec}f} a {self.spec.default_target_points:.{dec}f} {target_unit}",
            "======================================================================"
        ]

        return "\n".join(lines)

    def check_target_obstacles(
        self,
        direction: Any,
        entry_price: float,
        target_price: float
    ) -> List[str]:
        """
        Mapeia se o caminho entre a Entrada e o Alvo possui Obstáculos Institucionais
        (FVGs não liquidados em direção contrária) ou se há Passagem Livre.
        """
        dir_str = getattr(direction, 'value', str(direction)).upper()
        unliquidated = self.get_unliquidated_fvgs()
        dec = getattr(self.spec, "decimals", 0)
        unit = "pts" if getattr(self.spec, "symbol_base", "WIN") in ("WIN", "WDO") else "reais"

        obstacles: List[str] = []

        if dir_str == "COMPRA":
            # Entrada abaixo do alvo (preço subindo rumo ao gain)
            # Obstáculo: FVG Bearish (Resistência) no caminho entre entrada e alvo
            for f in unliquidated:
                if f.direction == "BEARISH":
                    # FVG localizado entre entrada e alvo (ou penetrando a zona)
                    if (entry_price <= f.bottom <= target_price) or (entry_price <= f.ce_50 <= target_price) or (f.bottom <= entry_price <= f.top):
                        dist = max(0.0, f.bottom - entry_price)
                        dist_str = f"{dist:.{dec}f}" if dec > 0 else f"{int(round(dist))}"
                        bottom_str = formatar_preco(f.bottom, dec)
                        top_str = formatar_preco(f.top, dec)
                        ce_str = formatar_preco(f.ce_50, dec)
                        obstacles.append(
                            f"[ALERTA] OBSTÁCULO INSTITUCIONAL: Resistência FVG de {f.timeframe}m em {bottom_str} - {top_str} "
                            f"(50% CE: {ce_str}) a {dist_str} {unit} da entrada (no caminho do alvo)"
                        )
        elif dir_str == "VENDA":
            # Entrada acima do alvo (preço descendo rumo ao gain)
            # Obstáculo: FVG Bullish (Suporte) no caminho entre entrada e alvo
            for f in unliquidated:
                if f.direction == "BULLISH":
                    # FVG localizado entre entrada e alvo (ou penetrando a zona)
                    if (target_price <= f.top <= entry_price) or (target_price <= f.ce_50 <= entry_price) or (f.bottom <= entry_price <= f.top):
                        dist = max(0.0, entry_price - f.top)
                        dist_str = f"{dist:.{dec}f}" if dec > 0 else f"{int(round(dist))}"
                        bottom_str = formatar_preco(f.bottom, dec)
                        top_str = formatar_preco(f.top, dec)
                        ce_str = formatar_preco(f.ce_50, dec)
                        obstacles.append(
                            f"[ALERTA] OBSTÁCULO INSTITUCIONAL: Suporte FVG de {f.timeframe}m em {bottom_str} - {top_str} "
                            f"(50% CE: {ce_str}) a {dist_str} {unit} da entrada (no caminho do alvo)"
                        )

        if not obstacles:
            diff_pts = abs(target_price - entry_price)
            diff_str = f"{diff_pts:.{dec}f}" if dec > 0 else f"{int(round(diff_pts))}"
            tgt_str = formatar_preco(target_price, dec)
            return [f"PASSAGEM LIVRE: Nenhum obstáculo institucional (FVG MTF contrário) entre entrada e alvo ({diff_str} {unit} livres até {tgt_str})"]

        return obstacles
