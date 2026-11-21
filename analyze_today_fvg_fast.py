"""
analyze_today_fvg_fast.py
Processamento limpo e rápido dos dados de hoje (05/11/2026).
"""

import re
import os

log_path = os.path.join(os.path.dirname(__file__), 'data', 'live_alerts_win.log')
with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
    raw_text = f.read()

# Remover todos os códigos ANSI primeiro
text = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', raw_text)

# Dividir por blocos
raw_blocks = text.split("SETUP DISPARADO:")
print(f"Blocos lidos: {len(raw_blocks)}")

events = []
prices_series = []

for b in raw_blocks[1:]:
    ts_m = re.search(r'DATA/HORA:\s*(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2})', b)
    ent_m = re.search(r'ENTRADA:\s*([\d\.,]+)', b)
    act_m = re.search(r'AÇÃO NO SUPERDOM:\s*(.*?)\n', b)
    stp_m = re.search(r'SETUP:\s*(.*?)\n', b)
    fvg_m = re.search(r'FVG:\s*(.*?)\n', b)
    
    if ts_m and ent_m:
        p_val = float(ent_m.group(1).replace('.', '').replace(',', '.'))
        ts_str = ts_m.group(1)
        prices_series.append(p_val)
        
        if act_m and stp_m:
            act_str = "COMPRA" if "COMPRA" in act_m.group(1) else "VENDA"
            stp_name = stp_m.group(1).strip()
            fvg_str = fvg_m.group(1).strip() if fvg_m else ""
            
            # Checar se envolve FVG
            is_fvg = (
                ("fvg" in fvg_str.lower() and "nenhum fvg ativo" not in fvg_str.lower()) or
                "continuidade" in stp_name.lower() or
                "reteste" in stp_name.lower() or
                "defesa institucional" in stp_name.lower()
            )
            
            if is_fvg:
                tf_m = re.search(r'(\d+)m', fvg_str) or re.search(r'(\d+)m', stp_name)
                tf = f"{tf_m.group(1)}m" if tf_m else "5m"
                events.append({
                    "idx": len(prices_series) - 1,
                    "time": ts_str.split()[1],
                    "dir": act_str,
                    "price": p_val,
                    "setup": stp_name,
                    "fvg": fvg_str,
                    "tf": tf
                })

print(f"Total de preços na série: {len(prices_series)}")
print(f"Total de eventos FVG brutos: {len(events)}")

# Filtrar para entradas únicas espaçadas (ao menos 20 segundos ou 25 pontos de diferença)
unique_trades = []
last_time = None
last_price = None

for e in events:
    t_str = e["time"]
    price = e["price"]
    
    # Manter um trade por minuto ou quando houver mudança de preço relevante
    t_min = t_str[:5] # HH:MM
    if (t_min != last_time) or (last_price is None or abs(price - last_price) >= 30.0):
        unique_trades.append(e)
        last_time = t_min
        last_price = price

print(f"Total de entradas únicas com FVG/Reversão no pregão de hoje: {len(unique_trades)}")

# Avaliar evolução subsequente na série de preços
results = []
n_prices = len(prices_series)

for t in unique_trades:
    start_i = t["idx"]
    direction = t["dir"]
    ent = t["price"]
    stop_p = ent - 250.0 if direction == "COMPRA" else ent + 250.0
    tgt_200 = ent + 200.0 if direction == "COMPRA" else ent - 200.0
    tgt_300 = ent + 300.0 if direction == "COMPRA" else ent - 300.0
    
    # Janela de até 800 cotações subsequentes
    window = prices_series[start_i:min(n_prices, start_i + 800)]
    
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
        "setup": t["setup"]
    })

g200 = sum(1 for r in results if "GAIN" in r["r200"])
g300 = sum(1 for r in results if "GAIN" in r["r300"])
tot = len(results)

print(f"\n========================================================")
print(f"RELATÓRIO DO PREGÃO DE HOJE (05/11/2026) - MINI ÍNDICE WIN")
print(f"Total de Operações Únicas de FVG/Reversão: {tot}")
print(f"Taxa de Acerto para Gain de 200 pts: {(g200/tot)*100:.1f}% ({g200}/{tot})")
print(f"Taxa de Acerto para Gain de 300 pts: {(g300/tot)*100:.1f}% ({g300}/{tot})")
print(f"========================================================\n")

print(f"{'#':<3} | {'Hora':<8} | {'TF':<4} | {'Direção':<6} | {'Entrada':<7} | {'Stop 250':<8} | {'MAE':<6} | {'MFE':<6} | {'Alvo 200':<12} | {'Alvo 300':<12} | Setup")
print("-" * 125)

for idx, r in enumerate(results[:30]):
    ent_s = f"{int(r['entry']):,}".replace(',', '.')
    stp_s = f"{int(r['stop']):,}".replace(',', '.')
    print(f"{idx+1:<3} | {r['time']:<8} | {r['tf']:<4} | {r['dir']:<6} | {ent_s:<7} | {stp_s:<8} | {r['mae']:>4.0f}pt | {r['mfe']:>4.0f}pt | {r['r200']:<12} | {r['r300']:<12} | {r['setup'][:38]}")

print("-" * 125)
