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
app.lap_rows = [(1, 1, 100000, 210.0, True, "21-14-03"),
                (2, 2, 99000, 212.0, True, "21-14-03"),
                (3, 3, 95000, 215.0, False, "21-14-03"),
                (4, 4, 99500, 211.0, True, "21-14-03")]
app._refresh_laps()
root.update_idletasks()
colors = {"#3fb950": "GREEN", "#f0584b": "RED", "#e6e8eb": "TEXT",
          "#8a909a": "MUTED", "#6e7681": "GREY"}
for i in range(app.lap_list.size()):
    fg = app.lap_list.itemcget(i, "foreground")
    print("lap row:", app.lap_list.get(i), "->", colors.get(fg, fg))

# a second stint: the game restarts its lap numbers, so a separator must split them
# and the rows must stay individually addressable
app.lap_rows += [(5, 1, 101000, 209.0, True, "21-38-11"),
                 (6, 2, 99200, 211.0, True, "21-38-11")]
app._refresh_laps()
root.update_idletasks()
print("two logs -> rows:", app.lap_list.size(), "| row_seq:", app.row_seq)
print("separator text:", repr(app.lap_list.get(5)))

# selecting rows drives the fuel average; separators must not count as laps
app.fuel.reset()
for seq, (fuel, ms) in enumerate([(60.0, 100000), (55.0, 100000),
                                  (54.0, 100000), (53.0, 100000)], start=1):
    app.fuel.lap_completed(seq, fuel, ms, True)
print("auto (last 3):", "{0:.2f}".format(app.fuel.l_per_lap()))
app.lap_list.selection_clear(0, "end")
app.lap_list.selection_set(1)            # seq 1: the opening lap, no burn to measure
app._on_lap_select()
print("choosing only the opening lap:", "l/lap:", app.fuel.l_per_lap(),
      "| label:", app.fuel_src.cget("text"))
app.lap_list.selection_clear(0, "end")
app.lap_list.selection_set(2)            # seq 2 -> burned 5.0 L
app.lap_list.selection_set(5)            # the separator row
app._on_lap_select()
root.update_idletasks()
print("after choosing one lap + a separator:",
      "selection:", app.fuel.selection(),
      "| l/lap:", "{0:.2f}".format(app.fuel.l_per_lap()),
      "| label:", app.fuel_src.cget("text"))
app._clear_lap_select()
root.update_idletasks()
print("after Esc:", "selection:", app.fuel.selection(),
      "| l/lap:", "{0:.2f}".format(app.fuel.l_per_lap()),
      "| label:", app.fuel_src.cget("text"))

# a chosen lap must stay chosen when a new lap arrives and the list is rebuilt
app.lap_list.selection_set(2)
app._on_lap_select()
app.lap_rows.append((7, 3, 99000, 210.0, True, "21-38-11"))
app._refresh_laps()
root.update_idletasks()
print("choice survives a new lap:", app.fuel.selection(),
      "| still highlighted:", 2 in app.lap_list.curselection())
app._clear_lap_select()

# quitting the sim must not wipe what you were about to read
app._apply_game(None)
root.update_idletasks()
print("after the sim quits -> laps kept:", len(app.lap_rows),
      "| l/lap kept:", app.metrics["llap"].cget("text"),
      "| laps left blanked:", app.fuel_left.cget("text"))

# scrolling: a long stint must stay reachable and follow the newest lap
app.fuel.reset()
app.lap_rows = [(n, n, 99000 + n * 10, 210.0, True, "21-14-03") for n in range(1, 26)]
app._refresh_laps()
root.update_idletasks()
first, last = app.lap_list.yview()
print("25 laps -> rows in listbox:", app.lap_list.size(),
      "| visible fraction: {0:.2f}..{1:.2f}".format(first, last),
      "| scrollable:", last - first < 0.999)
app.lap_list.yview_moveto(0.0)          # user scrolls up to look at early laps
root.update_idletasks()
app.lap_rows.append((26, 26, 98000, 211.0, True, "21-14-03"))
app._refresh_laps()
root.update_idletasks()
print("after a new lap while scrolled up, top fraction stays:",
      "{0:.2f}".format(app.lap_list.yview()[0]))

# fuel: two crossings 3.0 L apart, 100 s laps
app.fuel.lap_completed(1, 60.0, 100000, True)
app.fuel.lap_completed(2, 57.0, 100000, True)
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
