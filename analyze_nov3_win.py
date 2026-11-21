import re
import os

path = os.path.join(os.path.dirname(__file__), 'data', 'live_alerts.log')
start_byte = max(0, 21400000)
end_byte = 34750000

print(f"Lendo bytes {start_byte} até {end_byte}...")
with open(path, 'r', encoding='utf-8', errors='ignore') as f:
    f.seek(start_byte)
    raw = f.read(end_byte - start_byte)

clean = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', raw)
raw_blocks = clean.split("SETUP DISPARADO:")

win_prices = []
all_events = []

for b in raw_blocks:
    # Apenas 03/11/2026
    ts_m = re.search(r'DATA/HORA:\s*03/11/2026\s+(\d{2}:\d{2}:\d{2})', b)
    if not ts_m:
        continue
        
    src_m = re.search(r'FONTE:\s*(.*?)\n', b)
    src = src_m.group(1) if src_m else ""
    if "Test Simulator" in src or "Replay" in src:
        continue

    sym_m = re.search(r'ATIVO/VENCIMENTO:\s*(.*?)\n', b)
    sym = sym_m.group(1) if sym_m else ""
    if "WDO" in sym or "VALE" in sym:
        continue
        
    ent_m = re.search(r'ENTRADA:\s*([\d\.,]+)', b)
    act_m = re.search(r'AÇÃO NO SUPERDOM:\s*(.*?)\n', b)
    stp_m = re.search(r'SETUP:\s*(.*?)\n', b)
    fvg_m = re.search(r'FVG:\s*(.*?)\n', b)
    
    if ent_m:
        p_val = float(ent_m.group(1).replace('.', '').replace(',', '.'))
        if p_val < 50000.0:
            continue
        win_prices.append(p_val)
        
        if act_m and stp_m:
            act_str = "COMPRA" if "COMPRA" in act_m.group(1) else "VENDA"
            stp_name = stp_m.group(1).strip()
            fvg_str = fvg_m.group(1).strip() if fvg_m else ""
            
            tf_m = re.search(r'(\d+)m', fvg_str) or re.search(r'(\d+)m', stp_name)
            tf = f"{tf_m.group(1)}m" if tf_m else "5m"
            
            all_events.append({
                "idx": len(win_prices) - 1,
                "time": ts_m.group(1),
                "dir": act_str,
                "price": p_val,
                "setup": stp_name,
                "fvg": fvg_str,
                "tf": tf
            })

print(f"Cotações WIN em 03/11: {len(win_prices)}")
print(f"Total de alertas brutos WIN em 03/11: {len(all_events)}")

# Filtrar para entradas distintas (mínimo de 3 minutos ou mudança significativa de preço/fvg)
def to_mins(t_str):
    h, m, s = map(int, t_str.split(':'))
    return h * 60 + m

distinct_trades = []
last_time_min = -10
last_dir = None
last_fvg = None

for ev in all_events:
    t_min = to_mins(ev["time"])
    fvg_key = ev["fvg"] if ev["fvg"] else ev["setup"]
    if (t_min - last_time_min >= 3) or (ev["dir"] != last_dir) or (fvg_key != last_fvg and abs(ev["price"] - (distinct_trades[-1]["price"] if distinct_trades else 0)) > 50):
        distinct_trades.append(ev)
        last_time_min = t_min
        last_dir = ev["dir"]
        last_fvg = fvg_key

n_p = len(win_prices)
evaluated = []

for t in distinct_trades:
    start_i = t["idx"]
    direction = t["dir"]
    ent = t["price"]
    stop_p = ent - 250.0 if direction == "COMPRA" else ent + 250.0
    tgt_200 = ent + 200.0 if direction == "COMPRA" else ent - 200.0
    tgt_300 = ent + 300.0 if direction == "COMPRA" else ent - 300.0
    
    # Próximas 500 cotações da mesma sessão
    window = win_prices[start_i:min(n_p, start_i + 500)]
    
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
        else:
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
    
    is_fvg = ("fvg" in t["fvg"].lower() and "nenhum" not in t["fvg"].lower()) or ("fvg" in t["setup"].lower()) or ("reteste de 50%" in t["setup"].lower())
    
    evaluated.append({
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
        "fvg": t["fvg"],
        "is_fvg": is_fvg
    })

fvg_only = [e for e in evaluated if e["is_fvg"]]
tot_fvg = len(fvg_only)
g200_fvg = sum(1 for e in fvg_only if "GAIN" in e["r200"])
g300_fvg = sum(1 for e in fvg_only if "GAIN" in e["r300"])

tot_all = len(evaluated)
g200_all = sum(1 for e in evaluated if "GAIN" in e["r200"])
g300_all = sum(1 for e in evaluated if "GAIN" in e["r300"])

print(f"\n========================================================")
print(f"RESULTADO REAL DO MINI ÍNDICE (WIN) EM 03 DE NOVEMBRO DE 2026")
print(f"Total de Operações SMC Distintas: {tot_all}")
print(f"  Gain 200 pts: {(g200_all/tot_all)*100:.1f}% ({g200_all}/{tot_all})")
print(f"  Gain 300 pts: {(g300_all/tot_all)*100:.1f}% ({g300_all}/{tot_all})")
print(f"Operações com FVG Relevante Distintas: {tot_fvg}")
print(f"  Gain 200 pts: {(g200_fvg/tot_fvg)*100:.1f}% ({g200_fvg}/{tot_fvg})")
print(f"  Gain 300 pts: {(g300_fvg/tot_fvg)*100:.1f}% ({g300_fvg}/{tot_fvg})")
print(f"========================================================\n")

print(f"{'#':<3} | {'Hora':<8} | {'TF':<4} | {'Direção':<6} | {'Entrada':<7} | {'Stop 250':<8} | {'MAE':<6} | {'MFE':<6} | {'Alvo 200':<12} | {'Alvo 300':<12} | Setup / FVG")
print("-" * 130)

for idx, r in enumerate(fvg_only):
    ent_s = f"{int(r['entry']):,}".replace(',', '.')
    stp_s = f"{int(r['stop']):,}".replace(',', '.')
    desc = f"{r['setup'][:32]}"
    if r['fvg'] and "nenhum" not in r['fvg'].lower():
        desc += f" ({r['fvg'][:22]})"
    print(f"{idx+1:<3} | {r['time']:<8} | {r['tf']:<4} | {r['dir']:<6} | {ent_s:<7} | {stp_s:<8} | {r['mae']:>4.0f}pt | {r['mfe']:>4.0f}pt | {r['r200']:<12} | {r['r300']:<12} | {desc}")

print("-" * 130)
