"""Race report: стінти, піт, паливо, деградація. stdlib only."""
import csv, glob, os, sys
from collections import OrderedDict
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

folder = os.path.dirname(os.path.abspath(__file__))
files = sorted(glob.glob(os.path.join(folder, "**", "*.csv"), recursive=True), key=os.path.getmtime)
p = sys.argv[1] if len(sys.argv) > 1 else files[-1]
rows = list(csv.DictReader(open(p, encoding="utf-8")))
F = lambda r, k: float(r[k])
I = lambda r, k: int(float(r[k]))

dur = F(rows[-1], "t") - F(rows[0], "t")
print("FILE:", os.path.basename(p))
print(f"rows={len(rows)}  dur={dur:.0f}s ({dur/60:.1f} min)")
if rows and rows[0].get("session"):
    fp = rows[-1].get("race_pos", "")
    place = f"  |  фініш: P{fp}" if fp.isdigit() and int(fp) > 0 else ""
    print(f"сесія: {rows[-1]['session']}{place}")

# --- fuel ---
fuel = [F(r, "fuel") for r in rows]
refuel = 0.0
ref_idx = None
for i in range(1, len(rows)):
    d = fuel[i] - fuel[i - 1]
    if d > 2.0:
        refuel += d
        if ref_idx is None:
            ref_idx = i
maxlap = max(int(r["lap"]) for r in rows)
burn = fuel[0] + refuel - fuel[-1]
print("\n== ПАЛИВО ==")
print(f"старт {fuel[0]:.1f} л  |  фініш {fuel[-1]:.1f} л  |  долито ~{refuel:.0f} л")
if ref_idx:
    print(f"перед доливкою лишалось {fuel[ref_idx-1]:.1f} л")
print(f"спалено ~{burn:.1f} л за ~{maxlap} кіл  ->  {burn/max(maxlap,1):.2f} л/коло")

# --- pit ---
pit_laps = sorted(set(int(r["lap"]) for r in rows if I(r, "inpit") == 1))
print("\n== ПІТ ==")
print(f"піт під час completedLaps: {pit_laps if pit_laps else 'не виявлено'}")

# --- stints ---
stints = []
cur = []
prev_pit = False
for r in rows:
    pit = I(r, "inpit") == 1
    if pit:
        if cur and not prev_pit:
            stints.append(cur)
            cur = []
    elif F(r, "speed_kmh") > 30:
        cur.append(r)
    prev_pit = pit
if cur:
    stints.append(cur)
stints = [s for s in stints if len(s) > 200]


def metrics(rs):
    n = len(rs) or 1
    a = lambda k: sum(F(r, k) for r in rs) / n
    return ((a("press_fl") + a("press_fr")) / 2, (a("press_rl") + a("press_rr")) / 2,
            (a("ttemp_fl") + a("ttemp_fr")) / 2, (a("ttemp_rl") + a("ttemp_rr")) / 2)


print(f"\n== СТІНТИ ({len(stints)}) ==")
for si, s in enumerate(stints, 1):
    ld = OrderedDict()
    for r in s:
        ld.setdefault(int(r["lap"]), []).append(r)
    valid = []
    for lp, rs in ld.items():
        d = F(rs[-1], "t") - F(rs[0], "t")
        prr = max(F(r, "pos") for r in rs) - min(F(r, "pos") for r in rs)
        if prr > 0.9 and 50 < d < 150:
            valid.append((lp, d, rs))
    if not valid:
        continue
    print(f"\n-- Стінт {si}: кола {valid[0][0]}-{valid[-1][0]} ({len(valid)} повних) --")
    print("lap |  time  | pF   pR  | tF  tR")
    for lp, d, rs in valid:
        pf, pr, tf, tr = metrics(rs)
        print(f"{lp:3} | {int(d)//60}:{d-(int(d)//60)*60:05.2f} | {pf:4.1f} {pr:4.1f} | {tf:3.0f} {tr:3.0f}")
    tms = [d for _, d, _ in valid]
    print(f"  best {min(tms):.2f}s | avg {sum(tms)/len(tms):.2f}s")
