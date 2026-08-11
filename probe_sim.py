"""Print the raw shared memory fields the logger relies on, with a verdict on
whether each looks sane. Run it WHILE the sim is on track:

    python probe_sim.py

It exists for the fields that cannot be judged from a CSV — either because the
logger deliberately does not log them (surfaceGrip) or because they can never be
non-zero in a file (isInPitLane: entering the pit lane finalizes the CSV).
"""

import sys
import time

import sim_shm
from sim_shm import AC, ACC

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SAMPLES = 40
INTERVAL = 0.1


def verdict(ok, note=""):
    """The note explains a failure, so it must not be printed next to an "ok"."""
    if ok:
        return "ok"
    return "SUSPECT" + ((" - " + note) if note else "")


def main():
    game = sim_shm.detect_game()
    if game is None:
        print("no sim running (looked for acs.exe / acs_x86.exe / AC2-Win64-Shipping.exe)")
        return 1
    reader = sim_shm.SimReader(game)
    reader.attach()
    if not reader.valid():
        print("{0} is running but shared memory is empty — get on track first".format(game))
        return 1

    s, g, p = reader.stat, reader.graph, reader.phys
    print("game: {0}   car: {1}   track: {2}   sm {3} / build {4}".format(
        game, (s.carModel or "").strip(), (s.track or "").strip(),
        (s.smVersion or "").strip(), (s.acVersion or "").strip()))
    print("sampling {0} times at {1:.0f} ms\n".format(SAMPLES, INTERVAL * 1000))

    seen = {}
    for _ in range(SAMPLES):
        seen.setdefault("speed", []).append(p.speedKmh)
        seen.setdefault("clutch", []).append(p.clutch)
        seen.setdefault("session_left_ms", []).append(g.sessionTimeLeft)
        if game == ACC:
            for i, w in enumerate(("fl", "fr", "rl", "rr")):
                seen.setdefault("btemp_" + w, []).append(p.brakeTemp[i])
            seen.setdefault("surfaceGrip", []).append(g.surfaceGrip)
            seen.setdefault("idealLineOn", []).append(g.idealLineOn)
            seen.setdefault("isInPitLane", []).append(g.isInPitLane)
            seen.setdefault("isValidLap", []).append(g.isValidLap)
            seen.setdefault("fuelXLap", []).append(g.fuelXLap)
            seen.setdefault("fuelEstimatedLaps", []).append(g.fuelEstimatedLaps)
            seen.setdefault("tyreCompound", []).append((g.tyreCompound or "").strip())
        time.sleep(INTERVAL)

    def rng(key):
        v = seen[key]
        return min(v), max(v)

    # not "> 0": a parked car still jitters at ~0.04 km/h, which would read as ok
    lo, hi = rng("speed")
    print("{0:<20} {1:>8.1f} .. {2:<8.1f} {3}".format(
        "speed_kmh", lo, hi, verdict(hi > 1.0, "car never moved, drive while probing")))

    # press the clutch fully and release it while probing: the field must span
    # the full 0..1, and which end means "released" is what tells us the polarity
    lo, hi = rng("clutch")
    print("{0:<20} {1:>8.2f} .. {2:<8.2f} {3}".format(
        "clutch", lo, hi,
        verdict(0 <= lo and hi <= 1 and hi - lo > 0.5,
                "pedal never moved, or offsets wrong (expected a 0..1 swing)")))

    if game == AC:
        print("\nAC has no isValidLap / fuelXLap / brakeTemp to check.")
        reader.close()
        return 0

    for w in ("fl", "fr", "rl", "rr"):
        k = "btemp_" + w
        lo, hi = rng(k)
        print("{0:<20} {1:>8.1f} .. {2:<8.1f} {3}".format(
            k, lo, hi, verdict(5 < hi < 1200, "outside 5..1200 C, offsets suspect")))

    # Zero is the expected answer here, so ok/SUSPECT would read backwards:
    # the official doc calls this a friction coefficient, the field returns 0.
    lo, hi = rng("surfaceGrip")
    print("{0:<20} {1:>8.3f} .. {2:<8.3f} {3}".format(
        "surfaceGrip", lo, hi,
        "always 0, as expected - not logged" if hi == 0
        else "NON-ZERO - the grip column is worth adding after all"))

    for k in ("idealLineOn", "isInPitLane", "isValidLap"):
        vals = sorted(set(seen[k]))
        print("{0:<20} {1:<21} {2}".format(
            k, str(vals), verdict(all(v in (0, 1) for v in vals), "not a 0/1 flag")))

    lo, hi = rng("fuelXLap")
    print("{0:<20} {1:>8.3f} .. {2:<8.3f} {3}".format(
        "fuelXLap", lo, hi, verdict(0 <= hi < 20, "implausible litres per lap")))

    lo, hi = rng("fuelEstimatedLaps")
    print("{0:<20} {1:>8.2f} .. {2:<8.2f} {3}".format(
        "fuelEstimatedLaps", lo, hi, verdict(0 <= hi < 200)))

    comp = sorted(set(seen["tyreCompound"]))
    print("{0:<20} {1:<21} {2}".format(
        "tyreCompound", str(comp),
        verdict(any("compound" in c for c in comp), "expected dry_compound / wet_compound")))

    reader.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
