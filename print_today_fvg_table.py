import analyze_today_fvg_fast as a

seen_levels = set()
filtered = []
for r in a.results:
    lvl = round(r['entry'] / 50.0) * 50
    k = (r['dir'], lvl, r['setup'])
    if k not in seen_levels:
        seen_levels.add(k)
        filtered.append(r)

print(f"Total de eventos distintos de FVG/Reversao no pregao de hoje: {len(filtered)}")
g2 = sum(1 for r in filtered if 'GAIN' in r['r200'])
g3 = sum(1 for r in filtered if 'GAIN' in r['r300'])
print(f"Taxa de Gain 200 pts: {(g2/len(filtered))*100:.1f}% ({g2}/{len(filtered)})")
print(f"Taxa de Gain 300 pts: {(g3/len(filtered))*100:.1f}% ({g3}/{len(filtered)})")

print("\n" + "=" * 115)
header = f"{'#':<2} | {'Hora':<8} | {'TF':<4} | {'Direcao':<6} | {'Entrada':<7} | {'Stop 250':<8} | {'MAE':<6} | {'MFE':<6} | {'Alvo 200':<12} | {'Alvo 300':<12} | Setup"
print(header)
print("=" * 115)

for idx, r in enumerate(filtered[:18]):
    ent_s = f"{int(r['entry']):,}".replace(',', '.')
    stp_s = f"{int(r['stop']):,}".replace(',', '.')
    line = f"{idx+1:<2} | {r['time']:<8} | {r['tf']:<4} | {r['dir']:<6} | {ent_s:<7} | {stp_s:<8} | {r['mae']:>4.0f}pt | {r['mfe']:>4.0f}pt | {r['r200']:<12} | {r['r300']:<12} | {r['setup'][:32]}"
    print(line)

print("=" * 115)
