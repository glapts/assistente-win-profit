import re
import os

path = os.path.join(os.path.dirname(__file__), 'data', 'live_alerts.log')
start_byte = 34652000
end_byte = 71320000

with open(path, 'r', encoding='utf-8', errors='ignore') as f:
    f.seek(start_byte)
    raw = f.read(end_byte - start_byte)

clean = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', raw)
raw_blocks = clean.split("SETUP DISPARADO:")

win_trades = []
win_prices = []

for b in raw_blocks:
    sym_m = re.search(r'ATIVO/VENCIMENTO:\s*(.*?)\n', b)
    sym = sym_m.group(1) if sym_m else ""
    if "WDO" in sym or "VALE" in sym:
        continue
        
    ts_m = re.search(r'DATA/HORA:\s*04/11/2026\s+(\d{2}:\d{2}:\d{2})', b)
    ent_m = re.search(r'ENTRADA:\s*([\d\.,]+)', b)
    act_m = re.search(r'AÇÃO NO SUPERDOM:\s*(.*?)\n', b)
    stp_m = re.search(r'SETUP:\s*(.*?)\n', b)
    fvg_m = re.search(r'FVG:\s*(.*?)\n', b)
    
    if ts_m and ent_m:
        p_val = float(ent_m.group(1).replace('.', '').replace(',', '.'))
        if p_val < 50000.0:
            continue
            
        win_prices.append(p_val)
        
        if act_m and stp_m:
            act_str = "COMPRA" if "COMPRA" in act_m.group(1) else "VENDA"
            stp_name = stp_m.group(1).strip()
            fvg_str = fvg_m.group(1).strip() if fvg_m else ""
            
            # Apenas operações que envolvam FVG explicitamente
            has_fvg = ("fvg" in fvg_str.lower() and "nenhum" not in fvg_str.lower()) or ("fvg" in stp_name.lower()) or ("reteste de 50%" in stp_name.lower())
            
            tf_m = re.search(r'(\d+)m', fvg_str) or re.search(r'(\d+)m', stp_name)
            tf = f"{tf_m.group(1)}m" if tf_m else "5m"
            
            if has_fvg:
                win_trades.append({
                    "idx": len(win_prices) - 1,
                    "time": ts_m.group(1),
                    "dir": act_str,
                    "price": p_val,
                    "setup": stp_name,
                    "fvg": fvg_str,
                    "tf": tf
                })

# Filtrar operações com intervalo de tempo/preço
filtered_trades = []
last_t = None
last_p = None

for t in win_trades:
    t_min = t["time"][:5]
    p = t["price"]
    if (t_min != last_t) or (last_p is None or abs(p - last_p) >= 30.0):
        filtered_trades.append(t)
        last_t = t_min
        last_p = p

results = []
n_p = len(win_prices)

for t in filtered_trades:
    start_i = t["idx"]
    direction = t["dir"]
    ent = t["price"]
    stop_p = ent - 250.0 if direction == "COMPRA" else ent + 250.0
    tgt_200 = ent + 200.0 if direction == "COMPRA" else ent - 200.0
    tgt_300 = ent + 300.0 if direction == "COMPRA" else ent - 300.0
    
    window = win_prices[start_i:min(n_p, start_i + 600)]
    
    hit_200 = False
    hit_300 = False
    hit_stop = False
    mae = 0.0
    mfe = 0.0
    
    for p in window:
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
                
    r200 = "GAIN (+200)" if hit_200 and not (hit_stop and mfe < 200.0) else "STOP (-250)"
    r300 = "GAIN (+300)" if hit_300 and not (hit_stop and mfe < 300.0) else "STOP (-250)"
    
    results.append({
        "time": t["time"],
        "tf": t["tf"],
        "dir": t["dir"],
        "entry": ent,
        "stop": stop_p,
        "mae": mae,
        "mfe": mfe,
        "r200": r200,
        "r300": r300,
        "setup": t["setup"],
        "fvg": t["fvg"]
    })

g200 = sum(1 for r in results if "GAIN" in r["r200"])
g300 = sum(1 for r in results if "GAIN" in r["r300"])
tot = len(results)

print(f"Total FVG puro: {tot}")
if tot > 0:
    print(f"Gain 200: {(g200/tot)*100:.1f}% ({g200}/{tot})")
    print(f"Gain 300: {(g300/tot)*100:.1f}% ({g300}/{tot})")

print(f"\nLista de Operações com FVG Identificado:")
seen_levels = set()
for idx, r in enumerate(results):
    lvl = round(r['entry'] / 30.0) * 30
    k = (r['dir'], lvl, r['time'][:5])
    if k not in seen_levels:
        seen_levels.add(k)
        ent_s = f"{int(r['entry']):,}".replace(',', '.')
        stp_s = f"{int(r['stop']):,}".replace(',', '.')
        print(f"{r['time']} | {r['tf']} | {r['dir']} | Ent: {ent_s} | Stop: {stp_s} | MAE: {r['mae']:.0f}pt | MFE: {r['mfe']:.0f}pt | 200: {r['r200']} | 300: {r['r300']} | {r['setup']} | FVG: {r['fvg']}")
