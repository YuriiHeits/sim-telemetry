"""Trail-braking analyzer for AC telemetry (stdlib only).

Trail braking = keeping brake pressure while turning in, releasing it
gradually as lateral load builds. We measure, per braking zone:
  - lateral G at the moment brake is released (are you still turning?)
  - overlap: share of the braking done while cornering
Zones are clustered by track position so you see it corner-by-corner.

Axes (verified): gx = lateral G (cornering), gz = longitudinal (braking).
Usage: python trail_report.py [file.csv ...]   (default: newest csv)
"""
import csv, glob, os, sys, statistics as st
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

folder = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
if not args:
    files = sorted(glob.glob(os.path.join(folder, "**", "*.csv"), recursive=True), key=os.path.getmtime)
    args = [files[-1]]

F = lambda r, k: float(r[k])
I = lambda r, k: int(float(r[k]))
GMAX = 3.5  # clip gx spikes (kerbs / glitches) above this

def load(path):
    return list(csv.DictReader(open(path, encoding="utf-8")))

def valid_laps(rows):
    """Return {lap: rows} for clean, representative laps (drop pit/spins/slow)."""
    from collections import OrderedDict
    segs = OrderedDict()
    for r in rows:
        segs.setdefault(I(r, "lap"), []).append(r)
    cand = []
    for lp, rs in segs.items():
        d = F(rs[-1], "t") - F(rs[0], "t")
        prr = max(F(r, "pos") for r in rs) - min(F(r, "pos") for r in rs)
        pit = sum(I(r, "inpit") for r in rs) / len(rs)
        if prr > 0.9 and pit < 0.05 and 50 < d < 150:
            cand.append((lp, d, rs))
    if not cand:
        return [], 0.0
    best = min(c[1] for c in cand)
    good = [(lp, d, rs) for lp, d, rs in cand if d <= best * 1.06]  # representative pace only
    return good, best

def lat(r):
    g = abs(F(r, "gx"))
    return g if g <= GMAX else None

def brake_zones(rs):
    """Detect braking zones in one lap. rs is time-ordered."""
    zones, i, n = [], 0, len(rs)
    while i < n:
        if F(rs[i], "brake") > 0.15:
            j = i
            gap = 0
            while j < n:
                if F(rs[j], "brake") > 0.08:
                    gap = 0
                else:
                    gap += 1
                    if gap >= 4:  # ~0.12s below threshold -> zone ends
                        break
                j += 1
            seg = rs[i:j - gap + 1] if gap else rs[i:j]
            zones.append(seg)
            i = j + 1
        else:
            i += 1
    return zones

def zone_metrics(seg):
    speeds = [F(r, "speed_kmh") for r in seg]
    entry, vmin = speeds[0], min(speeds)
    peak = max(F(r, "brake") for r in seg)
    if peak < 0.35 or (entry - vmin) < 8:
        return None  # brush, not a real corner braking event
    # release = last sample still meaningfully on the brake
    rel_idx = max(k for k, r in enumerate(seg) if F(r, "brake") > 0.15)
    tail = [lat(r) for r in seg[max(0, rel_idx - 2):rel_idx + 1]]
    tail = [x for x in tail if x is not None]
    lat_release = st.median(tail) if tail else 0.0
    steer_release = st.median(abs(F(r, "steer")) for r in seg[max(0, rel_idx - 2):rel_idx + 1])
    latv = [lat(r) for r in seg]
    latv = [x for x in latv if x is not None]
    overlap = (sum(1 for x in latv if x > 0.6) / len(latv)) if latv else 0.0
    pos = st.median(F(r, "pos") for r in seg)
    return dict(entry=entry, vmin=vmin, peak=peak, lat_release=lat_release,
                steer_release=steer_release, overlap=overlap, pos=pos)

def cluster(zones):
    """Group zones (dicts) by track position into corners."""
    zs = sorted(zones, key=lambda z: z["pos"])
    clusters, cur = [], []
    for z in zs:
        if cur and z["pos"] - cur[-1]["pos"] > 0.03:
            clusters.append(cur); cur = []
        cur.append(z)
    if cur:
        clusters.append(cur)
    return clusters

# ---- run ----
allz = []
laps_used = 0
best = 0.0
for path in args:
    rows = load(path)
    good, b = valid_laps(rows)
    best = b if best == 0 else min(best, b)
    laps_used += len(good)
    for lp, d, rs in good:
        for seg in brake_zones(rs):
            m = zone_metrics(seg)
            if m:
                allz.append(m)

print("FILES:", ", ".join(os.path.basename(a) for a in args))
mm = lambda s: f"{int(s)//60}:{s-(int(s)//60)*60:05.2f}"
print(f"representative laps used: {laps_used}   best: {mm(best)}   braking zones: {len(allz)}\n")

if not allz:
    print("no braking zones found"); sys.exit()

lr = [z["lat_release"] for z in allz]
ov = [z["overlap"] for z in allz]
straight = sum(1 for z in allz if z["lat_release"] < 0.4)
print("== SESSION TRAIL-BRAKING ==")
print(f"lateral G at brake-release:  median {st.median(lr):.2f}g   (higher = still turning when you lift off)")
print(f"braking-while-cornering:     median {st.median(ov)*100:.0f}% of each zone")
print(f"'brake-straight-then-turn':  {straight}/{len(allz)} zones ({straight/len(allz)*100:.0f}%)  <- released while basically straight\n")

clusters = cluster(allz)
print("== CORNER-BY-CORNER (grouped by track position) ==")
print("pos  | seen | entry | vmin | peak | latG@rel | overlap | verdict")
def verdict(lr, ov):
    if lr >= 1.0 and ov >= 0.35: return "trail OK"
    if lr < 0.4: return "BRAKE-STRAIGHT (leak)"
    return "partial"
worst = []
for cl in clusters:
    if len(cl) < 3:  # not seen on enough laps -> skip noise
        continue
    pos = st.median(z["pos"] for z in cl)
    entry = st.median(z["entry"] for z in cl)
    vmin = st.median(z["vmin"] for z in cl)
    peak = st.median(z["peak"] for z in cl)
    lrm = st.median(z["lat_release"] for z in cl)
    ovm = st.median(z["overlap"] for z in cl)
    v = verdict(lrm, ovm)
    print(f"{pos:4.2f} |  {len(cl):2}  | {entry:4.0f}  | {vmin:4.0f} | {peak:4.2f} |  {lrm:4.2f}g  |  {ovm*100:3.0f}%  | {v}")
    worst.append((lrm, pos, entry, vmin, v))

print("\n== BIGGEST LEAKS (low latG@release, meaningful entry speed) ==")
for lrm, pos, entry, vmin, v in sorted(worst)[:3]:
    print(f"  pos {pos:.2f}: entry {entry:.0f}->{vmin:.0f} km/h, releases brake at only {lrm:.2f}g lateral  [{v}]")
