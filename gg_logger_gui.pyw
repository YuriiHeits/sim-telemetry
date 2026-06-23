"""GG Telemetry Logger - GUI (Python 3.x + tkinter, stdlib only).
Works for Assetto Corsa AND ACC (reads shared memory via ctypes/mmap).
Auto-detects a live session, logs a CSV per stint to this folder.
The CSV is FINALIZED (closed) on pit-entry or when you leave the track,
so it can be read without quitting the sim. Double-click to run."""

import os
import sys
import time
import csv
import ctypes
import mmap
import tkinter as tk

if getattr(sys, "frozen", False):
    OUT_DIR = os.path.dirname(sys.executable)
else:
    OUT_DIR = os.path.dirname(os.path.abspath(__file__))
AC_LIVE = 2

# ---- colors ----
BG = "#14161b"
CARD = "#1d2129"
TEXT = "#e6e8eb"
MUTED = "#8a909a"
GREEN = "#3fb950"
AMBER = "#d29922"
BLUE = "#4aa3ff"
RED = "#f0584b"
GREY = "#6e7681"


class Physics(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("packetId", ctypes.c_int32), ("gas", ctypes.c_float), ("brake", ctypes.c_float),
        ("fuel", ctypes.c_float), ("gear", ctypes.c_int32), ("rpms", ctypes.c_int32),
        ("steerAngle", ctypes.c_float), ("speedKmh", ctypes.c_float),
        ("velocity", ctypes.c_float * 3), ("accG", ctypes.c_float * 3),
        ("wheelSlip", ctypes.c_float * 4), ("wheelLoad", ctypes.c_float * 4),
        ("wheelsPressure", ctypes.c_float * 4), ("wheelAngularSpeed", ctypes.c_float * 4),
        ("tyreWear", ctypes.c_float * 4), ("tyreDirtyLevel", ctypes.c_float * 4),
        ("tyreCoreTemperature", ctypes.c_float * 4), ("camberRAD", ctypes.c_float * 4),
        ("suspensionTravel", ctypes.c_float * 4), ("drs", ctypes.c_float), ("tc", ctypes.c_float),
        ("heading", ctypes.c_float), ("pitch", ctypes.c_float), ("roll", ctypes.c_float),
        ("cgHeight", ctypes.c_float), ("carDamage", ctypes.c_float * 5),
        ("numberOfTyresOut", ctypes.c_int32), ("pitLimiterOn", ctypes.c_int32), ("abs", ctypes.c_float),
    ]


class Graphics(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("packetId", ctypes.c_int32), ("status", ctypes.c_int32), ("session", ctypes.c_int32),
        ("currentTime", ctypes.c_wchar * 15), ("lastTime", ctypes.c_wchar * 15),
        ("bestTime", ctypes.c_wchar * 15), ("split", ctypes.c_wchar * 15),
        ("completedLaps", ctypes.c_int32), ("position", ctypes.c_int32),
        ("iCurrentTime", ctypes.c_int32), ("iLastTime", ctypes.c_int32), ("iBestTime", ctypes.c_int32),
        ("sessionTimeLeft", ctypes.c_float), ("distanceTraveled", ctypes.c_float),
        ("isInPit", ctypes.c_int32), ("currentSectorIndex", ctypes.c_int32),
        ("lastSectorTime", ctypes.c_int32), ("numberOfLaps", ctypes.c_int32),
        ("tyreCompound", ctypes.c_wchar * 33), ("replayTimeMultiplier", ctypes.c_float),
        ("normalizedCarPosition", ctypes.c_float), ("carCoordinates", ctypes.c_float * 3),
    ]


class Static(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("smVersion", ctypes.c_wchar * 15), ("acVersion", ctypes.c_wchar * 15),
        ("numberOfSessions", ctypes.c_int32), ("numCars", ctypes.c_int32),
        ("carModel", ctypes.c_wchar * 33), ("track", ctypes.c_wchar * 33),
        ("playerName", ctypes.c_wchar * 33), ("playerSurname", ctypes.c_wchar * 33),
        ("playerNick", ctypes.c_wchar * 33), ("sectorCount", ctypes.c_int32),
    ]


COLS = ["t", "lap", "pos", "speed_kmh", "rpm", "gear", "gas", "brake", "steer",
        "gx", "gy", "gz", "slip_fl", "slip_fr", "slip_rl", "slip_rr",
        "press_fl", "press_fr", "press_rl", "press_rr",
        "ttemp_fl", "ttemp_fr", "ttemp_rl", "ttemp_rr",
        "camber_fl", "camber_fr", "camber_rl", "camber_rr",
        "susp_fl", "susp_fr", "susp_rl", "susp_rr",
        "tc", "abs", "fuel", "inpit", "last_ms", "best_ms", "session", "race_pos",
        "heading", "vel_x", "vel_y", "vel_z",
        "tyres_out", "dirt_fl", "dirt_fr", "dirt_rl", "dirt_rr"]

# AC/ACC session type enum
SESSION_NAMES = {-1: "UNKNOWN", 0: "PRACTICE", 1: "QUALI", 2: "RACE", 3: "HOTLAP",
                 4: "TIMEATK", 5: "DRIFT", 6: "DRAG", 7: "HOTSTINT", 8: "SUPERPOLE"}


def sess_name(v):
    return SESSION_NAMES.get(v, "S{0}".format(v))


def safe(s):
    out = ""
    for ch in (s or ""):
        out += ch if (ch.isalnum() or ch in "._-") else "_"
    return out or "unknown"


def press_fg(v):
    if v <= 1:
        return MUTED
    if 26.5 <= v <= 28.5:
        return GREEN
    return BLUE if v < 26.5 else RED


def temp_fg(v):
    if v <= 1:
        return MUTED
    if 75 <= v <= 95:
        return GREEN
    return BLUE if v < 75 else RED


class App:
    def __init__(self, root):
        self.root = root
        self.maps = []
        self.phys = self.graph = self.stat = None
        self.f = None
        self.w = None
        self.rows = 0
        self.t0 = 0.0
        self.acc = 0.0
        self.stopped = 0.0
        self.prev_pit = True
        self.last_saved = "-"
        self.reattach_t = 0.0
        self.lap_rows = []          # [(lap_no, time_ms, max_kmh), ...] for current stint
        self.prev_completed = -1
        self.cur_max = 0.0
        self._build()
        self._attach()
        self.poll()

    # ---------- UI ----------
    def _lab(self, parent, text, fg=TEXT, font=("Segoe UI", 10), bg=BG):
        l = tk.Label(parent, text=text, fg=fg, bg=bg, font=font)
        return l

    def _tyre_grid(self, parent, title):
        wrap = tk.Frame(parent, bg=BG)
        self._lab(wrap, title, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w")
        grid = tk.Frame(wrap, bg=CARD)
        grid.pack(fill="x", pady=(2, 0))
        cells = []
        for r in range(2):
            for c in range(2):
                cell = tk.Label(grid, text="--", fg=MUTED, bg=CARD,
                                font=("Consolas", 15, "bold"), width=6, pady=6)
                cell.grid(row=r, column=c, padx=1, pady=1, sticky="nsew")
                cells.append(cell)
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)
        return wrap, cells

    def _build(self):
        r = self.root
        r.title("GG Telemetry Logger")
        r.configure(bg=BG)
        r.geometry("330x600")
        r.resizable(False, False)

        self._lab(r, "GG TELEMETRY LOGGER", fg=TEXT, font=("Segoe UI Semibold", 13)).pack(pady=(12, 2))
        self.status = self._lab(r, "○  WAITING FOR SIM", fg=GREY, font=("Segoe UI", 14, "bold"))
        self.status.pack(pady=(0, 6))
        self.carlbl = self._lab(r, "—", fg=MUTED, font=("Segoe UI", 10))
        self.carlbl.pack()
        self.sesslbl = self._lab(r, "", fg=MUTED, font=("Segoe UI", 11, "bold"))
        self.sesslbl.pack()

        mid = tk.Frame(r, bg=BG)
        mid.pack(fill="x", padx=16, pady=10)
        self.metrics = {}
        for i, (key, name) in enumerate([("speed", "SPEED"), ("lap", "LAP"), ("fuel", "FUEL L")]):
            col = tk.Frame(mid, bg=BG)
            col.grid(row=0, column=i, sticky="nsew")
            mid.columnconfigure(i, weight=1)
            self._lab(col, name, fg=MUTED, font=("Segoe UI", 9)).pack()
            v = self._lab(col, "--", fg=TEXT, font=("Consolas", 16, "bold"))
            v.pack()
            self.metrics[key] = v

        tyres = tk.Frame(r, bg=BG)
        tyres.pack(fill="x", padx=16, pady=4)
        pw, self.press_cells = self._tyre_grid(tyres, "TYRE PRESSURE (psi)")
        pw.grid(row=0, column=0, padx=(0, 8), sticky="nsew")
        tw, self.temp_cells = self._tyre_grid(tyres, "TYRE TEMP (C)")
        tw.grid(row=0, column=1, sticky="nsew")
        tyres.columnconfigure(0, weight=1)
        tyres.columnconfigure(1, weight=1)

        self._lab(r, "LAPS  (time · max km/h)", fg=MUTED, font=("Segoe UI", 9)).pack(pady=(12, 2))
        lapcard = tk.Frame(r, bg=CARD)
        lapcard.pack(fill="x", padx=16)
        self.lap_labels = []
        for _ in range(6):
            lab = tk.Label(lapcard, text="", fg=TEXT, bg=CARD, font=("Consolas", 11),
                           anchor="w", padx=8, pady=1)
            lab.pack(fill="x")
            self.lap_labels.append(lab)
        self._refresh_laps()

        self.filelbl = self._lab(r, "file: -", fg=MUTED, font=("Consolas", 9))
        self.filelbl.pack(pady=(12, 0))
        self.savedlbl = self._lab(r, "saved: -", fg=MUTED, font=("Consolas", 9))
        self.savedlbl.pack()

        btns = tk.Frame(r, bg=BG)
        btns.pack(pady=12)
        tk.Button(btns, text="Open folder", command=lambda: os.startfile(OUT_DIR),
                  bg=CARD, fg=TEXT, relief="flat", padx=10, pady=4,
                  activebackground="#2a2f38", activeforeground=TEXT).pack(side="left", padx=4)
        tk.Button(btns, text="Quit", command=self.quit,
                  bg=CARD, fg=TEXT, relief="flat", padx=10, pady=4,
                  activebackground="#2a2f38", activeforeground=TEXT).pack(side="left", padx=4)
        r.protocol("WM_DELETE_WINDOW", self.quit)

    # ---------- shared memory ----------
    def _attach(self):
        for m in self.maps:
            try:
                m.close()
            except Exception:
                pass
        self.maps = []
        try:
            mp = mmap.mmap(-1, ctypes.sizeof(Physics), tagname="acpmf_physics")
            mg = mmap.mmap(-1, ctypes.sizeof(Graphics), tagname="acpmf_graphics")
            ms = mmap.mmap(-1, ctypes.sizeof(Static), tagname="acpmf_static")
            self.maps = [mp, mg, ms]
            self.phys = Physics.from_buffer(mp)
            self.graph = Graphics.from_buffer(mg)
            self.stat = Static.from_buffer(ms)
        except Exception:
            self.phys = self.graph = self.stat = None

    def _valid(self):
        try:
            return bool(self.stat and (self.stat.carModel or "").strip())
        except Exception:
            return False

    # ---------- file ----------
    def _open(self):
        car = safe((self.stat.carModel or "").strip())
        trk = safe((self.stat.track or "").strip())
        day = time.strftime("%Y-%m-%d")
        folder = os.path.join(OUT_DIR, trk, car, day)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        tag = sess_name(self.graph.session)
        path = os.path.join(folder, time.strftime("%H-%M-%S") + "_" + tag + ".csv")
        self.f = open(path, "w", newline="")
        self.w = csv.writer(self.f)
        self.w.writerow(COLS)
        self.rows = 0
        self.t0 = time.perf_counter()
        self.lap_rows = []
        self.prev_completed = -1
        self.cur_max = 0.0
        self._refresh_laps()
        self.filelbl.config(text="file: " + os.path.basename(path))

    def _close(self):
        if self.f is not None:
            try:
                self.f.flush()
                self.last_saved = os.path.basename(self.f.name)
                self.f.close()
                self.savedlbl.config(text="saved: " + self.last_saved)
            except Exception:
                pass
            self.f = None
            self.w = None

    # ---------- loop ----------
    def poll(self):
        now = time.perf_counter()
        if not self._valid():
            if now - self.reattach_t > 1.0:
                self._attach()
                self.reattach_t = now
            self._set_status("○  WAITING FOR SIM", GREY)
            self.carlbl.config(text="start AC / ACC and get on track")
            self.sesslbl.config(text="")
            self._close()
            self.root.after(200, self.poll)
            return

        p, g, s = self.phys, self.graph, self.stat
        in_pit = (g.isInPit == 1)
        live = (g.status == AC_LIVE)
        self.carlbl.config(text="{0}  @  {1}".format((s.carModel or "").strip(), (s.track or "").strip()))

        if in_pit and not self.prev_pit:
            self._close()
        self.prev_pit = in_pit

        if live and not in_pit:
            moving = p.speedKmh >= 5.0
            if moving:
                self.stopped = 0.0
                if self.f is None:
                    self._open()
            else:
                self.stopped += 0.02
                if self.f is not None and self.stopped > 3.0:
                    self._close()  # parked / return-to-garage -> finalize
            if self.f is not None:
                self._write(p, g)
                self._set_status("●  REC", GREEN)
            elif self.last_saved != "-":
                self._set_status("■  PARKED - saved", AMBER)
            else:
                self._set_status("○  READY (drive to start)", GREY)
            self._update_live(p, g)
        elif in_pit:
            self._close()
            self._set_status("■  PIT - saved", AMBER)
        else:
            self._close()
            self._set_status("○  IDLE", GREY)

        self.root.after(20, self.poll)

    def _write(self, p, g):
        self.w.writerow([
            "{0:.3f}".format(time.perf_counter() - self.t0), g.completedLaps, "{0:.5f}".format(g.normalizedCarPosition),
            "{0:.2f}".format(p.speedKmh), p.rpms, p.gear,
            "{0:.3f}".format(p.gas), "{0:.3f}".format(p.brake), "{0:.4f}".format(p.steerAngle),
            "{0:.3f}".format(p.accG[0]), "{0:.3f}".format(p.accG[1]), "{0:.3f}".format(p.accG[2]),
            "{0:.3f}".format(p.wheelSlip[0]), "{0:.3f}".format(p.wheelSlip[1]), "{0:.3f}".format(p.wheelSlip[2]), "{0:.3f}".format(p.wheelSlip[3]),
            "{0:.2f}".format(p.wheelsPressure[0]), "{0:.2f}".format(p.wheelsPressure[1]), "{0:.2f}".format(p.wheelsPressure[2]), "{0:.2f}".format(p.wheelsPressure[3]),
            "{0:.1f}".format(p.tyreCoreTemperature[0]), "{0:.1f}".format(p.tyreCoreTemperature[1]), "{0:.1f}".format(p.tyreCoreTemperature[2]), "{0:.1f}".format(p.tyreCoreTemperature[3]),
            "{0:.4f}".format(p.camberRAD[0]), "{0:.4f}".format(p.camberRAD[1]), "{0:.4f}".format(p.camberRAD[2]), "{0:.4f}".format(p.camberRAD[3]),
            "{0:.4f}".format(p.suspensionTravel[0]), "{0:.4f}".format(p.suspensionTravel[1]), "{0:.4f}".format(p.suspensionTravel[2]), "{0:.4f}".format(p.suspensionTravel[3]),
            "{0:.2f}".format(p.tc), "{0:.2f}".format(p.abs), "{0:.2f}".format(p.fuel), g.isInPit,
            g.iLastTime, g.iBestTime, sess_name(g.session), g.position,
            "{0:.5f}".format(p.heading), "{0:.4f}".format(p.velocity[0]),
            "{0:.4f}".format(p.velocity[1]), "{0:.4f}".format(p.velocity[2]),
            p.numberOfTyresOut,
            "{0:.3f}".format(p.tyreDirtyLevel[0]), "{0:.3f}".format(p.tyreDirtyLevel[1]),
            "{0:.3f}".format(p.tyreDirtyLevel[2]), "{0:.3f}".format(p.tyreDirtyLevel[3]),
        ])
        self.rows += 1
        if self.rows % 50 == 0:
            self.f.flush()

        # --- per-lap time + peak speed ---
        if p.speedKmh > self.cur_max:
            self.cur_max = p.speedKmh
        c = g.completedLaps
        if self.prev_completed < 0:
            self.prev_completed = c
        elif c > self.prev_completed:
            self._add_lap(c, g.iLastTime, self.cur_max)  # the lap just crossed
            self.prev_completed = c
            self.cur_max = 0.0

    @staticmethod
    def _fmt_ms(ms):
        if not (0 < ms < 600000):
            return "--:--.---"
        s = ms / 1000.0
        return "{0:d}:{1:06.3f}".format(int(s) // 60, s - (int(s) // 60) * 60)

    def _add_lap(self, lap_no, time_ms, max_kmh):
        self.lap_rows.append((lap_no, time_ms, max_kmh))
        self._refresh_laps()

    def _refresh_laps(self):
        valid = [t for _, t, _ in self.lap_rows if 0 < t < 600000]
        best = min(valid) if valid else None
        shown = self.lap_rows[-6:]
        for i, lab in enumerate(self.lap_labels):
            if i < len(shown):
                ln, t, spd = shown[i]
                txt = "L{0:<3} {1:>9}  {2:3.0f} km/h".format(ln, self._fmt_ms(t), spd)
                fg = GREEN if (best is not None and t == best) else TEXT
                lab.config(text=txt, fg=fg)
            elif i == 0 and not shown:
                lab.config(text="(no completed laps yet)", fg=MUTED)
            else:
                lab.config(text="")

    def _update_live(self, p, g):
        if g.session in (1, 2) and g.position > 0:   # quali / race -> show place
            self.sesslbl.config(text="{0}  ·  P{1}".format(sess_name(g.session), g.position), fg=AMBER)
        else:
            self.sesslbl.config(text=sess_name(g.session), fg=MUTED)
        self.metrics["speed"].config(text="{0:.0f}".format(p.speedKmh))
        self.metrics["lap"].config(text=str(g.completedLaps))
        self.metrics["fuel"].config(text="{0:.1f}".format(p.fuel))
        for i in range(4):
            v = p.wheelsPressure[i]
            self.press_cells[i].config(text="{0:.1f}".format(v), fg=press_fg(v))
            t = p.tyreCoreTemperature[i]
            self.temp_cells[i].config(text="{0:.0f}".format(t), fg=temp_fg(t))
        self.filelbl.config(text="file: ...  rows: {0}".format(self.rows))

    def _set_status(self, text, color):
        self.status.config(text=text, fg=color)

    def quit(self):
        self._close()
        self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
