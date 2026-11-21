"""
core/harness/state_machine.py
Máquina de Estados Finita para Zonas FVG e iFVG (Inversion Fair Value Gap) de 60m.
Gerencia transições:
  UNMITIGATED -> TESTING_CONTINUATION -> INVERTED_PENDING_RETEST -> TRIGGER_IFVG -> EXHAUSTED
"""

from typing import List, Dict, Optional, Tuple, Any
from datetime import datetime
from core.harness.contracts import (
    FVGZone,
    ZoneStatus,
    ZoneType,
    PrimarySetup,
    TradingDirection
)


class FVGStateMachine:
    def __init__(self, zones: List[FVGZone]):
        self.zones: Dict[str, FVGZone] = {z.id: z for z in zones}
        self.proximity_threshold_pts: float = 150.0

    def get_all_zones(self) -> List[FVGZone]:
        return list(self.zones.values())

    def get_active_zones(self) -> List[FVGZone]:
        return [z for z in self.zones.values() if z.status not in (ZoneStatus.EXHAUSTED, ZoneStatus.INVALIDATED)]

    def evaluate_price_tick(self, current_price: float, timestamp: datetime) -> List[Dict[str, Any]]:
        """
        Processa um tick de preço contra todas as zonas ativas.
        Retorna eventos detectados (aproximação, entrada na zona, teste).
        """
        events = []

        for zone in self.get_active_zones():
            # 1. Checagem de Proximidade (Aviso Prévio)
            dist_top = abs(current_price - zone.top)
            dist_bottom = abs(current_price - zone.bottom)
            min_dist = min(dist_top, dist_bottom)

            inside_zone = (zone.bottom <= current_price <= zone.top)

            if zone.status == ZoneStatus.UNMITIGATED:
                if inside_zone:
                    zone.status = ZoneStatus.TESTING_CONTINUATION
                    events.append({
                        "type": "ZONE_ENTERED",
                        "zone_id": zone.id,
                        "zone_type": zone.tipo_original,
                        "price": current_price,
                        "status": zone.status,
                        "timestamp": timestamp,
                        "message": f"Preço entrou na zona {zone.id} [{zone.bottom:.0f} - {zone.top:.0f}]. Testando continuidade."
                    })
                elif min_dist <= self.proximity_threshold_pts:
                    events.append({
                        "type": "PROXIMITY_ALERT",
                        "zone_id": zone.id,
                        "zone_type": zone.tipo_original,
                        "price": current_price,
                        "distance_pts": min_dist,
                        "timestamp": timestamp,
                        "message": f"Preço a {min_dist:.0f} pts da borda da zona {zone.id} ({zone.bottom:.0f} - {zone.top:.0f})."
                    })

            elif zone.status == ZoneStatus.TESTING_CONTINUATION:
                if inside_zone:
                    events.append({
                        "type": "ZONE_TESTING",
                        "zone_id": zone.id,
                        "price": current_price,
                        "timestamp": timestamp
                    })

            elif zone.status == ZoneStatus.INVERTED_PENDING_RETEST:
                # Preço voltou para retestar a zona rompida (iFVG)
                if inside_zone:
                    zone.status = ZoneStatus.TRIGGER_IFVG
                    events.append({
                        "type": "IFVG_RETEST_ENTERED",
                        "zone_id": zone.id,
                        "price": current_price,
                        "status": zone.status,
                        "timestamp": timestamp,
                        "message": f"Preço retestando iFVG invertido {zone.id} [{zone.bottom:.0f} - {zone.top:.0f}]."
                    })

        return events

    def on_candle_closed(self, timeframe: int, open_p: float, high_p: float, low_p: float, close_p: float, timestamp: datetime) -> List[Dict[str, Any]]:
        """
        Processa fechamento de candle de 5m ou 15m para detectar rompimento estrutural (inversão em iFVG).
        """
        events = []
        if timeframe not in (5, 15, 60):
            return events

        for zone in self.get_active_zones():
            # Inversão de FVG de Baixa (Bearish) para iFVG de Alta:
            # O candle fechou com corpo ACIMA do topo da zona de baixa
            if zone.tipo_original == ZoneType.BEARISH and zone.status in (ZoneStatus.UNMITIGATED, ZoneStatus.TESTING_CONTINUATION):
                if close_p > zone.top:
                    zone.status = ZoneStatus.INVERTED_PENDING_RETEST
                    zone.inversion_level = zone.top
                    events.append({
                        "type": "ZONE_INVERTED_TO_BULLISH_IFVG",
                        "zone_id": zone.id,
                        "breakout_price": close_p,
                        "inversion_level": zone.top,
                        "timeframe": timeframe,
                        "timestamp": timestamp,
                        "message": f"Candle de {timeframe}m fechou acima ({close_p:.0f} > {zone.top:.0f}). Zona {zone.id} virou iFVG de ALTA (suporte no reteste)."
                    })

            # Inversão de FVG de Alta (Bullish) para iFVG de Baixa:
            # O candle fechou com corpo ABAIXO do fundo da zona de alta
            elif zone.tipo_original == ZoneType.BULLISH and zone.status in (ZoneStatus.UNMITIGATED, ZoneStatus.TESTING_CONTINUATION):
                if close_p < zone.bottom:
                    zone.status = ZoneStatus.INVERTED_PENDING_RETEST
                    zone.inversion_level = zone.bottom
                    events.append({
                        "type": "ZONE_INVERTED_TO_BEARISH_IFVG",
                        "zone_id": zone.id,
                        "breakout_price": close_p,
                        "inversion_level": zone.bottom,
                        "timeframe": timeframe,
                        "timestamp": timestamp,
                        "message": f"Candle de {timeframe}m fechou abaixo ({close_p:.0f} < {zone.bottom:.0f}). Zona {zone.id} virou iFVG de BAIXA (resistência no reteste)."
                    })

        return events

    def mark_zone_exhausted(self, zone_id: str, reason: str = "TARGET_OR_STOP_REACHED"):
        if zone_id in self.zones:
            self.zones[zone_id].status = ZoneStatus.EXHAUSTED
