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


class TestCfg(unittest.TestCase):
    """logger.cfg holds more than one setting - saving one must not silently
    drop the others, which a plain json.dump(single_key) would do."""

    def setUp(self):
        fd, path = tempfile.mkstemp(suffix=".cfg")
        os.close(fd)
        os.remove(path)  # load_* must cope with the file not existing yet
        orig_cfg_path = stint_logger.CFG_PATH
        stint_logger.CFG_PATH = path
        self.addCleanup(setattr, stint_logger, "CFG_PATH", orig_cfg_path)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))

    def test_neckfx_visible_defaults_to_off(self):
        self.assertFalse(stint_logger.load_neckfx_visible())

    def test_neckfx_visible_round_trips(self):
        stint_logger.save_neckfx_visible(True)
        self.assertTrue(stint_logger.load_neckfx_visible())
        stint_logger.save_neckfx_visible(False)
        self.assertFalse(stint_logger.load_neckfx_visible())

    def test_plan_minutes_round_trips(self):
        stint_logger.save_plan_minutes(45)
        self.assertEqual(stint_logger.load_plan_minutes(), 45)

    def test_saving_plan_minutes_does_not_drop_neckfx_visible(self):
        stint_logger.save_neckfx_visible(True)
        stint_logger.save_plan_minutes(45)
        self.assertTrue(stint_logger.load_neckfx_visible())
        self.assertEqual(stint_logger.load_plan_minutes(), 45)

    def test_saving_neckfx_visible_does_not_drop_plan_minutes(self):
        stint_logger.save_plan_minutes(45)
        stint_logger.save_neckfx_visible(True)
        self.assertEqual(stint_logger.load_plan_minutes(), 45)
        self.assertTrue(stint_logger.load_neckfx_visible())


if __name__ == "__main__":
    unittest.main()
