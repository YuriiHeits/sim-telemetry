import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import updater

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# The entry point is a .pyw, so it cannot be imported by name
_spec = importlib.util.spec_from_file_location(
    "stint_logger", os.path.join(ROOT, "stint_logger.pyw"))
stint_logger = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stint_logger)


def fixture(name):
    with open(os.path.join(ROOT, "tests", "fixtures", name), encoding="utf-8") as fh:
        return json.load(fh)


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


class TestPickAsset(unittest.TestCase):

    def test_takes_the_exe_and_its_tag_and_size(self):
        got = updater.pick_asset(fixture("github_release.json"))
        self.assertEqual(got["tag"], "v1.2.0")
        self.assertEqual(got["url"], "https://example.invalid/StintLogger.exe")
        self.assertEqual(got["size"], 25897150)

    def test_a_release_without_our_asset_is_no_release(self):
        payload = fixture("github_release.json")
        payload["assets"] = [a for a in payload["assets"] if a["name"] != "StintLogger.exe"]
        self.assertIsNone(updater.pick_asset(payload))

    def test_a_release_with_no_assets_at_all(self):
        payload = fixture("github_release.json")
        payload["assets"] = []
        self.assertIsNone(updater.pick_asset(payload))

    def test_a_payload_without_a_tag(self):
        payload = fixture("github_release.json")
        del payload["tag_name"]
        self.assertIsNone(updater.pick_asset(payload))


class TestFetchLatest(unittest.TestCase):
    """The one line that touches the network is injected, so the parsing around
    it is tested for real while the socket is not."""

    def test_sends_a_user_agent_because_github_answers_403_without_one(self):
        seen = {}

        def opener(req, timeout=None):
            seen["ua"] = req.get_header("User-agent")
            return _Resp(json.dumps(fixture("github_release.json")).encode())

        updater.fetch_latest(opener=opener)
        self.assertIn("StintLogger", seen["ua"] or "")

    def test_returns_the_asset_on_a_good_answer(self):
        def opener(req, timeout=None):
            return _Resp(json.dumps(fixture("github_release.json")).encode())

        self.assertEqual(updater.fetch_latest(opener=opener)["tag"], "v1.2.0")

    def test_a_network_error_is_not_an_update(self):
        def opener(req, timeout=None):
            raise OSError("no route to host")

        self.assertIsNone(updater.fetch_latest(opener=opener))

    def test_garbage_instead_of_json_is_not_an_update(self):
        def opener(req, timeout=None):
            return _Resp(b"<html>rate limited</html>")

        self.assertIsNone(updater.fetch_latest(opener=opener))


class TestGate(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def test_a_file_that_is_not_a_windows_binary_is_rejected(self):
        p = os.path.join(self.dir, "not.exe")
        with open(p, "wb") as fh:
            fh.write(b"<html>404 not found</html>")
        self.assertFalse(updater.looks_like_exe(p))

    def test_a_file_starting_with_mz_passes(self):
        p = os.path.join(self.dir, "yes.exe")
        with open(p, "wb") as fh:
            fh.write(b"MZ\x90\x00")
        self.assertTrue(updater.looks_like_exe(p))

    def test_a_missing_file_is_rejected(self):
        self.assertFalse(updater.looks_like_exe(os.path.join(self.dir, "gone.exe")))

    def test_version_is_read_out_of_the_programs_own_greeting(self):
        self.assertEqual(updater.version_from_output("StintLogger 1.2.0\n"), "1.2.0")

    def test_anything_else_on_stdout_is_no_version(self):
        for text in ("", "Traceback (most recent call last):", "StintLogger", "1.2.0"):
            self.assertIsNone(updater.version_from_output(text), text)

    def test_download_writes_the_file_and_checks_the_size(self):
        body = b"MZ" + b"\x00" * 100
        p = os.path.join(self.dir, "dl.exe")

        def opener(url, timeout=None):
            return _Resp(body)

        self.assertTrue(updater.download("https://example.invalid/x", p, len(body), opener))
        with open(p, "rb") as fh:
            self.assertEqual(fh.read(), body)

    def test_a_truncated_download_is_discarded(self):
        p = os.path.join(self.dir, "short.exe")

        def opener(url, timeout=None):
            return _Resp(b"MZ")

        self.assertFalse(updater.download("https://example.invalid/x", p, 999, opener))
        self.assertFalse(os.path.exists(p))


class _Resp:
    """Minimal stand-in for what urlopen returns: a context manager that reads."""

    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


if __name__ == "__main__":
    unittest.main()
