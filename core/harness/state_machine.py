"""
core/harness/state_machine.py
Máquina de Estados Finita para Zonas FVG e iFVG (Inversion Fair Value Gap) de 60m.
Gerencia o ciclo de vida rigoroso de cada zona:
  UNMITIGATED -> TESTING_CONTINUATION -> CANDIDATE -> VALIDATED -> EMITTING -> EMITTED -> EXHAUSTED
Suporta persistência de sessão em disco para evitar reemissão de sinais após reinício.
"""

import os
import json
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
    def __init__(self, zones: List[FVGZone], session_storage_path: Optional[str] = None):
        self.zones: Dict[str, FVGZone] = {z.id: z for z in zones}
        self.proximity_threshold_pts: float = 150.0
        self.session_storage_path = session_storage_path
        
        # Se um caminho de sessão foi informado, restaura estado prévio
        if self.session_storage_path and os.path.exists(self.session_storage_path):
            self.load_session(self.session_storage_path)

    def get_all_zones(self) -> List[FVGZone]:
        return list(self.zones.values())

    def update_zones(self, new_zones: List[FVGZone]):
        """Atualiza ou adiciona zonas em tempo de execução preservando o status das já existentes."""
        for z in new_zones:
            if z.id in self.zones:
                prev_status = self.zones[z.id].status
                self.zones[z.id] = z
                self.zones[z.id].status = prev_status
            else:
                self.zones[z.id] = z

    def get_active_zones(self) -> List[FVGZone]:
        return [
            z for z in self.zones.values()
            if z.status not in (ZoneStatus.EXHAUSTED, ZoneStatus.INVALIDATED, ZoneStatus.STANDBY_DEEP_PULLBACK)
        ]

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

            elif zone.status == ZoneStatus.COOLDOWN:
                # Calcula afastamento da zona (clearance)
                if current_price > zone.top:
                    clearance = current_price - zone.top
                elif current_price < zone.bottom:
                    clearance = zone.bottom - current_price
                else:
                    clearance = 0.0

                if clearance > zone.max_clearance_reached:
                    zone.max_clearance_reached = clearance

                # Condição de Rearme Inteligente: Tempo (>= cooldown_until) E Afastamento (>= min_clearance_required)
                time_ok = (zone.cooldown_until is None or timestamp >= zone.cooldown_until)
                clearance_ok = (zone.max_clearance_reached >= zone.min_clearance_required)

                if time_ok and clearance_ok:
                    # Rearma a zona para novo teste
                    if inside_zone:
                        zone.status = ZoneStatus.TESTING_CONTINUATION
                    else:
                        zone.status = ZoneStatus.UNMITIGATED

                    events.append({
                        "type": "ZONE_REARMED",
                        "zone_id": zone.id,
                        "price": current_price,
                        "status": zone.status,
                        "touch_count": zone.touch_count,
                        "max_touches": zone.max_touches,
                        "clearance_reached": zone.max_clearance_reached,
                        "timestamp": timestamp,
                        "message": (
                            f"🔄 ZONA REARMADA: {zone.id} cumpriu 10m de repouso e afastamento de "
                            f"{zone.max_clearance_reached:.0f} pts (Toque {zone.touch_count}/{zone.max_touches})."
                        )
                    })
                    zone.cooldown_until = None
                    zone.max_clearance_reached = 0.0
                    self.save_session()

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
                    self.save_session()

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
                    self.save_session()

        return events

    def save_session(self, path: Optional[str] = None) -> bool:
        """Persiste o estado das zonas em disco para tolerância a reinício."""
        target_path = path or self.session_storage_path
        if not target_path:
            return False
        try:
            os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
            payload = {
                "updated_at": datetime.now().isoformat(),
                "zones": {
                    z_id: {
                        "status": z.status.value,
                        "touch_count": getattr(z, "touch_count", 0),
                        "max_touches": getattr(z, "max_touches", 3),
                        "cooldown_until": z.cooldown_until.isoformat() if getattr(z, "cooldown_until", None) else None,
                        "max_clearance_reached": getattr(z, "max_clearance_reached", 0.0)
                    }
                    for z_id, z in self.zones.items()
                }
            }
            with open(target_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            return True
        except Exception as e:
            print(f"[STATE MACHINE WARN] Falha ao persistir sessão: {e}")
            return False

    def load_session(self, path: str) -> bool:
        """Restaura o estado das zonas a partir de sessão gravada."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Validação de data: se a sessão for de dia anterior, reseta para o novo pregão
            updated_at_str = data.get("updated_at")
            if updated_at_str:
                try:
                    updated_date = datetime.fromisoformat(updated_at_str).date()
                    if updated_date != datetime.now().date():
                        print(f"[STATE MACHINE] Sessão gravada é de {updated_date} (dia anterior). Resetando zonas limpas para o pregão de hoje ({datetime.now().date()}).")
                        return False
                except Exception:
                    pass

            zone_states = data.get("zones", {})
            restored = 0
            for z_id, st_val in zone_states.items():
                if z_id in self.zones:
                    if isinstance(st_val, dict):
                        self.zones[z_id].status = ZoneStatus(st_val.get("status", "UNMITIGATED"))
                        self.zones[z_id].touch_count = st_val.get("touch_count", 0)
                        self.zones[z_id].max_touches = st_val.get("max_touches", 3)
                        self.zones[z_id].max_clearance_reached = st_val.get("max_clearance_reached", 0.0)
                        if st_val.get("cooldown_until"):
                            try:
                                self.zones[z_id].cooldown_until = datetime.fromisoformat(st_val["cooldown_until"])
                            except Exception:
                                self.zones[z_id].cooldown_until = None
                    else:
                        self.zones[z_id].status = ZoneStatus(st_val)
                    restored += 1
            return True
        except Exception as e:
            print(f"[STATE MACHINE WARN] Falha ao carregar sessão anterior: {e}")
            return False
