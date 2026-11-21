"""
analyze_nov4_session.py
Analisa a sessão real de 04 de Novembro de 2026 registrada no log oficial do algoritmo.
"""

import re
import os

path = os.path.join(os.path.dirname(__file__), 'data', 'live_alerts.log')
start_byte = 34652000
end_byte = 71320000

with open(path, 'r', encoding='utf-8', errors='ignore') as f:
    f.seek(start_byte)
    raw = f.read(end_byte - start_byte)

# Limpar ANSI
clean = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', raw)

blocks = clean.split("SETUP DISPARADO:")
print(f"Total de blocos de alerta registrados em 04/11/2026: {len(blocks)}")

# Coletar histórico sequencial de preços da sessão de 04/11
price_series = []
events = []

for b in blocks:
    ts_m = re.search(r'DATA/HORA:\s*04/11/2026\s+(\d{2}:\d{2}:\d{2})', b)
    ent_m = re.search(r'ENTRADA:\s*([\d\.,]+)', b)
    act_m = re.search(r'AÇÃO NO SUPERDOM:\s*(.*?)\n', b)
    stp_m = re.search(r'SETUP:\s*(.*?)\n', b)
    fvg_m = re.search(r'FVG:\s*(.*?)\n', b)
    
    if ts_m and ent_m:
        t_str = ts_m.group(1)
        p_val = float(ent_m.group(1).replace('.', '').replace(',', '.'))
        price_series.append(p_val)
        
        if act_m and stp_m:
            act_str = "COMPRA" if "COMPRA" in act_m.group(1) else "VENDA"
            stp_name = stp_m.group(1).strip()
            fvg_str = fvg_m.group(1).strip() if fvg_m else ""
            
            is_fvg = (
                ("fvg" in fvg_str.lower() and "nenhum fvg ativo" not in fvg_str.lower()) or
                "continuidade" in stp_name.lower() or
                "reteste" in stp_name.lower() or
                "sweep" in stp_name.lower() or
                "choch" in stp_name.lower()
            )
            
            tf_m = re.search(r'(\d+)m', fvg_str) or re.search(r'(\d+)m', stp_name)
            tf = f"{tf_m.group(1)}m" if tf_m else "5m"
            
            if is_fvg:
                events.append({
                    "idx": len(price_series) - 1,
                    "time": t_str,
                    "dir": act_str,
                    "price": p_val,
                    "setup": stp_name,
                    "fvg": fvg_str,
                    "tf": tf
                })

print(f"Total de cotações em 04/11: {len(price_series)}")
print(f"Total de eventos de setup/FVG em 04/11: {len(events)}")

# Filtrar para operações únicas distintas (espaçadas por tempo e nível de preço)
unique_trades = []
last_time_min = None
last_price = None

for e in events:
    t_min = e["time"][:5] # HH:MM
    price = e["price"]
    
    if (t_min != last_time_min) or (last_price is None or abs(price - last_price) >= 30.0):
        unique_trades.append(e)
        last_time_min = t_min
        last_price = price

print(f"Total de operações únicas em 04/11/2026: {len(unique_trades)}")

# Avaliar evolução dos preços (Stop 250, Alvo 200, Alvo 300)
results = []
n_prices = len(price_series)

for t in unique_trades:
    start_i = t["idx"]
    direction = t["dir"]
    ent = t["price"]
    stop_p = ent - 250.0 if direction == "COMPRA" else ent + 250.0
    tgt_200 = ent + 200.0 if direction == "COMPRA" else ent - 200.0
    tgt_300 = ent + 300.0 if direction == "COMPRA" else ent - 300.0
    
    window = price_series[start_i:min(n_prices, start_i + 800)]
    
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
print(f"RELATÓRIO DO PREGÃO DE 04/11/2026 - MINI ÍNDICE (WIN)")
print(f"Total de Operações Únicas Avaliadas: {tot}")
print(f"Taxa de Acerto para Gain de 200 pts: {(g200/tot)*100:.1f}% ({g200}/{tot})")
print(f"Taxa de Acerto para Gain de 300 pts: {(g300/tot)*100:.1f}% ({g300}/{tot})")
print(f"========================================================\n")

print(f"{'#':<3} | {'Hora':<8} | {'TF':<4} | {'Direção':<6} | {'Entrada':<7} | {'Stop 250':<8} | {'MAE':<6} | {'MFE':<6} | {'Alvo 200':<12} | {'Alvo 300':<12} | Setup / FVG")
print("-" * 125)

# Filtrar para exibir operações distintas bem espaçadas
seen_lvls = set()
display_list = []
for r in results:
    lvl = round(r['entry'] / 50.0) * 50
    k = (r['dir'], lvl, r['setup'][:25])
    if k not in seen_lvls:
        seen_lvls.add(k)
        display_list.append(r)

for idx, r in enumerate(display_list[:25]):
    ent_s = f"{int(r['entry']):,}".replace(',', '.')
    stp_s = f"{int(r['stop']):,}".replace(',', '.')
    desc = f"{r['setup'][:30]}"
    if r['fvg'] and "nenhum" not in r['fvg'].lower():
        desc += f" ({r['fvg'][:18]})"
    print(f"{idx+1:<3} | {r['time']:<8} | {r['tf']:<4} | {r['dir']:<6} | {ent_s:<7} | {stp_s:<8} | {r['mae']:>4.0f}pt | {r['mfe']:>4.0f}pt | {r['r200']:<12} | {r['r300']:<12} | {desc}")

print("-" * 125)
