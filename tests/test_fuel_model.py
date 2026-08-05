import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fuel_model import FuelModel


class TestFuelModel(unittest.TestCase):

    def feed(self, model, samples):
        """samples: [(fuel_at_crossing, lap_ms, lap_valid), ...]"""
        for fuel, ms, valid in samples:
            model.lap_completed(fuel, ms, valid)

    def test_nothing_before_first_sample(self):
        m = FuelModel()
        self.assertIsNone(m.l_per_lap())
        self.assertIsNone(m.avg_lap_ms())
        self.assertIsNone(m.laps_left(50.0))
        self.assertIsNone(m.fuel_for_ms(1800000))

    def test_first_crossing_yields_no_sample(self):
        # one crossing gives a fuel reading but no consumption yet
        m = FuelModel()
        m.lap_completed(60.0, 100000, True)
        self.assertIsNone(m.l_per_lap())

    def test_second_crossing_yields_first_number(self):
        m = FuelModel()
        self.feed(m, [(60.0, 100000, True), (57.2, 100000, True)])
        self.assertAlmostEqual(m.l_per_lap(), 2.8, places=6)
        self.assertAlmostEqual(m.avg_lap_ms(), 100000, places=6)

    def test_window_is_last_three(self):
        m = FuelModel()
        # consumption: 5.0, 1.0, 1.0, 1.0 -> the 5.0 must fall out of the window
        self.feed(m, [(60.0, 100000, True), (55.0, 100000, True),
                      (54.0, 100000, True), (53.0, 100000, True),
                      (52.0, 100000, True)])
        self.assertAlmostEqual(m.l_per_lap(), 1.0, places=6)

    def test_refuel_lap_is_discarded(self):
        m = FuelModel()
        # fuel goes up on the third crossing (pit stop) -> negative consumption
        self.feed(m, [(60.0, 100000, True), (57.0, 100000, True),
                      (95.0, 100000, True), (92.0, 100000, True)])
        self.assertAlmostEqual(m.l_per_lap(), 3.0, places=6)

    def test_invalid_lap_is_discarded(self):
        m = FuelModel()
        self.feed(m, [(60.0, 100000, True), (57.0, 100000, True),
                      (50.0, 100000, False)])
        self.assertAlmostEqual(m.l_per_lap(), 3.0, places=6)

    def test_absurd_lap_time_is_discarded(self):
        m = FuelModel()
        self.feed(m, [(60.0, 100000, True), (57.0, 100000, True),
                      (54.0, 900000, True)])
        self.assertAlmostEqual(m.avg_lap_ms(), 100000, places=6)

    def test_discarded_lap_still_advances_fuel_baseline(self):
        # an invalid lap must not make the NEXT lap's consumption look doubled
        m = FuelModel()
        self.feed(m, [(60.0, 100000, True), (57.0, 100000, False),
                      (54.0, 100000, True)])
        self.assertAlmostEqual(m.l_per_lap(), 3.0, places=6)

    def test_laps_left(self):
        m = FuelModel()
        self.feed(m, [(60.0, 100000, True), (57.0, 100000, True)])
        self.assertAlmostEqual(m.laps_left(30.0), 10.0, places=6)

    def test_fuel_for_ms_adds_one_lap(self):
        m = FuelModel()
        self.feed(m, [(60.0, 100000, True), (57.0, 100000, True)])
        # 1_000_000 ms / 100_000 = 10 laps, +1 for the lap after the timer hits zero
        self.assertAlmostEqual(m.fuel_for_ms(1000000), 33.0, places=6)

    def test_fuel_for_ms_rounds_partial_lap_up(self):
        m = FuelModel()
        self.feed(m, [(60.0, 100000, True), (57.0, 100000, True)])
        # 1_050_000 / 100_000 = 10.5 -> 11 laps, +1 = 12
        self.assertAlmostEqual(m.fuel_for_ms(1050000), 36.0, places=6)

    def test_reset_clears_state(self):
        m = FuelModel()
        self.feed(m, [(60.0, 100000, True), (57.0, 100000, True)])
        m.reset()
        self.assertIsNone(m.l_per_lap())
        self.assertIsNone(m.laps_left(30.0))


if __name__ == "__main__":
    unittest.main()
