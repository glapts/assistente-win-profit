"""
analyze_today_fvg.py
Analisa todos os setups disparados hoje (05/11/2026) que envolveram Fair Value Gaps (FVGs),
mapeando preço de entrada, stop de 250 pontos, alvos de reversão (200 pts e 300 pts)
e se atingiram o gain ou respeitaram o stop.
"""

import re
import os

log_path = os.path.join(os.path.dirname(__file__), 'data', 'live_alerts_win.log')
if not os.path.exists(log_path):
    print("Log não encontrado")
    exit(1)

with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
    text = f.read()

# Dividir por blocos de SETUP DISPARADO
blocks = text.split("SETUP DISPARADO:")
print(f"Total de blocos de alerta registrados hoje: {len(blocks)}")

fvg_trades = []
last_key = None

for block in blocks[1:]:
    lines = [l.strip() for l in block.splitlines() if l.strip()]
    
    ts_match = re.search(r'DATA/HORA:\s*(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2})', block)
    action_match = re.search(r'AÇÃO NO SUPERDOM:\s*(.*)', block)
    entry_match = re.search(r'ENTRADA:\s*([\d\.,]+)', block)
    stop_match = re.search(r'STOP EM PREÇO E PONTOS:\s*([\d\.,]+)', block)
    target_match = re.search(r'ALVOS EM PREÇO E PONTOS:\s*([\d\.,]+)', block)
    setup_match = re.search(r'SETUP:\s*(.*)', block)
    fvg_match = re.search(r'FVG:\s*(.*)', block)
    
    if entry_match and fvg_match and action_match:
        fvg_text = fvg_match.group(1).strip()
        # Verificar se envolve FVG de fato
        if "fvg" in fvg_text.lower() or "fvg" in (setup_match.group(1) if setup_match else "").lower():
            ts = ts_match.group(1) if ts_match else "05/11/2026"
            action = "COMPRA" if "COMPRA" in action_match.group(1) else "VENDA"
            
            ent_str = entry_match.group(1).replace('.', '').replace(',', '.')
            stp_str = stop_match.group(1).replace('.', '').replace(',', '.') if stop_match else "0"
            tgt_str = target_match.group(1).replace('.', '').replace(',', '.') if target_match else "0"
            
            try:
                entry_val = float(ent_str)
                stop_val = float(stp_str)
                target_val = float(tgt_str)
            except ValueError:
                continue
                
            setup_name = setup_match.group(1).strip() if setup_match else "Setup FVG"
            
            # Limpar caracteres de escape ANSI de setup_name e fvg_text
            setup_name = re.sub(r'\x1b\[[0-9;]*m', '', setup_name)
            fvg_text = re.sub(r'\x1b\[[0-9;]*m', '', fvg_text)
            
            key = (action, entry_val, setup_name)
            if key != last_key:
                fvg_trades.append({
                    "timestamp": ts,
                    "action": action,
                    "entry": entry_val,
                    "stop": stop_val,
                    "target": target_val,
                    "setup": setup_name,
                    "fvg": fvg_text
                })
                last_key = key

print(f"Total de operações com FVG identificadas no pregão de hoje: {len(fvg_trades)}")

# Extrair sequência de preços do dia para avaliar o desfecho exato de cada entrada
price_pattern = re.compile(r'Preço atual:\s*([\d\.]+)')
all_prices_str = price_pattern.findall(text)
all_prices = []
for p in all_prices_str:
    try:
        all_prices.append(float(p.replace('.', '')))
    except ValueError:
        pass

print(f"Total de cotações rastreadas no dia: {len(all_prices)}")

# Para cada trade único de FVG, verificar evolução subseqüente no pregão
print("\n" + "=" * 110)
print(f"{'#':<3} | {'Hora':<8} | {'Direção':<6} | {'Entrada':<7} | {'Stop 250':<8} | {'Alvo 200':<8} | {'Alvo 300':<8} | {'Desfecho 200':<12} | {'Desfecho 300':<12} | Setup")
print("=" * 110)

analyzed_trades = []
for idx, trade in enumerate(fvg_trades):
    # Encontrar índice de preço correspondente
    ent = trade["entry"]
    direction = trade["action"]
    stop_p = ent - 250.0 if direction == "COMPRA" else ent + 250.0
    t200 = ent + 200.0 if direction == "COMPRA" else ent - 200.0
    t300 = ent + 300.0 if direction == "COMPRA" else ent - 300.0
    
    # Avaliar próximos preços a partir de quando ocorreu o alerta
    # Busca a primeira ocorrência do preço de entrada na série
    start_search = 0
    for i, p in enumerate(all_prices):
        if abs(p - ent) < 1.0:
            start_search = i
            break
            
    future_prices = all_prices[start_search:start_search + 1500] if start_search < len(all_prices) else []
    
    hit_200 = False
    hit_300 = False
    hit_stop = False
    max_fav = 0.0
    max_adv = 0.0
    
    for p in future_prices:
        if direction == "COMPRA":
            fav = p - ent
            adv = ent - p
            if fav > max_fav: max_fav = fav
            if adv > max_adv: max_adv = adv
            
            if p >= t200: hit_200 = True
            if p >= t300: hit_300 = True
            if p <= stop_p:
                hit_stop = True
                break
        else: # VENDA
            fav = ent - p
            adv = p - ent
            if fav > max_fav: max_fav = fav
            if adv > max_adv: max_adv = adv
            
            if p <= t200: hit_200 = True
            if p <= t300: hit_300 = True
            if p >= stop_p:
                hit_stop = True
                break
                
    res_200 = "GAIN (+200)" if hit_200 and not (hit_stop and max_fav < 200) else "STOP (-250)"
    res_300 = "GAIN (+300)" if hit_300 and not (hit_stop and max_fav < 300) else "STOP (-250)"
    
    analyzed_trades.append({
        "id": idx + 1,
        "time": trade["timestamp"].split()[1] if " " in trade["timestamp"] else trade["timestamp"],
        "direction": direction,
        "entry": ent,
        "stop": stop_p,
        "t200": t200,
        "t300": t300,
        "mae": max_adv,
        "mfe": max_fav,
        "res_200": res_200,
        "res_300": res_300,
        "setup": trade["setup"]
    })

for t in analyzed_trades[:25]:
    ent_s = f"{int(t['entry']):,}".replace(',', '.')
    stp_s = f"{int(t['stop']):,}".replace(',', '.')
    t2_s = f"{int(t['t200']):,}".replace(',', '.')
    t3_s = f"{int(t['t300']):,}".replace(',', '.')
    setup_short = t['setup'][:30]
    print(f"{t['id']:<3} | {t['time']:<8} | {t['direction']:<6} | {ent_s:<7} | {stp_s:<8} | {t2_s:<8} | {t3_s:<8} | {t['res_200']:<12} | {t['res_300']:<12} | {setup_short}")

print("=" * 110)

if analyzed_trades:
    g2 = sum(1 for t in analyzed_trades if "GAIN" in t["res_200"])
    g3 = sum(1 for t in analyzed_trades if "GAIN" in t["res_300"])
    tot = len(analyzed_trades)
    print(f"\nDESEMPENHO CONSOLIDADO DAS OPERAÇÕES COM FVG DE HOJE:")
    print(f"Total de Eventos Únicos com FVG: {tot}")
    print(f"Taxa de Acerto para Gain de 200 pts: {(g2/tot)*100:.1f}% ({g2}/{tot})")
    print(f"Taxa de Acerto para Gain de 300 pts: {(g3/tot)*100:.1f}% ({g3}/{tot})")
