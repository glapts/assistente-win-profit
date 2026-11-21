"""
analyze_today_fvg_real.py
Extrai todas as entradas disparadas hoje (05/11/2026) baseadas em FVG
(Setup 1: Compra em FVG, Setup 2: Venda em FVG, Setup 9: Reteste 50% CE, Setup 10: Defesa Institucional)
e calcula se o mercado respeitou o stop de 250 pontos e atingiu +200 pontos e +300 pontos de gain.
"""

import re
import os

log_path = os.path.join(os.path.dirname(__file__), 'data', 'live_alerts_win.log')
with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
    text = f.read()

# 1. Extrair histórico sequencial de preços e timestamps
price_events = []
for m in re.finditer(r'\[(\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2})\].*?ENTRADA:\s*([\d\.,]+)', text, re.DOTALL):
    ts = m.group(1)
    p = float(m.group(2).replace('.', '').replace(',', '.'))
    price_events.append((ts, p))

# 2. Extrair blocos de alerta únicos
blocks = text.split("SETUP DISPARADO:")

fvg_trades = []
last_key = None

for block in blocks[1:]:
    fvg_m = re.search(r'FVG:\s*(.*?)\n', block)
    setup_m = re.search(r'SETUP:\s*(.*?)\n', block)
    action_m = re.search(r'AÇÃO NO SUPERDOM:\s*(.*?)\n', block)
    entry_m = re.search(r'ENTRADA:\s*([\d\.,]+)', block)
    ts_m = re.search(r'DATA/HORA:\s*(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2})', block)
    
    if not (fvg_m and entry_m and action_m and ts_m):
        continue
        
    fvg_raw = re.sub(r'\x1b\[[0-9;]*m', '', fvg_m.group(1)).strip()
    setup_raw = re.sub(r'\x1b\[[0-9;]*m', '', setup_m.group(1)).strip() if setup_m else ""
    action_raw = "COMPRA" if "COMPRA" in action_m.group(1) else "VENDA"
    ts = ts_m.group(1)
    
    # Identificar se o FVG é ativo ou se o setup é baseado em FVG
    is_fvg_setup = (
        "fvg" in fvg_raw.lower() or
        "fvg" in setup_raw.lower() or
        "reteste de 50%" in setup_raw.lower() or
        "continuidade" in setup_raw.lower() or
        "defesa institucional" in setup_raw.lower()
    )
    
    if not is_fvg_setup or "nenhum fvg ativo" in fvg_raw.lower():
        continue
        
    entry_val = float(entry_m.group(1).replace('.', '').replace(',', '.'))
    
    # Identificar timeframe do FVG
    tf_m = re.search(r'(\d+)m', fvg_raw) or re.search(r'(\d+)m', setup_raw)
    tf_str = f"{tf_m.group(1)}m" if tf_m else "5m"
    
    key = (action_raw, entry_val, setup_raw)
    if key != last_key:
        fvg_trades.append({
            "timestamp": ts,
            "action": action_raw,
            "entry": entry_val,
            "setup": setup_raw,
            "fvg": fvg_raw,
            "timeframe": tf_str
        })
        last_key = key

print(f"Total de operações baseadas em FVG/Estrutura únicas identificadas hoje: {len(fvg_trades)}")

# 3. Para cada operação, rastrear nos preços posteriores da sessão
results = []
all_prices_only = [p for _, p in price_events]

for idx, t in enumerate(fvg_trades):
    ent = t["entry"]
    direction = t["action"]
    stop_p = ent - 250.0 if direction == "COMPRA" else ent + 250.0
    tgt_200 = ent + 200.0 if direction == "COMPRA" else ent - 200.0
    tgt_300 = ent + 300.0 if direction == "COMPRA" else ent - 300.0
    
    # Encontrar ponto de entrada na série de preços
    # Procurar primeiro preço próximo após o timestamp
    start_idx = 0
    for i, (ts_p, p_val) in enumerate(price_events):
        if ts_p >= t["timestamp"] and abs(p_val - ent) <= 5.0:
            start_idx = i
            break
            
    future_series = all_prices_only[start_idx:start_idx + 2500]
    
    mae = 0.0
    mfe = 0.0
    hit_200 = False
    hit_300 = False
    hit_stop = False
    
    for p in future_series:
        if direction == "COMPRA":
            fav = p - ent
            adv = ent - p
            if fav > mfe: mfe = fav
            if adv > mae: mae = adv
            if p >= tgt_200: hit_200 = True
            if p >= tgt_300: hit_300 = True
            if p <= stop_p:
                hit_stop = True
                break
        else: # VENDA
            fav = ent - p
            adv = p - ent
            if fav > mfe: mfe = fav
            if adv > mae: mae = adv
            if p <= tgt_200: hit_200 = True
            if p <= tgt_300: hit_300 = True
            if p >= stop_p:
                hit_stop = True
                break
                
    res_200 = "GAIN (+200)" if hit_200 and not (hit_stop and mfe < 200.0) else "STOP (-250)"
    res_300 = "GAIN (+300)" if hit_300 and not (hit_stop and mfe < 300.0) else "STOP (-250)"
    
    results.append({
        "id": idx + 1,
        "time": t["timestamp"].split()[1] if " " in t["timestamp"] else t["timestamp"],
        "tf": t["timeframe"],
        "dir": direction,
        "entry": ent,
        "stop": stop_p,
        "mae": mae,
        "mfe": mfe,
        "r200": res_200,
        "r300": res_300,
        "setup": t["setup"],
        "fvg": t["fvg"]
    })

print(f"Total de trades analisados com desfecho: {len(results)}")
g200_count = sum(1 for r in results if "GAIN" in r["r200"])
g300_count = sum(1 for r in results if "GAIN" in r["r300"])
tot = len(results)

print(f"Taxa de Acerto para Gain de 200 pts: {(g200_count/tot)*100:.1f}% ({g200_count}/{tot})")
print(f"Taxa de Acerto para Gain de 300 pts: {(g300_count/tot)*100:.1f}% ({g300_count}/{tot})")

print("\n" + "=" * 125)
print(f"{'#':<3} | {'Hora':<8} | {'TF':<4} | {'Direção':<6} | {'Entrada':<7} | {'Stop 250':<7} | {'MAE':<6} | {'MFE':<6} | {'Alvo 200':<12} | {'Alvo 300':<12} | FVG / Setup")
print("=" * 125)
for r in results[:20]:
    ent_s = f"{int(r['entry']):,}".replace(',', '.')
    stp_s = f"{int(r['stop']):,}".replace(',', '.')
    desc = f"{r['setup'][:28]} ({r['fvg'][:20]})"
    print(f"{r['id']:<3} | {r['time']:<8} | {r['tf']:<4} | {r['dir']:<6} | {ent_s:<7} | {stp_s:<7} | {r['mae']:>4.0f}pt | {r['mfe']:>4.0f}pt | {r['r200']:<12} | {r['r300']:<12} | {desc}")
print("=" * 125)
