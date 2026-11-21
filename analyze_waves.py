import re
from datetime import datetime

with open('data/live_alerts_win.log', 'r', encoding='utf-8', errors='ignore') as f:
    text = f.read()

# Let's find distinct trade episodes (clustered by time within 3 minutes)
import parse_today_trades
entries = parse_today_trades.entries

# Filter only today 05/11/2026 after 09:00 (regular market hours)
market_entries = []
for e in entries:
    ts_str = e.get('timestamp', '')
    if '05/11/2026' in ts_str:
        time_part = ts_str.split(' ')[1]
        hour = int(time_part.split(':')[0])
        if hour >= 9:
            market_entries.append(e)

print(f"Total entries during market hours: {len(market_entries)}")

# Cluster trades by wave (gap > 60 seconds)
waves = []
curr_wave = []
last_dt = None

for e in market_entries:
    dt = datetime.strptime(e['timestamp'], "%d/%m/%Y %H:%M:%S")
    if last_dt is None or (dt - last_dt).total_seconds() > 90:
        if curr_wave:
            waves.append(curr_wave)
        curr_wave = [e]
    else:
        curr_wave.append(e)
    last_dt = dt

if curr_wave:
    waves.append(curr_wave)

print(f"Total trade waves: {len(waves)}")
for idx, w in enumerate(waves, 1):
    first = w[0]
    last = w[-1]
    ac = first.get('acao')
    ent = first.get('entrada')
    stp = first.get('stop')
    alv = first.get('alvo')
    setup_name = first.get('setup')
    print(f"ONDA {idx}: {first['timestamp']} até {last['timestamp']} | {ac} | Entrada Ref: {ent} | {setup_name} | Alvo: {alv} | Stop: {stp}")
