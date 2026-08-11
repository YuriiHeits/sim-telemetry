import importlib.util
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# The entry point is a .pyw, so it cannot be imported by name
_spec = importlib.util.spec_from_file_location(
    "stint_logger", os.path.join(ROOT, "stint_logger.pyw"))
stint_logger = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stint_logger)


class TestVersionFlag(unittest.TestCase):
    """--version is what the update gate runs on a freshly downloaded build, so
    it must answer on stdout and exit without a window or a mutex."""

    def test_version_constant_looks_like_a_version(self):
        self.assertRegex(stint_logger.APP_VERSION, r"^\d+\.\d+\.\d+$")

    def test_version_flag_prints_the_version_and_exits_zero(self):
        r = subprocess.run(
            [sys.executable, os.path.join(ROOT, "stint_logger.pyw"), "--version"],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "StintLogger " + stint_logger.APP_VERSION)


if __name__ == "__main__":
    unittest.main()
