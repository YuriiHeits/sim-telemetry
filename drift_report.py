"""Drift telemetry analyzer — кут заносу, час боком, перекладки, зриви.
Потрібні колонки heading + vel_x/vel_z (логгер від 2026-06-22+). stdlib only."""
import csv, glob, os, sys, math, statistics
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

folder = os.path.dirname(os.path.abspath(__file__))
files = sorted(glob.glob(os.path.join(folder, "**", "*.csv"), recursive=True), key=os.path.getmtime)
path = sys.argv[1] if len(sys.argv) > 1 else files[-1]
rows = list(csv.DictReader(open(path, encoding="utf-8")))
F = lambda r, k: float(r[k])

print("FILE:", os.path.basename(path))
if not rows or "heading" not in rows[0]:
    print("  ⚠ немає колонок heading/vel — лог зі старого логгера. Перезапиши новим StintLogger.")
    sys.exit()


def wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


# raw body-slip = кут між напрямком носа (heading) і напрямком руху (вектор швидкості).
# +pi/2 — стала конвенції координат AC (на прямих дає ~0; перевірено на реальному лозі).
def raw_slip(r):
    return wrap(F(r, "heading") - math.atan2(F(r, "vel_z"), F(r, "vel_x")) + math.pi / 2)


mv = [r for r in rows if F(r, "speed_kmh") > 15]
if not mv:
    print("  (немає руху)")
    sys.exit()

# авто-калібровка залишку: справді прямі = мале кермо І мале бічне G (не плутати з перекладкою)
straight = [raw_slip(r) for r in mv if abs(F(r, "steer")) < 0.08 and abs(F(r, "gx")) < 0.25 and F(r, "speed_kmh") > 40]
offset = statistics.median(straight) if straight else 0.0
slips = [math.degrees(wrap(raw_slip(r) - offset)) for r in mv]

# валідація: |вектор швидкості| має збігатися з логнутою швидкістю
vmag = [math.sqrt(F(r, "vel_x") ** 2 + F(r, "vel_z") ** 2) * 3.6 for r in mv]
verr = statistics.mean(abs(vmag[i] - F(mv[i], "speed_kmh")) for i in range(len(mv)))
dur = F(rows[-1], "t") - F(rows[0], "t")
print(f"rows={len(rows)}  dur={dur:.0f}s   (вектор-швидкість vs лог: Δ{verr:.1f} км/год{'  ⚠ перевір осі' if verr > 5 else ' ✓'})")
if not straight:
    print("  (нема прямих ділянок для калібровки — кут може мати зсув)")

SIDE = 10.0  # боком від 10°
TR = 12.0    # поріг для перекладки
side = [abs(s) for s in slips if abs(s) > SIDE]
sidepct = 100 * len(side) / len(mv)
maxang = max((abs(s) for s in slips), default=0.0)
avgside = sum(side) / len(side) if side else 0.0

# перекладки: зміни знаку кута через стійкий занос в обидва боки (гістерезис)
st = 0
trans = 0
for s in slips:
    if s > TR and st != 1:
        if st == -1:
            trans += 1
        st = 1
    elif s < -TR and st != -1:
        if st == 1:
            trans += 1
        st = -1

# зриви: кут >90° (ніс різко не туди), із дебаунсом
spins = 0
inspin = False
for s in slips:
    if abs(s) > 90 and not inspin:
        spins += 1
        inspin = True
    elif abs(s) < 60:
        inspin = False

gas = [F(r, "gas") for r in mv]
siderows = [mv[i] for i, s in enumerate(slips) if abs(s) > SIDE]
gas_side = [F(r, "gas") for r in siderows]

print("\n== ДРИФТ ==")
print(f"час боком (>{SIDE:.0f}°):   {sidepct:.0f}%  ({len(side)}/{len(mv)} кадрів руху)")
print(f"кут заносу:         середній {avgside:.0f}°   макс {maxang:.0f}°")
print(f"перекладки:         {trans}")
print(f"зриви (>90°):       {spins}")
print(f"газ загалом:        {sum(gas)/len(gas):.2f}  (модуляція {statistics.pstdev(gas):.2f})")
if gas_side:
    print(f"газ у заносі:       {sum(gas_side)/len(gas_side):.2f}  (модуляція {statistics.pstdev(gas_side):.2f})")

if "tyres_out" in mv[0]:
    out_evt = 0
    out_frames = 0
    maxout = 0
    prev = 0
    for r in mv:
        n = int(float(r["tyres_out"]))
        if n > 0:
            out_frames += 1
            maxout = max(maxout, n)
            if prev == 0:
                out_evt += 1
        prev = n
    dirt = {k: max(F(r, "dirt_" + k) for r in mv) for k in ("fl", "fr", "rl", "rr")}
    dirtiest = max(dirt, key=dirt.get)
    print("\n== ПОКРИТТЯ ==")
    print(f"виїзди за межі:    {out_evt} епізодів  (макс {maxout} коліс одночасно, {100*out_frames/len(mv):.0f}% часу хоч одне за межами)")
    print(f"бруд по колесах:   FL {dirt['fl']:.2f}  FR {dirt['fr']:.2f}  RL {dirt['rl']:.2f}  RR {dirt['rr']:.2f}  -> найчастіше на газоні {dirtiest.upper()}")
