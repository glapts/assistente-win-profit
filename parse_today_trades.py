import os

log_path = os.path.join(os.path.dirname(__file__), 'data', 'live_alerts_win.log')
if not os.path.exists(log_path):
    print("Log file not found")
    exit()

with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
    lines = f.readlines()

entries = []
cur = {}
for line in lines:
    line_clean = line.strip()
    if 'SETUP DISPARADO:' in line_clean:
        if cur and 'entrada' in cur:
            entries.append(cur)
        ts = line_clean.split(']')[0].replace('[', '')
        cur = {'timestamp': ts}
    elif 'ENTRADA:' in line_clean:
        cur['entrada'] = line_clean.split('ENTRADA:')[1].strip()
    elif 'SETUP:' in line_clean:
        cur['setup'] = line_clean.split('SETUP:')[1].strip()
    elif 'SUPERDOM:' in line_clean:
        cur['acao'] = line_clean.split('SUPERDOM:')[1].strip()
    elif 'STOP EM PRE' in line_clean:
        cur['stop'] = line_clean.split(':')[1].strip()
    elif 'ALVOS EM PRE' in line_clean:
        cur['alvo'] = line_clean.split(':')[1].strip()

if cur and 'entrada' in cur:
    entries.append(cur)

print(f"Total alerts logged: {len(entries)}")
unique_trades = []
last_key = None
for e in entries:
    k = (e.get('acao'), e.get('entrada'), e.get('setup'))
    if k != last_key:
        unique_trades.append(e)
        last_key = k

print("--- ENTRADAS REGISTRADAS HOJE ---")
for u in unique_trades:
    ts = u.get('timestamp')
    ac = u.get('acao')
    ent = u.get('entrada')
    stp = u.get('stop')
    alv = u.get('alvo')
    stp_name = u.get('setup')
    print(f"{ts} | {ac} | Entrada: {ent} | Stop: {stp} | Alvo: {alv} | {stp_name}")
