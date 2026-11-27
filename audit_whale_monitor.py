import sys
import os
import json
from datetime import datetime

print("==================================================================")
print("        AUDITORIA COMPLETA DE FUNCIONAMENTO: WHALE FLOW MONITOR   ")
print("==================================================================")

from whale_ny_monitor import (
    WhaleNYMonitor,
    TimesTradesParser,
    WhaleClusterAggregator,
    SMCZonesManager,
    NYCashOpenManager,
    CrossMarketState,
    WhaleDecisionEngine,
    VisualConsoleRenderer,
    classify_broker,
    classify_magnitude,
    sanitize_price,
    sanitize_quantity
)

# 1. Auditoria das Zonas SMC
zones_path = os.path.join("data", "niveis_60m.json")
with open(zones_path, "r", encoding="utf-8") as f:
    zdata = json.load(f)
zmgr = SMCZonesManager(zones_path)
print(f"[1/7] Zonas SMC Carregadas     : {len(zmgr.zones)} zonas | Ativo: {zdata.get('ativo')} | Topo: {zdata['dealing_range']['topo_estrutural']} | Fundo: {zdata['dealing_range']['fundo_estrutural']}")

# 2. Auditoria do Runtime State & Circuit Breaker
monitor = WhaleNYMonitor()
monitor.update_cross_market_from_runtime()
print(f"[2/7] Sincronização Runtime    : Stops: {monitor.daily_stops_count}/{monitor.max_daily_stops} | CB Lockout: {monitor.circuit_breaker_active} | Trading Enabled: {monitor.trading_enabled}")

# 3. Auditoria do Regime de Horário (09:35)
now = datetime.now()
regime_id, regime_desc, is_blocked = NYCashOpenManager.get_regime(now)
print(f"[3/7] Regime Horário ({now.strftime('%H:%M:%S')}) : Regime: {regime_id} | Desc: {regime_desc} | Bloqueado: {is_blocked}")

# 4. Auditoria do Parser de Times & Trades
raw_line = "09:35:10.500\tMorgan\t166.450*\t500\tBTG\tComprador"
rec = TimesTradesParser.parse_line(raw_line)
assert rec is not None, "Falha no parser do T&T"
assert rec.broker == "Morgan", "Falha no broker"
assert rec.quantity == 500, "Falha na quantidade"
assert rec.price == 166450.0, "Falha no preço"
print(f"[4/7] Parser Times & Trades    : OK -> {rec.broker} agrediu {rec.quantity} cts @ {rec.price}")

# 5. Auditoria do Agregador de Clusters (3s)
agg = WhaleClusterAggregator(window_seconds=3.0)
c1 = agg.add_trade(rec)
assert c1 is not None, "Falha: cluster deveria ser confirmado com 500 cts"
print(f"[5/7] Agregação de Clusters    : OK -> Cluster total {c1.total_quantity} cts em {c1.trades_count} fatiamentos [{c1.magnitude}]")

# 6. Auditoria do Motor de Decisão e Destravamento 09h-10h
# ZONA_05_MAXIMA_NY_166480 está em 166480 (Supply/Venda). Preço 166450 está a 30 pts de distância!
alert = monitor.decision_engine.evaluate_cluster(
    cluster=c1,
    current_price=166450.0,
    cross_market=monitor.cross_market,
    current_time=now
)
assert alert is not None, "Falha: alerta deveria ser gerado"
print(f"[6/7] Motor de Decisão         : OK -> Alerta Gerado: {alert.direction} @ {alert.entry_price} (Score: {alert.score})")

# 7. Auditoria de Ingestão e Saída de Alerta Completo
print("[7/7] Teste de Ingestão de Payload e Emissão de Sinal:")
sample_payload = """
09:35:10.500\tMorgan\t166.450*\t500\tBTG\tComprador
09:35:11.200\tMorgan\t166.450*\t350\tXP\tComprador
"""
out_alerts = monitor.process_text_payload(sample_payload, check_staleness=False)
print(f"Total de Alertas Executáveis Emitidos: {len(out_alerts)}")
assert len(out_alerts) > 0, "Alerta foi indevidamente bloqueado!"
print("==================================================================")
print("     RESULTADO DA AUDITORIA: 100% OPERACIONAL, DESTRAVADO E ÍNTEGRO!")
print("==================================================================")
