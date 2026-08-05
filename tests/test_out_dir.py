import importlib.util
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# The entry point is a .pyw, so it cannot be imported by name
_spec = importlib.util.spec_from_file_location(
    "stint_logger", os.path.join(ROOT, "stint_logger.pyw"))
stint_logger = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stint_logger)


class TestOutDir(unittest.TestCase):
    """Logs go next to the program; a read-only location must fall back to
    Documents rather than raise on every poll (someone will put the exe in
    Program Files)."""

    def test_writable_on_a_real_directory(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(stint_logger._writable(d))

    def test_writable_leaves_no_probe_file_behind(self):
        with tempfile.TemporaryDirectory() as d:
            stint_logger._writable(d)
            self.assertEqual(os.listdir(d), [])

    def test_not_writable_on_a_missing_directory(self):
        missing = os.path.join(tempfile.gettempdir(), "stintlogger-does-not-exist-42")
        self.assertFalse(os.path.isdir(missing))
        self.assertFalse(stint_logger._writable(missing))

    def test_chosen_out_dir_is_usable(self):
        self.assertTrue(os.path.isdir(stint_logger.OUT_DIR))
        self.assertTrue(stint_logger._writable(stint_logger.OUT_DIR))

    def test_config_lives_in_the_chosen_dir(self):
        self.assertEqual(os.path.dirname(stint_logger.CFG_PATH), stint_logger.OUT_DIR)


if __name__ == "__main__":
    unittest.main()
