"""Fuel consumption model — pure arithmetic, no tkinter and no shared memory.

Fed one sample per finish-line crossing; answers "litres per lap", "laps left"
and "litres needed for N milliseconds of racing". Same model for AC and ACC so
the two games produce comparable numbers (AC exposes nothing of its own; ACC's
own fuelXLap is used to cross-check this math, not to replace it).
"""

import math

WINDOW = 3            # rolling average over the last N valid laps
MAX_LAP_MS = 600000   # anything longer is not a lap we want in the average


class FuelModel:

    def __init__(self):
        self.reset()

    def reset(self):
        self._prev_fuel = None
        self._used = []
        self._times = []

    def lap_completed(self, fuel_l, lap_ms, lap_valid):
        """Record a finish-line crossing. fuel_l is the tank level at that moment.

        lap_valid is decided by the caller: no pit during the lap (AC), plus the
        game's own isValidLap (ACC).
        """
        prev = self._prev_fuel
        # The baseline advances even for a discarded lap, otherwise the next lap
        # would look like it burned both laps' fuel.
        self._prev_fuel = fuel_l
        if prev is None:
            return  # first crossing: a level, but no consumption yet
        used = prev - fuel_l
        if used <= 0:
            return  # refuelled
        if not lap_valid or not (0 < lap_ms < MAX_LAP_MS):
            return
        self._used = (self._used + [used])[-WINDOW:]
        self._times = (self._times + [float(lap_ms)])[-WINDOW:]

    def l_per_lap(self):
        if not self._used:
            return None
        return sum(self._used) / len(self._used)

    def avg_lap_ms(self):
        if not self._times:
            return None
        return sum(self._times) / len(self._times)

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
