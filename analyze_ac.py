"""AC telemetry analyzer — per-lap (стінт) + фільтр сміттєвих кіл. stdlib only."""
import csv, glob, os, sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

folder = os.path.dirname(os.path.abspath(__file__))
files = sorted(glob.glob(os.path.join(folder, "**", "*.csv"), recursive=True), key=os.path.getmtime)
path = sys.argv[1] if len(sys.argv) > 1 else files[-1]

rows = list(csv.DictReader(open(path, encoding="utf-8")))
F = lambda r, k: float(r[k])
I = lambda r, k: int(float(r[k]))

print("FILE:", os.path.basename(path))
print(f"rows={len(rows)}  dur={F(rows[-1],'t')-F(rows[0],'t'):.0f}s")
if rows and rows[0].get("session"):
    fp = rows[-1].get("race_pos", "")
    place = f"  |  місце: P{fp}" if fp.isdigit() and int(fp) > 0 else ""
    print(f"сесія: {rows[-1]['session']}{place}")

from collections import OrderedDict
segs = OrderedDict()
for r in rows:
    segs.setdefault(int(r["lap"]), []).append(r)


def drv(rs):
    return [r for r in rs if F(r, "speed_kmh") > 30 and I(r, "inpit") == 0]


def metrics(rs):
    n = len(rs) or 1
    a = lambda k: sum(F(r, k) for r in rs) / n
    pf = (a("press_fl") + a("press_fr")) / 2
    pr = (a("press_rl") + a("press_rr")) / 2
    tf = (a("ttemp_fl") + a("ttemp_fr")) / 2
    tr = (a("ttemp_rl") + a("ttemp_rr")) / 2
    corn = [r for r in rs if abs(F(r, "gx")) > 1.0]
    if corn:
        m = len(corn)
        fs = sum(F(r, "slip_fl") + F(r, "slip_fr") for r in corn) / (2 * m)
        rsl = sum(F(r, "slip_rl") + F(r, "slip_rr") for r in corn) / (2 * m)
    else:
        fs = rsl = 0.0
    return pf, pr, tf, tr, fs, rsl


def bal(fs, rsl):
    return "OS" if rsl > fs * 1.1 else "US" if fs > rsl * 1.1 else "ok"


def mmss(d):
    return f"{int(d)//60}:{d-(int(d)//60)*60:05.2f}"


print("\n== PER-LAP (стінт) ==")
print("lap |  time  | pF   pR  | tF  tR | slipF slipR | bal")
valid = []
for lp, rs in segs.items():
    d = F(rs[-1], "t") - F(rs[0], "t")
    prr = max(F(r, "pos") for r in rs) - min(F(r, "pos") for r in rs)
    pit = sum(I(r, "inpit") for r in rs) / len(rs)
    if not (prr > 0.9 and pit < 0.05 and 50 < d < 150):
        continue
    dr = drv(rs)
    pf, pr, tf, tr, fs, rsl = metrics(dr)
    valid.append((lp, d, dr))
    print(f"{lp:3} | {mmss(d)} | {pf:4.1f} {pr:4.1f} | {tf:3.0f} {tr:3.0f} | {fs:5.2f} {rsl:5.2f} | {bal(fs,rsl)}")

if not valid:
    print("  (немає валідних повних кіл)")
    sys.exit()

best = min(valid, key=lambda x: x[1])
print(f"\nbest lap: {mmss(best[1])}  (lap {best[0]})  валідних кіл: {len(valid)}")

allrows = [r for _, _, dr in valid for r in dr]
pf, pr, tf, tr, fs, rsl = metrics(allrows)
print("\n== ЗВЕДЕНО (по валідних колах) ==")
print(f"тиск гарячий:  перед {pf:.1f}  зад {pr:.1f}")
print(f"темп core:     перед {tf:.0f}  зад {tr:.0f}")
print(f"баланс:        слип перед {fs:.2f} / зад {rsl:.2f}  -> {('ЗАНОС' if rsl>fs*1.1 else 'НЕДОПОВОРОТ' if fs>rsl*1.1 else 'нейтрально')}")
if rows and "heading" in rows[0]:
    import math, statistics
    _wrap = lambda a: (a + math.pi) % (2 * math.pi) - math.pi
    _slip = lambda r: _wrap(F(r, "heading") - math.atan2(F(r, "vel_z"), F(r, "vel_x")) + math.pi / 2)
    _straight = [_slip(r) for r in allrows if abs(F(r, "steer")) < 0.08 and abs(F(r, "gx")) < 0.3 and F(r, "speed_kmh") > 80]
    _off = statistics.median(_straight) if _straight else 0.0
    _corn = [abs(math.degrees(_wrap(_slip(r) - _off))) for r in allrows if abs(F(r, "gx")) > 1.0]
    if _corn:
        print(f"кут заносу:    у поворотах avg {sum(_corn)/len(_corn):.1f}°  макс {max(_corn):.0f}°")
brk = [r for r in allrows if F(r, "brake") > 0.7]
if brk:
    print(f"гальмо:        ABS {sum(1 for r in brk if F(r,'abs')>0.01)/len(brk)*100:.0f}%, слип перед {sum(F(r,'slip_fl')+F(r,'slip_fr') for r in brk)/(2*len(brk)):.2f}")
ext = [r for r in allrows if F(r, "gas") > 0.6 and F(r, "speed_kmh") < 160]
if ext:
    print(f"тяга на виході: слип зад {sum(F(r,'slip_rl')+F(r,'slip_rr') for r in ext)/(2*len(ext)):.2f}")

if rows and "tyres_out" in rows[0]:
    drv = [r for r in rows if F(r, "speed_kmh") > 30 and I(r, "inpit") == 0]
    evt = all4 = prev = 0
    for r in drv:
        n = int(float(r["tyres_out"]))
        if n > 0 and prev == 0:
            evt += 1
        if n >= 4 and prev < 4:
            all4 += 1
        prev = n
    print(f"track limits:  {evt} виїздів (≥1 колесо за межами), з них {all4} з усіма 4 (анулює коло)")
