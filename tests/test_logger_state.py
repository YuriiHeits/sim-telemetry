import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logger_state


class TestLoggerState(unittest.TestCase):
    """The pointer other tools read to find this logger. Every test runs against
    a temp directory: touching the real ~/.stintlogger would rewrite the user's
    own state."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = os.environ.get("STINTLOGGER_STATE_DIR")
        os.environ["STINTLOGGER_STATE_DIR"] = self._tmp.name

    def tearDown(self):
        if self._old is None:
            os.environ.pop("STINTLOGGER_STATE_DIR", None)
        else:
            os.environ["STINTLOGGER_STATE_DIR"] = self._old
        self._tmp.cleanup()

    def test_round_trip(self):
        self.assertTrue(logger_state.write_state(r"D:\sim\logs", "1.1.0", "ACC",
                                                 "2026-08-06T11:42:00"))
        got = logger_state.read_state()
        self.assertEqual(got["logs_dir"], "D:/sim/logs")
        self.assertEqual(got["version"], "1.1.0")
        self.assertEqual(got["last_game"], "ACC")
        self.assertEqual(got["last_run"], "2026-08-06T11:42:00")

    def test_creates_the_directory(self):
        nested = os.path.join(self._tmp.name, "deeper")
        os.environ["STINTLOGGER_STATE_DIR"] = nested
        self.assertTrue(logger_state.write_state("C:/logs", "1.1.0"))
        self.assertTrue(os.path.isfile(os.path.join(nested, "state.json")))

    def test_missing_file_reads_as_none(self):
        self.assertIsNone(logger_state.read_state())

    def test_broken_file_reads_as_none(self):
        with open(logger_state.state_path(), "w", encoding="utf-8") as fh:
            fh.write("{not json")
        self.assertIsNone(logger_state.read_state())

    def test_file_without_logs_dir_reads_as_none(self):
        with open(logger_state.state_path(), "w", encoding="utf-8") as fh:
            json.dump({"version": "1.1.0"}, fh)
        self.assertIsNone(logger_state.read_state())

    def test_last_writer_wins(self):
        logger_state.write_state("C:/first", "1.1.0")
        logger_state.write_state("C:/second", "1.1.0")
        self.assertEqual(logger_state.read_state()["logs_dir"], "C:/second")

    def test_write_never_raises_on_a_bad_location(self):
        # A file standing where the directory should be: makedirs cannot win,
        # and write_state must report failure rather than take the logger down.
        blocker = os.path.join(self._tmp.name, "blocker")
        with open(blocker, "w", encoding="utf-8") as fh:
            fh.write("not a directory")
        os.environ["STINTLOGGER_STATE_DIR"] = os.path.join(blocker, "sub")
        self.assertFalse(logger_state.write_state("C:/logs", "1.1.0"))


if __name__ == "__main__":
    unittest.main()
