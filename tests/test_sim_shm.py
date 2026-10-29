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
                      "carDamage", "pitLimiterOn", "abs", "brakeTemp", "clutch",
                      "wheelAngularSpeed", "turboBoost", "localAngularVel"):
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
            reader.stat = sim_shm.Static()
            self.assertEqual(len(reader.row(1.0)), len(reader.cols), game)


class TestDriftChannels(unittest.TestCase):
    """yaw rate, per-wheel spin, boost and world position, appended after every
    pre-1.3.0 column so old CSVs and index-based readers stay valid."""

    NEW = ["angvel_x", "angvel_y", "angvel_z", "yaw_rate",
           "wheel_w_fl", "wheel_w_fr", "wheel_w_rl", "wheel_w_rr",
           "turbo_boost", "car_x", "car_y", "car_z"]

    def _reader(self, game):
        reader = sim_shm.SimReader(game)
        reader.phys = reader._phys_t()
        reader.graph = reader._graph_t()
        reader.stat = sim_shm.Static()
        p = reader.phys
        p.localAngularVel[0], p.localAngularVel[1], p.localAngularVel[2] = 0.1, -0.75, 0.2
        for i, w in enumerate((101.0, 102.0, 150.0, 152.0)):
            p.wheelAngularSpeed[i] = w
        p.turboBoost = 1.25
        return reader

    def _by_name(self, reader):
        return dict(zip(reader.cols, reader.row(1.0)))

    def test_new_columns_are_appended_after_the_old_ones(self):
        old = {AC: sim_shm.CORE_COLS + sim_shm.AC_EXTRA_COLS,
               ACC: sim_shm.CORE_COLS + sim_shm.ACC_EXTRA_COLS}
        for game in (AC, ACC):
            cols = sim_shm.cols_for(game)
            self.assertEqual(cols[:len(old[game])], old[game], game)

    def test_physics_channels_land_in_their_columns(self):
        for game in (AC, ACC):
            row = self._by_name(self._reader(game))
            self.assertEqual(row["angvel_x"], "0.1000", game)
            self.assertEqual(row["angvel_y"], "-0.7500", game)
            self.assertEqual(row["angvel_z"], "0.2000", game)
            # AC/ACC are Y-up (vel_y/car_y are height), so yaw is rotation about Y
            self.assertEqual(row["yaw_rate"], row["angvel_y"], game)
            self.assertEqual([row["wheel_w_" + w] for w in ("fl", "fr", "rl", "rr")],
                             ["101.000", "102.000", "150.000", "152.000"], game)
            self.assertEqual(row["turbo_boost"], "1.250", game)

    def test_ac_position_comes_from_car_coordinates(self):
        reader = self._reader(AC)
        reader.graph.carCoordinates[0] = -123.5
        reader.graph.carCoordinates[1] = 4.25
        reader.graph.carCoordinates[2] = 987.75
        row = self._by_name(reader)
        self.assertEqual((row["car_x"], row["car_y"], row["car_z"]),
                         ("-123.500", "4.250", "987.750"))

    def test_acc_position_is_the_player_slot_not_slot_zero(self):
        reader = self._reader(ACC)
        g = reader.graph
        g.activeCars = 3
        g.carID[0], g.carID[1], g.carID[2] = 7, 42, 9
        g.playerCarID = 42
        for i in range(3):
            g.carCoordinates[i * 3] = i * 100.0
            g.carCoordinates[i * 3 + 1] = i + 0.5
            g.carCoordinates[i * 3 + 2] = -i * 100.0
        row = self._by_name(reader)
        self.assertEqual((row["car_x"], row["car_y"], row["car_z"]),
                         ("100.000", "1.500", "-100.000"))

    def test_acc_position_is_blank_when_the_player_is_not_listed(self):
        reader = self._reader(ACC)
        g = reader.graph
        g.activeCars = 2
        g.carID[0], g.carID[1] = 7, 9
        g.carID[5] = 42          # beyond activeCars: stale slot, must be ignored
        g.playerCarID = 42
        row = self._by_name(reader)
        self.assertEqual((row["car_x"], row["car_y"], row["car_z"]), ("", "", ""))

    def test_drift_columns_keep_their_1_3_0_place(self):
        n = len(self.NEW)
        old = {AC: sim_shm.CORE_COLS + sim_shm.AC_EXTRA_COLS,
               ACC: sim_shm.CORE_COLS + sim_shm.ACC_EXTRA_COLS}
        for game in (AC, ACC):
            self.assertEqual(sim_shm.cols_for(game)[len(old[game]):len(old[game]) + n],
                             self.NEW, game)

    def test_acc_position_survives_a_garbage_active_cars(self):
        reader = self._reader(ACC)
        g = reader.graph
        g.activeCars = 1000      # must not index past the 60-car arrays
        g.playerCarID = 42
        row = self._by_name(reader)
        self.assertEqual(row["car_x"], "")


class TestSetupChannels(unittest.TestCase):
    """1.4.0: tyre forces, slip, local velocity, temperatures across the tread,
    aid activity and car constants, appended after the 1.3.0 drift columns."""

    SHARED = ["slip_ang_fl", "slip_ang_fr", "slip_ang_rl", "slip_ang_rr",
              "slip_ratio_fl", "slip_ratio_fr", "slip_ratio_rl", "slip_ratio_rr",
              "lvel_x", "lvel_y", "lvel_z", "final_ff", "brake_bias", "max_rpm"]

    def _reader(self, game):
        reader = sim_shm.SimReader(game)
        reader.phys = reader._phys_t()
        reader.graph = reader._graph_t()
        reader.stat = sim_shm.Static()
        p, s = reader.phys, reader.stat
        for i in range(4):
            p.slipAngle[i] = 0.1 * (i + 1)
            p.slipRatio[i] = -0.05 * (i + 1)
            p.wheelLoad[i] = 3000.0 + i
            p.fx[i], p.fy[i], p.mz[i] = 100.0 + i, -200.0 - i, 5.0 + i
            p.tyreTempI[i], p.tyreTempM[i], p.tyreTempO[i] = 80.0 + i, 75.0 + i, 70.0 + i
            s.tyreRadius[i] = 0.30 + 0.01 * i
            s.suspensionMaxTravel[i] = 0.10 + 0.01 * i
        p.localVelocity[0], p.localVelocity[1], p.localVelocity[2] = -3.5, 0.25, 22.0
        p.finalFF, p.brakeBias = 0.875, 0.56
        p.tcinAction, p.absInAction = 1, 0
        p.rideHeight[0], p.rideHeight[1] = 0.055, 0.07
        s.maxRpm, s.maxTurboBoost = 8000, 1.2
        return reader

    def _by_name(self, reader):
        return dict(zip(reader.cols, reader.row(1.0)))

    def test_columns_follow_the_drift_block(self):
        for game in (AC, ACC):
            cols = sim_shm.cols_for(game)
            start = cols.index("car_z") + 1
            tail = self.SHARED + (sim_shm.AC_SETUP_COLS if game == AC else [])
            self.assertEqual(cols[start:], tail, game)

    def test_ac_only_setup_columns_absent_in_acc(self):
        acc = sim_shm.cols_for(ACC)
        for col in ("load_fl", "fy_fl", "ttemp_i_fl", "tc_active", "max_turbo",
                    "tyre_r_fl", "susp_max_fl", "ride_h_f"):
            self.assertNotIn(col, acc)

    def test_no_duplicate_columns(self):
        for game in (AC, ACC):
            cols = sim_shm.cols_for(game)
            self.assertEqual(len(cols), len(set(cols)), game)

    def test_row_length_matches_column_count(self):
        for game in (AC, ACC):
            reader = self._reader(game)
            self.assertEqual(len(reader.row(1.0)), len(reader.cols), game)

    def test_shared_channels_land_in_their_columns(self):
        for game in (AC, ACC):
            row = self._by_name(self._reader(game))
            self.assertEqual([row["slip_ang_" + w] for w in ("fl", "fr", "rl", "rr")],
                             ["0.1000", "0.2000", "0.3000", "0.4000"], game)
            self.assertEqual(row["slip_ratio_rr"], "-0.2000", game)
            self.assertEqual((row["lvel_x"], row["lvel_y"], row["lvel_z"]),
                             ("-3.5000", "0.2500", "22.0000"), game)
            self.assertEqual(row["final_ff"], "0.875", game)
            self.assertEqual(row["brake_bias"], "0.560", game)
            self.assertEqual(row["max_rpm"], 8000, game)

    def test_ac_channels_land_in_their_columns(self):
        row = self._by_name(self._reader(AC))
        self.assertEqual(row["load_fr"], "3001.0")
        self.assertEqual((row["fx_rl"], row["fy_rl"], row["mz_rl"]),
                         ("102.0", "-202.0", "7.00"))
        self.assertEqual((row["ttemp_i_rr"], row["ttemp_m_rr"], row["ttemp_o_rr"]),
                         ("83.0", "78.0", "73.0"))
        self.assertEqual((row["tc_active"], row["abs_active"]), (1, 0))
        self.assertEqual((row["ride_h_f"], row["ride_h_r"]), ("0.0550", "0.0700"))
        self.assertEqual(row["max_turbo"], "1.200")
        self.assertEqual(row["tyre_r_rr"], "0.3300")
        self.assertEqual(row["susp_max_fl"], "0.1000")

    def test_physics_tail_offsets(self):
        # counted by hand from the Kunos layout after clutch; a missing or
        # mis-sized field anywhere in between shifts slipAngle
        for t in (sim_shm.ACPhysics, sim_shm.ACCPhysics):
            clutch = t.clutch.offset
            self.assertEqual(t.tyreTempI.offset, clutch + 4)
            self.assertEqual(t.brakeBias.offset, clutch + 4 + 48 + 4 + 144)
            self.assertEqual(t.localVelocity.offset, clutch + 204)
            self.assertEqual(t.mz.offset, clutch + 228)
            self.assertEqual(t.slipAngle.offset, clutch + 292)
            self.assertEqual(t.absInAction.offset, clutch + 312)

    def test_static_offsets(self):
        s = sim_shm.Static
        self.assertEqual(s.maxRpm.offset, s.sectorCount.offset + 12)
        self.assertEqual(s.tyreRadius.offset, s.sectorCount.offset + 36)
        self.assertEqual(s.maxTurboBoost.offset, s.sectorCount.offset + 52)


if __name__ == "__main__":
    unittest.main()
