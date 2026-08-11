"""StintLogger - telemetry logger for Assetto Corsa and ACC.

GUI, Python 3 + tkinter, stdlib only (pystray/PIL optional, for the tray icon).

Detects which sim is running (Assetto Corsa or ACC) and logs a CSV per stint to
this folder, with the column set that matches the game — see sim_shm.py. The CSV
is FINALIZED (closed) on pit entry or when you leave the track, so it can be read
without quitting the sim. Double-click to run.

NeckFX is a Custom Shaders Patch feature and therefore exists in AC only; its
block is hidden while ACC is running, and also hidden by default in AC - toggle
"Show NeckFX button" in the tray menu to reveal it (remembered in logger.cfg).
Everything else is the same in both games.
"""

import os
import sys
import re
import json
import time
import csv
import ctypes
import shutil
import threading
import winreg
import tkinter as tk

import sim_shm
from sim_shm import ACC
from fuel_model import FuelModel

try:
    import pystray
    from PIL import Image, ImageDraw
    HAS_TRAY = True
except Exception:
    HAS_TRAY = False

APP_NAME = "StintLogger"        # window title: also the single-instance key
APP_REG_NAME = "StintLogger"   # HKCU Run entry name
APP_VERSION = "1.1.0"           # NeckFX OFF fix + tray toggle for the button

def _writable(path):
    probe = os.path.join(path, ".stintlogger_write_test")
    try:
        with open(probe, "w"):
            pass
        os.remove(probe)
        return True
    except Exception:
        return False


def _out_dir():
    """Logs go next to the program, which is what a portable tool should do.

    Except when that folder is read-only — dropping the exe into Program Files
    is a normal thing for someone to try, and there the first makedirs would
    raise on every poll. Fall back to Documents instead of failing.
    """
    home = os.path.dirname(sys.executable if getattr(sys, "frozen", False)
                           else os.path.abspath(__file__))
    if _writable(home):
        return home
    docs = os.path.join(os.path.expanduser("~"), "Documents", APP_NAME)
    try:
        os.makedirs(docs, exist_ok=True)
    except Exception:
        pass
    return docs if _writable(docs) else home


OUT_DIR = _out_dir()

CFG_PATH = os.path.join(OUT_DIR, "logger.cfg")
DEFAULT_PLAN_MIN = 30

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


def fmt_ms(ms):
    if not (0 < ms < 600000):
        return "--:--.---"
    s = ms / 1000.0
    return "{0:d}:{1:06.3f}".format(int(s) // 60, s - (int(s) // 60) * 60)


def _load_cfg():
    try:
        with open(CFG_PATH, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_cfg(updates):
    # read-modify-write on the whole file: a plain json.dump(updates) would
    # silently drop every other setting logger.cfg holds
    d = _load_cfg()
    d.update(updates)
    try:
        with open(CFG_PATH, "w", encoding="utf-8") as fh:
            json.dump(d, fh)
    except Exception:
        pass


def load_plan_minutes():
    try:
        v = int(_load_cfg().get("plan_minutes", DEFAULT_PLAN_MIN))
        return v if 1 <= v <= 600 else DEFAULT_PLAN_MIN
    except Exception:
        return DEFAULT_PLAN_MIN


def save_plan_minutes(v):
    _save_cfg({"plan_minutes": v})


def load_neckfx_visible():
    return bool(_load_cfg().get("neckfx_visible", False))


def save_neckfx_visible(v):
    _save_cfg({"neckfx_visible": bool(v)})


# ---- NeckFX preset switching (edits assettocorsa/extension/config/neck.ini) ----
NECKFX_PRESETS = {
    "OFF": {
        ("BASIC", "ENABLED"): "0",  # takes full effect on session reload
        # zero the movement so it also goes neutral live (ENABLED flag isn't hot-reloaded);
        # SCRIPT must go off too, or its cockpit-camera script keeps driving the head
        # and ignores ALIGNMENT_BASE entirely (neck.ini marks those keys "hidden with
        # SCRIPT/ENABLED") - this is why OFF used to look applied but not turn anything off
        ("SCRIPT", "ENABLED"): "0",
        ("ALIGNMENT_BASE", "ALIGN_WITH_VELOCITY"): "0.0",
        ("ALIGNMENT_BASE", "ALIGN_WITH_STEERING"): "0.0",
        ("ALIGNMENT_BASE", "HORIZON_LOCK"): "0.0",
        ("ALIGNMENT_BASE", "G_TILT_X"): "0.0",
        ("ALIGNMENT_BASE", "G_TILT_Z"): "0.0",
        ("LOOKAHEAD", "GAIN"): "0.0",
    },
    "DRIFT": {
        ("BASIC", "ENABLED"): "1",
        ("SCRIPT", "ENABLED"): "0",  # use base sections so values below apply predictably
        ("ALIGNMENT_BASE", "ALIGN_WITH_VELOCITY"): "0.6",
        ("ALIGNMENT_BASE", "ALIGN_WITH_STEERING"): "0.0",
        ("ALIGNMENT_BASE", "HORIZON_LOCK"): "0.2",
        ("LOOKAHEAD", "GAIN"): "0.3",
    },
    "GRIP": {
        ("BASIC", "ENABLED"): "1",
        ("SCRIPT", "ENABLED"): "0",
        ("ALIGNMENT_BASE", "ALIGN_WITH_VELOCITY"): "0.4",
        ("ALIGNMENT_BASE", "ALIGN_WITH_STEERING"): "0.2",
        ("ALIGNMENT_BASE", "HORIZON_LOCK"): "0.3",
        ("LOOKAHEAD", "GAIN"): "0.6",
    },
}
# MINE is deliberately not a preset: its values are not a table, they are the
# neck.ini the user had before we ever touched it (kept in the .ggbak snapshot).
NECK_MINE = "MINE"
NECKFX_CYCLE = [NECK_MINE, "OFF", "DRIFT", "GRIP"]
_KEY_RE = re.compile(r'^(\s*)([A-Za-z0-9_]+)(\s*)=(\s*)([^;\r\n]*?)(\s*)(;.*)?$')


def _find_ac_root():
    steam_dirs = [r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"]
    for sd in list(steam_dirs):
        vdf = os.path.join(sd, "steamapps", "libraryfolders.vdf")
        try:
            with open(vdf, "r", encoding="utf-8", errors="replace") as fh:
                txt = fh.read()
            for m in re.finditer(r'"path"\s*"([^"]+)"', txt):
                steam_dirs.append(m.group(1).replace("\\\\", "\\"))
        except Exception:
            pass
    for sd in steam_dirs:
        p = os.path.join(sd, "steamapps", "common", "assettocorsa")
        if os.path.isdir(p):
            return p
    return None


AC_ROOT = _find_ac_root()
NECK_INI = os.path.join(AC_ROOT, "extension", "config", "neck.ini") if AC_ROOT else None


def _read_keys(path, keys):
    got = {}
    section = None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                s = line.strip()
                if s.startswith("[") and s.endswith("]"):
                    section = s[1:-1]
                    continue
                m = _KEY_RE.match(line)
                if m and section is not None and (section, m.group(2)) in keys:
                    got[(section, m.group(2))] = m.group(5)
    except Exception:
        pass
    return got


def _same_value(a, b):
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return a.strip() == b.strip()


def read_neck_mode(path):
    """Which of our presets the file is, or MINE when it is anything else.

    Guessing the mode from a couple of keys labelled a stranger's own config as
    one of ours, and then the first click silently replaced their values.
    """
    if not path or not os.path.exists(path):
        return "OFF"
    for name, changes in NECKFX_PRESETS.items():
        got = _read_keys(path, set(changes))
        if len(got) == len(changes) and all(_same_value(got[k], v) for k, v in changes.items()):
            return name
    return NECK_MINE


def backup_neck_once(path):
    bak = path + ".ggbak"
    if not os.path.exists(bak):
        shutil.copy2(path, bak)


def restore_neck_ini(path):
    """Put the pre-first-edit snapshot back as a whole file.

    Copying the file beats merging keys back: only this returns sections we have
    no preset for at all — a script-driven NeckFX setup, above all.

    False means there is no snapshot, i.e. we never edited anything and the file
    on disk already is the user's own.
    """
    bak = path + ".ggbak"
    if not os.path.exists(bak):
        return False
    shutil.copy2(bak, path)
    return True


def patch_neck_ini(path, preset_name):
    """Apply a preset, adding whatever the file does not already have.

    Replacing only the keys that happen to exist applied a preset half way and
    said nothing about it: a CSP build without [LOOKAHEAD] would answer a click
    on DRIFT with something that is not DRIFT.
    """
    changes = NECKFX_PRESETS[preset_name]
    # newline="" or universal newlines hands us "\n" for a CRLF file and every
    # save would quietly convert the user's file to LF
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as fh:
        raw = fh.read()
    nl = "\r\n" if "\r\n" in raw else "\n"
    lines = raw.replace("\r\n", "\n").split("\n")

    # blocks of (section, its lines including the header) — a key belongs to the
    # last header above it, so this is the unit both edits and inserts work on
    blocks = [(None, [])]
    for line in lines:
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            blocks.append((s[1:-1], [line]))
        else:
            blocks[-1][1].append(line)

    done = set()
    for section, body in blocks:
        for i, line in enumerate(body):
            m = _KEY_RE.match(line)
            if not m or (section, m.group(2)) not in changes:
                continue
            key = (section, m.group(2))
            comment = m.group(7) or ""
            body[i] = "{0}{1}={2}".format(m.group(1), m.group(2), changes[key])
            if comment:
                body[i] += " " + comment
            done.add(key)

    for section, body in blocks:
        missing = [k for k in changes if k[0] == section and k not in done]
        at = len(body)
        while at > 1 and not body[at - 1].strip():
            at -= 1  # before the blank line that separates us from the next section
        for key in missing:
            body.insert(at, "{0}={1}".format(key[1], changes[key]))
            at += 1
            done.add(key)

    out = [line for _, body in blocks for line in body]
    for section in dict.fromkeys(k[0] for k in changes if k not in done):
        out += ["", "[" + section + "]"]
        out += ["{0}={1}".format(k[1], v) for k, v in changes.items()
                if k[0] == section and k not in done]
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(nl.join(out))


# ---- Autostart at login (HKCU Run key; not a service) ----
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _startup_command():
    if getattr(sys, "frozen", False):
        return '"{0}" --tray'.format(sys.executable)
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return '"{0}" "{1}" --tray'.format(pyw, os.path.abspath(__file__))


def is_autostart():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_REG_NAME)
        return True
    except Exception:
        return False


def set_autostart(on):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, APP_REG_NAME, 0, winreg.REG_SZ, _startup_command())
            else:
                try:
                    winreg.DeleteValue(k, APP_REG_NAME)
                except FileNotFoundError:
                    pass
    except Exception:
        pass


class App:
    def __init__(self, root):
        self.root = root
        self.game = None            # None until a sim process shows up
        self.reader = None
        self.f = None
        self.w = None
        self.rows = 0
        self.t0 = 0.0
        self.acc = 0.0
        self.stopped = 0.0
        self.prev_pit = True
        self.last_saved = "-"
        self.reattach_t = 0.0
        self.game_check_t = 0.0
        self.session_key = None
        self.lap_rows = []          # [(seq, lap_no, time_ms, max_kmh, valid, log_tag), ...]
        # The game restarts its lap counter on every stint, so it cannot identify a
        # lap within a session. `seq` can, and that is what the fuel model selects on.
        self.lap_seq = 0
        self.log_tag = "-"
        self.row_seq = []           # listbox row -> lap seq (None on a separator row)
        self.prev_completed = -1
        self.cur_max = 0.0
        self.lap_had_pit = False
        self.lap_invalid = False    # latched: set the moment the game says invalid
        self.fuel = FuelModel()
        self.last_fuel = None       # last seen telemetry, kept so the fuel block can
        self.last_session_ms = None # be repainted while parked (e.g. plan edited)
        self.neck_mode = read_neck_mode(NECK_INI)
        self.neckfx_visible = load_neckfx_visible()
        self.tray = None
        self._build()
        self._setup_tray()
        if HAS_TRAY and "--tray" in sys.argv:
            self.root.withdraw()
        self._apply_game(sim_shm.detect_game())
        self.poll()

    # ---------- UI ----------
    def _lab(self, parent, text, fg=TEXT, font=("Segoe UI", 10), bg=BG):
        return tk.Label(parent, text=text, fg=fg, bg=bg, font=font)

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

    def _fuel_row(self, parent, r, name):
        self._lab(parent, name, fg=MUTED, font=("Segoe UI", 9), bg=CARD).grid(
            row=r, column=0, sticky="w", padx=8, pady=1)
        val = tk.Label(parent, text="--", fg=TEXT, bg=CARD, font=("Consolas", 11, "bold"))
        val.grid(row=r, column=1, sticky="e", padx=8, pady=1)
        return val

    def _build(self):
        r = self.root
        r.title(APP_NAME)
        r.configure(bg=BG)
        r.resizable(False, False)

        self.title_lab = self._lab(r, "ASSETTO CORSA LOGGER", fg=TEXT,
                                   font=("Segoe UI Semibold", 13))
        self.title_lab.pack(pady=(12, 2))
        self.status = self._lab(r, "○  WAITING FOR SIM", fg=GREY, font=("Segoe UI", 14, "bold"))
        self.status.pack(pady=(0, 6))
        self.carlbl = self._lab(r, "—", fg=MUTED, font=("Segoe UI", 10))
        self.carlbl.pack()
        self.sesslbl = self._lab(r, "", fg=MUTED, font=("Segoe UI", 11, "bold"))
        self.sesslbl.pack()

        mid = tk.Frame(r, bg=BG)
        mid.pack(fill="x", padx=16, pady=10)
        self.metrics = {}
        for i, (key, name) in enumerate([("lap", "LAP"), ("fuel", "FUEL L"), ("llap", "L / LAP")]):
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
        # Listbox rather than a row of labels: it scrolls, and unlike a Canvas it
        # still gives per-row colour, which the red/green lap marking needs.
        self.lap_scroll = tk.Scrollbar(lapcard, orient="vertical", width=10,
                                       relief="flat", borderwidth=0,
                                       troughcolor=CARD, bg=GREY, activebackground=MUTED)
        # selectmode "extended": picking the laps the fuel average runs on is the
        # whole point of the list now, so the selection has to be visible and multi-row
        self.lap_list = tk.Listbox(lapcard, height=6, bg=CARD, fg=TEXT,
                                   font=("Consolas", 11), activestyle="none",
                                   highlightthickness=0, borderwidth=0,
                                   selectmode="extended", exportselection=False,
                                   selectbackground=BG, selectforeground=TEXT,
                                   yscrollcommand=self.lap_scroll.set)
        self.lap_scroll.config(command=self.lap_list.yview)
        self.lap_list.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=2)
        self.lap_scroll.pack(side="right", fill="y")
        self.lap_list.bind("<<ListboxSelect>>", self._on_lap_select)
        self.lap_list.bind("<Escape>", self._clear_lap_select)
        self.root.bind("<Escape>", self._clear_lap_select)
        self.fuel_src = self._lab(r, "fuel: last 3 valid laps", fg=MUTED,
                                  font=("Segoe UI", 9))
        self.fuel_src.pack(pady=(2, 0))
        self._refresh_laps()

        self._lab(r, "FUEL PLAN", fg=MUTED, font=("Segoe UI", 9)).pack(pady=(12, 2))
        fuelcard = tk.Frame(r, bg=CARD)
        fuelcard.pack(fill="x", padx=16)
        fuelcard.columnconfigure(1, weight=1)
        self.fuel_left = self._fuel_row(fuelcard, 0, "LAPS LEFT")
        self.fuel_end = self._fuel_row(fuelcard, 1, "TO SESSION END")
        planwrap = tk.Frame(fuelcard, bg=CARD)
        planwrap.grid(row=2, column=0, sticky="w", padx=8, pady=1)
        self._lab(planwrap, "PLAN", fg=MUTED, font=("Segoe UI", 9), bg=CARD).pack(side="left")
        self.plan_var = tk.StringVar(value=str(load_plan_minutes()))
        self.plan_entry = tk.Entry(planwrap, textvariable=self.plan_var, width=4,
                                   justify="center", bg=BG, fg=TEXT,
                                   insertbackground=TEXT, relief="flat",
                                   font=("Consolas", 10))
        self.plan_entry.pack(side="left", padx=4)
        self.plan_entry.bind("<Return>", lambda e: self._save_plan())
        self.plan_entry.bind("<FocusOut>", lambda e: self._save_plan(defocus=False))
        # Labels and frames never take focus in Tk, so clicking "outside" the entry
        # would otherwise leave the caret sitting in it forever.
        r.bind_all("<Button-1>", self._click_defocus, add="+")
        self._lab(planwrap, "min", fg=MUTED, font=("Segoe UI", 9), bg=CARD).pack(side="left")
        self.fuel_plan = tk.Label(fuelcard, text="--", fg=TEXT, bg=CARD,
                                  font=("Consolas", 11, "bold"))
        self.fuel_plan.grid(row=2, column=1, sticky="e", padx=8, pady=1)

        self.filelbl = self._lab(r, "file: -", fg=MUTED, font=("Consolas", 9))
        self.filelbl.pack(pady=(12, 0))
        self.savedlbl = self._lab(r, "saved: -", fg=MUTED, font=("Consolas", 9))
        self.savedlbl.pack()

        self.btns = tk.Frame(r, bg=BG)
        self.neckwrap = tk.Frame(r, bg=BG)
        self.neck_btn = tk.Button(self.neckwrap, text="NeckFX: OFF", command=self.cycle_neck,
                                  bg=CARD, fg=GREY, relief="flat", padx=12, pady=4, width=16,
                                  activebackground="#2a2f38", activeforeground=TEXT)
        self.neck_btn.pack()
        self.neckhint = self._lab(self.neckwrap, "", fg=MUTED, font=("Segoe UI", 8))
        self.neckhint.pack()
        # not packed here: _apply_game() decides on first call, from neckfx_visible + game

        self.btns.pack(pady=12)
        tk.Button(self.btns, text="Open folder", command=lambda: os.startfile(OUT_DIR),
                  bg=CARD, fg=TEXT, relief="flat", padx=10, pady=4,
                  activebackground="#2a2f38", activeforeground=TEXT).pack(side="left", padx=4)
        tk.Button(self.btns, text="Quit", command=self.quit,
                  bg=CARD, fg=TEXT, relief="flat", padx=10, pady=4,
                  activebackground="#2a2f38", activeforeground=TEXT).pack(side="left", padx=4)
        self._paint_neck()
        r.protocol("WM_DELETE_WINDOW", self.on_close)

    def _fit(self):
        """Height follows the layout instead of a hardcoded number, so hiding the
        NeckFX block cannot clip the window or leave a gap."""
        self.root.update_idletasks()
        self.root.geometry("330x{0}".format(self.root.winfo_reqheight()))

    def _click_defocus(self, event):
        if event.widget is not self.plan_entry:
            self.root.focus_set()

    def _save_plan(self, defocus=True):
        try:
            v = int(self.plan_var.get())
        except Exception:
            v = DEFAULT_PLAN_MIN
        v = min(600, max(1, v))
        self.plan_var.set(str(v))
        save_plan_minutes(v)
        # repaint right away: without this, pressing Enter looks like it did nothing
        # until the next telemetry frame arrives — and while parked none arrives
        self._paint_fuel(self.last_fuel, self.last_session_ms)
        if defocus:
            self.root.focus_set()

    def _plan_minutes(self):
        try:
            return min(600, max(1, int(self.plan_var.get())))
        except Exception:
            return DEFAULT_PLAN_MIN

    # ---------- game switching ----------
    def _apply_game(self, game):
        """Called on startup and whenever the running sim changes."""
        self._close()
        if self.reader is not None:
            self.reader.close()
        self.game = game
        self.reader = sim_shm.SimReader(game) if game else None
        if self.reader is not None:
            self.reader.attach()
        # Laps and the fuel history deliberately survive this: quitting to the menu
        # or closing the sim must not wipe the window you were about to read. They
        # are cleared where they actually stop meaning anything — on a session change.
        self.prev_completed = -1
        self.cur_max = 0.0
        self.lap_had_pit = False
        self.lap_invalid = False
        self.last_fuel = None       # tank level is meaningless with no sim attached
        self.last_session_ms = None
        self.title_lab.config(text="ACC LOGGER" if game == ACC else "ASSETTO CORSA LOGGER")
        self._update_neck_visibility()
        self._refresh_laps()
        self._paint_fuel()
        self._fit()
        if self.tray is not None:
            try:
                self.tray.update_menu()
            except Exception:
                pass

    # ---------- file ----------
    def _open(self):
        s, g = self.reader.stat, self.reader.graph
        car = safe((s.carModel or "").strip())
        trk = safe((s.track or "").strip())
        day = time.strftime("%Y-%m-%d")
        folder = os.path.join(OUT_DIR, trk, car, day)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        tag = sim_shm.sess_name(g.session)
        self.log_tag = time.strftime("%H-%M-%S")
        path = os.path.join(folder, "{0}_{1}_{2}.csv".format(
            self.log_tag, self.game, tag))
        self.f = open(path, "w", newline="")
        self.w = csv.writer(self.f)
        self.w.writerow(self.reader.cols)
        self.rows = 0
        self.t0 = time.perf_counter()
        # lap_rows is NOT cleared here: a new file starts on every pit stop, and the
        # laps you drove before the stop are still part of this session
        self.prev_completed = -1
        self.cur_max = 0.0
        self.lap_had_pit = False
        self.lap_invalid = False
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
        if now - self.game_check_t > 1.0:
            self.game_check_t = now
            found = sim_shm.detect_game()
            if found != self.game:
                self._apply_game(found)

        r = self.reader
        if r is None or not r.valid():
            if r is not None and now - self.reattach_t > 1.0:
                r.attach()
                self.reattach_t = now
            self._set_status("○  WAITING FOR SIM", GREY)
            self.carlbl.config(text="start AC / ACC and get on track")
            self.sesslbl.config(text="")
            self._close()
            self.root.after(200, self.poll)
            return

        p, g, s = r.phys, r.graph, r.stat
        # A session is one track + car + day — the same thing the output folder is,
        # so the window and the disk never disagree about where a session begins.
        key = ((s.carModel or "").strip(), (s.track or "").strip(),
               time.strftime("%Y-%m-%d"))
        if key != self.session_key:
            self.session_key = key
            self.fuel.reset()      # new car, track or day: the history means nothing
            self.lap_rows = []
            self.lap_seq = 0
            self.prev_completed = -1
            self._refresh_laps()
            self._paint_fuel()
        in_pit = r.in_pit_for_finalize()
        self.carlbl.config(text="{0}  @  {1}".format(key[0], key[1]))

        if in_pit:
            self.lap_had_pit = True
        if r.lap_invalid_now():
            self.lap_invalid = True   # latched until the lap is recorded

        if in_pit and not self.prev_pit:
            self._close()
        self.prev_pit = in_pit

        if r.live() and not in_pit:
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
        self.w.writerow(self.reader.row(time.perf_counter() - self.t0))
        self.rows += 1
        if self.rows % 50 == 0:
            self.f.flush()

        # --- per-lap time, peak speed, validity, fuel ---
        if p.speedKmh > self.cur_max:
            self.cur_max = p.speedKmh
        c = g.completedLaps
        if self.prev_completed < 0:
            self.prev_completed = c
        elif c > self.prev_completed:
            valid = not self.lap_invalid
            seq = self._add_lap(c, g.iLastTime, self.cur_max, valid)
            self.fuel.lap_completed(seq, p.fuel, g.iLastTime,
                                    valid and not self.lap_had_pit)
            self.prev_completed = c
            self.cur_max = 0.0
            self.lap_had_pit = False
            self.lap_invalid = False

    def _add_lap(self, lap_no, time_ms, max_kmh, valid):
        self.lap_seq += 1
        self.lap_rows.append((self.lap_seq, lap_no, time_ms, max_kmh, valid, self.log_tag))
        self._refresh_laps()
        return self.lap_seq

    def _refresh_laps(self):
        # an invalidated lap must not win "best", or a cut corner would show green
        times = [t for _, _, t, _, v, _ in self.lap_rows if 0 < t < 600000 and v]
        best = min(times) if times else None
        # follow the newest lap only when already at the bottom, so scrolling back
        # through a long stint is not yanked away every time a lap completes
        at_bottom = self.lap_list.yview()[1] >= 0.999
        chosen = set(self.fuel.selection() or ())
        self.lap_list.delete(0, "end")
        self.row_seq = []
        if not self.lap_rows:
            self.lap_list.insert("end", "(no completed laps yet)")
            self.lap_list.itemconfig(0, foreground=MUTED)
            self.row_seq.append(None)
            return
        prev_tag = None
        for seq, ln, t, spd, valid, tag in self.lap_rows:
            # one separator per log: a session spans several files (every pit stop
            # starts a new one) and the game restarts its lap numbers with each
            if tag != prev_tag:
                prev_tag = tag
                i = self.lap_list.size()
                self.lap_list.insert("end", " log {0} ".format(tag).center(24, "-"))
                self.lap_list.itemconfig(i, foreground=GREY)
                self.row_seq.append(None)
            i = self.lap_list.size()
            self.lap_list.insert("end", "L{0:<3} {1:>9}  {2:3.0f} km/h".format(
                ln, fmt_ms(t), spd))
            if not valid:
                fg = RED
            elif best is not None and t == best:
                fg = GREEN
            else:
                fg = TEXT
            self.lap_list.itemconfig(i, foreground=fg)
            self.row_seq.append(seq)
            if seq in chosen:
                self.lap_list.selection_set(i)
        if at_bottom:
            self.lap_list.see("end")

    def _on_lap_select(self, _event=None):
        # a separator is not a lap; clicking one must not silently drop the choice
        for i in self.lap_list.curselection():
            if i < len(self.row_seq) and self.row_seq[i] is None:
                self.lap_list.selection_clear(i)
        seqs = [self.row_seq[i] for i in self.lap_list.curselection()
                if i < len(self.row_seq) and self.row_seq[i] is not None]
        self.fuel.set_selection(seqs)
        self._paint_fuel(self.last_fuel, self.last_session_ms)

    def _clear_lap_select(self, _event=None):
        self.lap_list.selection_clear(0, "end")
        self.fuel.set_selection(None)
        self._paint_fuel(self.last_fuel, self.last_session_ms)

    def _paint_fuel(self, fuel_l=None, session_ms=None):
        sel = self.fuel.selection()
        if sel:
            n = sum(1 for s in self.fuel.samples()
                    if s.lap_no in set(sel) and s.selectable)
            # the opening lap of a session has no previous fuel level to subtract
            # from, and a refuelled lap has no meaningful burn — say so rather than
            # leaving the driver staring at "--" with rows visibly highlighted
            if n == 0:
                self.fuel_src.config(fg=AMBER,
                                     text="fuel: chosen laps have no usable burn  ·  Esc = auto")
            else:
                self.fuel_src.config(fg=BLUE, text="fuel: {0} chosen lap{1}  ·  Esc = auto"
                                     .format(n, "" if n == 1 else "s"))
        else:
            self.fuel_src.config(fg=MUTED, text="fuel: last 3 valid laps")
        lpl = self.fuel.l_per_lap()
        self.metrics["llap"].config(text="--" if lpl is None else "{0:.2f}".format(lpl))

        left = None if fuel_l is None else self.fuel.laps_left(fuel_l)
        self.fuel_left.config(text="--" if left is None else "{0:.1f}".format(left),
                              fg=TEXT if left is None else (RED if left < 2 else TEXT))

        for lab, ms in ((self.fuel_end, session_ms),
                        (self.fuel_plan, self._plan_minutes() * 60000)):
            need = self.fuel.fuel_for_ms(ms)
            if need is None:
                lab.config(text="--", fg=TEXT)
                continue
            if fuel_l is None:
                lab.config(text="{0:.1f} L".format(need), fg=TEXT)
                continue
            delta = need - fuel_l
            lab.config(text="{0:.1f} L  ({1:+.1f})".format(need, delta),
                       fg=RED if delta > 0 else GREEN)

    def _update_live(self, p, g):
        if g.session in (1, 2) and g.position > 0:   # quali / race -> show place
            self.sesslbl.config(text="{0}  ·  P{1}".format(sim_shm.sess_name(g.session),
                                                           g.position), fg=AMBER)
        else:
            self.sesslbl.config(text=sim_shm.sess_name(g.session), fg=MUTED)
        self.metrics["lap"].config(text=str(g.completedLaps))
        self.metrics["fuel"].config(text="{0:.1f}".format(p.fuel))
        for i in range(4):
            v = p.wheelsPressure[i]
            self.press_cells[i].config(text="{0:.1f}".format(v), fg=press_fg(v))
            t = p.tyreCoreTemperature[i]
            self.temp_cells[i].config(text="{0:.0f}".format(t), fg=temp_fg(t))
        stl = g.sessionTimeLeft
        self.last_fuel = p.fuel
        self.last_session_ms = stl if stl and stl > 0 else None
        self._paint_fuel(self.last_fuel, self.last_session_ms)
        self.filelbl.config(text="file: ...  rows: {0}".format(self.rows))

    def _set_status(self, text, color):
        self.status.config(text=text, fg=color)

    # ---------- NeckFX ----------
    def _update_neck_visibility(self):
        if self.neckfx_visible and self.game != ACC:
            self.neckwrap.pack(pady=(12, 0), before=self.btns)
        else:
            self.neckwrap.pack_forget()

    def _set_neckfx_visible(self, v):
        self.neckfx_visible = v
        save_neckfx_visible(v)
        self._update_neck_visibility()
        self._fit()
        if self.tray is not None:
            try:
                self.tray.update_menu()
            except Exception:
                pass

    def _paint_neck(self):
        colors = {"OFF": GREY, "DRIFT": BLUE, "GRIP": GREEN}
        self.neck_btn.config(text="NeckFX: " + self.neck_mode, fg=colors.get(self.neck_mode, TEXT))

    def _apply_neck(self, mode):
        self.neck_mode = mode
        ok, msg = True, "re-enter session to apply"
        if not NECK_INI or not os.path.exists(NECK_INI):
            ok, msg = False, "neck.ini not found"
        else:
            try:
                if mode == NECK_MINE:
                    if not restore_neck_ini(NECK_INI):
                        msg = "nothing to restore: never edited"
                else:
                    backup_neck_once(NECK_INI)
                    patch_neck_ini(NECK_INI, mode)
            except Exception as e:
                ok, msg = False, "err: " + str(e)[:28]
        self.neckhint.config(text=msg, fg=(MUTED if ok else RED))
        self._paint_neck()
        if self.tray is not None:
            try:
                self.tray.update_menu()
            except Exception:
                pass

    def cycle_neck(self):
        i = NECKFX_CYCLE.index(self.neck_mode) if self.neck_mode in NECKFX_CYCLE else 0
        self._apply_neck(NECKFX_CYCLE[(i + 1) % len(NECKFX_CYCLE)])

    # ---------- tray ----------
    def _tray_image(self):
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([4, 4, 59, 59], radius=12, fill=(29, 33, 41, 255))
        d.text((13, 22), "SL", fill=(74, 163, 255, 255))
        return img

    def _setup_tray(self):
        if not HAS_TRAY:
            return
        neck_menu = pystray.Menu(
            pystray.MenuItem("MINE (restore)", lambda i, it: self._tray_neck(NECK_MINE),
                             checked=lambda it: self.neck_mode == NECK_MINE, radio=True),
            pystray.MenuItem("OFF", lambda i, it: self._tray_neck("OFF"),
                             checked=lambda it: self.neck_mode == "OFF", radio=True),
            pystray.MenuItem("DRIFT", lambda i, it: self._tray_neck("DRIFT"),
                             checked=lambda it: self.neck_mode == "DRIFT", radio=True),
            pystray.MenuItem("GRIP", lambda i, it: self._tray_neck("GRIP"),
                             checked=lambda it: self.neck_mode == "GRIP", radio=True),
        )
        menu = pystray.Menu(
            pystray.MenuItem("Show", lambda i, it: self._tray_show(), default=True),
            # NeckFX is CSP, i.e. AC only. Editing neck.ini before AC starts is
            # useful, so this stays enabled unless ACC is the running sim.
            pystray.MenuItem(lambda it: "NeckFX: " + self.neck_mode, neck_menu,
                             enabled=lambda it: self.game != ACC),
            pystray.MenuItem("Show NeckFX button", lambda i, it: self._tray_toggle_neck_visible(),
                             checked=lambda it: self.neckfx_visible),
            pystray.MenuItem("Run at startup", lambda i, it: self._tray_autostart(),
                             checked=lambda it: is_autostart()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda i, it: self._tray_quit()),
        )
        self.tray = pystray.Icon(APP_REG_NAME, self._tray_image(),
                                 "{0} {1}".format(APP_NAME, APP_VERSION), menu)
        threading.Thread(target=self.tray.run, daemon=True).start()

    def _tray_show(self):
        self.root.after(0, lambda: (self.root.deiconify(), self.root.lift()))

    def _tray_neck(self, mode):
        self.root.after(0, lambda: self._apply_neck(mode))

    def _tray_toggle_neck_visible(self):
        self.root.after(0, lambda: self._set_neckfx_visible(not self.neckfx_visible))

    def _tray_autostart(self):
        set_autostart(not is_autostart())
        if self.tray is not None:
            self.tray.update_menu()

    def _tray_quit(self):
        self.root.after(0, self.quit)

    def on_close(self):
        if HAS_TRAY and self.tray is not None:
            self.root.withdraw()
        else:
            self.quit()

    def quit(self):
        self._close()
        if self.reader is not None:
            self.reader.close()
        if self.tray is not None:
            try:
                self.tray.stop()
            except Exception:
                pass
        self.root.destroy()


_MUTEX_HANDLE = None


def single_instance_ok():
    """True if we are the first instance; False if one is already running."""
    global _MUTEX_HANDLE
    try:
        k = ctypes.windll.kernel32
        _MUTEX_HANDLE = k.CreateMutexW(None, False, "StintLogger_singleton")
        return k.GetLastError() != 183  # 183 = ERROR_ALREADY_EXISTS
    except Exception:
        return True  # never block startup if the check itself fails


def show_existing_window():
    try:
        u = ctypes.windll.user32
        hwnd = u.FindWindowW(None, APP_NAME)
        if hwnd:
            u.ShowWindow(hwnd, 9)  # SW_RESTORE
            u.SetForegroundWindow(hwnd)
    except Exception:
        pass


def main():
    if "--version" in sys.argv:
        # the update gate runs exactly this on a downloaded build before trusting it
        print("{0} {1}".format(APP_NAME, APP_VERSION))
        return
    if not single_instance_ok():
        show_existing_window()
        return
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
