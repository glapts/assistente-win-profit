import openpyxl
from datetime import datetime

wb = openpyxl.load_workbook('C:/Users/glaci/Downloads/1.imagens/winz26_ohlcv_atual.xlsx', read_only=True)
sheet = wb.active

candles = []
for r in sheet.iter_rows(values_only=True):
    if r[0] and isinstance(r[0], datetime):
        candles.append({
            'time': r[0],
            'open': float(r[1]),
            'high': float(r[2]),
            'low': float(r[3]),
            'close': float(r[4])
        })

candles.sort(key=lambda x: x['time'])

dates_to_test = [datetime(2026, 11, 23).date(), datetime(2026, 11, 24).date()]

def evaluate_day(target_date):
    day_candles = [c for c in candles if c['time'].date() == target_date]
    n_candles = len(day_candles)
    
    print(f"\n{'='*110}")
    print(f"AUDITORIA QUANTITATIVA COM DADOS REAIS PROFIT PRO: {target_date.strftime('%d/%m/%Y')} ({n_candles} candles 1m)")
    print(f"{'='*110}")
    
    fvg_records = []
    ifvg_records = []
    
    for i in range(2, n_candles):
        c1 = day_candles[i-2]
        c2 = day_candles[i-1]
        c3 = day_candles[i]
        
        # --- BULLISH FVG (COMPRA) ---
        if c3['low'] > c1['high'] + 5: # Gap mínimo de 10 pts
            gap_bottom = c1['high']
            gap_top = c3['low']
            gap_size = gap_top - gap_bottom
            ce_50 = (gap_top + gap_bottom) / 2.0
            
            entered = False
            entry_time = None
            outcome = 'SEM_RETESTE'
            max_favorable = 0.0
            max_adverse = 0.0
            
            # iFVG tracking
            inverted = False
            inv_time = None
            inv_entered = False
            inv_entry_time = None
            inv_outcome = 'SEM_RETESTE'
            inv_max_fav = 0.0
            inv_max_adv = 0.0
            
            for j in range(i + 1, n_candles):
                cj = day_candles[j]
                
                # FVG normal
                if not entered and not inverted:
                    if cj['close'] < gap_bottom:
                        inverted = True
                        inv_time = cj['time']
                    elif cj['low'] <= ce_50:
                        entered = True
                        entry_time = cj['time']
                        
                        target_price = ce_50 + 100.0
                        stop_price = ce_50 - 150.0
                        
                        hit_target = cj['high'] >= target_price
                        hit_stop = cj['low'] <= stop_price
                        
                        if hit_target and not hit_stop:
                            outcome = 'GAIN_100_PTS'
                            max_favorable = cj['high'] - ce_50
                            max_adverse = ce_50 - cj['low']
                        elif hit_stop and not hit_target:
                            outcome = 'STOP_150_PTS'
                            max_adverse = ce_50 - cj['low']
                            max_favorable = max(0.0, cj['high'] - ce_50)
                            inverted = True
                            inv_time = cj['time']
                        elif hit_target and hit_stop:
                            outcome = 'STOP_150_PTS'
                            inverted = True
                            inv_time = cj['time']
                        else:
                            max_favorable = max(max_favorable, cj['high'] - ce_50)
                            max_adverse = max(max_adverse, ce_50 - cj['low'])
                            
                elif entered and outcome not in ['GAIN_100_PTS', 'STOP_150_PTS']:
                    target_price = ce_50 + 100.0
                    stop_price = ce_50 - 150.0
                    
                    hit_target = cj['high'] >= target_price
                    hit_stop = cj['low'] <= stop_price
                    
                    max_favorable = max(max_favorable, cj['high'] - ce_50)
                    max_adverse = max(max_adverse, ce_50 - cj['low'])
                    
                    if hit_target and not hit_stop:
                        outcome = 'GAIN_100_PTS'
                    elif hit_stop and not hit_target:
                        outcome = 'STOP_150_PTS'
                        inverted = True
                        inv_time = cj['time']
                    elif hit_target and hit_stop:
                        outcome = 'STOP_150_PTS'
                        inverted = True
                        inv_time = cj['time']
                    
                    if cj['close'] < gap_bottom and not inverted:
                        inverted = True
                        inv_time = cj['time']
                        
                # Se foi invertido, monitorar como iFVG de Venda
                if inverted:
                    if not inv_entered:
                        # Reteste de baixo para cima no 50% CE
                        if cj['high'] >= ce_50:
                            inv_entered = True
                            inv_entry_time = cj['time']
                            inv_target = ce_50 - 100.0
                            inv_stop = ce_50 + 150.0
                            
                            hit_t = cj['low'] <= inv_target
                            hit_s = cj['high'] >= inv_stop
                            
                            if hit_t and not hit_s:
                                inv_outcome = 'GAIN_100_PTS'
                                inv_max_fav = ce_50 - cj['low']
                                inv_max_adv = cj['high'] - ce_50
                            elif hit_s and not hit_t:
                                inv_outcome = 'STOP_150_PTS'
                                inv_max_adv = cj['high'] - ce_50
                                inv_max_fav = max(0.0, ce_50 - cj['low'])
                            elif hit_t and hit_s:
                                inv_outcome = 'STOP_150_PTS'
                            else:
                                inv_max_fav = max(inv_max_fav, ce_50 - cj['low'])
                                inv_max_adv = max(inv_max_adv, cj['high'] - ce_50)
                    elif inv_entered and inv_outcome not in ['GAIN_100_PTS', 'STOP_150_PTS']:
                        inv_target = ce_50 - 100.0
                        inv_stop = ce_50 + 150.0
                        
                        hit_t = cj['low'] <= inv_target
                        hit_s = cj['high'] >= inv_stop
                        
                        inv_max_fav = max(inv_max_fav, ce_50 - cj['low'])
                        inv_max_adv = max(inv_max_adv, cj['high'] - ce_50)
                        
                        if hit_t and not hit_s:
                            inv_outcome = 'GAIN_100_PTS'
                        elif hit_s and not hit_t:
                            inv_outcome = 'STOP_150_PTS'
                        elif hit_t and hit_s:
                            inv_outcome = 'STOP_150_PTS'
            
            fvg_records.append({
                'type': 'BULLISH_FVG (COMPRA)',
                'time_c1': c1['time'].strftime('%H:%M'),
                'time_c2': c2['time'].strftime('%H:%M'),
                'time_c3': c3['time'].strftime('%H:%M'),
                'gap_bottom': gap_bottom,
                'gap_top': gap_top,
                'gap_size': gap_size,
                'ce_50': ce_50,
                'entered': entered,
                'entry_time': entry_time.strftime('%H:%M') if entry_time else '-',
                'outcome': outcome,
                'max_favorable': max_favorable,
                'max_adverse': max_adverse,
                'inverted': inverted,
                'inv_time': inv_time.strftime('%H:%M') if inv_time else '-',
                'inv_entered': inv_entered,
                'inv_entry_time': inv_entry_time.strftime('%H:%M') if inv_entry_time else '-',
                'inv_outcome': inv_outcome,
                'inv_max_fav': inv_max_fav,
                'inv_max_adv': inv_max_adv
            })
            
            if inverted:
                ifvg_records.append({
                    'parent_type': 'BULLISH_FVG',
                    'ifvg_type': 'iFVG_VENDA (RESISTÊNCIA)',
                    'orig_time': f"{c1['time'].strftime('%H:%M')}->{c3['time'].strftime('%H:%M')}",
                    'inv_time': inv_time.strftime('%H:%M') if inv_time else '-',
                    'ce_50': ce_50,
                    'entered': inv_entered,
                    'entry_time': inv_entry_time.strftime('%H:%M') if inv_entry_time else '-',
                    'outcome': inv_outcome,
                    'max_fav': inv_max_fav,
                    'max_adv': inv_max_adv
                })

        # --- BEARISH FVG (VENDA) ---
        elif c3['high'] < c1['low'] - 5:
            gap_top = c1['low']
            gap_bottom = c3['high']
            gap_size = gap_top - gap_bottom
            ce_50 = (gap_top + gap_bottom) / 2.0
            
            entered = False
            entry_time = None
            outcome = 'SEM_RETESTE'
            max_favorable = 0.0
            max_adverse = 0.0
            
            inverted = False
            inv_time = None
            inv_entered = False
            inv_entry_time = None
            inv_outcome = 'SEM_RETESTE'
            inv_max_fav = 0.0
            inv_max_adv = 0.0
            
            for j in range(i + 1, n_candles):
                cj = day_candles[j]
                
                if not entered and not inverted:
                    if cj['close'] > gap_top:
                        inverted = True
                        inv_time = cj['time']
                    elif cj['high'] >= ce_50:
                        entered = True
                        entry_time = cj['time']
                        
                        target_price = ce_50 - 100.0
                        stop_price = ce_50 + 150.0
                        
                        hit_target = cj['low'] <= target_price
                        hit_stop = cj['high'] >= stop_price
                        
                        if hit_target and not hit_stop:
                            outcome = 'GAIN_100_PTS'
                            max_favorable = ce_50 - cj['low']
                            max_adverse = cj['high'] - ce_50
                        elif hit_stop and not hit_target:
                            outcome = 'STOP_150_PTS'
                            max_adverse = cj['high'] - ce_50
                            max_favorable = max(0.0, ce_50 - cj['low'])
                            inverted = True
                            inv_time = cj['time']
                        elif hit_target and hit_stop:
                            outcome = 'STOP_150_PTS'
                            inverted = True
                            inv_time = cj['time']
                        else:
                            max_favorable = max(max_favorable, ce_50 - cj['low'])
                            max_adverse = max(max_adverse, cj['high'] - ce_50)
                            
                elif entered and outcome not in ['GAIN_100_PTS', 'STOP_150_PTS']:
                    target_price = ce_50 - 100.0
                    stop_price = ce_50 + 150.0
                    
                    hit_target = cj['low'] <= target_price
                    hit_stop = cj['high'] >= stop_price
                    
                    max_favorable = max(max_favorable, ce_50 - cj['low'])
                    max_adverse = max(max_adverse, cj['high'] - ce_50)
                    
                    if hit_target and not hit_stop:
                        outcome = 'GAIN_100_PTS'
                    elif hit_stop and not hit_target:
                        outcome = 'STOP_150_PTS'
                        inverted = True
                        inv_time = cj['time']
                    elif hit_target and hit_stop:
                        outcome = 'STOP_150_PTS'
                        inverted = True
                        inv_time = cj['time']
                        
                    if cj['close'] > gap_top and not inverted:
                        inverted = True
                        inv_time = cj['time']
                        
                if inverted:
                    if not inv_entered:
                        # Reteste de cima para baixo no 50% CE
                        if cj['low'] <= ce_50:
                            inv_entered = True
                            inv_entry_time = cj['time']
                            inv_target = ce_50 + 100.0
                            inv_stop = ce_50 - 150.0
                            
                            hit_t = cj['high'] >= inv_target
                            hit_s = cj['low'] <= inv_stop
                            
                            if hit_t and not hit_s:
                                inv_outcome = 'GAIN_100_PTS'
                                inv_max_fav = cj['high'] - ce_50
                                inv_max_adv = ce_50 - cj['low']
                            elif hit_s and not hit_t:
                                inv_outcome = 'STOP_150_PTS'
                                inv_max_adv = ce_50 - cj['low']
                                inv_max_fav = max(0.0, cj['high'] - ce_50)
                            elif hit_t and hit_s:
                                inv_outcome = 'STOP_150_PTS'
                            else:
                                inv_max_fav = max(inv_max_fav, cj['high'] - ce_50)
                                inv_max_adv = max(inv_max_adv, ce_50 - cj['low'])
                    elif inv_entered and inv_outcome not in ['GAIN_100_PTS', 'STOP_150_PTS']:
                        inv_target = ce_50 + 100.0
                        inv_stop = ce_50 - 150.0
                        
                        hit_t = cj['high'] >= inv_target
                        hit_s = cj['low'] <= inv_stop
                        
                        inv_max_fav = max(inv_max_fav, cj['high'] - ce_50)
                        inv_max_adv = max(inv_max_adv, ce_50 - cj['low'])
                        
                        if hit_t and not hit_s:
                            inv_outcome = 'GAIN_100_PTS'
                        elif hit_s and not hit_t:
                            inv_outcome = 'STOP_150_PTS'
                        elif hit_t and hit_s:
                            inv_outcome = 'STOP_150_PTS'

            fvg_records.append({
                'type': 'BEARISH_FVG (VENDA)',
                'time_c1': c1['time'].strftime('%H:%M'),
                'time_c2': c2['time'].strftime('%H:%M'),
                'time_c3': c3['time'].strftime('%H:%M'),
                'gap_bottom': gap_bottom,
                'gap_top': gap_top,
                'gap_size': gap_size,
                'ce_50': ce_50,
                'entered': entered,
                'entry_time': entry_time.strftime('%H:%M') if entry_time else '-',
                'outcome': outcome,
                'max_favorable': max_favorable,
                'max_adverse': max_adverse,
                'inverted': inverted,
                'inv_time': inv_time.strftime('%H:%M') if inv_time else '-',
                'inv_entered': inv_entered,
                'inv_entry_time': inv_entry_time.strftime('%H:%M') if inv_entry_time else '-',
                'inv_outcome': inv_outcome,
                'inv_max_fav': inv_max_fav,
                'inv_max_adv': inv_max_adv
            })
            
            if inverted:
                ifvg_records.append({
                    'parent_type': 'BEARISH_FVG',
                    'ifvg_type': 'iFVG_COMPRA (SUPORTE)',
                    'orig_time': f"{c1['time'].strftime('%H:%M')}->{c3['time'].strftime('%H:%M')}",
                    'inv_time': inv_time.strftime('%H:%M') if inv_time else '-',
                    'ce_50': ce_50,
                    'entered': inv_entered,
                    'entry_time': inv_entry_time.strftime('%H:%M') if inv_entry_time else '-',
                    'outcome': inv_outcome,
                    'max_fav': inv_max_fav,
                    'max_adv': inv_max_adv
                })

    # Métricas FVG Normal
    entered_fvg = [r for r in fvg_records if r['entered']]
    gains_fvg = [r for r in entered_fvg if r['outcome'] == 'GAIN_100_PTS']
    stops_fvg = [r for r in entered_fvg if r['outcome'] == 'STOP_150_PTS']
    
    # Métricas iFVG
    entered_ifvg = [r for r in ifvg_records if r['entered']]
    gains_ifvg = [r for r in entered_ifvg if r['outcome'] == 'GAIN_100_PTS']
    stops_ifvg = [r for r in entered_ifvg if r['outcome'] == 'STOP_150_PTS']
    
    print(f"\n--- PAINEL 1: FVG CLÁSSICO (MITIGAÇÃO DIRETA NO 50% CE) ---")
    print(f"Total Formados             : {len(fvg_records)} (Bullish: {sum(1 for r in fvg_records if 'COMPRA' in r['type'])}, Bearish: {sum(1 for r in fvg_records if 'VENDA' in r['type'])})")
    print(f"Entradas Acionadas (50% CE): {len(entered_fvg)} ({len(entered_fvg)/len(fvg_records)*100:.1f}%)")
    print(f"Alvo >= +100 Pts (GAIN)    : {len(gains_fvg)} ({len(gains_fvg)/len(entered_fvg)*100 if entered_fvg else 0:.1f}%)")
    print(f"Stop <= -150 Pts (LOSS)    : {len(stops_fvg)} ({len(stops_fvg)/len(entered_fvg)*100 if entered_fvg else 0:.1f}%)")
    
    print(f"\n--- PAINEL 2: iFVG (INVERSÃO DE POLARIDADE APÓS ROMPIMENTO) ---")
    print(f"Total Invertidos (iFVG)    : {len(ifvg_records)}")
    print(f"Entradas Acionadas (50% CE): {len(entered_ifvg)} ({len(entered_ifvg)/len(ifvg_records)*100 if ifvg_records else 0:.1f}%)")
    print(f"Alvo >= +100 Pts (GAIN)    : {len(gains_ifvg)} ({len(gains_ifvg)/len(entered_ifvg)*100 if entered_ifvg else 0:.1f}%)")
    print(f"Stop <= -150 Pts (LOSS)    : {len(stops_ifvg)} ({len(stops_ifvg)/len(entered_ifvg)*100 if entered_ifvg else 0:.1f}%)")
    
    print(f"\n--- PAINEL 3: DETALHAMENTO DE TODAS AS ENTRADAS EXECUTADAS NO 50% CE ---")
    print(f"{'TIPO':<10} | {'SUBTIPO':<12} | {'HORÁRIO C1-C3':<13} | {'MÍN-MÁX GAP':<16} | {'50% CE':<8} | {'HORA ENTRADA':<12} | {'RESULTADO':<13} | {'MFE (Pts)':<9} | {'MAE (Pts)':<9}")
    print(f"{'-'*10}-+-{'-'*12}-+-{'-'*13}-+-{'-'*16}-+-{'-'*8}-+-{'-'*12}-+-{'-'*13}-+-{'-'*9}-+-{'-'*9}")
    
    for r in entered_fvg:
        sub = 'COMPRA' if 'COMPRA' in r['type'] else 'VENDA'
        faixa = f"{r['gap_bottom']:.0f}-{r['gap_top']:.0f}"
        print(f"{'FVG':<10} | {sub:<12} | {r['time_c1']}->{r['time_c3']:<7} | {faixa:<16} | {r['ce_50']:<8.0f} | {r['entry_time']:<12} | {r['outcome']:<13} | {r['max_favorable']:<9.0f} | {r['max_adverse']:<9.0f}")

    for r in entered_ifvg:
        sub = 'COMPRA' if 'COMPRA' in r['ifvg_type'] else 'VENDA'
        print(f"{'iFVG':<10} | {sub:<12} | {r['orig_time']:<13} | {'Invertido':<16} | {r['ce_50']:<8.0f} | {r['entry_time']:<12} | {r['outcome']:<13} | {r['max_fav']:<9.0f} | {r['max_adv']:<9.0f}")

for d in dates_to_test:
    evaluate_day(d)
