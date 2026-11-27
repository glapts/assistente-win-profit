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

# Group by day in November 2026
by_day = {}
for c in candles:
    d = c['time'].date()
    if d >= datetime(2026, 11, 1).date():
        by_day.setdefault(d, []).append(c)

high_calor_trades = [] # 75 <= mae < 100
extreme_calor_trades = [] # 100 <= mae < 150

for d, day_candles in by_day.items():
    n = len(day_candles)
    for i in range(2, n):
        c1, c2, c3 = day_candles[i-2], day_candles[i-1], day_candles[i]
        side, gap, ce = None, 0, 0
        if c3['low'] > c1['high']:
            gap = c3['low'] - c1['high']
            side = 'COMPRA'
            ce = (c3['low'] + c1['high']) / 2.0
        elif c3['high'] < c1['low']:
            gap = c1['low'] - c3['high']
            side = 'VENDA'
            ce = (c1['low'] + c3['high']) / 2.0
            
        # Gaps pequenos apenas (5 <= gap < 20 pts)
        if side and 5 <= gap < 20:
            hit_entry = False
            entry_time = None
            mae = 0.0
            target = ce + 100 if side == 'COMPRA' else ce - 100
            stop = ce - 150 if side == 'COMPRA' else ce + 150
            
            for j in range(i+1, n):
                cj = day_candles[j]
                if not hit_entry:
                    if (side == 'COMPRA' and cj['low'] <= ce) or (side == 'VENDA' and cj['high'] >= ce):
                        hit_entry = True
                        entry_time = cj['time']
                        if side == 'COMPRA':
                            mae = max(mae, ce - cj['low'])
                        else:
                            mae = max(mae, cj['high'] - ce)
                            
                        h_t = cj['high'] >= target if side == 'COMPRA' else cj['low'] <= target
                        h_s = cj['low'] <= stop if side == 'COMPRA' else cj['high'] >= stop
                        
                        if h_t and not h_s:
                            rec = {
                                'date': d, 
                                'c1_time': c1['time'], 
                                'c3_time': c3['time'], 
                                'entry_time': entry_time, 
                                'target_time': cj['time'], 
                                'side': side, 
                                'gap': gap, 
                                'ce': ce, 
                                'mae': mae
                            }
                            if 75 <= mae < 100: high_calor_trades.append(rec)
                            elif 100 <= mae < 150: extreme_calor_trades.append(rec)
                            break
                        elif h_s:
                            break
                else:
                    if side == 'COMPRA':
                        mae = max(mae, ce - cj['low'])
                    else:
                        mae = max(mae, cj['high'] - ce)
                        
                    h_t = cj['high'] >= target if side == 'COMPRA' else cj['low'] <= target
                    h_s = cj['low'] <= stop if side == 'COMPRA' else cj['high'] >= stop
                    
                    if h_t and not h_s:
                        rec = {
                            'date': d, 
                            'c1_time': c1['time'], 
                            'c3_time': c3['time'], 
                            'entry_time': entry_time, 
                            'target_time': cj['time'], 
                            'side': side, 
                            'gap': gap, 
                            'ce': ce, 
                            'mae': mae
                        }
                        if 75 <= mae < 100: high_calor_trades.append(rec)
                        elif 100 <= mae < 150: extreme_calor_trades.append(rec)
                        break
                    elif h_s:
                        break

print(f"Total de Trades com Calor Alto (75 a 100 pts): {len(high_calor_trades)}")
print(f"Total de Trades com Calor Extremo (100 a 150 pts): {len(extreme_calor_trades)}")

print("\n" + "="*105)
print("TABELA 1: TODOS OS TRADES COM CALOR EXTREMO (100 a 150 pts de recuo adverso antes do GAIN)")
print("="*105)
print(f"{'DATA':<10} | {'HORA FVG':<13} | {'ENTRADA':<7} | {'ALVO':<7} | {'DIREÇÃO':<7} | {'GAP (Pts)':<9} | {'PREÇO 50% CE':<12} | {'CALOR (MAE)':<11}")
print("-" * 105)
for r in extreme_calor_trades:
    d_str = r['date'].strftime('%d/%m/%Y')
    fvg_str = f"{r['c1_time'].strftime('%H:%M')}->{r['c3_time'].strftime('%H:%M')}"
    ent_str = r['entry_time'].strftime('%H:%M')
    tgt_str = r['target_time'].strftime('%H:%M')
    print(f"{d_str:<10} | {fvg_str:<13} | {ent_str:<7} | {tgt_str:<7} | {r['side']:<7} | {r['gap']:<9.0f} | {r['ce']:<12.1f} | {r['mae']:<11.1f}")

print("\n" + "="*105)
print("TABELA 2: TODOS OS TRADES COM CALOR ALTO (75 a 100 pts de recuo adverso antes do GAIN)")
print("="*105)
print(f"{'DATA':<10} | {'HORA FVG':<13} | {'ENTRADA':<7} | {'ALVO':<7} | {'DIREÇÃO':<7} | {'GAP (Pts)':<9} | {'PREÇO 50% CE':<12} | {'CALOR (MAE)':<11}")
print("-" * 105)
for r in high_calor_trades:
    d_str = r['date'].strftime('%d/%m/%Y')
    fvg_str = f"{r['c1_time'].strftime('%H:%M')}->{r['c3_time'].strftime('%H:%M')}"
    ent_str = r['entry_time'].strftime('%H:%M')
    tgt_str = r['target_time'].strftime('%H:%M')
    print(f"{d_str:<10} | {fvg_str:<13} | {ent_str:<7} | {tgt_str:<7} | {r['side']:<7} | {r['gap']:<9.0f} | {r['ce']:<12.1f} | {r['mae']:<11.1f}")
