import importlib.util
import os
import shutil
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


# A CSP-written neck.ini carrying every key our presets touch.
FULL_INI = """\
[BASIC]
ENABLED=1

[SCRIPT]
ENABLED=0

[ALIGNMENT_BASE]
ALIGN_WITH_VELOCITY=0.4
ALIGN_WITH_STEERING=0.2
HORIZON_LOCK=0.3
G_TILT_X=0.1
G_TILT_Z=0.1

[LOOKAHEAD]
GAIN=0.6
"""

# The same file as it looks on someone whose CSP build never wrote [LOOKAHEAD]
# and has no G_TILT keys: patching it must add what is missing, not skip it.
SPARSE_INI = """\
[BASIC]
ENABLED=1

[ALIGNMENT_BASE]
ALIGN_WITH_VELOCITY=0.4
ALIGN_WITH_STEERING=0.2
HORIZON_LOCK=0.3
"""


def write(path, text, newline="\n"):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text.replace("\n", newline))


class NeckCase(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.ini = os.path.join(self.dir, "neck.ini")
        self.bak = self.ini + ".ggbak"
        self.addCleanup(shutil.rmtree, self.dir, True)


class TestModeDetection(NeckCase):

    def test_missing_file_reads_as_off(self):
        self.assertEqual(stint_logger.read_neck_mode(self.ini), "OFF")

    def test_each_preset_reads_back_after_patching(self):
        for preset in ("OFF", "DRIFT", "GRIP"):
            write(self.ini, FULL_INI)
            stint_logger.patch_neck_ini(self.ini, preset)
            self.assertEqual(stint_logger.read_neck_mode(self.ini), preset, preset)

    def test_preset_reads_back_on_a_file_that_lacked_our_keys(self):
        write(self.ini, SPARSE_INI)
        stint_logger.patch_neck_ini(self.ini, "DRIFT")
        self.assertEqual(stint_logger.read_neck_mode(self.ini), "DRIFT")

    def test_own_settings_are_not_reported_as_a_preset(self):
        # ENABLED=1 with ALIGN_WITH_STEERING=0 is what the old two-key guess
        # called "DRIFT"; none of these values are ours
        write(self.ini, FULL_INI.replace("ALIGN_WITH_VELOCITY=0.4", "ALIGN_WITH_VELOCITY=0.85")
                                .replace("ALIGN_WITH_STEERING=0.2", "ALIGN_WITH_STEERING=0.0")
                                .replace("GAIN=0.6", "GAIN=0.9"))
        self.assertEqual(stint_logger.read_neck_mode(self.ini), "MINE")

    def test_own_settings_with_neckfx_disabled_are_still_mine(self):
        # ENABLED=0 alone used to read as OFF, which would let us zero the rest
        write(self.ini, FULL_INI.replace("[BASIC]\nENABLED=1", "[BASIC]\nENABLED=0"))
        self.assertEqual(stint_logger.read_neck_mode(self.ini), "MINE")

    def test_file_without_our_sections_is_mine(self):
        write(self.ini, "[BASIC]\nENABLED=1\n")
        self.assertEqual(stint_logger.read_neck_mode(self.ini), "MINE")

    def test_values_compare_as_numbers_not_strings(self):
        write(self.ini, FULL_INI)
        stint_logger.patch_neck_ini(self.ini, "DRIFT")
        with open(self.ini, encoding="utf-8") as fh:
            raw = fh.read()
        write(self.ini, raw.replace("ALIGN_WITH_VELOCITY=0.6", "ALIGN_WITH_VELOCITY=0.60"))
        self.assertEqual(stint_logger.read_neck_mode(self.ini), "DRIFT")


class TestPatching(NeckCase):

    def read(self):
        with open(self.ini, encoding="utf-8") as fh:
            return fh.read()

    def test_missing_key_is_added_to_its_existing_section(self):
        write(self.ini, SPARSE_INI)
        stint_logger.patch_neck_ini(self.ini, "OFF")
        self.assertIn("G_TILT_X=0.0", self.read())

    def test_missing_section_is_created(self):
        write(self.ini, SPARSE_INI)
        self.assertNotIn("LOOKAHEAD", self.read())
        stint_logger.patch_neck_ini(self.ini, "DRIFT")
        text = self.read()
        self.assertIn("[LOOKAHEAD]", text)
        self.assertIn("GAIN=0.3", text)

    def test_added_key_lands_inside_its_own_section(self):
        # a key appended to the wrong section reads back as absent, which is how
        # a half-applied preset would go unnoticed
        write(self.ini, SPARSE_INI)
        stint_logger.patch_neck_ini(self.ini, "OFF")
        got = stint_logger._read_keys(self.ini, {("ALIGNMENT_BASE", "G_TILT_X")})
        self.assertEqual(got.get(("ALIGNMENT_BASE", "G_TILT_X")), "0.0")

    def test_foreign_keys_and_comments_survive(self):
        write(self.ini, FULL_INI + "\n[MY_OWN]\nFOREIGN=42 ; hands off\n")
        stint_logger.patch_neck_ini(self.ini, "GRIP")
        text = self.read()
        self.assertIn("[MY_OWN]", text)
        self.assertIn("FOREIGN=42 ; hands off", text)

    def test_comment_on_a_patched_key_survives(self):
        write(self.ini, FULL_INI.replace("GAIN=0.6", "GAIN=0.6 ; tuned by me"))
        stint_logger.patch_neck_ini(self.ini, "GRIP")
        self.assertIn("GAIN=0.6 ; tuned by me", self.read())

    def test_crlf_file_stays_crlf(self):
        write(self.ini, SPARSE_INI, newline="\r\n")
        stint_logger.patch_neck_ini(self.ini, "DRIFT")
        with open(self.ini, "rb") as fh:
            raw = fh.read()
        self.assertIn(b"\r\n", raw)
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))


class TestBackupAndRestore(NeckCase):

    def test_backup_does_not_overwrite_an_existing_one(self):
        write(self.ini, FULL_INI)
        stint_logger.backup_neck_once(self.ini)
        write(self.ini, SPARSE_INI)
        stint_logger.backup_neck_once(self.ini)
        with open(self.bak, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), FULL_INI)

    def test_restore_brings_the_file_back_byte_for_byte(self):
        write(self.ini, FULL_INI + "\n[SCRIPT_TUNING]\nMINE=1\n", newline="\r\n")
        with open(self.ini, "rb") as fh:
            original = fh.read()
        stint_logger.backup_neck_once(self.ini)
        stint_logger.patch_neck_ini(self.ini, "DRIFT")
        self.assertTrue(stint_logger.restore_neck_ini(self.ini))
        with open(self.ini, "rb") as fh:
            self.assertEqual(fh.read(), original)

    def test_restore_without_a_backup_changes_nothing(self):
        write(self.ini, FULL_INI)
        self.assertFalse(stint_logger.restore_neck_ini(self.ini))
        with open(self.ini, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), FULL_INI)


class TestCycle(unittest.TestCase):

    def test_own_settings_come_first_in_the_cycle(self):
        self.assertEqual(stint_logger.NECKFX_CYCLE[0], "MINE")

    def test_cycle_covers_the_three_presets_and_mine(self):
        self.assertEqual(set(stint_logger.NECKFX_CYCLE),
                         {"MINE"} | set(stint_logger.NECKFX_PRESETS))

    def test_mine_is_not_a_preset(self):
        self.assertNotIn("MINE", stint_logger.NECKFX_PRESETS)


if __name__ == "__main__":
    unittest.main()
