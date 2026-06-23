"""
AC telemetry logger — читає shared memory Assetto Corsa і пише CSV.
Тільки stdlib (ctypes, mmap, csv). Python 3.x, Windows.

ЯК КОРИСТУВАТИСЬ:
  1. Запусти Assetto Corsa, зайди в сесію і ВИЇДЬ НА ТРАСУ (камера в машині).
  2. У терміналі:  py "C:\\Users\\YuriiHeits\\sim-telemetry\\ac_logger.py"
  3. Скрипт надрукує твою машину + трасу (це перевірка, що дані валідні).
     Якщо там абракадабра — скажи мені, поправлю структуру.
  4. Проїдь кілька кіл (прогрівне + 2-3 чистих). Ctrl+C — зупинити.
  CSV ляже поряд зі скриптом: ac_<машина>_<траса>_<час>.csv
"""
import ctypes, mmap, csv, time, os, datetime, re

AC_OFF, AC_REPLAY, AC_LIVE, AC_PAUSE = 0, 1, 2, 3


class Physics(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("packetId", ctypes.c_int32),
        ("gas", ctypes.c_float),
        ("brake", ctypes.c_float),
        ("fuel", ctypes.c_float),
        ("gear", ctypes.c_int32),
        ("rpms", ctypes.c_int32),
        ("steerAngle", ctypes.c_float),
        ("speedKmh", ctypes.c_float),
        ("velocity", ctypes.c_float * 3),
        ("accG", ctypes.c_float * 3),
        ("wheelSlip", ctypes.c_float * 4),
        ("wheelLoad", ctypes.c_float * 4),
        ("wheelsPressure", ctypes.c_float * 4),
        ("wheelAngularSpeed", ctypes.c_float * 4),
        ("tyreWear", ctypes.c_float * 4),
        ("tyreDirtyLevel", ctypes.c_float * 4),
        ("tyreCoreTemperature", ctypes.c_float * 4),
        ("camberRAD", ctypes.c_float * 4),
        ("suspensionTravel", ctypes.c_float * 4),
        ("drs", ctypes.c_float),
        ("tc", ctypes.c_float),
        ("heading", ctypes.c_float),
        ("pitch", ctypes.c_float),
        ("roll", ctypes.c_float),
        ("cgHeight", ctypes.c_float),
        ("carDamage", ctypes.c_float * 5),
        ("numberOfTyresOut", ctypes.c_int32),
        ("pitLimiterOn", ctypes.c_int32),
        ("abs", ctypes.c_float),
    ]


class Graphics(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("packetId", ctypes.c_int32),
        ("status", ctypes.c_int32),
        ("session", ctypes.c_int32),
        ("currentTime", ctypes.c_wchar * 15),
        ("lastTime", ctypes.c_wchar * 15),
        ("bestTime", ctypes.c_wchar * 15),
        ("split", ctypes.c_wchar * 15),
        ("completedLaps", ctypes.c_int32),
        ("position", ctypes.c_int32),
        ("iCurrentTime", ctypes.c_int32),
        ("iLastTime", ctypes.c_int32),
        ("iBestTime", ctypes.c_int32),
        ("sessionTimeLeft", ctypes.c_float),
        ("distanceTraveled", ctypes.c_float),
        ("isInPit", ctypes.c_int32),
        ("currentSectorIndex", ctypes.c_int32),
        ("lastSectorTime", ctypes.c_int32),
        ("numberOfLaps", ctypes.c_int32),
        ("tyreCompound", ctypes.c_wchar * 33),
        ("replayTimeMultiplier", ctypes.c_float),
        ("normalizedCarPosition", ctypes.c_float),
        ("carCoordinates", ctypes.c_float * 3),
    ]


class Static(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("smVersion", ctypes.c_wchar * 15),
        ("acVersion", ctypes.c_wchar * 15),
        ("numberOfSessions", ctypes.c_int32),
        ("numCars", ctypes.c_int32),
        ("carModel", ctypes.c_wchar * 33),
        ("track", ctypes.c_wchar * 33),
        ("playerName", ctypes.c_wchar * 33),
        ("playerSurname", ctypes.c_wchar * 33),
        ("playerNick", ctypes.c_wchar * 33),
        ("sectorCount", ctypes.c_int32),
    ]


def attach(name, struct):
    buf = mmap.mmap(-1, ctypes.sizeof(struct), tagname=name)
    return struct.from_buffer(buf), buf


def safe(s):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", (s or "").strip()) or "unknown"


def fmt_ms(ms):
    if ms <= 0 or ms > 3_600_000:
        return "--"
    return f"{ms // 60000}:{(ms % 60000) / 1000:06.3f}"


def main():
    print("Attaching to AC shared memory...")
    phys, _mp = attach("acpmf_physics", Physics)
    graph, _mg = attach("acpmf_graphics", Graphics)
    stat, _ms = attach("acpmf_static", Static)

    print("Waiting for a LIVE session (get on track in AC)...")
    waited = 0.0
    while graph.status != AC_LIVE:
        time.sleep(0.5)
        waited += 0.5
        if waited >= 12 and not stat.acVersion:
            print("  ! AC не видно. Переконайся, що AC запущений і ти НА ТРАСІ, "
                  "потім перезапусти скрипт.")
            waited = 0.0

    car, track = safe(stat.carModel), safe(stat.track)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       f"ac_{car}_{track}_{ts}.csv")
    print(f"\n  Машина: {stat.carModel}")
    print(f"  Траса:  {stat.track}")
    print(f"  AC ver: {stat.acVersion}")
    print(f"  -> {out}")
    print("\n  Якщо машина/траса вгорі правильні — все ок, ЇДЬ. Ctrl+C — стоп.\n")

    cols = ["t", "lap", "pos", "speed_kmh", "rpm", "gear", "gas", "brake", "steer",
            "gx", "gy", "gz",
            "slip_fl", "slip_fr", "slip_rl", "slip_rr",
            "press_fl", "press_fr", "press_rl", "press_rr",
            "ttemp_fl", "ttemp_fr", "ttemp_rl", "ttemp_rr",
            "camber_fl", "camber_fr", "camber_rl", "camber_rr",
            "susp_fl", "susp_fr", "susp_rl", "susp_rr",
            "tc", "abs", "fuel", "inpit", "last_ms", "best_ms"]

    f = open(out, "w", newline="", encoding="utf-8")
    w = csv.writer(f)
    w.writerow(cols)

    t0 = time.perf_counter()
    last_flush = t0
    last_lap = graph.completedLaps
    rows = 0
    try:
        while True:
            if graph.status != AC_LIVE:
                time.sleep(0.2)
                continue
            t = time.perf_counter() - t0
            p, g = phys, graph
            w.writerow([
                f"{t:.3f}", g.completedLaps, f"{g.normalizedCarPosition:.5f}",
                f"{p.speedKmh:.2f}", p.rpms, p.gear,
                f"{p.gas:.3f}", f"{p.brake:.3f}", f"{p.steerAngle:.4f}",
                f"{p.accG[0]:.3f}", f"{p.accG[1]:.3f}", f"{p.accG[2]:.3f}",
                f"{p.wheelSlip[0]:.3f}", f"{p.wheelSlip[1]:.3f}", f"{p.wheelSlip[2]:.3f}", f"{p.wheelSlip[3]:.3f}",
                f"{p.wheelsPressure[0]:.2f}", f"{p.wheelsPressure[1]:.2f}", f"{p.wheelsPressure[2]:.2f}", f"{p.wheelsPressure[3]:.2f}",
                f"{p.tyreCoreTemperature[0]:.1f}", f"{p.tyreCoreTemperature[1]:.1f}", f"{p.tyreCoreTemperature[2]:.1f}", f"{p.tyreCoreTemperature[3]:.1f}",
                f"{p.camberRAD[0]:.4f}", f"{p.camberRAD[1]:.4f}", f"{p.camberRAD[2]:.4f}", f"{p.camberRAD[3]:.4f}",
                f"{p.suspensionTravel[0]:.4f}", f"{p.suspensionTravel[1]:.4f}", f"{p.suspensionTravel[2]:.4f}", f"{p.suspensionTravel[3]:.4f}",
                f"{p.tc:.2f}", f"{p.abs:.2f}", f"{p.fuel:.2f}", g.isInPit,
                g.iLastTime, g.iBestTime,
            ])
            rows += 1

            if g.completedLaps != last_lap:
                print(f"  Коло {g.completedLaps}: {fmt_ms(g.iLastTime)}")
                last_lap = g.completedLaps

            now = time.perf_counter()
            if now - last_flush > 1.0:
                f.flush()
                last_flush = now
            time.sleep(0.02)  # ~50 Hz
    except KeyboardInterrupt:
        pass
    finally:
        f.flush()
        f.close()
        print(f"\nЗупинено. Записано {rows} рядків -> {out}")


if __name__ == "__main__":
    main()
