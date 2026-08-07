# Автооновлення StintLogger — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Логер сам перевіряє GitHub Releases, завантажує новішу збірку, переконується що вона справжня, підміняє себе і піднімається — або не робить нічого й лишається робочим.

**Architecture:** Уся логіка живе в новому модулі `updater.py` чистими функціями (парсинг версій, вибір asset-а, завантаження, гейт перевірки, підміна файлів) — так її можна накрити тестами без мережі й без справжніх exe. `stint_logger.pyw` лише викликає її з daemon-потоку й показує результат. Підміна робиться перейменуванням запущеного exe, без bat-хелпера: Windows не дає його перезаписати, але дає перейменувати.

**Tech Stack:** Python 3, тільки стандартна бібліотека (`urllib.request`, `json`, `subprocess`, `shutil`, `os`, `ctypes`), тести — `unittest`.

## Global Constraints

- **Спека:** `docs/superpowers/specs/2026-08-07-auto-update-design.md`. Розходження з нею — дефект плану, не імпровізація.
- **Тільки стандартна бібліотека.** Ні `requests`, ні `packaging`, ні `pytest`.
- **Windows-only**, як і решта застосунку.
- **Мережа ніколи не блокує запуск.** Перевірка — у daemon-потоці, таймаут 5 с, будь-яка помилка = тихо нічого не робимо.
- **Гейт перед підміною обов'язковий:** файл починається з `MZ` **і** запуск `<файл> --version` друкує саму ту версію, яку обіцяв реліз. Не так — оновлення скасовано, старий exe недоторканий.
- **`StintLogger.old.exe` видаляється лише після успішного старту нового.**
- **Ім'я asset-а в релізі — рівно `StintLogger.exe`.** Це контракт релізу, не припущення.
- **Заголовок `User-Agent` в запиті до GitHub обов'язковий** — без нього API віддає 403.
- **Single-instance у цьому застосунку — named mutex `StintLogger_singleton`** (`single_instance_ok()`, `stint_logger.pyw:870`), а не заголовок вікна. Вікно за назвою шукається лише щоб підняти наявне (`show_existing_window()`). Новий процес після оновлення мусить чекати звільнення **мьютекса**, тобто виходу старого процесу.
- **UI застосунку англійською**, README українською.
- **`APP_VERSION` може вже існувати:** його додає `docs/superpowers/plans/2026-08-06-sim-setup-skill.md` (Task 6) як `APP_VERSION = "1.1.0"`. Якщо константа вже у файлі — **не дублювати й не перейменовувати**. Якщо ще ні — додати рівно з цією назвою й значенням.

---

## File Structure

**Створюємо:**

| файл | відповідальність |
|---|---|
| `updater.py` | вся логіка оновлення: версії, реліз, завантаження, гейт, підміна файлів |
| `tests/test_update.py` | тести всього перерахованого, без мережі |
| `tests/fixtures/github_release.json` | обрізана відповідь GitHub API (справжня структура, вигадані URL) |

**Змінюємо:**

| файл | що саме |
|---|---|
| `stint_logger.pyw` | `APP_VERSION` (якщо ще немає), аргументи `--version` і `--after-update`, потік перевірки, рядок стану, пункт у треї, прибирання `.old` при старті |
| `README.md` | розділ про оновлення: як працює, контракт релізу, куди не класти exe |

`sim_shm.py`, аналізатори й `fuel_model.py` не чіпаємо — оновлення їх не стосується.

---

### Task 1: `APP_VERSION` і аргумент `--version`

Це фундамент гейта: перевірити завантажений exe можна лише тим, що він сам називає свою версію.

**Files:**
- Modify: `stint_logger.pyw` (константа біля `APP_NAME`, рядок ~37; ранній вихід у `main()`, рядок ~892)
- Create: `tests/test_update.py`

**Interfaces:**
- Produces: `stint_logger.APP_VERSION` (str, формат `X.Y.Z`); поведінка CLI `--version` → друкує `StintLogger <APP_VERSION>` і виходить з кодом 0, **не створюючи вікна й не торкаючись мьютекса**.

- [ ] **Step 1: Написати падаючий тест**

Створити `tests/test_update.py`:

```python
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
```

- [ ] **Step 2: Запустити, переконатися що падає**

Run: `python -m unittest tests.test_update -v`
Expected: FAIL — `AttributeError: module 'stint_logger' has no attribute 'APP_VERSION'` (або, якщо `APP_VERSION` уже додав план sim-setup — падає лише другий тест, бо `--version` не оброблений і процес відкриває вікно / зависає до таймауту).

- [ ] **Step 3: Реалізувати**

У `stint_logger.pyw` біля `APP_NAME` (рядок ~37), **тільки якщо константи ще немає**:

```python
APP_VERSION = "1.1.0"          # bumped: this build announces itself in state.json
```

У `main()` — найпершим рядком, до `single_instance_ok()`:

```python
def main():
    if "--version" in sys.argv:
        # the update gate runs exactly this on a downloaded build before trusting it
        print("{0} {1}".format(APP_NAME, APP_VERSION))
        return
    if not single_instance_ok():
```

- [ ] **Step 4: Запустити, переконатися що проходить**

Run: `python -m unittest tests.test_update -v`
Expected: PASS (2 тести)

Run: `python -m unittest discover -s tests`
Expected: OK, нічого не зламано

- [ ] **Step 5: Коміт**

```bash
git add stint_logger.pyw tests/test_update.py
git commit -m "Add APP_VERSION and a --version flag the update gate can trust"
```

---

### Task 2: Порівняння версій

**Files:**
- Create: `updater.py`
- Modify: `tests/test_update.py`

**Interfaces:**
- Produces: `updater.parse_version(text) -> tuple[int, ...] | None`, `updater.newer(latest, current) -> bool`

- [ ] **Step 1: Написати падаючий тест**

Дописати в `tests/test_update.py` (імпорт `import updater` — поряд з іншими на початку файлу):

```python
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
```

- [ ] **Step 2: Запустити, переконатися що падає**

Run: `python -m unittest tests.test_update -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'updater'`

- [ ] **Step 3: Реалізувати**

Створити `updater.py`:

```python
"""Self-update from GitHub Releases.

Everything here is deliberately a plain function over plain data: the network
call and the process launch are one thin line each, and the rest — version
maths, asset picking, the verification gate, the file swap — is testable without
a network or a real exe.
"""

import json
import os
import shutil
import subprocess
import urllib.request

REPO = "YuriiHeits/sim-telemetry"
ASSET_NAME = "StintLogger.exe"          # release contract, see README
API_URL = "https://api.github.com/repos/{0}/releases/latest".format(REPO)


def parse_version(text):
    """(1, 2, 0) from "v1.2" — None when it is not a version at all.

    Unparsable means "no update": a tag like "latest" must never be read as
    newer than what is running.
    """
    s = (text or "").strip()
    if s[:1] in ("v", "V"):
        s = s[1:]
    parts = s.split(".")
    if not s or len(parts) > 3:
        return None
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums)


def newer(latest, current):
    a, b = parse_version(latest), parse_version(current)
    if a is None or b is None:
        return False
    return a > b
```

- [ ] **Step 4: Запустити, переконатися що проходить**

Run: `python -m unittest tests.test_update -v`
Expected: PASS (8 тестів)

- [ ] **Step 5: Коміт**

```bash
git add updater.py tests/test_update.py
git commit -m "Compare release versions, treating an unparsable tag as no update"
```

---

### Task 3: Вибір asset-а з відповіді GitHub

**Files:**
- Modify: `updater.py`
- Create: `tests/fixtures/github_release.json`
- Modify: `tests/test_update.py`

**Interfaces:**
- Consumes: нічого з попередніх задач
- Produces: `updater.pick_asset(payload, asset_name=ASSET_NAME) -> dict | None` з ключами `tag` (str), `url` (str), `size` (int); `updater.fetch_latest(timeout=5.0, opener=urllib.request.urlopen) -> dict | None` (той самий словник)

- [ ] **Step 1: Написати падаючий тест**

Створити `tests/fixtures/github_release.json` (структура справжня, URL вигадані):

```json
{
  "tag_name": "v1.2.0",
  "name": "StintLogger v1.2.0",
  "draft": false,
  "prerelease": false,
  "assets": [
    {
      "name": "Source code (zip)",
      "size": 91234,
      "browser_download_url": "https://example.invalid/source.zip"
    },
    {
      "name": "StintLogger.exe",
      "size": 25897150,
      "browser_download_url": "https://example.invalid/StintLogger.exe"
    }
  ]
}
```

Дописати в `tests/test_update.py`:

```python
import json


def fixture(name):
    with open(os.path.join(ROOT, "tests", "fixtures", name), encoding="utf-8") as fh:
        return json.load(fh)


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
```

- [ ] **Step 2: Запустити, переконатися що падає**

Run: `python -m unittest tests.test_update -v`
Expected: FAIL — `AttributeError: module 'updater' has no attribute 'pick_asset'`

- [ ] **Step 3: Реалізувати**

Дописати в `updater.py`:

```python
def pick_asset(payload, asset_name=ASSET_NAME):
    """The tag and the exe URL, or None when this release is not usable."""
    try:
        tag = payload["tag_name"]
        for a in payload.get("assets") or []:
            if a.get("name") == asset_name:
                return {"tag": tag, "url": a["browser_download_url"],
                        "size": int(a.get("size") or 0)}
    except (KeyError, TypeError, ValueError):
        return None
    return None


def fetch_latest(timeout=5.0, opener=urllib.request.urlopen):
    """Ask GitHub about the latest release. None on any trouble at all —
    a logger that cannot reach the internet is a working logger.
    """
    req = urllib.request.Request(API_URL, headers={
        "User-Agent": "StintLogger",
        "Accept": "application/vnd.github+json",
    })
    try:
        with opener(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:
        return None
    return pick_asset(payload)
```

- [ ] **Step 4: Запустити, переконатися що проходить**

Run: `python -m unittest tests.test_update -v`
Expected: PASS (16 тестів)

- [ ] **Step 5: Коміт**

```bash
git add updater.py tests/fixtures/github_release.json tests/test_update.py
git commit -m "Find the release asset, with a User-Agent GitHub will answer"
```

---

### Task 4: Завантаження й гейт перевірки

**Files:**
- Modify: `updater.py`
- Modify: `tests/test_update.py`

**Interfaces:**
- Consumes: `updater.fetch_latest` (Task 3)
- Produces: `updater.update_dir() -> str`, `updater.looks_like_exe(path) -> bool`, `updater.version_from_output(text) -> str | None`, `updater.download(url, dest, expected_size, opener=urllib.request.urlopen) -> bool`, `updater.reports_version(path, expected_tag, run=subprocess.run) -> bool`

- [ ] **Step 1: Написати падаючий тест**

Дописати в `tests/test_update.py`:

```python
import tempfile


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
```

- [ ] **Step 2: Запустити, переконатися що падає**

Run: `python -m unittest tests.test_update -v`
Expected: FAIL — `AttributeError: module 'updater' has no attribute 'looks_like_exe'`

- [ ] **Step 3: Реалізувати**

Дописати в `updater.py`:

```python
def update_dir():
    """Downloads go to LOCALAPPDATA, never next to the exe: that folder can be
    read-only (Program Files) and we must not fail there."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "StintLogger", "update")
    os.makedirs(path, exist_ok=True)
    return path


def looks_like_exe(path):
    try:
        with open(path, "rb") as fh:
            return fh.read(2) == b"MZ"
    except Exception:
        return False


def version_from_output(text):
    """"1.2.0" out of "StintLogger 1.2.0" — None if that is not what we got."""
    parts = (text or "").strip().split()
    if len(parts) != 2 or parts[0] != "StintLogger":
        return None
    return parts[1] if parse_version(parts[1]) else None


def download(url, dest, expected_size, opener=urllib.request.urlopen):
    """True only when the whole file arrived. A partial file is deleted, not kept:
    a half-downloaded exe that passes no gate is still a landmine.
    """
    try:
        with opener(url, timeout=60) as resp:
            body = resp.read()
        if expected_size and len(body) != expected_size:
            raise ValueError("size mismatch")
        with open(dest, "wb") as fh:
            fh.write(body)
        return True
    except Exception:
        try:
            os.remove(dest)
        except OSError:
            pass
        return False


def reports_version(path, expected_tag, run=subprocess.run):
    """Make the downloaded build say who it is, and check the answer.

    This is the gate: without it, self-replacement means overwriting a working
    tool with whatever arrived over the network.
    """
    if not looks_like_exe(path):
        return False
    try:
        r = run([path, "--version"], capture_output=True, text=True, timeout=15)
    except Exception:
        return False
    got = version_from_output(r.stdout or "")
    return got is not None and parse_version(got) == parse_version(expected_tag)
```

Додати `import shutil` у тести, якщо його там ще немає (використовується в `setUp`).

- [ ] **Step 4: Запустити, переконатися що проходить**

Run: `python -m unittest tests.test_update -v`
Expected: PASS (23 тести)

- [ ] **Step 5: Коміт**

```bash
git add updater.py tests/test_update.py
git commit -m "Download the build and make it prove its version before we trust it"
```

---

### Task 5: Підміна файлів і прибирання

**Files:**
- Modify: `updater.py`
- Modify: `tests/test_update.py`

**Interfaces:**
- Consumes: `updater.looks_like_exe` (Task 4)
- Produces: `updater.old_path(target) -> str`, `updater.swap_in_place(new_path, target) -> bool`, `updater.cleanup_old(target) -> None`

- [ ] **Step 1: Написати падаючий тест**

Дописати в `tests/test_update.py`:

```python
class TestSwap(unittest.TestCase):
    """Windows refuses to overwrite a running exe but allows renaming it, which
    is the whole trick. Plain files stand in for the binaries here."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.target = os.path.join(self.dir, "StintLogger.exe")
        self.new = os.path.join(self.dir, "StintLogger-v1.2.0.exe")
        with open(self.target, "wb") as fh:
            fh.write(b"MZ old")
        with open(self.new, "wb") as fh:
            fh.write(b"MZ new")

    def read(self, p):
        with open(p, "rb") as fh:
            return fh.read()

    def test_new_build_takes_the_place_and_the_old_one_is_kept(self):
        self.assertTrue(updater.swap_in_place(self.new, self.target))
        self.assertEqual(self.read(self.target), b"MZ new")
        self.assertEqual(self.read(updater.old_path(self.target)), b"MZ old")
        self.assertFalse(os.path.exists(self.new))

    def test_a_leftover_old_file_does_not_block_the_swap(self):
        with open(updater.old_path(self.target), "wb") as fh:
            fh.write(b"MZ ancient")
        self.assertTrue(updater.swap_in_place(self.new, self.target))
        self.assertEqual(self.read(self.target), b"MZ new")

    def test_a_missing_new_file_leaves_everything_alone(self):
        os.remove(self.new)
        self.assertFalse(updater.swap_in_place(self.new, self.target))
        self.assertEqual(self.read(self.target), b"MZ old")
        self.assertFalse(os.path.exists(updater.old_path(self.target)))

    def test_cleanup_removes_the_old_build(self):
        updater.swap_in_place(self.new, self.target)
        updater.cleanup_old(self.target)
        self.assertFalse(os.path.exists(updater.old_path(self.target)))

    def test_cleanup_is_quiet_when_there_is_nothing_to_clean(self):
        updater.cleanup_old(self.target)  # must not raise
        self.assertTrue(os.path.exists(self.target))
```

- [ ] **Step 2: Запустити, переконатися що падає**

Run: `python -m unittest tests.test_update -v`
Expected: FAIL — `AttributeError: module 'updater' has no attribute 'swap_in_place'`

- [ ] **Step 3: Реалізувати**

Дописати в `updater.py`:

```python
def old_path(target):
    root, ext = os.path.splitext(target)
    return root + ".old" + ext


def swap_in_place(new_path, target):
    """Rename the running exe out of the way, move the new one in.

    Returns False and touches nothing when the new file is not there. If the
    move fails after the rename, the old build is put back: never leave the
    user without a working exe.
    """
    if not looks_like_exe(new_path):
        return False
    old = old_path(target)
    try:
        os.remove(old)
    except OSError:
        pass
    try:
        os.replace(target, old)
    except OSError:
        return False
    try:
        shutil.move(new_path, target)
    except Exception:
        try:
            os.replace(old, target)
        except OSError:
            pass
        return False
    return True


def cleanup_old(target):
    """Drop the previous build. Failing is fine — an antivirus may still hold
    the file, and the next start will try again."""
    try:
        os.remove(old_path(target))
    except OSError:
        pass
```

- [ ] **Step 4: Запустити, переконатися що проходить**

Run: `python -m unittest tests.test_update -v`
Expected: PASS (28 тестів)

Run: `python -m unittest discover -s tests`
Expected: OK

- [ ] **Step 5: Коміт**

```bash
git add updater.py tests/test_update.py
git commit -m "Swap the new build in by renaming the old one, with a rollback"
```

---

### Task 6: Обв'язка в застосунку

**Files:**
- Modify: `stint_logger.pyw` (імпорт; `main()` рядок ~892; `App.__init__` де будується UI; `_setup_tray()` рядок ~746)
- Modify: `tests/test_update.py`

**Interfaces:**
- Consumes: `updater.fetch_latest`, `updater.newer`, `updater.update_dir`, `updater.download`, `updater.reports_version`, `updater.swap_in_place`, `updater.cleanup_old`, `updater.old_path`
- Produces: `updater.run_update(current_version, target, say)` — одна функція, яку викликає і потік при старті, і пункт у треї. `say(text)` — колбек для рядка стану; повертає `True`, якщо підміна відбулася і треба перезапускатися.

- [ ] **Step 1: Написати падаючий тест**

Дописати в `tests/test_update.py`:

```python
class TestRunUpdate(unittest.TestCase):
    """The whole decision chain, with the two impure steps injected: no network,
    no process launch, real files."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.target = os.path.join(self.dir, "StintLogger.exe")
        with open(self.target, "wb") as fh:
            fh.write(b"MZ old")
        self.said = []

    def body(self):
        return b"MZ" + b"\x00" * 50

    def opener(self, url, timeout=None):
        return _Resp(self.body())

    def release(self, tag="v1.2.0"):
        return {"tag": tag, "url": "https://example.invalid/StintLogger.exe",
                "size": len(self.body())}

    def test_a_newer_release_that_passes_the_gate_is_installed(self):
        done = updater.run_update("1.1.0", self.target, self.said.append,
                                  fetch=lambda: self.release(),
                                  opener=self.opener,
                                  verify=lambda path, tag: True)
        self.assertTrue(done)
        with open(self.target, "rb") as fh:
            self.assertEqual(fh.read(), self.body())

    def test_the_gate_refusing_leaves_the_old_build_in_place(self):
        done = updater.run_update("1.1.0", self.target, self.said.append,
                                  fetch=lambda: self.release(),
                                  opener=self.opener,
                                  verify=lambda path, tag: False)
        self.assertFalse(done)
        with open(self.target, "rb") as fh:
            self.assertEqual(fh.read(), b"MZ old")
        self.assertFalse(os.path.exists(updater.old_path(self.target)))

    def test_the_same_version_downloads_nothing(self):
        def fetch():
            return self.release("v1.1.0")

        def boom(*a, **k):
            raise AssertionError("must not download")

        self.assertFalse(updater.run_update("1.1.0", self.target, self.said.append,
                                            fetch=fetch, opener=boom,
                                            verify=lambda p, t: True))

    def test_no_release_information_is_not_an_error(self):
        self.assertFalse(updater.run_update("1.1.0", self.target, self.said.append,
                                            fetch=lambda: None,
                                            opener=self.opener,
                                            verify=lambda p, t: True))
        self.assertTrue(self.said)  # the user is told the check did not work out
```

- [ ] **Step 2: Запустити, переконатися що падає**

Run: `python -m unittest tests.test_update -v`
Expected: FAIL — `AttributeError: module 'updater' has no attribute 'run_update'`

- [ ] **Step 3: Реалізувати**

Дописати в `updater.py`:

```python
def run_update(current_version, target, say, fetch=fetch_latest,
               opener=urllib.request.urlopen, verify=reports_version):
    """Check, download, verify, swap. True means "restart into the new build".

    fetch/opener/verify are injected so the decision chain can be tested without
    a network and without launching anything.
    """
    rel = fetch()
    if rel is None:
        say("update check failed")
        return False
    if not newer(rel["tag"], current_version):
        say("up to date")
        return False
    say("downloading " + rel["tag"])
    dest = os.path.join(update_dir(), "StintLogger-{0}.exe".format(rel["tag"]))
    if not download(rel["url"], dest, rel["size"], opener):
        say("download failed")
        return False
    if not verify(dest, rel["tag"]):
        say("bad download, ignored")
        try:
            os.remove(dest)
        except OSError:
            pass
        return False
    if not swap_in_place(dest, target):
        say("cannot replace the exe here")
        return False
    say("updated to " + rel["tag"] + ", restarting")
    return True
```

У `stint_logger.pyw` — імпорт поряд з іншими локальними:

```python
import updater
```

У `main()`, після обробки `--version` і **перед** `single_instance_ok()`:

```python
    if "--after-update" in sys.argv:
        # the build we replaced is still exiting; its mutex is what we wait for
        for _ in range(20):
            if single_instance_ok():
                break
            time.sleep(0.5)
```

Одразу після `App(root)` у `main()`:

```python
    updater.cleanup_old(sys.executable)   # the build we replaced, if any
```

В `App.__init__` — власний рядок для версії й повідомлень оновлення, **відразу
після `self.savedlbl`** (рядок ~487). Не використовувати `self.neckhint`: блок
NeckFX ховається під ACC (`self.neckwrap.pack_forget()`, рядок ~503), і
повідомлення про оновлення були б невидимі в половині випадків.

```python
        self.updlbl = self._lab(r, "v" + APP_VERSION, fg=MUTED, font=("Consolas", 9))
        self.updlbl.pack()
```

Там же, наприкінці `__init__`, — перевірка в потоці. Лише для frozen-збірки: у
dev-запуску `sys.executable` це `python.exe`, і підміняти інтерпретатор не треба.

```python
        if getattr(sys, "frozen", False):
            threading.Thread(target=self._check_update, daemon=True).start()
```

Методи в `App`:

```python
    def _check_update(self):
        """Runs off the UI thread: the network must never hold up the window."""
        if updater.run_update(APP_VERSION, sys.executable,
                              lambda t: self.root.after(0, self._say_update, t)):
            self.root.after(0, self._restart_into_new_build)

    def _say_update(self, text):
        self.updlbl.config(text="v" + APP_VERSION + "  ·  " + text)

    def _restart_into_new_build(self):
        try:
            subprocess.Popen([sys.executable, "--after-update"])
        except Exception:
            return
        self.on_close()
```

`import subprocess` і `import time` — додати до імпортів, якщо їх ще немає.

У `_setup_tray()`, у головне меню (не в підменю NeckFX):

```python
            pystray.MenuItem("Check for updates",
                             lambda i, it: threading.Thread(
                                 target=self._check_update, daemon=True).start()),
```

Там же — версія в підказці іконки: третій аргумент `pystray.Icon` це і є tooltip
(рядок ~768).

```python
        self.tray = pystray.Icon(APP_REG_NAME, self._tray_image(),
                                 "{0} {1}".format(APP_NAME, APP_VERSION), menu)
```

- [ ] **Step 4: Запустити, переконатися що проходить**

Run: `python -m unittest tests.test_update -v`
Expected: PASS (32 тести)

Run: `python -m unittest discover -s tests`
Expected: OK

Run: `python tests/smoke_gui.py`
Expected: закінчується `OK` — вікно будується, нічого не впало

- [ ] **Step 5: Коміт**

```bash
git add updater.py stint_logger.pyw tests/test_update.py
git commit -m "Check for updates in the background and restart into the new build"
```

---

### Task 7: README, контракт релізу і жива перевірка

**Files:**
- Modify: `README.md` (новий розділ після «Зібрати exe самому»)

- [ ] **Step 1: Дописати README**

```markdown
## Оновлення

Логер сам перевіряє [Releases](../../releases) при старті (і будь-коли — пункт
`Check for updates` у треї). Якщо там новіша версія, він її завантажує, і
**перед підміною змушує завантажений файл назвати свою версію** (`--version`).
Не назвав, або це взагалі не exe — оновлення скасовується, а робоча збірка
лишається недоторканою.

Стара збірка не видаляється одразу: вона лежить поряд як `StintLogger.old.exe`
доки нова не піднялася. Якщо щось пішло не так — перейменуй її назад.

Перевірка ніколи не блокує запуск: без інтернету логер працює як завжди.

**Контракт релізу:** asset у релізі має називатися рівно `StintLogger.exe`, а тег —
`vX.Y.Z`. Інакше оновлення просто не знайдеться.

**Не кладіть exe у `Program Files`:** підміна файлу там впаде на правах, і
оновлення тихо скасується. Будь-яка тека користувача підходить.
```

- [ ] **Step 2: Перевірити пакування**

Run:
```bash
python -m PyInstaller --noconfirm --onefile --windowed --icon stint_logger.ico ^
  --name StintLogger --distpath _build --workpath _build/work stint_logger.pyw
```
Expected: `Build complete!`

Run: `_build\StintLogger.exe --version`
Expected: друкує `StintLogger 1.1.0` і виходить — **у frozen-збірці, а не лише в python**. Це і є гейт; якщо onefile-збірка не друкує в stdout (windowed-режим), гейт треба переробити на файл-маркер, а не на stdout — це відкритий ризик і його треба перевірити саме тут.

- [ ] **Step 3: Коміт**

```bash
git add README.md
git commit -m "README: how updating works and what a release must contain"
```

- [ ] **Step 4: Жива перевірка (руками, не автоматизується)**

Це те, чого тести не покривають. Порядок:

1. Зібрати exe з `APP_VERSION = "1.1.0"`, покласти в теку користувача, запустити.
2. Підняти `APP_VERSION` до `1.2.0`, зібрати ще раз, викласти реліз `v1.2.0` з asset-ом `StintLogger.exe`.
3. У запущеній 1.1.0 натиснути `Check for updates`.
4. Очікувано: рядок стану пише `downloading v1.2.0` → `updated to v1.2.0, restarting`, вікно закривається й піднімається знову, у ньому версія 1.2.0, `StintLogger.old.exe` зникає протягом секунд після старту.
5. Перевірити автозапуск: якщо в реєстрі був `HKCU\...\Run\StintLogger`, він мусить і далі вести на той самий шлях і працювати після оновлення.
6. Перевірити відкат: перейменувати `StintLogger.old.exe` назад і переконатися, що стара збірка запускається.

Записати результат кроків 4–6 у коміт-повідомлення або в issue — це єдина перевірка, яка доводить, що фіча працює цілком.

---

## Відомі ризики цього плану

- **`--version` у windowed onefile-збірці може не мати stdout.** PyInstaller з `--windowed` збирає GUI-застосунок без консолі, і `print` там може піти в нікуди. Гейт на цьому тримається, тому Task 7 Step 2 перевіряє це **першим**. Якщо stdout недоступний — заміна: `--version` записує версію у файл, шлях до якого передається аргументом (`--version-to <файл>`), і гейт читає той файл. Тести Task 1 і Task 4 тоді треба переписати під цей контракт.
- **Антивірус на щойно завантаженому неподписаному exe.** Гейт не пройде, оновлення скасується — саме те, що потрібно. Окремо не лікуємо.
- **`sys.executable` у dev-запуску — це `python.exe`.** Тому перевірка вішається тільки під `getattr(sys, "frozen", False)`, інакше застосунок спробував би підмінити інтерпретатор.
