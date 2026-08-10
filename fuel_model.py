"""Fuel consumption model — pure arithmetic, no tkinter and no shared memory.

Fed one sample per finish-line crossing; answers "litres per lap", "laps left"
and "litres needed for N milliseconds of racing". Same model for AC and ACC so
the two games produce comparable numbers (AC exposes nothing of its own; ACC's
own fuelXLap is used to cross-check this math, not to replace it).

Every lap is kept. By default the answer comes from the last few valid laps,
but the driver can name an explicit set of laps instead — the automation cannot
see a lap that was slow for a reason it doesn't track (cooling, traffic).
"""

import math

WINDOW = 3            # rolling average over the last N valid laps, when nothing is chosen
MAX_LAP_MS = 600000   # anything longer is not a lap we want in the average


class Sample:
    """One completed lap's fuel burn.

    `valid` is what the caller said about the lap; `selectable` is whether the
    arithmetic holds up at all. The driver may overrule `valid` — cutting a
    corner makes the lap TIME suspect, not the fuel burn — but not `selectable`,
    because a refuelled or absurdly long lap carries no usable number.
    """

    __slots__ = ("lap_no", "used", "lap_ms", "valid")

    def __init__(self, lap_no, used, lap_ms, valid):
        self.lap_no = lap_no
        self.used = used
        self.lap_ms = lap_ms
        self.valid = valid

    @property
    def selectable(self):
        return self.used > 0 and 0 < self.lap_ms < MAX_LAP_MS

    @property
    def in_default_window(self):
        return self.selectable and self.valid


class FuelModel:

    def __init__(self):
        self.reset()

    def reset(self):
        self._prev_fuel = None
        self._samples = []
        self._selection = None

    def lap_completed(self, lap_no, fuel_l, lap_ms, lap_valid):
        """Record a finish-line crossing. fuel_l is the tank level at that moment.

        lap_valid is decided by the caller: no pit during the lap (AC), plus the
        game's own isValidLap (ACC).
        """
        prev = self._prev_fuel
        # The baseline advances even for a lap we would not average, otherwise the
        # next lap would look like it burned both laps' fuel.
        self._prev_fuel = fuel_l
        if prev is None:
            return  # first crossing: a level, but no consumption yet
        self._samples.append(Sample(lap_no, prev - fuel_l, float(lap_ms), lap_valid))

    # ---------- what there is to choose from ----------

    def samples(self):
        """Every recorded lap, oldest first — including the ones no average uses."""
        return list(self._samples)

    def selection(self):
        """The lap numbers chosen by hand, or None while the default window applies."""
        return self._selection

    def set_selection(self, lap_nos):
        """Choose the laps to average. Empty or None goes back to the default window."""
        self._selection = tuple(lap_nos) if lap_nos else None

    def _active(self):
        if self._selection is None:
            return [s for s in self._samples if s.in_default_window][-WINDOW:]
        chosen = set(self._selection)
        return [s for s in self._samples if s.lap_no in chosen and s.selectable]

    # ---------- answers ----------

    def l_per_lap(self):
        active = self._active()
        if not active:
            return None
        return sum(s.used for s in active) / len(active)

    def avg_lap_ms(self):
        active = self._active()
        if not active:
            return None
        return sum(s.lap_ms for s in active) / len(active)

    def laps_left(self, fuel_l):
        lpl = self.l_per_lap()
        if not lpl:
            return None
        return fuel_l / lpl

    def fuel_for_ms(self, ms):
        """Litres needed to run for `ms`, plus the lap that follows the timer."""
        lpl = self.l_per_lap()
        avg = self.avg_lap_ms()
        if not lpl or not avg or ms is None or ms <= 0:
            return None
        return (math.ceil(ms / avg) + 1) * lpl
