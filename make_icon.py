"""Generate stint_logger.ico - a clean speedometer gauge icon."""
from PIL import Image, ImageDraw
import math
import os

S = 1024
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# dark rounded tile
m = 36
d.rounded_rectangle([m, m, S - m, S - m], radius=190, fill=(26, 29, 36, 255))

# speedo gauge
cx, cy = S // 2, int(S * 0.55)
r = int(S * 0.31)
bbox = [cx - r, cy - r, cx + r, cy + r]
w = 74
start, end = 135, 405  # 270 deg sweep, gap at bottom
d.arc(bbox, start, end, fill=(64, 70, 80, 255), width=w)          # track
vend = start + (end - start) * 0.72
d.arc(bbox, start, vend, fill=(63, 185, 80, 255), width=w)        # value (green)

# tick marks
for i in range(7):
    a = math.radians(start + (end - start) * i / 6.0)
    r1, r2 = r + w // 2 + 14, r + w // 2 + 54
    d.line([cx + r1 * math.cos(a), cy + r1 * math.sin(a),
            cx + r2 * math.cos(a), cy + r2 * math.sin(a)],
           fill=(150, 156, 166, 255), width=12)

# needle + hub
a = math.radians(vend)
d.line([cx, cy, cx + int(r * 0.92 * math.cos(a)), cy + int(r * 0.92 * math.sin(a))],
       fill=(235, 237, 240, 255), width=30)
hr = 52
d.ellipse([cx - hr, cy - hr, cx + hr, cy + hr], fill=(235, 237, 240, 255))
d.ellipse([cx - 20, cy - 20, cx + 20, cy + 20], fill=(63, 185, 80, 255))

img = img.resize((256, 256), Image.LANCZOS)
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stint_logger.ico")
img.save(out, sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
print("icon saved:", out)
