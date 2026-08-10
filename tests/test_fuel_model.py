import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fuel_model import FuelModel


class TestFuelModel(unittest.TestCase):

    def feed(self, model, samples, start=1):
        """samples: [(fuel_at_crossing, lap_ms, lap_valid), ...], numbered from `start`"""
        for i, (fuel, ms, valid) in enumerate(samples):
            model.lap_completed(start + i, fuel, ms, valid)

    def test_nothing_before_first_sample(self):
        m = FuelModel()
        self.assertIsNone(m.l_per_lap())
        self.assertIsNone(m.avg_lap_ms())
        self.assertIsNone(m.laps_left(50.0))
        self.assertIsNone(m.fuel_for_ms(1800000))

    def test_first_crossing_yields_no_sample(self):
        # one crossing gives a fuel reading but no consumption yet
        m = FuelModel()
        m.lap_completed(1, 60.0, 100000, True)
        self.assertIsNone(m.l_per_lap())
        self.assertEqual(m.samples(), [])

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

    # ---------- every lap is kept, not just the window ----------

    def test_samples_keep_every_lap_beyond_the_window(self):
        m = FuelModel()
        self.feed(m, [(60.0, 100000, True), (55.0, 100000, True),
                      (54.0, 100000, True), (53.0, 100000, True),
                      (52.0, 100000, True)])
        # laps 2..5 produced consumption; the window only averages the last three,
        # but all four must still be there to choose from
        self.assertEqual([s.lap_no for s in m.samples()], [2, 3, 4, 5])
        self.assertAlmostEqual(m.samples()[0].used, 5.0, places=6)

    def test_unusable_laps_are_kept_but_flagged(self):
        m = FuelModel()
        self.feed(m, [(60.0, 100000, True), (57.0, 100000, False),
                      (95.0, 100000, True), (92.0, 100000, True)])
        by_lap = {s.lap_no: s for s in m.samples()}
        self.assertFalse(by_lap[2].valid)       # driver-invalidated, still selectable
        self.assertTrue(by_lap[2].selectable)
        self.assertFalse(by_lap[3].selectable)  # refuelled: negative consumption
        self.assertTrue(by_lap[4].selectable)

    # ---------- manual selection ----------

    def test_no_selection_means_the_default_window(self):
        m = FuelModel()
        self.feed(m, [(60.0, 100000, True), (55.0, 100000, True)])
        self.assertIsNone(m.selection())

    def test_selection_overrides_the_window(self):
        m = FuelModel()
        # consumption 5.0, 1.0, 1.0, 1.0 — the window would say 1.0
        self.feed(m, [(60.0, 100000, True), (55.0, 100000, True),
                      (54.0, 100000, True), (53.0, 100000, True),
                      (52.0, 100000, True)])
        m.set_selection([2])
        self.assertEqual(m.selection(), (2,))
        self.assertAlmostEqual(m.l_per_lap(), 5.0, places=6)

    def test_selection_can_exclude_a_slow_lap_the_automation_kept(self):
        # the case that motivated this: a valid but slow lap (cooling, traffic)
        m = FuelModel()
        self.feed(m, [(60.0, 100000, True), (58.0, 100000, True),
                      (52.0, 160000, True), (50.0, 100000, True)])
        self.assertAlmostEqual(m.l_per_lap(), (2.0 + 6.0 + 2.0) / 3, places=6)
        m.set_selection([2, 4])
        self.assertAlmostEqual(m.l_per_lap(), 2.0, places=6)
        self.assertAlmostEqual(m.avg_lap_ms(), 100000, places=6)

    def test_selection_may_include_a_lap_the_game_called_invalid(self):
        # cutting a corner makes the lap TIME suspect, not the fuel burn — so the
        # driver is allowed to put it back in
        m = FuelModel()
        self.feed(m, [(60.0, 100000, True), (57.0, 100000, False)])
        self.assertIsNone(m.l_per_lap())
        m.set_selection([2])
        self.assertAlmostEqual(m.l_per_lap(), 3.0, places=6)

    def test_selection_cannot_resurrect_a_refuelled_lap(self):
        # negative consumption is not a judgement call, it is garbage
        m = FuelModel()
        self.feed(m, [(60.0, 100000, True), (95.0, 100000, True)])
        m.set_selection([2])
        self.assertIsNone(m.l_per_lap())

    def test_selection_cannot_resurrect_an_absurd_lap_time(self):
        m = FuelModel()
        self.feed(m, [(60.0, 100000, True), (57.0, 900000, True)])
        m.set_selection([2])
        self.assertIsNone(m.l_per_lap())

    def test_unknown_lap_numbers_in_a_selection_are_ignored(self):
        m = FuelModel()
        self.feed(m, [(60.0, 100000, True), (57.0, 100000, True)])
        m.set_selection([2, 99])
        self.assertAlmostEqual(m.l_per_lap(), 3.0, places=6)

    def test_empty_selection_returns_to_the_default_window(self):
        m = FuelModel()
        self.feed(m, [(60.0, 100000, True), (55.0, 100000, True),
                      (54.0, 100000, True), (53.0, 100000, True),
                      (52.0, 100000, True)])
        m.set_selection([2])
        m.set_selection([])
        self.assertIsNone(m.selection())
        self.assertAlmostEqual(m.l_per_lap(), 1.0, places=6)

    def test_selection_survives_later_laps(self):
        # a chosen set stays chosen; new laps must not silently join it
        m = FuelModel()
        self.feed(m, [(60.0, 100000, True), (55.0, 100000, True)])
        m.set_selection([2])
        self.feed(m, [(50.0, 100000, True)], start=3)
        self.assertEqual(m.selection(), (2,))
        self.assertAlmostEqual(m.l_per_lap(), 5.0, places=6)

    def test_reset_clears_the_selection(self):
        m = FuelModel()
        self.feed(m, [(60.0, 100000, True), (55.0, 100000, True)])
        m.set_selection([2])
        m.reset()
        self.assertIsNone(m.selection())
        self.assertEqual(m.samples(), [])


if __name__ == "__main__":
    unittest.main()
