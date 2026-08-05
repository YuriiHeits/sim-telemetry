"""Manual smoke check for the GUI: builds the window without any sim running,
switches layouts, and feeds fake laps. Needs a desktop, so it is deliberately
NOT named test_* — `unittest discover` must not pick it up.

Run: python tests/smoke_gui.py
"""

import os
import sys
import tkinter as tk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.argv = [sys.argv[0]]  # keep --tray out of it

import importlib.util

spec = importlib.util.spec_from_file_location(
    "stint_logger", os.path.join(ROOT, "stint_logger.pyw"))
gui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gui)

from sim_shm import AC, ACC

root = tk.Tk()
app = gui.App(root)
root.update_idletasks()

print("tray available:", gui.HAS_TRAY)
print("detected game at start:", app.game)
print("neck.ini:", gui.NECK_INI)
print("plan minutes from cfg:", app.plan_var.get())

for game in (AC, ACC, None):
    app._apply_game(game)
    root.update_idletasks()
    neck_visible = bool(app.neckwrap.winfo_manager())
    print("game={0!s:<5} title={1:<22} neckfx_shown={2!s:<5} height={3}".format(
        game, app.title_lab.cget("text"), neck_visible, root.winfo_reqheight()))

# fake laps: L3 invalid but fastest -> must be red, and must not take "best"
app._apply_game(ACC)
app.lap_rows = [(1, 100000, 210.0, True), (2, 99000, 212.0, True),
                (3, 95000, 215.0, False), (4, 99500, 211.0, True)]
app._refresh_laps()
root.update_idletasks()
colors = {"#3fb950": "GREEN", "#f0584b": "RED", "#e6e8eb": "TEXT", "#8a909a": "MUTED"}
for i in range(app.lap_list.size()):
    fg = app.lap_list.itemcget(i, "foreground")
    print("lap row:", app.lap_list.get(i), "->", colors.get(fg, fg))

# scrolling: a long stint must stay reachable and follow the newest lap
app.lap_rows = [(n, 99000 + n * 10, 210.0, True) for n in range(1, 26)]
app._refresh_laps()
root.update_idletasks()
first, last = app.lap_list.yview()
print("25 laps -> rows in listbox:", app.lap_list.size(),
      "| visible fraction: {0:.2f}..{1:.2f}".format(first, last),
      "| scrollable:", last - first < 0.999)
app.lap_list.yview_moveto(0.0)          # user scrolls up to look at early laps
root.update_idletasks()
app.lap_rows.append((26, 98000, 211.0, True))
app._refresh_laps()
root.update_idletasks()
print("after a new lap while scrolled up, top fraction stays:",
      "{0:.2f}".format(app.lap_list.yview()[0]))

# fuel: two crossings 3.0 L apart, 100 s laps
app.fuel.lap_completed(60.0, 100000, True)
app.fuel.lap_completed(57.0, 100000, True)
app._paint_fuel(fuel_l=57.0, session_ms=1000000)
root.update_idletasks()
print("l/lap:", app.metrics["llap"].cget("text"))
print("laps left:", app.fuel_left.cget("text"))
print("to session end:", app.fuel_end.cget("text"))
print("plan:", app.fuel_plan.cget("text"))

# plan entry: typing a value and hitting Enter must repaint and drop focus.
# The real logger.cfg belongs to the user, so put back whatever was there.
original_plan = app.plan_var.get()
app.plan_var.set("45")
app.plan_entry.focus_set()
root.update_idletasks()
app._save_plan()
root.update_idletasks()
print("plan after Enter:", app.plan_var.get(), "| litres:", app.fuel_plan.cget("text"),
      "| entry still focused:", root.focus_get() is app.plan_entry)
app.plan_var.set("9999")
app._save_plan()
print("plan clamped:", app.plan_var.get())
app.plan_var.set(original_plan)
app._save_plan()
print("plan restored to:", app.plan_var.get())

app.quit()
print("OK")
