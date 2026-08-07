"""Shared memory access for Assetto Corsa and Assetto Corsa Competizione.

Both games publish the same mapping names (acpmf_physics / acpmf_graphics /
acpmf_static) and share a common field prefix, but they diverge after it and ACC
leaves a number of AC fields unpopulated. So the game is identified first — by
process name, which is the only unambiguous source — and only then are the
matching structures mapped.

Field order, types and the "not used in ACC" notes come from the official Kunos
shared memory documentation cross-checked against PyAccSharedMemory; see
docs/reference/acc-shared-memory.md. Do not reorder anything here: every field
below is a byte offset for the fields after it, including the ones we never read.
"""

import ctypes
import mmap

AC = "AC"
ACC = "ACC"

STATUS_LIVE = 2

# AC publishes no lap-validity flag, so a cut is derived from wheels off track.
# Four is the standard AC/ACC rule; Real Penalty expresses the same thing as
# "wheels out permitted" and defaults to allowing two.
WHEELS_OUT_FOR_CUT = 4

# ACC first: if both are somehow running they fight over the same mapping names,
# so the choice must at least be deterministic. ACC is the less likely of the two
# to be sitting idle in the background.
_PROCESS_NAMES = [
    ("ac2-win64-shipping.exe", ACC),
    ("acs.exe", AC),
    ("acs_x86.exe", AC),
]

SESSION_NAMES = {-1: "UNKNOWN", 0: "PRACTICE", 1: "QUALI", 2: "RACE", 3: "HOTLAP",
                 4: "TIMEATK", 5: "DRIFT", 6: "DRAG", 7: "HOTSTINT", 8: "SUPERPOLE"}


def sess_name(v):
    return SESSION_NAMES.get(v, "S{0}".format(v))


# ---------------------------------------------------------------- game detection

def game_for_processes(names):
    """Map a set of running process names to a game. Pure, so it is testable."""
    lowered = set(n.lower() for n in names)
    for exe, game in _PROCESS_NAMES:
        if exe in lowered:
            return game
    return None


TH32CS_SNAPPROCESS = 0x00000002
_INVALID_HANDLE = ctypes.c_void_p(-1).value


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_ulong), ("cntUsage", ctypes.c_ulong),
        ("th32ProcessID", ctypes.c_ulong),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),  # ULONG_PTR
        ("th32ModuleID", ctypes.c_ulong), ("cntThreads", ctypes.c_ulong),
        ("th32ParentProcessID", ctypes.c_ulong), ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.c_ulong), ("szExeFile", ctypes.c_wchar * 260),
    ]


def running_process_names():
    k = ctypes.windll.kernel32
    snap = k.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == _INVALID_HANDLE:
        return []
    names = []
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
        ok = k.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            names.append(entry.szExeFile)
            ok = k.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k.CloseHandle(snap)
    return names


def detect_game():
    """"AC", "ACC", or None when neither is running."""
    try:
        return game_for_processes(running_process_names())
    except Exception:
        return None


# -------------------------------------------------------------------- structures

class ACPhysics(ctypes.Structure):
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
        ("numberOfTyresOut", ctypes.c_int32), ("pitLimiterOn", ctypes.c_int32),
        ("abs", ctypes.c_float),
        # --- padding fields, never read, present only to reach clutch ---
        ("kersCharge", ctypes.c_float), ("kersInput", ctypes.c_float),
        ("autoShifterOn", ctypes.c_int32), ("rideHeight", ctypes.c_float * 2),
        ("turboBoost", ctypes.c_float), ("ballast", ctypes.c_float),
        ("airDensity", ctypes.c_float), ("airTemp", ctypes.c_float),
        ("roadTemp", ctypes.c_float), ("localAngularVel", ctypes.c_float * 3),
        ("finalFF", ctypes.c_float), ("performanceMeter", ctypes.c_float),
        ("engineBrake", ctypes.c_int32), ("ersRecoveryLevel", ctypes.c_int32),
        ("ersPowerLevel", ctypes.c_int32), ("ersHeatCharging", ctypes.c_int32),
        ("ersIsCharging", ctypes.c_int32), ("kersCurrentKJ", ctypes.c_float),
        ("drsAvailable", ctypes.c_int32), ("drsEnabled", ctypes.c_int32),
        ("brakeTemp", ctypes.c_float * 4),
        # --- wanted ---
        ("clutch", ctypes.c_float),
    ]


class ACCPhysics(ctypes.Structure):
    """Identical to AC up to clutch; declared further only to reach brakeTemp.

    drs is an int here (AC declares it float) — same 4 bytes, so nothing shifts.
    """
    _pack_ = 4
    _fields_ = [
        ("packetId", ctypes.c_int32), ("gas", ctypes.c_float), ("brake", ctypes.c_float),
        ("fuel", ctypes.c_float), ("gear", ctypes.c_int32), ("rpms", ctypes.c_int32),
        ("steerAngle", ctypes.c_float), ("speedKmh", ctypes.c_float),
        ("velocity", ctypes.c_float * 3), ("accG", ctypes.c_float * 3),
        ("wheelSlip", ctypes.c_float * 4),
        ("wheelLoad", ctypes.c_float * 4),            # not used in ACC
        ("wheelsPressure", ctypes.c_float * 4), ("wheelAngularSpeed", ctypes.c_float * 4),
        ("tyreWear", ctypes.c_float * 4),             # not used in ACC
        ("tyreDirtyLevel", ctypes.c_float * 4),       # not used in ACC
        ("tyreCoreTemperature", ctypes.c_float * 4),
        ("camberRAD", ctypes.c_float * 4),            # not used in ACC
        ("suspensionTravel", ctypes.c_float * 4),
        ("drs", ctypes.c_int32),                      # not used in ACC
        ("tc", ctypes.c_float),
        ("heading", ctypes.c_float), ("pitch", ctypes.c_float), ("roll", ctypes.c_float),
        ("cgHeight", ctypes.c_float),                 # not used in ACC
        ("carDamage", ctypes.c_float * 5),
        ("numberOfTyresOut", ctypes.c_int32),         # not used in ACC
        ("pitLimiterOn", ctypes.c_int32),
        ("abs", ctypes.c_float),
        # --- padding fields, never read, present only to keep offsets right ---
        ("kersCharge", ctypes.c_float), ("kersInput", ctypes.c_float),
        ("autoShifterOn", ctypes.c_int32), ("rideHeight", ctypes.c_float * 2),
        ("turboBoost", ctypes.c_float), ("ballast", ctypes.c_float),
        ("airDensity", ctypes.c_float), ("airTemp", ctypes.c_float),
        ("roadTemp", ctypes.c_float), ("localAngularVel", ctypes.c_float * 3),
        ("finalFF", ctypes.c_float), ("performanceMeter", ctypes.c_float),
        ("engineBrake", ctypes.c_int32), ("ersRecoveryLevel", ctypes.c_int32),
        ("ersPowerLevel", ctypes.c_int32), ("ersHeatCharging", ctypes.c_int32),
        ("ersIsCharging", ctypes.c_int32), ("kersCurrentKJ", ctypes.c_float),
        ("drsAvailable", ctypes.c_int32), ("drsEnabled", ctypes.c_int32),
        # --- wanted ---
        ("brakeTemp", ctypes.c_float * 4),
        ("clutch", ctypes.c_float),
    ]


class ACGraphics(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("packetId", ctypes.c_int32), ("status", ctypes.c_int32), ("session", ctypes.c_int32),
        ("currentTime", ctypes.c_wchar * 15), ("lastTime", ctypes.c_wchar * 15),
        ("bestTime", ctypes.c_wchar * 15), ("split", ctypes.c_wchar * 15),
        ("completedLaps", ctypes.c_int32), ("position", ctypes.c_int32),
        ("iCurrentTime", ctypes.c_int32), ("iLastTime", ctypes.c_int32),
        ("iBestTime", ctypes.c_int32),
        ("sessionTimeLeft", ctypes.c_float), ("distanceTraveled", ctypes.c_float),
        ("isInPit", ctypes.c_int32), ("currentSectorIndex", ctypes.c_int32),
        ("lastSectorTime", ctypes.c_int32), ("numberOfLaps", ctypes.c_int32),
        ("tyreCompound", ctypes.c_wchar * 33), ("replayTimeMultiplier", ctypes.c_float),
        ("normalizedCarPosition", ctypes.c_float), ("carCoordinates", ctypes.c_float * 3),
    ]


class ACCGraphics(ctypes.Structure):
    """Identical to AC up to normalizedCarPosition, then ACC's own tail."""
    _pack_ = 4
    _fields_ = [
        ("packetId", ctypes.c_int32), ("status", ctypes.c_int32), ("session", ctypes.c_int32),
        ("currentTime", ctypes.c_wchar * 15), ("lastTime", ctypes.c_wchar * 15),
        ("bestTime", ctypes.c_wchar * 15), ("split", ctypes.c_wchar * 15),
        ("completedLaps", ctypes.c_int32), ("position", ctypes.c_int32),
        ("iCurrentTime", ctypes.c_int32), ("iLastTime", ctypes.c_int32),
        ("iBestTime", ctypes.c_int32),
        ("sessionTimeLeft", ctypes.c_float), ("distanceTraveled", ctypes.c_float),
        ("isInPit", ctypes.c_int32), ("currentSectorIndex", ctypes.c_int32),
        ("lastSectorTime", ctypes.c_int32), ("numberOfLaps", ctypes.c_int32),
        ("tyreCompound", ctypes.c_wchar * 33), ("replayTimeMultiplier", ctypes.c_float),
        ("normalizedCarPosition", ctypes.c_float),
        ("activeCars", ctypes.c_int32),
        ("carCoordinates", ctypes.c_float * (60 * 3)), ("carID", ctypes.c_int32 * 60),
        ("playerCarID", ctypes.c_int32), ("penaltyTime", ctypes.c_float),
        ("flag", ctypes.c_int32), ("penalty", ctypes.c_int32),
        # --- wanted ---
        ("idealLineOn", ctypes.c_int32), ("isInPitLane", ctypes.c_int32),
        ("surfaceGrip", ctypes.c_float),
        # --- padding fields, never read, present only to keep offsets right ---
        ("mandatoryPitDone", ctypes.c_int32),
        ("windSpeed", ctypes.c_float), ("windDirection", ctypes.c_float),
        ("isSetupMenuVisible", ctypes.c_int32), ("mainDisplayIndex", ctypes.c_int32),
        ("secondaryDisplayIndex", ctypes.c_int32), ("TC", ctypes.c_int32),
        ("TCCut", ctypes.c_int32), ("engineMap", ctypes.c_int32), ("ABS", ctypes.c_int32),
        # --- wanted ---
        ("fuelXLap", ctypes.c_float),
        # --- padding ---
        ("rainLights", ctypes.c_int32), ("flashingLights", ctypes.c_int32),
        ("lightsStage", ctypes.c_int32), ("exhaustTemperature", ctypes.c_float),
        ("wiperLV", ctypes.c_int32), ("driverStintTotalTimeLeft", ctypes.c_int32),
        ("driverStintTimeLeft", ctypes.c_int32), ("rainTyres", ctypes.c_int32),
        ("sessionIndex", ctypes.c_int32), ("usedFuel", ctypes.c_float),
        ("deltaLapTime", ctypes.c_wchar * 15), ("iDeltaLapTime", ctypes.c_int32),
        ("estimatedLapTime", ctypes.c_wchar * 15), ("iEstimatedLapTime", ctypes.c_int32),
        ("isDeltaPositive", ctypes.c_int32), ("iSplit", ctypes.c_int32),
        # --- wanted ---
        ("isValidLap", ctypes.c_int32), ("fuelEstimatedLaps", ctypes.c_float),
    ]


class Static(ctypes.Structure):
    """Prefix is identical in both games and the logger only reads carModel/track."""
    _pack_ = 4
    _fields_ = [
        ("smVersion", ctypes.c_wchar * 15), ("acVersion", ctypes.c_wchar * 15),
        ("numberOfSessions", ctypes.c_int32), ("numCars", ctypes.c_int32),
        ("carModel", ctypes.c_wchar * 33), ("track", ctypes.c_wchar * 33),
        ("playerName", ctypes.c_wchar * 33), ("playerSurname", ctypes.c_wchar * 33),
        ("playerNick", ctypes.c_wchar * 33), ("sectorCount", ctypes.c_int32),
    ]


# ----------------------------------------------------------------------- columns

CORE_COLS = ["t", "lap", "pos", "speed_kmh", "rpm", "gear", "gas", "brake", "clutch", "steer",
             "gx", "gy", "gz", "slip_fl", "slip_fr", "slip_rl", "slip_rr",
             "press_fl", "press_fr", "press_rl", "press_rr",
             "ttemp_fl", "ttemp_fr", "ttemp_rl", "ttemp_rr",
             "susp_fl", "susp_fr", "susp_rl", "susp_rr",
             "tc", "abs", "fuel", "inpit", "last_ms", "best_ms", "session", "race_pos",
             "heading", "vel_x", "vel_y", "vel_z"]

AC_EXTRA_COLS = ["camber_fl", "camber_fr", "camber_rl", "camber_rr",
                 "dirt_fl", "dirt_fr", "dirt_rl", "dirt_rr", "tyres_out", "drs"]

# No in_pitlane column on purpose: the file is finalized the moment the pit lane
# is entered, so no row with in_pitlane=1 can ever be written. Confirmed on a live
# session before it was dropped.
ACC_EXTRA_COLS = ["btemp_fl", "btemp_fr", "btemp_rl", "btemp_rr",
                  "ideal_line", "valid_lap", "fuel_x_lap", "fuel_est_laps"]


def cols_for(game):
    return CORE_COLS + (AC_EXTRA_COLS if game == AC else ACC_EXTRA_COLS)


def _f(v, nd=3):
    return "{0:.{1}f}".format(v, nd)


def _f4(arr, nd=3):
    return [_f(arr[i], nd) for i in range(4)]


# ------------------------------------------------------------------------ reader

class SimReader:
    """Owns the mappings for one game and turns them into CSV rows.

    Everything game-specific lives here so the UI never branches on the game
    except for the NeckFX block.
    """

    def __init__(self, game):
        self.game = game
        self.cols = cols_for(game)
        self._phys_t = ACPhysics if game == AC else ACCPhysics
        self._graph_t = ACGraphics if game == AC else ACCGraphics
        self.maps = []
        self.phys = self.graph = self.stat = None

    def attach(self):
        self.close()
        try:
            mp = mmap.mmap(-1, ctypes.sizeof(self._phys_t), tagname="acpmf_physics")
            mg = mmap.mmap(-1, ctypes.sizeof(self._graph_t), tagname="acpmf_graphics")
            ms = mmap.mmap(-1, ctypes.sizeof(Static), tagname="acpmf_static")
            self.maps = [mp, mg, ms]
            self.phys = self._phys_t.from_buffer(mp)
            self.graph = self._graph_t.from_buffer(mg)
            self.stat = Static.from_buffer(ms)
        except Exception:
            self.close()

    def close(self):
        # ctypes views must go before the mmaps they point into, or closing raises
        self.phys = self.graph = self.stat = None
        for m in self.maps:
            try:
                m.close()
            except Exception:
                pass
        self.maps = []

    def valid(self):
        try:
            return bool(self.stat and (self.stat.carModel or "").strip())
        except Exception:
            return False

    def live(self):
        return bool(self.graph and self.graph.status == STATUS_LIVE)

    def in_pit_for_finalize(self):
        """AC: isInPit. ACC: isInPitLane — there isInPit only means "in the box",
        so the file would stay open for the whole pit lane."""
        g = self.graph
        if self.game == AC:
            return g.isInPit == 1
        return g.isInPitLane == 1

    def lap_invalid_now(self):
        """True while the current lap is being spoiled — latch this over the lap.

        ACC hands us its own verdict. AC has no validity field, so it is derived
        from wheels off track, which is the same input Real Penalty's cutting
        system uses (its "wheels out permitted" setting). Four wheels off is the
        standard AC/ACC rule.
        """
        if self.game == AC:
            return self.phys.numberOfTyresOut >= WHEELS_OUT_FOR_CUT
        return self.graph.isValidLap == 0

    def row(self, t):
        p, g = self.phys, self.graph
        out = [_f(t, 3), g.completedLaps, _f(g.normalizedCarPosition, 5),
               _f(p.speedKmh, 2), p.rpms, p.gear,
               _f(p.gas), _f(p.brake), _f(p.clutch), _f(p.steerAngle, 4),
               _f(p.accG[0]), _f(p.accG[1]), _f(p.accG[2])]
        out += _f4(p.wheelSlip)
        out += _f4(p.wheelsPressure, 2)
        out += _f4(p.tyreCoreTemperature, 1)
        out += _f4(p.suspensionTravel, 4)
        out += [_f(p.tc, 2), _f(p.abs, 2), _f(p.fuel, 2), g.isInPit,
                g.iLastTime, g.iBestTime, sess_name(g.session), g.position,
                _f(p.heading, 5), _f(p.velocity[0], 4), _f(p.velocity[1], 4),
                _f(p.velocity[2], 4)]
        if self.game == AC:
            out += _f4(p.camberRAD, 4)
            out += _f4(p.tyreDirtyLevel)
            out += [p.numberOfTyresOut, _f(p.drs, 2)]
        else:
            out += _f4(p.brakeTemp, 1)
            out += [g.idealLineOn, g.isValidLap,
                    _f(g.fuelXLap, 3), _f(g.fuelEstimatedLaps, 2)]
        return out
