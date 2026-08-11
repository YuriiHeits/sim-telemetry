import importlib.util
import os
import subprocess
import sys
import unittest

import updater

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


class TestVersionCompare(unittest.TestCase):

    def test_patch_minor_and_major_all_count_as_newer(self):
        for older, later in (("1.0.0", "1.0.1"), ("1.0.1", "1.1.0"), ("1.9.9", "2.0.0")):
            self.assertTrue(updater.newer(later, older), (older, later))

    def test_same_version_is_not_newer(self):
        self.assertFalse(updater.newer("1.1.0", "1.1.0"))

    def test_older_release_is_not_newer(self):
        self.assertFalse(updater.newer("1.0.0", "1.1.0"))

    def test_v_prefix_is_accepted(self):
        self.assertTrue(updater.newer("v1.2.0", "1.1.0"))

    def test_short_version_is_padded_not_rejected(self):
        self.assertFalse(updater.newer("1.1", "1.1.0"))
        self.assertTrue(updater.newer("1.2", "1.1.9"))

    def test_a_tag_we_cannot_parse_never_triggers_an_update(self):
        for tag in ("latest", "", "v", "1.x", "release-2026"):
            self.assertFalse(updater.newer(tag, "1.1.0"), tag)


if __name__ == "__main__":
    unittest.main()
