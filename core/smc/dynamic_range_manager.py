"""
core/smc/dynamic_range_manager.py
Gerenciador Determinístico de Recálculo Dinâmico de Dealing Range Intradiário (DynamicRangeManager).

Implementa:
  1. Gatilho de Expansão de Dealing Range (Extremos) via Confirmação Dupla em M5 com Filtro Anatômico de Continuidade:
     - 2 candles consecutivos de 5 minutos fechando fora do topo/fundo estrutural.
     - Renovação de extremo: High[2] > High[1] (alta) ou Low[2] < Low[1] (baixa).
     - Fechamento no terço extremo sem pavio de rejeição > 30%.
     - Deslocamento mínimo acumulado >= clearance_threshold (default 300 pts).
  2. Protocolo 4x4 de Validação:
     - Camada 1: M5 duplo + anatomia de continuidade.
     - Camada 2: Deslocamento mínimo.
     - Camada 3: Fluxo institucional (Delta 15m >= +3000 / <= -3000) e Cross-Market sem veto severo.
     - Camada 4: Janelas de horário operacionais (bloqueio 09h-10h e 11h28-11h33).
  3. Geometria do Novo Dealing Range:
     - Novo Topo / Fundo (máxima/mínima intradiária) e S/R Flip da fronteira rompida como nova base.
     - Novo 50% Equilibrium recalculado.
     - Zonas antigas distantes preservadas como STANDBY_DEEP_PULLBACK.
     - Injeção atômica de 3 novas zonas na pernada de expansão:
       (a) SR_FLIP_RETEST (Reteste da base rompida)
       (b) EXPANSION_FVG (FVG em região Discount/Premium da nova pernada)
       (c) NEW_EXTREME_EXHAUSTION (Exaustão na nova máxima/mínima)
       Todas com stop_sugerido_pts = 250.0 e alvo_sugerido_pts = 400.0 (R/R 1.60 fixo).
  4. Promoção de Zonas Intermediárias a Breaker Block:
     - Se 2 candles M5 com continuidade atravessarem um Order Block / FVG, decreta sua falha e promove
       automaticamente a BREAKER (inversão de polaridade: suporte virando venda, resistência virando compra).
  5. Escrita Atômica:
     - Gravação em data/niveis_60m.json.tmp com substituição atômica via os.replace para Hot-Reload
       instantâneo e seguro pelo Execution Harness.
"""

import os
import json
import logging
from enum import Enum
from datetime import datetime, time, timedelta
from typing import List, Optional, Tuple, Dict, Any
from dataclasses import dataclass, field

from core.models import Candle
from core.harness.contracts import (
    DealingRange,
    FVGZone,
    Niveis60mContract,
    ZoneType,
    ZoneStatus,
    PrimarySetup
)

# Estilização ANSI para logs
ANSI_RESET = "\033[0m"
ANSI_BOLD = "\033[1m"
ANSI_RED = "\033[31m"
ANSI_GREEN = "\033[32m"
ANSI_YELLOW = "\033[33m"
ANSI_BLUE = "\033[34m"
ANSI_MAGENTA = "\033[35m"
ANSI_CYAN = "\033[36m"


class DynamicRangeState(str, Enum):
    RANGE_ORIGINAL = "RANGE_ORIGINAL"
    EXPANSION_ACTIVE = "EXPANSION_ACTIVE"
    STANDBY_DEEP_PULLBACK = "STANDBY_DEEP_PULLBACK"
    BREAKER_PROMOTED = "BREAKER_PROMOTED"


class M5CandleBuilder:
    """Agregador de ticks em barras fechadas de 5 minutos (M5)."""
    def __init__(self):
        self.current_candle: Optional[Candle] = None
        self.current_period_start: Optional[datetime] = None

    def update_tick(
        self,
        price: float,
        timestamp: Optional[datetime] = None,
        volume: float = 0.0
    ) -> Optional[Candle]:
        """
        Recebe um tick. Se cruzou a fronteira de 5 minutos (:00, :05, :10...),
        fecha e retorna o candle anterior com is_closed=True.
        """
        now = timestamp or datetime.now()
        minute_slot = (now.minute // 5) * 5
        period_start = now.replace(minute=minute_slot, second=0, microsecond=0)

        closed_candle = None
        if self.current_period_start is not None and period_start > self.current_period_start:
            if self.current_candle:
                self.current_candle.is_closed = True
                self.current_candle.close_time = now
                closed_candle = self.current_candle
            self.current_candle = None

        if self.current_candle is None:
            self.current_period_start = period_start
            self.current_candle = Candle(
                timeframe=5,
                open_time=period_start,
                close_time=period_start + timedelta(minutes=5),
                open=price,
                high=price,
                low=price,
                close=price,
                volume=volume,
                is_closed=False
            )
        else:
            self.current_candle.high = max(self.current_candle.high, price)
            self.current_candle.low = min(self.current_candle.low, price)
            self.current_candle.close = price
            self.current_candle.volume += volume

        return closed_candle


@dataclass
class DynamicRangeEvent:
    event_type: str                   # "BULLISH_EXPANSION", "BEARISH_EXPANSION", "BREAKER_PROMOTION", "STANDBY_UPDATE"
    timestamp: datetime
    previous_dealing_range: DealingRange
    new_dealing_range: Optional[DealingRange]
    affected_zones: List[FVGZone]
    details: str


class DynamicRangeManager:
    """
    Gerenciador determinístico de Dealing Range e transições de Breaker Block.
    Opera em background (Orquestrador) e sincroniza via Hot-Reload atômico em niveis_60m.json.
    """
    def __init__(
        self,
        niveis_path: str = "data/niveis_60m.json",
        clearance_threshold: float = 300.0,
        enforce_time_windows: bool = True,
        enforce_delta_filter: bool = True
    ):
        self.niveis_path = niveis_path
        self.clearance_threshold = clearance_threshold
        self.enforce_time_windows = enforce_time_windows
        self.enforce_delta_filter = enforce_delta_filter
        
        self.state: DynamicRangeState = DynamicRangeState.RANGE_ORIGINAL
        self.candles_m5: List[Candle] = []
        self.events_history: List[DynamicRangeEvent] = []
        
        # Estado atual em cache
        self.cached_niveis: Optional[Niveis60mContract] = None
        self._load_current_niveis()

    def _load_current_niveis(self) -> Optional[Niveis60mContract]:
        """Carrega e valida o contrato de níveis atual a partir do disco."""
        if not os.path.exists(self.niveis_path):
            return None
        try:
            with open(self.niveis_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.cached_niveis = Niveis60mContract(**data)
            return self.cached_niveis
        except Exception as e:
            logging.error(f"[DYNAMIC RANGE] Erro ao carregar {self.niveis_path}: {e}")
            return None

    def is_in_allowed_time_window(self, t: time) -> Tuple[bool, str]:
        """
        Valida Camada 4: Janelas Operacionais e Blackouts.
        """
        if not self.enforce_time_windows:
            return True, "Filtro de horário desativado para testes/simulação"

        # Janelas de Blackout Rígido
        if time(9, 0) <= t < time(10, 0):
            return False, "BLACKOUT B3: 09:00 - 10:00 (Mercado à vista em leilão)"
        if time(11, 28) <= t <= time(11, 33):
            return False, "BLACKOUT NYSE: 11:28 - 11:33 (Leilão e abertura de Nova York)"

        # Janelas Permitidas
        is_window_1 = time(10, 30) <= t <= time(11, 25)
        is_window_2 = time(11, 35) <= t <= time(13, 0)
        is_window_3 = time(14, 0) <= t <= time(16, 45)

        if is_window_1 or is_window_2 or is_window_3:
            return True, "Janela operacional autorizada"

        return False, f"Fora das janelas permitidas de expansão institucional ({t.strftime('%H:%M:%S')})"

    def validate_anatomical_continuity(
        self,
        c1: Candle,
        c2: Candle,
        direction: str,
        boundary: float
    ) -> Tuple[bool, str]:
        """
        Valida Camada 1 (M5 Duplo + Anatomia) e Camada 2 (Clearance).
        Retorna (autorizado: bool, motivo: str).
        """
        # Checagem de barras válidas
        if c1.range <= 0 or c2.range <= 0:
            return False, "Candle com amplitude nula ou dados corrompidos"

        if direction == "BULLISH":
            # 1. Ambos os candles devem fechar acima da fronteira
            if c1.close <= boundary or c2.close <= boundary:
                return False, f"Fechamento fora do padrão: C1.close={c1.close:.0f}, C2.close={c2.close:.0f} <= Topo={boundary:.0f}"

            # 2. Renovação de Máxima: High[2] > High[1]
            if c2.high <= c1.high:
                return False, f"Falta de expansão direcional: C2.high ({c2.high:.0f}) <= C1.high ({c1.high:.0f})"

            # 3. Pavio Superior de Rejeição (Shooting Star / Upthrust Trap Filter)
            # Pavio superior <= 30% da amplitude total da barra
            upper_wick = c2.high - max(c2.open, c2.close)
            wick_ratio = upper_wick / c2.range
            if wick_ratio > 0.30:
                return False, f"UPTHRUST TRAP: Pavio superior excessivo ({wick_ratio*100:.1f}% > 30%). Rejeição institucional de topo."

            # 4. Fechamento no terço superior do range
            lower_third_boundary = c2.low + (2.0 / 3.0) * c2.range
            if c2.close < lower_third_boundary:
                return False, "Fechamento de C2 fora do terço superior da barra."

            # 5. Clearance Mínimo (Camada 2): Avanço acumulado >= clearance_threshold
            max_reached = max(c1.high, c2.high)
            advance = max_reached - boundary
            if advance < self.clearance_threshold:
                return False, f"Clearance insuficiente: avanço de {advance:.0f} pts < mínimo de {self.clearance_threshold:.0f} pts (Rompimento anêmico)."

            # Garante que o fechamento de C2 não ficou grudado na linha
            if (c2.close - boundary) < (self.clearance_threshold * 0.60):
                return False, "Candle 2 retraiu excessivamente próximo à linha rompida."

            return True, f"BOS ALTA CONFIRMADO: C1={c1.close:.0f}, C2={c2.close:.0f}, Avanço={advance:.0f} pts sem pavio de rejeição."

        elif direction == "BEARISH":
            # 1. Ambos os candles devem fechar abaixo da fronteira
            if c1.close >= boundary or c2.close >= boundary:
                return False, f"Fechamento fora do padrão: C1.close={c1.close:.0f}, C2.close={c2.close:.0f} >= Fundo={boundary:.0f}"

            # 2. Renovação de Mínima: Low[2] < Low[1]
            if c2.low >= c1.low:
                return False, f"Falta de expansão direcional: C2.low ({c2.low:.0f}) >= C1.low ({c1.low:.0f})"

            # 3. Pavio Inferior de Rejeição (Hammer / Liquidity Grab Filter)
            # Pavio inferior <= 30% da amplitude total da barra
            lower_wick = min(c2.open, c2.close) - c2.low
            wick_ratio = lower_wick / c2.range
            if wick_ratio > 0.30:
                return False, f"HAMMER TRAP: Pavio inferior excessivo ({wick_ratio*100:.1f}% > 30%). Rejeição institucional de fundo."

            # 4. Fechamento no terço inferior do range
            upper_third_boundary = c2.low + (1.0 / 3.0) * c2.range
            if c2.close > upper_third_boundary:
                return False, "Fechamento de C2 fora do terço inferior da barra."

            # 5. Clearance Mínimo (Camada 2)
            min_reached = min(c1.low, c2.low)
            advance = boundary - min_reached
            if advance < self.clearance_threshold:
                return False, f"Clearance insuficiente: avanço de {advance:.0f} pts < mínimo de {self.clearance_threshold:.0f} pts (Rompimento anêmico)."

            if (boundary - c2.close) < (self.clearance_threshold * 0.60):
                return False, "Candle 2 retraiu excessivamente próximo à linha rompida."

            return True, f"BOS BAIXA CONFIRMADO: C1={c1.close:.0f}, C2={c2.close:.0f}, Avanço={advance:.0f} pts sem pavio de rejeição."

        return False, "Direção inválida"

    def check_expansion_trigger(
        self,
        c1: Candle,
        c2: Candle,
        current_time: datetime,
        delta_15m: float = 0.0,
        macro_veto_buy: bool = False,
        macro_veto_sell: bool = False
    ) -> Optional[Tuple[str, str]]:
        """
        Avalia o Checklist 4x4 completo.
        Retorna (direction, reason) se aprovado, ou None se rejeitado.
        """
        niveis = self.cached_niveis or self._load_current_niveis()
        if not niveis:
            return None

        dr = niveis.dealing_range
        t = current_time.time()

        # Camada 4: Janela de Horário
        time_ok, time_msg = self.is_in_allowed_time_window(t)
        if not time_ok:
            return None

        # 1. Avalia Expansão de Alta
        if c1.close > dr.topo_estrutural and c2.close > dr.topo_estrutural:
            # Camada 3: Macro & Delta
            if macro_veto_buy:
                return None
            if self.enforce_delta_filter and delta_15m < 3000.0 and delta_15m != 0.0:
                return None

            # Camadas 1 e 2: Anatomia e Clearance
            ok_alta, msg_alta = self.validate_anatomical_continuity(c1, c2, "BULLISH", dr.topo_estrutural)
            if ok_alta:
                return ("BULLISH_EXPANSION", msg_alta)

        # 2. Avalia Expansão de Baixa
        if c1.close < dr.fundo_estrutural and c2.close < dr.fundo_estrutural:
            # Camada 3: Macro & Delta
            if macro_veto_sell:
                return None
            if self.enforce_delta_filter and delta_15m > -3000.0 and delta_15m != 0.0:
                return None

            # Camadas 1 e 2: Anatomia e Clearance
            ok_baixa, msg_baixa = self.validate_anatomical_continuity(c1, c2, "BEARISH", dr.fundo_estrutural)
            if ok_baixa:
                return ("BEARISH_EXPANSION", msg_baixa)

        return None

    def recalculate_dealing_range_and_zones(
        self,
        direction: str,
        c1: Candle,
        c2: Candle,
        current_time: datetime
    ) -> Tuple[DealingRange, List[FVGZone]]:
        """
        Gera a nova geometria matemática do Dealing Range e injeta as 3 zonas
        frescas da pernada de expansão, marcando as antigas como STANDBY_DEEP_PULLBACK.
        """
        niveis = self.cached_niveis or self._load_current_niveis()
        old_dr = niveis.dealing_range
        updated_zones: List[FVGZone] = []

        if direction == "BULLISH_EXPANSION":
            novo_topo = round(max(c1.high, c2.high), 0)
            # O antigo topo agora atua como suporte / S/R Flip (Fundo da nova pernada)
            novo_fundo = round(old_dr.topo_estrutural, 0)
            novo_eq = round((novo_topo + novo_fundo) / 2.0, 2)
            new_dr = DealingRange(
                topo_estrutural=novo_topo,
                fundo_estrutural=novo_fundo,
                equilibrium_50=novo_eq
            )

            # 1. Zonas antigas que ficaram abaixo do novo fundo entram em STANDBY
            for z in niveis.zonas_fvg:
                if z.top < novo_fundo:
                    z.status = ZoneStatus.STANDBY_DEEP_PULLBACK
                    updated_zones.append(z)
                else:
                    updated_zones.append(z)

            # 2. Injeta as 3 Novas Zonas Estratégicas
            # (a) Reteste de S/R Flip (Antigo Topo que virou Suporte)
            z_sr_flip = FVGZone(
                id=f"ZONA_SR_FLIP_SUPORTE_{int(novo_fundo)}",
                tipo_original=ZoneType.BULLISH,
                top=novo_fundo + 50.0,
                ce_50=novo_fundo,
                bottom=novo_fundo - 50.0,
                setup_primario=PrimarySetup.CONTINUATION_BUY,
                stop_sugerido_pts=250.0,
                alvo_sugerido_pts=400.0,
                status=ZoneStatus.UNMITIGATED,
                notes=f"S/R FLIP SUPORTE em {novo_fundo:.0f}: Antigo topo rompido agora atuando como base de suporte."
            )

            # (b) FVG de Continuação em Região DISCOUNT do Novo Range
            fvg_level = round(novo_fundo + (novo_topo - novo_fundo) * 0.35, 0)
            z_expansion_fvg = FVGZone(
                id=f"ZONA_EXPANSAO_FVG_DISCOUNT_{int(fvg_level)}",
                tipo_original=ZoneType.BULLISH,
                top=fvg_level + 40.0,
                ce_50=fvg_level,
                bottom=fvg_level - 40.0,
                setup_primario=PrimarySetup.CONTINUATION_BUY,
                stop_sugerido_pts=250.0,
                alvo_sugerido_pts=400.0,
                status=ZoneStatus.UNMITIGATED,
                notes=f"EXPANSION FVG em {fvg_level:.0f}: Ponto de recarga institucional em DISCOUNT da nova pernada."
            )

            # (c) Exaustão na Nova Máxima Intraday
            z_exhaustion = FVGZone(
                id=f"ZONA_EXAUSTAO_NOVA_MAXIMA_{int(novo_topo)}",
                tipo_original=ZoneType.BEARISH,
                top=novo_topo + 30.0,
                ce_50=novo_topo,
                bottom=novo_topo - 40.0,
                setup_primario=PrimarySetup.CONTINUATION_SELL,
                stop_sugerido_pts=250.0,
                alvo_sugerido_pts=400.0,
                status=ZoneStatus.UNMITIGATED,
                notes=f"TOPO EXAUSTÃO em {novo_topo:.0f}: Resistência tática de clímax na nova máxima da expansão."
            )

            updated_zones.extend([z_sr_flip, z_expansion_fvg, z_exhaustion])

        else: # BEARISH_EXPANSION
            novo_fundo = round(min(c1.low, c2.low), 0)
            # O antigo fundo agora atua como resistência / S/R Flip (Topo da nova pernada)
            novo_topo = round(old_dr.fundo_estrutural, 0)
            novo_eq = round((novo_topo + novo_fundo) / 2.0, 2)
            new_dr = DealingRange(
                topo_estrutural=novo_topo,
                fundo_estrutural=novo_fundo,
                equilibrium_50=novo_eq
            )

            # 1. Zonas antigas que ficaram acima do novo topo entram em STANDBY
            for z in niveis.zonas_fvg:
                if z.bottom > novo_topo:
                    z.status = ZoneStatus.STANDBY_DEEP_PULLBACK
                    updated_zones.append(z)
                else:
                    updated_zones.append(z)

            # 2. Injeta as 3 Novas Zonas Estratégicas
            # (a) Reteste de S/R Flip (Antigo Fundo que virou Resistência)
            z_sr_flip = FVGZone(
                id=f"ZONA_SR_FLIP_RESISTENCIA_{int(novo_topo)}",
                tipo_original=ZoneType.BEARISH,
                top=novo_topo + 50.0,
                ce_50=novo_topo,
                bottom=novo_topo - 50.0,
                setup_primario=PrimarySetup.CONTINUATION_SELL,
                stop_sugerido_pts=250.0,
                alvo_sugerido_pts=400.0,
                status=ZoneStatus.UNMITIGATED,
                notes=f"S/R FLIP RESISTÊNCIA em {novo_topo:.0f}: Antigo fundo rompido agora atuando como barreira de venda."
            )

            # (b) FVG de Continuação em Região PREMIUM do Novo Range
            fvg_level = round(novo_topo - (novo_topo - novo_fundo) * 0.35, 0)
            z_expansion_fvg = FVGZone(
                id=f"ZONA_EXPANSAO_FVG_PREMIUM_{int(fvg_level)}",
                tipo_original=ZoneType.BEARISH,
                top=fvg_level + 40.0,
                ce_50=fvg_level,
                bottom=fvg_level - 40.0,
                setup_primario=PrimarySetup.CONTINUATION_SELL,
                stop_sugerido_pts=250.0,
                alvo_sugerido_pts=400.0,
                status=ZoneStatus.UNMITIGATED,
                notes=f"EXPANSION FVG em {fvg_level:.0f}: Ponto de recarga institucional em PREMIUM da nova pernada de baixa."
            )

            # (c) Exaustão na Nova Mínima Intraday
            z_exhaustion = FVGZone(
                id=f"ZONA_EXAUSTAO_NOVA_MINIMA_{int(novo_fundo)}",
                tipo_original=ZoneType.BULLISH,
                top=novo_fundo + 40.0,
                ce_50=novo_fundo,
                bottom=novo_fundo - 30.0,
                setup_primario=PrimarySetup.CONTINUATION_BUY,
                stop_sugerido_pts=250.0,
                alvo_sugerido_pts=400.0,
                status=ZoneStatus.UNMITIGATED,
                notes=f"FUNDO EXAUSTÃO em {novo_fundo:.0f}: Suporte tático de clímax na nova mínima da expansão."
            )

            updated_zones.extend([z_sr_flip, z_expansion_fvg, z_exhaustion])

        return new_dr, updated_zones

    def evaluate_breaker_promotion(
        self,
        c1: Candle,
        c2: Candle
    ) -> List[FVGZone]:
        """
        Regra de Breaker Block em Zonas Intermediárias:
        Se 2 candles M5 fecharem atravessando um Order Block / FVG com continuidade,
        a defesa é decretada como FALHA e a zona é promovida a BREAKER_BLOCK (inversão).
        """
        niveis = self.cached_niveis or self._load_current_niveis()
        if not niveis:
            return []

        dr = niveis.dealing_range
        promoted: List[FVGZone] = []

        for z in niveis.zonas_fvg:
            # Só avalia zonas intermediárias ativas que ainda não são Breaker nem Standby
            if z.status in (ZoneStatus.EXHAUSTED, ZoneStatus.INVALIDATED, ZoneStatus.STANDBY_DEEP_PULLBACK):
                continue
            if z.tipo_original == ZoneType.BREAKER:
                continue

            # Zonas no limite estrutural de topo/fundo são geridas pelo Dealing Range
            if z.top >= (dr.topo_estrutural - 50.0) or z.bottom <= (dr.fundo_estrutural + 50.0):
                continue

            # Caso 1: Resistência (BEARISH) rompida para cima -> Vira BREAKER de Compra
            if z.tipo_original in (ZoneType.BEARISH, ZoneType.IFVG_BEARISH):
                if c1.close > z.top and c2.close > z.top and c2.high > c1.high:
                    upper_wick = c2.high - max(c2.open, c2.close)
                    if (c2.range > 0) and (upper_wick / c2.range <= 0.35):
                        z.tipo_original = ZoneType.BREAKER
                        z.setup_primario = PrimarySetup.INVERSION_BUY
                        z.status = ZoneStatus.UNMITIGATED
                        z.touch_count = 0
                        z.notes = f"PROMOVIDO A BREAKER BLOCK (COMPRA): Resistência {z.top:.0f} violada por 2x M5. Agora opera como suporte invertido."
                        promoted.append(z)

            # Caso 2: Suporte (BULLISH) rompido para baixo -> Vira BREAKER de Venda
            elif z.tipo_original in (ZoneType.BULLISH, ZoneType.IFVG_BULLISH):
                if c1.close < z.bottom and c2.close < z.bottom and c2.low < c1.low:
                    lower_wick = min(c2.open, c2.close) - c2.low
                    if (c2.range > 0) and (lower_wick / c2.range <= 0.35):
                        z.tipo_original = ZoneType.BREAKER
                        z.setup_primario = PrimarySetup.INVERSION_SELL
                        z.status = ZoneStatus.UNMITIGATED
                        z.touch_count = 0
                        z.notes = f"PROMOVIDO A BREAKER BLOCK (VENDA): Suporte {z.bottom:.0f} violado por 2x M5. Agora opera como resistência invertida."
                        promoted.append(z)

        return promoted

    def atomic_save_niveis(self, niveis: Niveis60mContract) -> bool:
        """
        Persiste o contrato atualizado de forma 100% atômica via os.replace,
        garantindo integridade de leitura pelo Hot-Reload do Execution Harness.
        """
        tmp_path = f"{self.niveis_path}.tmp"
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.niveis_path)), exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(niveis.model_dump(), f, indent=2, default=str)
                f.flush()
                os.fsync(f.fileno())

            os.replace(tmp_path, self.niveis_path)
            self.cached_niveis = niveis
            return True
        except Exception as e:
            logging.error(f"[DYNAMIC RANGE ATOMIC SAVE] Falha crítica ao gravar {self.niveis_path}: {e}")
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            return False

    def on_candle_closed(
        self,
        candle: Candle,
        delta_15m: float = 0.0,
        macro_veto_buy: bool = False,
        macro_veto_sell: bool = False
    ) -> Optional[DynamicRangeEvent]:
        """
        Handler oficial disparado no fechamento de cada candle de 5 minutos (M5).
        Executa os checks de Breaker Block e Expansão de Dealing Range.
        """
        # Só processa barras fechadas de 5 minutos
        if candle.timeframe != 5 or not candle.is_closed:
            return None

        self.candles_m5.append(candle)
        # Mantém histórico recente (últimos 10 candles M5)
        if len(self.candles_m5) > 10:
            self.candles_m5 = self.candles_m5[-10:]

        if len(self.candles_m5) < 2:
            return None

        c1 = self.candles_m5[-2]
        c2 = self.candles_m5[-1]
        now = candle.close_time or datetime.now()

        # 1. Verifica se houve Gatilho de Expansão do Dealing Range (Checklist 4x4)
        trigger_res = self.check_expansion_trigger(
            c1=c1,
            c2=c2,
            current_time=now,
            delta_15m=delta_15m,
            macro_veto_buy=macro_veto_buy,
            macro_veto_sell=macro_veto_sell
        )

        if trigger_res:
            direction, reason = trigger_res
            niveis = self.cached_niveis or self._load_current_niveis()
            if not niveis:
                return None

            old_dr = niveis.dealing_range
            new_dr, updated_zones = self.recalculate_dealing_range_and_zones(
                direction=direction,
                c1=c1,
                c2=c2,
                current_time=now
            )

            # Atualiza o contrato e salva atomicamente
            niveis.dealing_range = new_dr
            niveis.zonas_fvg = updated_zones
            success = self.atomic_save_niveis(niveis)

            if success:
                self.state = DynamicRangeState.EXPANSION_ACTIVE
                event = DynamicRangeEvent(
                    event_type=direction,
                    timestamp=now,
                    previous_dealing_range=old_dr,
                    new_dealing_range=new_dr,
                    affected_zones=[z for z in updated_zones if z.status == ZoneStatus.UNMITIGATED],
                    details=f"{reason} | Novo DR: Topo {new_dr.topo_estrutural:.0f} / Fundo {new_dr.fundo_estrutural:.0f} / Eq {new_dr.equilibrium_50:.0f}"
                )
                self.events_history.append(event)
                self._log_event(event)
                return event

        # 2. Verifica se houve falha de OB/FVG Intermediário -> Promoção para Breaker Block
        promoted_breakers = self.evaluate_breaker_promotion(c1, c2)
        if promoted_breakers:
            niveis = self.cached_niveis or self._load_current_niveis()
            if niveis:
                self.atomic_save_niveis(niveis)
                self.state = DynamicRangeState.BREAKER_PROMOTED
                event = DynamicRangeEvent(
                    event_type="BREAKER_PROMOTION",
                    timestamp=now,
                    previous_dealing_range=niveis.dealing_range,
                    new_dealing_range=None,
                    affected_zones=promoted_breakers,
                    details=f"Promoção de {len(promoted_breakers)} zona(s) a BREAKER BLOCK por rompimento M5 duplo."
                )
                self.events_history.append(event)
                self._log_event(event)
                return event

        return None

    def _log_event(self, event: DynamicRangeEvent):
        """Emite logs no terminal ANSI para rastreamento visual transparente."""
        now_str = event.timestamp.strftime("%H:%M:%S")
        if event.event_type == "BULLISH_EXPANSION":
            print(f"\n{ANSI_BOLD}{ANSI_CYAN}⚡ [DYNAMIC RANGE MANAGER — EXPANSION ACTIVE (ALTA)]{ANSI_RESET}")
            print(f"   Horário: {now_str} | {event.details}")
            print(f"   {ANSI_GREEN}Novo 50% Equilibrium: {event.new_dealing_range.equilibrium_50:.0f} (Região Discount redefinida para Compras){ANSI_RESET}\n")
        elif event.event_type == "BEARISH_EXPANSION":
            print(f"\n{ANSI_BOLD}{ANSI_MAGENTA}⚡ [DYNAMIC RANGE MANAGER — EXPANSION ACTIVE (BAIXA)]{ANSI_RESET}")
            print(f"   Horário: {now_str} | {event.details}")
            print(f"   {ANSI_RED}Novo 50% Equilibrium: {event.new_dealing_range.equilibrium_50:.0f} (Região Premium redefinida para Vendas){ANSI_RESET}\n")
        elif event.event_type == "BREAKER_PROMOTION":
            print(f"\n{ANSI_BOLD}{ANSI_YELLOW}🛡️ [DYNAMIC RANGE MANAGER — BREAKER PROMOTED]{ANSI_RESET}")
            for z in event.affected_zones:
                print(f"   Zona {z.id} ({z.tipo_original.value}) | {z.setup_primario.value} | {z.notes}")
            print()
