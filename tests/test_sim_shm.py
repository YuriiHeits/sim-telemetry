import ctypes
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sim_shm
from sim_shm import AC, ACC


class TestGameDetection(unittest.TestCase):

    def test_ac(self):
        self.assertEqual(sim_shm.game_for_processes(["explorer.exe", "acs.exe"]), AC)

    def test_ac_32bit(self):
        self.assertEqual(sim_shm.game_for_processes(["acs_x86.exe"]), AC)

    def test_acc(self):
        self.assertEqual(sim_shm.game_for_processes(["AC2-Win64-Shipping.exe"]), ACC)

    def test_case_insensitive(self):
        self.assertEqual(sim_shm.game_for_processes(["ACS.EXE"]), AC)
        self.assertEqual(sim_shm.game_for_processes(["ac2-win64-shipping.exe"]), ACC)

    def test_no_sim(self):
        self.assertIsNone(sim_shm.game_for_processes(["explorer.exe", "chrome.exe"]))

    def test_empty(self):
        self.assertIsNone(sim_shm.game_for_processes([]))

    def test_both_running_is_deterministic(self):
        both = ["acs.exe", "AC2-Win64-Shipping.exe"]
        self.assertEqual(sim_shm.game_for_processes(both), ACC)
        self.assertEqual(sim_shm.game_for_processes(list(reversed(both))), ACC)

    def test_real_snapshot_lists_this_process(self):
        names = [n.lower() for n in sim_shm.running_process_names()]
        self.assertTrue(any("python" in n for n in names), names[:20])


class TestColumns(unittest.TestCase):

    def test_core_is_shared(self):
        ac, acc = sim_shm.cols_for(AC), sim_shm.cols_for(ACC)
        self.assertEqual(ac[:len(sim_shm.CORE_COLS)], sim_shm.CORE_COLS)
        self.assertEqual(acc[:len(sim_shm.CORE_COLS)], sim_shm.CORE_COLS)

    def test_ac_only_columns_absent_in_acc(self):
        acc = sim_shm.cols_for(ACC)
        for col in ("camber_fl", "dirt_fl", "tyres_out", "drs"):
            self.assertNotIn(col, acc)

    def test_acc_only_columns_absent_in_ac(self):
        ac = sim_shm.cols_for(AC)
        for col in ("valid_lap", "fuel_x_lap", "fuel_est_laps"):
            self.assertNotIn(col, ac)

    def test_tyre_setup_channels_are_shared(self):
        for game in (AC, ACC):
            cols = sim_shm.cols_for(game)
            for col in ("wear_fl", "btemp_fl", "air_temp", "road_temp", "tyre_compound"):
                self.assertIn(col, cols, (game, col))

    def test_no_pitlane_column(self):
        # it could only ever be 0: entering the pit lane finalizes the file
        self.assertNotIn("in_pitlane", sim_shm.cols_for(ACC))

    def test_no_duplicate_columns(self):
        for game in (AC, ACC):
            cols = sim_shm.cols_for(game)
            self.assertEqual(len(cols), len(set(cols)), game)


class TestStructLayout(unittest.TestCase):
    """The ACC structs exist to reach a few fields far from the start; a wrong
    offset anywhere before them silently turns those fields into garbage. These
    guard the two things that can be checked without the game running: the shared
    prefix really is shared, and nothing exceeds the pages ACC publishes."""

    def test_prefix_offsets_match_between_games(self):
        for field in ("packetId", "gas", "brake", "fuel", "gear", "rpms", "steerAngle",
                      "speedKmh", "velocity", "accG", "wheelSlip", "wheelsPressure",
                      "tyreCoreTemperature", "suspensionTravel", "tc", "heading",
                      "carDamage", "pitLimiterOn", "abs", "brakeTemp", "clutch"):
            self.assertEqual(getattr(sim_shm.ACPhysics, field).offset,
                             getattr(sim_shm.ACCPhysics, field).offset, field)
        for field in ("packetId", "status", "session", "completedLaps", "position",
                      "iLastTime", "iBestTime", "sessionTimeLeft", "isInPit",
                      "tyreCompound", "normalizedCarPosition"):
            self.assertEqual(getattr(sim_shm.ACGraphics, field).offset,
                             getattr(sim_shm.ACCGraphics, field).offset, field)

    def test_structs_fit_the_pages_acc_publishes(self):
        # sizes ACC is known to publish (PyAccSharedMemory maps exactly these)
        self.assertLessEqual(ctypes.sizeof(sim_shm.ACCPhysics), 800)
        self.assertLessEqual(ctypes.sizeof(sim_shm.ACCGraphics), 1588)
        self.assertLessEqual(ctypes.sizeof(sim_shm.Static), 784)

    def test_wchar_arrays_do_not_shift_the_fields_after_them(self):
        # a 30-byte wchar[15] run must leave the next int 4-aligned, and the
        # 66-byte tyreCompound must be padded by 2 — this is what _pack_ = 4 buys
        self.assertEqual(sim_shm.ACGraphics.currentTime.offset, 12)
        self.assertEqual(sim_shm.ACGraphics.completedLaps.offset, 132)
        self.assertEqual(sim_shm.ACGraphics.tyreCompound.offset, 176)
        self.assertEqual(sim_shm.ACGraphics.replayTimeMultiplier.offset, 244)

    def test_attach_then_close_releases_the_mappings(self):
        # ctypes views keep the mmap buffer exported: closing an mmap while a view
        # is alive raises BufferError, which close() would swallow and leak. This
        # fails loudly if the drop-views-first ordering in close() is ever changed.
        reader = sim_shm.SimReader(ACC)
        for _ in range(3):
            reader.attach()
            self.assertEqual(len(reader.maps), 3)
            maps = list(reader.maps)
            reader.close()
            self.assertEqual(reader.maps, [])
            for m in maps:
                self.assertTrue(m.closed)

    def test_ac_lap_validity_comes_from_wheels_off_track(self):
        reader = sim_shm.SimReader(AC)
        reader.phys = sim_shm.ACPhysics()
        for n, invalid in ((0, False), (1, False), (2, False), (3, False), (4, True)):
            reader.phys.numberOfTyresOut = n
            self.assertEqual(reader.lap_invalid_now(), invalid, n)

    def test_acc_lap_validity_comes_from_the_game(self):
        reader = sim_shm.SimReader(ACC)
        reader.graph = sim_shm.ACCGraphics()
        reader.graph.isValidLap = 1
        self.assertFalse(reader.lap_invalid_now())
        reader.graph.isValidLap = 0
        self.assertTrue(reader.lap_invalid_now())

    def test_row_length_matches_column_count(self):
        for game in (AC, ACC):
            reader = sim_shm.SimReader(game)
            reader.phys = reader._phys_t()
            reader.graph = reader._graph_t()
            self.assertEqual(len(reader.row(1.0)), len(reader.cols), game)


if __name__ == "__main__":
    unittest.main()
