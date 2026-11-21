"""
analyze_nov4_win_only.py
Filtra estritamente as operações do Mini Índice (WIN) no pregão de 04/11/2026.
"""

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
    # Garantir que é WIN (preço > 50.000 ou símbolo WIN)
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
        if p_val < 50000.0:  # Exclui cotações de dólar ou ações
            continue
            
        win_prices.append(p_val)
        
        if act_m and stp_m:
            act_str = "COMPRA" if "COMPRA" in act_m.group(1) else "VENDA"
            stp_name = stp_m.group(1).strip()
            fvg_str = fvg_m.group(1).strip() if fvg_m else ""
            
            # FVG ou Reversão SMC
            is_relevant = (
                ("fvg" in fvg_str.lower() and "nenhum" not in fvg_str.lower()) or
                "continuidade" in stp_name.lower() or
                "reteste" in stp_name.lower() or
                "sweep" in stp_name.lower() or
                "choch" in stp_name.lower()
            )
            
            tf_m = re.search(r'(\d+)m', fvg_str) or re.search(r'(\d+)m', stp_name)
            tf = f"{tf_m.group(1)}m" if tf_m else "5m"
            
            if is_relevant:
                win_trades.append({
                    "idx": len(win_prices) - 1,
                    "time": ts_m.group(1),
                    "dir": act_str,
                    "price": p_val,
                    "setup": stp_name,
                    "fvg": fvg_str,
                    "tf": tf
                })

print(f"Cotações WIN em 04/11: {len(win_prices)}")
print(f"Total de trades WIN brutos em 04/11: {len(win_trades)}")

# Filtrar operações espaçadas no tempo (pelo menos 1 min de intervalo ou 30 pts)
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

print(f"Operações distintas de FVG/Reversão no WIN em 04/11: {len(filtered_trades)}")

results = []
n_p = len(win_prices)

for t in filtered_trades:
    start_i = t["idx"]
    direction = t["dir"]
    ent = t["price"]
    stop_p = ent - 250.0 if direction == "COMPRA" else ent + 250.0
    tgt_200 = ent + 200.0 if direction == "COMPRA" else ent - 200.0
    tgt_300 = ent + 300.0 if direction == "COMPRA" else ent - 300.0
    
    # Próximas 600 cotações da mesma sessão de WIN
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

print(f"\n========================================================")
print(f"RESULTADO REAL DO MINI ÍNDICE (WIN) EM 04 DE NOVEMBRO DE 2026")
print(f"Total de Operações Únicas Avaliadas: {tot}")
print(f"Taxa de Acerto para Gain de 200 pts: {(g200/tot)*100:.1f}% ({g200}/{tot})")
print(f"Taxa de Acerto para Gain de 300 pts: {(g300/tot)*100:.1f}% ({g300}/{tot})")
print(f"========================================================\n")

print(f"{'#':<3} | {'Hora':<8} | {'TF':<4} | {'Direção':<6} | {'Entrada':<7} | {'Stop 250':<8} | {'MAE':<6} | {'MFE':<6} | {'Alvo 200':<12} | {'Alvo 300':<12} | Setup / FVG")
print("-" * 125)

# Filtrar para listar as operações espaçadas e evitar repetições
seen_levels = set()
display_list = []
for r in results:
    lvl = round(r['entry'] / 40.0) * 40
    k = (r['dir'], lvl, r['setup'][:25])
    if k not in seen_levels:
        seen_levels.add(k)
        display_list.append(r)

for idx, r in enumerate(display_list[:25]):
    ent_s = f"{int(r['entry']):,}".replace(',', '.')
    stp_s = f"{int(r['stop']):,}".replace(',', '.')
    desc = f"{r['setup'][:30]}"
    if r['fvg'] and "nenhum" not in r['fvg'].lower():
        desc += f" ({r['fvg'][:18]})"
    print(f"{idx+1:<3} | {r['time']:<8} | {r['tf']:<4} | {r['dir']:<6} | {ent_s:<7} | {stp_s:<8} | {r['mae']:>4.0f}pt | {r['mfe']:>4.0f}pt | {r['r200']:<12} | {r['r300']:<12} | {desc}")

print("-" * 125)
