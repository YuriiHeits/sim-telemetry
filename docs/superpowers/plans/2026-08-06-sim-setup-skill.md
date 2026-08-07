# sim-setup Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Скіл для Claude Code і Codex, який сам знаходить логи StintLogger, ставить діагноз через наявні аналізатори і править сетапи ACC за правилами користувача.

**Architecture:** Скіл живе в цьому ж репозиторії (`skills/sim-setup/`) і викликає аналізатори з того ж клону, а не носить копію їхньої математики. Логер пише машинний вказівник `~/.stintlogger/state.json`, скіл його читає — так одна половина не вгадує те, що друга знає. Виявлення шляхів і перевірка готовності — скрипти, а не інструкції прозою, щоб результат був відтворюваним. Особисті дані (профіль, правила, журнал) — у `~/.sim-coach/`, поза репозиторієм.

**Tech Stack:** Python 3 (тільки стандартна бібліотека), `unittest`, Markdown зі YAML-frontmatter за стандартом agentskills.io.

## Global Constraints

- **Windows-only.** `winreg`, `ctypes.windll`, named shared memory. Не вводити залежностей від POSIX.
- **Тільки стандартна бібліотека.** Ні `pytest`, ні `psutil`, ні `pyyaml`. Тести — `unittest`.
- **Спека:** `docs/superpowers/specs/2026-08-06-sim-setup-skill-design.md`. Розходження з нею — дефект плану, не імпровізація.
- **`SKILL.md` англійською; вивід користувачу — українською.** Це прописано в самих інструкціях скіла.
- **Особисте ніколи не в репозиторії.** `~/.sim-coach/` і `~/.stintlogger/` не комітяться і не згадуються в `.gitignore` (вони поза деревом).
- **Похідні поля ACC не правити:** `staticCamber`, `toeOutLinear`, `rodLength`. Спроба — помилка, не попередження.
- **Крок зміни:** `fine` — 1–2 кліки; `coarse` — з названим абсолютним значенням і попередженням, що діапазони по машинах невідомі.
- **Нічого не качати й не запускати без явної згоди користувача.**
- **Аналізатори мусять і далі працювати самостійно** (`python trail_report.py <файл>`), скіл їх не підміняє.
- Тестова ізоляція через змінні оточення: `STINTLOGGER_STATE_DIR`, `SIM_COACH_HOME`, `STINT_LOGS`. Жоден тест не торкається справжніх `~/.stintlogger` чи `~/.sim-coach`.

---

## File Structure

**Створюємо:**

| файл | відповідальність |
|---|---|
| `logger_state.py` | запис і читання `~/.stintlogger/state.json`. Один модуль на обидві половини |
| `logs_dir.py` | де лежать CSV: єдиний порядок пошуку для аналізаторів і для скіла |
| `skills/sim-setup/SKILL.md` | інструкції скіла (англійською) |
| `skills/sim-setup/references/acc-setup-format.md` | структура ACC-сетапу: що кліки, що похідне |
| `skills/sim-setup/references/diagnosis.md` | симптом у телеметрії → параметр сетапу |
| `skills/sim-setup/scripts/read_setup.py` | показати сетап у читабельному вигляді |
| `skills/sim-setup/scripts/patch_setup.py` | застосувати зміни: бекап, запис, відмова на похідних |
| `skills/sim-setup/scripts/discover.py` | перевірка готовності + засів `~/.sim-coach/` |
| `tests/fixtures/acc_setup.json` | синтетичний ACC-сетап (не особистий файл автора) |
| `tests/test_logger_state.py` | тести вказівника |
| `tests/test_logs_dir.py` | тести порядку пошуку |
| `tests/test_setup_io.py` | тести читання й правки сетапів |
| `tests/test_discover.py` | тести перевірки готовності |
| `tests/synth_log.py` | генератор синтетичного ACC-логу для тестів |
| `tests/test_analyzer_defaults.py` | аналізатори знаходять логи без аргументів |

**Змінюємо:**

| файл | що саме |
|---|---|
| `stint_logger.pyw` | `APP_VERSION`, запис `state.json` при старті й на зміні гри |
| `trail_report.py`, `drift_report.py`, `analyze_ac.py`, `race_report.py` | дефолтна папка логів через `logs_dir.resolve()` |
| `README.md` | розділ про скіл: установка в Claude Code і Codex, що потрібно, де особисті дані |

`summarize.py` і `brno_summary.py` не чіпаємо: вони глобають від поточної папки (`glob.glob('**/*.csv')`), а не від себе, і це окремий сценарій «швидко подивитись у поточному каталозі».

---

### Task 1: Вказівник логера (`logger_state.py`)

**Files:**
- Create: `logger_state.py`
- Test: `tests/test_logger_state.py`

**Interfaces:**
- Consumes: нічого
- Produces: `logger_state.state_dir() -> str`, `logger_state.state_path() -> str`, `logger_state.write_state(logs_dir: str, version: str, game: str|None = None, when: str|None = None) -> bool`, `logger_state.read_state() -> dict|None`

- [ ] **Step 1: Write the failing test**

`tests/test_logger_state.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/sim-telemetry && python -m unittest tests.test_logger_state -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'logger_state'`

- [ ] **Step 3: Write minimal implementation**

`logger_state.py`:

```python
"""Machine-level pointer to this logger install, so other tools can find it.

This is not a log and not telemetry: it holds the address of the telemetry
folder plus who wrote it and when. Do not confuse it with logger.cfg, which
sits next to the executable and belongs to that one copy (portable settings).
This file is per-machine and exists only for discovery.

Written on startup and on game change - rare events, never from the 20 ms poll.
If several copies of the logger are installed, the one that ran last wins,
which is the semantics a consumer wants anyway.
"""

import json
import os
import time

ENV_DIR = "STINTLOGGER_STATE_DIR"   # tests point this at a temp folder


def state_dir():
    return os.environ.get(ENV_DIR) or os.path.join(os.path.expanduser("~"), ".stintlogger")


def state_path():
    return os.path.join(state_dir(), "state.json")


def write_state(logs_dir, version, game=None, when=None):
    """Best effort. A failure here must never take the logger down with it."""
    data = {
        "logs_dir": (logs_dir or "").replace("\\", "/"),
        "version": version,
        "last_run": when or time.strftime("%Y-%m-%dT%H:%M:%S"),
        "last_game": game,
    }
    try:
        os.makedirs(state_dir(), exist_ok=True)
        with open(state_path(), "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        return True
    except Exception:
        return False


def read_state():
    """The state, or None when absent, unreadable, or missing its one required key."""
    try:
        with open(state_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return None
    if not isinstance(data, dict) or not data.get("logs_dir"):
        return None
    return data
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_logger_state -v`
Expected: 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add logger_state.py tests/test_logger_state.py
git commit -m "Add the machine-level pointer other tools use to find the logger"
```

---

### Task 2: Логер пише вказівник

**Files:**
- Modify: `stint_logger.pyw` (додати `APP_VERSION`, імпорт, два виклики)
- Test: `tests/test_logger_state.py` (додати один тест)

**Interfaces:**
- Consumes: `logger_state.write_state(...)` з Task 1
- Produces: `stint_logger.APP_VERSION` (str) — використовується в `state.json` і в README

- [ ] **Step 1: Write the failing test**

Додати в `tests/test_logger_state.py`:

```python
class TestLoggerWritesState(unittest.TestCase):
    """The logger must announce itself, and must carry a version so a consumer
    can tell whether the CSV columns it needs exist yet."""

    def test_logger_exposes_a_version(self):
        import importlib.util
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spec = importlib.util.spec_from_file_location(
            "stint_logger", os.path.join(root, "stint_logger.pyw"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertRegex(mod.APP_VERSION, r"^\d+\.\d+\.\d+$")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_logger_state -v`
Expected: FAIL — `AttributeError: module 'stint_logger' has no attribute 'APP_VERSION'`

**Якщо тест одразу проходить** — це не помилка. План автооновлення
(`2026-08-07-auto-update.md`) вводить ту саму константу, і якщо він виконався
першим, `APP_VERSION` уже у файлі. Тоді не додавай другу: константа одна на файл,
дві розійшлися б за тиждень. Запиши це у звіт і переходь до обв'язки `state.json`,
яка й є суттю цієї задачі.

- [ ] **Step 3: Write minimal implementation**

У `stint_logger.pyw` після `APP_REG_NAME`:

```python
APP_VERSION = "1.1.0"          # bumped: this build announces itself in state.json
```

Додати імпорт біля `import sim_shm`:

```python
import logger_state
```

У `App.__init__`, відразу після `self._build()` (тобто коли `OUT_DIR` уже відомий, а вікно вже є):

```python
        logger_state.write_state(OUT_DIR, APP_VERSION)
```

У `App._apply_game`, у самому кінці методу (після `self._fit()`):

```python
        logger_state.write_state(OUT_DIR, APP_VERSION, game)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover tests -v`
Expected: усі PASS (8 у `test_logger_state`, решта як були)

- [ ] **Step 5: Verify by running the logger for real**

```bash
python -c "import logger_state, json; print(json.dumps(logger_state.read_state(), indent=2))"
```
Спочатку може бути `null`. Запустити логер (`python stint_logger.pyw`), закрити, повторити команду.
Expected: `logs_dir` вказує на папку репозиторію, `version` — `1.1.0`, `last_run` — щойно.

- [ ] **Step 6: Commit**

```bash
git add stint_logger.pyw tests/test_logger_state.py
git commit -m "Logger announces its logs folder and version on startup and game change"
```

---

### Task 3: Один порядок пошуку логів (`logs_dir.py`)

**Files:**
- Create: `logs_dir.py`
- Test: `tests/test_logs_dir.py`

**Interfaces:**
- Consumes: `logger_state.read_state()` з Task 1
- Produces: `logs_dir.csv_count(path) -> int`, `logs_dir.resolve() -> dict` з ключами `path` (str|None), `source` (str|None), `csv_count` (int), `tried` (list of dict з `source`/`path`/`csv_count`)

- [ ] **Step 1: Write the failing test**

`tests/test_logs_dir.py`:

```python
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import logs_dir


def make_csv(folder, name="a.csv"):
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, name), "w", encoding="utf-8") as fh:
        fh.write("t,lap\n0.0,0\n")


class TestResolveOrder(unittest.TestCase):
    """The order is the contract: an explicit override beats what the logger
    said, which beats a remembered answer, which beats the fallbacks."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._saved = {k: os.environ.get(k) for k in
                       ("STINT_LOGS", "STINTLOGGER_STATE_DIR", "SIM_COACH_HOME")}
        os.environ["STINTLOGGER_STATE_DIR"] = os.path.join(self._tmp.name, "state")
        os.environ["SIM_COACH_HOME"] = os.path.join(self._tmp.name, "coach")
        os.environ.pop("STINT_LOGS", None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()

    def path(self, name):
        return os.path.join(self._tmp.name, name)

    def test_env_var_wins(self):
        make_csv(self.path("fromenv"))
        make_csv(self.path("fromstate"))
        os.environ["STINT_LOGS"] = self.path("fromenv")
        self._write_state(self.path("fromstate"))
        got = logs_dir.resolve()
        self.assertEqual(got["source"], "STINT_LOGS")
        self.assertEqual(got["path"], self.path("fromenv"))
        self.assertEqual(got["csv_count"], 1)

    def test_state_json_is_next(self):
        make_csv(self.path("fromstate"))
        self._write_state(self.path("fromstate"))
        got = logs_dir.resolve()
        self.assertEqual(got["source"], "state.json")

    def test_remembered_answer_is_third(self):
        make_csv(self.path("remembered"))
        coach = os.environ["SIM_COACH_HOME"]
        os.makedirs(coach, exist_ok=True)
        with open(os.path.join(coach, "config.json"), "w", encoding="utf-8") as fh:
            json.dump({"logs_dir": self.path("remembered")}, fh)
        got = logs_dir.resolve()
        self.assertEqual(got["source"], "config.json")

    def test_nothing_found_reports_what_was_tried(self):
        got = logs_dir.resolve()
        self.assertIsNone(got["path"])
        self.assertEqual(got["csv_count"], 0)
        self.assertTrue(len(got["tried"]) >= 2)
        self.assertTrue(all("path" in t and "csv_count" in t for t in got["tried"]))

    def test_empty_override_is_reported_not_silently_skipped(self):
        os.environ["STINT_LOGS"] = self.path("empty")
        os.makedirs(self.path("empty"), exist_ok=True)
        got = logs_dir.resolve()
        sources = [t["source"] for t in got["tried"]]
        self.assertIn("STINT_LOGS", sources)
        self.assertEqual([t for t in got["tried"] if t["source"] == "STINT_LOGS"][0]["csv_count"], 0)

    def test_counts_csv_recursively(self):
        make_csv(os.path.join(self.path("deep"), "track", "car", "day"))
        self.assertEqual(logs_dir.csv_count(self.path("deep")), 1)

    def test_missing_folder_counts_zero(self):
        self.assertEqual(logs_dir.csv_count(self.path("nope")), 0)

    def _write_state(self, logs):
        import logger_state
        logger_state.write_state(logs, "1.1.0")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_logs_dir -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'logs_dir'`

- [ ] **Step 3: Write minimal implementation**

`logs_dir.py`:

```python
"""Where the telemetry CSVs live.

One implementation for everybody: the analyzers use it for their default, and
the skill's discover.py uses it for the readiness report. Two orders of search
would drift apart, and the whole point of the logger writing state.json is that
nobody has to guess.

Order, first hit with CSVs wins:
  1. STINT_LOGS         - a deliberate override by the user, so it outranks all
  2. state.json         - what the logger itself said (logger_state)
  3. config.json        - an answer the user already gave the skill once
  4. Documents/StintLogger - the logger's own fallback folder
  5. this folder        - the repo checkout, when the logger runs from source
"""

import glob
import json
import os

import logger_state

ENV_LOGS = "STINT_LOGS"
ENV_COACH = "SIM_COACH_HOME"


def coach_home():
    return os.environ.get(ENV_COACH) or os.path.join(os.path.expanduser("~"), ".sim-coach")


def csv_count(path):
    if not path or not os.path.isdir(path):
        return 0
    return len(glob.glob(os.path.join(path, "**", "*.csv"), recursive=True))


def _remembered():
    try:
        with open(os.path.join(coach_home(), "config.json"), "r", encoding="utf-8") as fh:
            return json.load(fh).get("logs_dir")
    except Exception:
        return None


def candidates():
    out = []
    env = os.environ.get(ENV_LOGS)
    if env:
        out.append(("STINT_LOGS", env))
    state = logger_state.read_state()
    if state:
        out.append(("state.json", state["logs_dir"]))
    remembered = _remembered()
    if remembered:
        out.append(("config.json", remembered))
    out.append(("Documents/StintLogger",
                os.path.join(os.path.expanduser("~"), "Documents", "StintLogger")))
    out.append(("repo folder", os.path.dirname(os.path.abspath(__file__))))
    return out


def resolve():
    """First candidate that actually holds CSVs.

    Candidates that hold nothing are still reported in `tried`: an STINT_LOGS
    pointing at an empty folder is a user error worth naming, not something to
    skip in silence.
    """
    tried = []
    for source, path in candidates():
        n = csv_count(path)
        tried.append({"source": source, "path": path, "csv_count": n})
        if n:
            return {"path": path, "source": source, "csv_count": n, "tried": tried}
    return {"path": None, "source": None, "csv_count": 0, "tried": tried}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_logs_dir -v`
Expected: 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add logs_dir.py tests/test_logs_dir.py
git commit -m "Add one search order for the telemetry folder, shared by all consumers"
```

---

### Task 4: Аналізатори беруть папку логів звідти ж

**Files:**
- Modify: `trail_report.py:18-23`, `drift_report.py:9-11`, `analyze_ac.py:8-10`, `race_report.py:9-11`
- Create: `tests/synth_log.py`, `tests/test_analyzer_defaults.py`

**Interfaces:**
- Consumes: `logs_dir.resolve()` з Task 3
- Produces: нічого нового; змінюється лише дефолт, коли шлях не передано аргументом

- [ ] **Step 1: Подивитись, що саме там зараз**

Run: `grep -n "os.path.dirname(os.path.abspath(__file__))" trail_report.py drift_report.py analyze_ac.py race_report.py`
Expected: по одному входженню в кожному — рядок, який робить папку скрипта коренем пошуку.

- [ ] **Step 2: Замінити дефолт у кожному з чотирьох**

У кожному файлі замінити рядок

```python
folder = os.path.dirname(os.path.abspath(__file__))
```

на

```python
import logs_dir
# Logs are usually not next to this script: the logger writes wherever it runs
# from. STINT_LOGS or the logger's own state.json say where they are.
folder = logs_dir.resolve()["path"] or os.path.dirname(os.path.abspath(__file__))
```

`logs_dir` лежить у тій самій папці, що й аналізатор, а Python сам додає папку
скрипта в `sys.path` — тому `sys.path.insert` тут не потрібен. `sys` уже
імпортований у всіх чотирьох файлах.

У `trail_report.py` рядок з `folder` стоїть перед `args = sys.argv[1:]` — порядок не змінювати, явний аргумент і далі має пріоритет над дефолтом.

- [ ] **Step 3: Написати автоматичний тест на дефолт**

Поведінку змінюємо — значить її треба перевіряти тестом, а не тільки руками.
Фікстуру не комітимо (справжній лог — мегабайти), а генеруємо в тимчасову папку.

`tests/synth_log.py`:

```python
"""Write a synthetic ACC log that the analyzers can actually chew on.

Not committed as a file: a real stint is megabytes. Generated per test run
instead, with a shape close enough to a real session that the analyzers reach
their normal code paths - braking, cornering, several laps.
"""

import csv
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sim_shm

HZ = 50
LAP_S = 60
LAPS = 3


def write(folder, name="synthetic_ACC_PRACTICE.csv"):
    os.makedirs(folder, exist_ok=True)
    cols = sim_shm.cols_for(sim_shm.ACC)
    path = os.path.join(folder, name)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for lap in range(LAPS):
            for i in range(LAP_S * HZ):
                t = lap * LAP_S + i / float(HZ)
                w.writerow(_row(cols, t, lap))
    return path


def _row(cols, t, lap):
    phase = (t % 10.0) / 10.0
    braking = 1.0 if 0.05 < phase < 0.25 else 0.0
    steer = math.sin(phase * math.pi * 2) * 0.6
    speed = 240 - 120 * braking - 40 * abs(steer)
    d = dict((c, "0") for c in cols)
    d.update({
        "t": "{0:.3f}".format(t), "lap": lap,
        "pos": "{0:.5f}".format((t % LAP_S) / LAP_S),
        "speed_kmh": "{0:.2f}".format(speed), "rpm": int(3000 + speed * 20),
        "gear": max(1, int(speed // 40)),
        "gas": "{0:.3f}".format(0.0 if braking else min(1.0, 0.4 + phase)),
        "brake": "{0:.3f}".format(braking * 0.8),
        "steer": "{0:.4f}".format(steer),
        "gx": "{0:.3f}".format(-1.8 * braking), "gy": "0.100",
        "gz": "{0:.3f}".format(steer * 1.5),
        "tc": "0.00", "abs": "0.00", "fuel": "{0:.2f}".format(60 - t * 0.03),
        "inpit": 0, "last_ms": 60000, "best_ms": 59500,
        "session": "PRACTICE", "race_pos": 4,
        "heading": "{0:.5f}".format(math.sin(t / 5.0)),
        "vel_x": "{0:.4f}".format(speed / 3.6 * math.cos(steer)),
        "vel_y": "0.0000",
        "vel_z": "{0:.4f}".format(speed / 3.6 * math.sin(steer) * 0.2),
        "ideal_line": 0, "valid_lap": 1,
        "fuel_x_lap": "2.850", "fuel_est_laps": "18.00",
    })
    for i, wheel in enumerate(("fl", "fr", "rl", "rr")):
        d["slip_" + wheel] = "{0:.3f}".format(abs(steer) * 0.4)
        d["press_" + wheel] = "27.6"
        d["ttemp_" + wheel] = "84.0"
        d["susp_" + wheel] = "0.0300"
        d["btemp_" + wheel] = "{0:.1f}".format(300 + 200 * braking)
    return [d[c] for c in cols]
```

`tests/test_analyzer_defaults.py`:

```python
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import synth_log

ANALYZERS = ["trail_report.py", "drift_report.py", "analyze_ac.py", "race_report.py"]


class TestAnalyzerDefaults(unittest.TestCase):
    """Run with no arguments at all: the analyzers must find logs where the
    logger writes them, not only next to their own file. Before this change they
    died with IndexError on an empty glob."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.logs = os.path.join(cls._tmp.name, "logs", "spa", "test_gt3", "2026-08-06")
        synth_log.write(cls.logs)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _run(self, script, cwd, logs):
        env = dict(os.environ)
        env["STINT_LOGS"] = logs
        env["STINTLOGGER_STATE_DIR"] = os.path.join(self._tmp.name, "nostate")
        env["SIM_COACH_HOME"] = os.path.join(self._tmp.name, "nocoach")
        return subprocess.run([sys.executable, os.path.join(ROOT, script)],
                              cwd=cwd, env=env, capture_output=True, text=True,
                              timeout=120)

    def test_each_analyzer_runs_from_an_unrelated_directory(self):
        for script in ANALYZERS:
            with self.subTest(script=script):
                done = self._run(script, self._tmp.name, os.path.dirname(
                    os.path.dirname(os.path.dirname(self.logs))))
                self.assertEqual(done.returncode, 0,
                                 "{0} failed:
{1}".format(script, done.stderr[-800:]))
                self.assertTrue(done.stdout.strip(), script + " printed nothing")

    def test_explicit_path_still_wins(self):
        csv_path = os.path.join(self.logs, "synthetic_ACC_PRACTICE.csv")
        env = dict(os.environ)
        env["STINT_LOGS"] = os.path.join(self._tmp.name, "empty")
        done = subprocess.run([sys.executable, os.path.join(ROOT, "trail_report.py"), csv_path],
                              cwd=self._tmp.name, env=env, capture_output=True,
                              text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr[-800:])
        self.assertIn("synthetic_ACC_PRACTICE.csv", done.stdout)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m unittest tests.test_analyzer_defaults -v`
Expected: 2 tests PASS. Якщо `test_each_analyzer_runs_from_an_unrelated_directory`
падає з `IndexError`, значить дефолт у якомусь з чотирьох файлів не замінений.

- [ ] **Step 5: Перевірити, що явний аргумент і далі працює**

```bash
F=$(python -c "import logs_dir,glob,os; p=logs_dir.resolve()['path']; print(sorted(glob.glob(os.path.join(p,'**','*.csv'),recursive=True))[-1])")
python trail_report.py "$F" | tail -3
python drift_report.py "$F" | tail -3
```
Expected: обидва друкують зведення без винятків.

- [ ] **Step 6: Перевірити дефолт із папки, де CSV немає**

```bash
mkdir -p /tmp/elsewhere && cd /tmp/elsewhere
STINT_LOGS="" python ~/sim-telemetry/analyze_ac.py 2>&1 | tail -2
```
Expected: працює через `state.json` (логер уже його записав у Task 2), а не падає з `IndexError: list index out of range`.

- [ ] **Step 7: Перевірити явний `STINT_LOGS` на шлях поза репо (крит. 8.4)**

```bash
mkdir -p /tmp/logs-elsewhere && cp "$F" /tmp/logs-elsewhere/
cd /tmp && STINT_LOGS=/tmp/logs-elsewhere python ~/sim-telemetry/race_report.py 2>&1 | head -3
```
Expected: читає файл із `/tmp/logs-elsewhere`, а не з репозиторію.

- [ ] **Step 8: Commit**

```bash
cd ~/sim-telemetry
git add trail_report.py drift_report.py analyze_ac.py race_report.py         tests/synth_log.py tests/test_analyzer_defaults.py
git commit -m "Analyzers look for logs where the logger actually writes them"
```

---

### Task 5: Читання ACC-сетапу (`read_setup.py`)

**Files:**
- Create: `skills/sim-setup/scripts/read_setup.py`, `tests/fixtures/acc_setup.json`
- Test: `tests/test_setup_io.py`

**Interfaces:**
- Consumes: нічого
- Produces: `read_setup.load(path) -> dict`, `read_setup.flatten(setup) -> list[tuple[str, object, bool]]` (шлях, значення, `derived`), `read_setup.DERIVED_KEYS -> set[str]`, `read_setup.get(setup, path) -> object`, `read_setup.steps(path) -> iterator`

- [ ] **Step 1: Створити фікстуру**

`tests/fixtures/acc_setup.json` — синтетичний файл тієї ж форми, що справжній (навмисно не сетап автора):

```json
{
  "carName": "test_gt3",
  "basicSetup": {
    "tyres": { "tyreCompound": 0, "tyrePressure": [ 45, 38, 36, 27 ] },
    "alignment": {
      "camber": [ 0, 0, 0, 0 ],
      "toe": [ 30, 30, 50, 50 ],
      "staticCamber": [ -4.65, -4.66, -5.14, -5.15 ],
      "toeOutLinear": [ -0.0004, -0.0004, 0.0005, 0.0005 ],
      "casterLF": 0,
      "casterRF": 0,
      "steerRatio": 2
    },
    "electronics": { "tC1": 3, "tC2": 4, "abs": 4, "eCUMap": 0, "fuelMix": 0, "telemetryLaps": 0 },
    "strategy": {
      "fuel": 60, "nPitStops": 0, "tyreSet": 1,
      "frontBrakePadCompound": 1, "rearBrakePadCompound": 1,
      "fuelPerLap": 2.7
    }
  },
  "advancedSetup": {
    "mechanicalBalance": {
      "aRBFront": 3, "aRBRear": 3,
      "wheelRate": [ 1, 1, 1, 1 ],
      "brakeTorque": 20, "brakeBias": 35
    },
    "dampers": {
      "bumpSlow": [ 6, 6, 5, 5 ], "bumpFast": [ 2, 2, 2, 2 ],
      "reboundSlow": [ 7, 7, 7, 7 ], "reboundFast": [ 6, 6, 8, 8 ]
    },
    "aeroBalance": {
      "rideHeight": [ 0, 6, 10, 18 ],
      "rodLength": [ 53.93, 53.93, 57.92, 57.92 ],
      "splitter": 0, "rearWing": 10, "brakeDuct": [ 4, 4 ]
    },
    "drivetrain": { "preload": 3 }
  }
}
```

- [ ] **Step 2: Write the failing test**

`tests/test_setup_io.py`:

```python
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "sim-setup", "scripts"))

import read_setup

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "acc_setup.json")


class TestReadSetup(unittest.TestCase):

    def test_loads_the_car_name(self):
        self.assertEqual(read_setup.load(FIXTURE)["carName"], "test_gt3")

    def test_flatten_exposes_dotted_paths_with_indices(self):
        flat = dict((p, v) for p, v, _ in read_setup.flatten(read_setup.load(FIXTURE)))
        self.assertEqual(flat["advancedSetup.mechanicalBalance.aRBFront"], 3)
        self.assertEqual(flat["basicSetup.tyres.tyrePressure[0]"], 45)
        self.assertEqual(flat["advancedSetup.aeroBalance.rearWing"], 10)

    def test_derived_fields_are_marked(self):
        marks = dict((p, d) for p, _, d in read_setup.flatten(read_setup.load(FIXTURE)))
        self.assertTrue(marks["basicSetup.alignment.staticCamber[0]"])
        self.assertTrue(marks["basicSetup.alignment.toeOutLinear[0]"])
        self.assertTrue(marks["advancedSetup.aeroBalance.rodLength[0]"])
        self.assertFalse(marks["basicSetup.alignment.camber[0]"])

    def test_get_reads_one_path(self):
        setup = read_setup.load(FIXTURE)
        self.assertEqual(read_setup.get(setup, "basicSetup.strategy.fuel"), 60)
        self.assertEqual(read_setup.get(setup, "basicSetup.tyres.tyrePressure[3]"), 27)

    def test_get_rejects_an_unknown_path(self):
        setup = read_setup.load(FIXTURE)
        with self.assertRaises(KeyError):
            read_setup.get(setup, "basicSetup.tyres.noSuchThing")

    def test_get_rejects_an_index_out_of_range(self):
        setup = read_setup.load(FIXTURE)
        with self.assertRaises(IndexError):
            read_setup.get(setup, "basicSetup.tyres.tyrePressure[9]")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m unittest tests.test_setup_io -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'read_setup'`

- [ ] **Step 4: Write minimal implementation**

`skills/sim-setup/scripts/read_setup.py`:

```python
"""Read an ACC setup file and show what is in it.

ACC stores clicks, not physical units: camber 0 is not zero degrees, it is the
first notch in the menu. Alongside the clicks the game keeps values it computed
itself - staticCamber, toeOutLinear, rodLength - which are outputs, not inputs.
They are marked derived here and must never be edited; the game rewrites them
from the clicks.

Usage:
    python read_setup.py <setup.json>            human readable listing
    python read_setup.py <setup.json> --json     the same as JSON
"""

import json
import sys

DERIVED_KEYS = {"staticCamber", "toeOutLinear", "rodLength"}


def load(path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return json.load(fh)


def _walk(node, prefix, out):
    if isinstance(node, dict):
        for key, value in node.items():
            _walk(value, "{0}.{1}".format(prefix, key) if prefix else key, out)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            _walk(value, "{0}[{1}]".format(prefix, i), out)
    else:
        leaf = prefix.split(".")[-1].split("[")[0]
        out.append((prefix, node, leaf in DERIVED_KEYS))


def flatten(setup):
    """[(dotted.path[index], value, is_derived), ...] in file order."""
    out = []
    _walk(setup, "", out)
    return out


def steps(path):
    for part in path.split("."):
        name, _, rest = part.partition("[")
        yield name
        while rest:
            index, _, rest = rest.partition("]")
            if index:
                yield int(index)
            _, _, rest = rest.partition("[")


def get(setup, path):
    """Value at a dotted path. Raises KeyError or IndexError rather than
    inventing a default: a typo must be loud."""
    node = setup
    for step in steps(path):
        node = node[step]
    return node


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 1
    setup = load(args[0])
    flat = flatten(setup)
    if "--json" in sys.argv:
        print(json.dumps([{"path": p, "value": v, "derived": d} for p, v, d in flat],
                         indent=2))
        return 0
    print("car: {0}".format(setup.get("carName", "?")))
    for path, value, derived in flat:
        print("{0:<58} {1!s:<12} {2}".format(path, value, "derived, read-only" if derived else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m unittest tests.test_setup_io -v`
Expected: 6 tests PASS

- [ ] **Step 6: Перевірити на справжньому сетапі**

```bash
python skills/sim-setup/scripts/read_setup.py "$(ls ~/Documents/'Assetto Corsa Competizione'/Setups/*/*/*.json | head -1)" | head -20
```
Expected: перелік шляхів зі значеннями; `staticCamber`, `toeOutLinear`, `rodLength` позначені `derived, read-only`.

- [ ] **Step 7: Commit**

```bash
git add skills/sim-setup/scripts/read_setup.py tests/fixtures/acc_setup.json tests/test_setup_io.py
git commit -m "Read ACC setups, marking the fields the game computes for itself"
```

---

### Task 6: Правка ACC-сетапу (`patch_setup.py`)

**Files:**
- Create: `skills/sim-setup/scripts/patch_setup.py`
- Test: `tests/test_setup_io.py` (додати класи)

**Interfaces:**
- Consumes: `read_setup.load`, `read_setup.get`, `read_setup.DERIVED_KEYS` з Task 5
- Produces: `patch_setup.apply(setup: dict, changes: dict) -> list[tuple[str, object, object]]` (шлях, було, стало), `patch_setup.DerivedFieldError`, `patch_setup.write(setup, out_path, backup: bool) -> str|None`

- [ ] **Step 1: Write the failing test**

Додати в `tests/test_setup_io.py`:

```python
sys.path.insert(0, os.path.join(ROOT, "skills", "sim-setup", "scripts"))
import patch_setup


class TestPatchSetup(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "base.json")
        shutil.copy(FIXTURE, self.path)

    def tearDown(self):
        self._tmp.cleanup()

    def test_apply_reports_before_and_after(self):
        setup = read_setup.load(self.path)
        diff = patch_setup.apply(setup, {"advancedSetup.mechanicalBalance.aRBFront": 4})
        self.assertEqual(diff, [("advancedSetup.mechanicalBalance.aRBFront", 3, 4)])
        self.assertEqual(read_setup.get(setup, "advancedSetup.mechanicalBalance.aRBFront"), 4)

    def test_only_the_named_field_changes(self):
        before = read_setup.load(self.path)
        after = read_setup.load(self.path)
        patch_setup.apply(after, {"basicSetup.tyres.tyrePressure[1]": 39})
        flat_before = dict((p, v) for p, v, _ in read_setup.flatten(before))
        flat_after = dict((p, v) for p, v, _ in read_setup.flatten(after))
        differing = [k for k in flat_before if flat_before[k] != flat_after[k]]
        self.assertEqual(differing, ["basicSetup.tyres.tyrePressure[1]"])

    def test_derived_fields_are_refused(self):
        setup = read_setup.load(self.path)
        for path in ("basicSetup.alignment.staticCamber[0]",
                     "basicSetup.alignment.toeOutLinear[2]",
                     "advancedSetup.aeroBalance.rodLength[3]"):
            with self.assertRaises(patch_setup.DerivedFieldError):
                patch_setup.apply(setup, {path: 1.0})

    def test_derived_fields_survive_a_normal_patch(self):
        setup = read_setup.load(self.path)
        derived_before = [(p, v) for p, v, d in read_setup.flatten(setup) if d]
        patch_setup.apply(setup, {"advancedSetup.aeroBalance.rearWing": 11})
        derived_after = [(p, v) for p, v, d in read_setup.flatten(setup) if d]
        self.assertEqual(derived_before, derived_after)

    def test_unknown_path_is_refused(self):
        setup = read_setup.load(self.path)
        with self.assertRaises(KeyError):
            patch_setup.apply(setup, {"advancedSetup.mechanicalBalance.noSuchThing": 1})

    def test_write_to_a_new_file_leaves_the_original_alone(self):
        setup = read_setup.load(self.path)
        patch_setup.apply(setup, {"advancedSetup.aeroBalance.rearWing": 12})
        out = os.path.join(self._tmp.name, "ai_v1.json")
        patch_setup.write(setup, out, backup=False)
        self.assertEqual(read_setup.get(read_setup.load(out),
                                        "advancedSetup.aeroBalance.rearWing"), 12)
        self.assertEqual(read_setup.get(read_setup.load(self.path),
                                        "advancedSetup.aeroBalance.rearWing"), 10)

    def test_in_place_write_backs_up_once(self):
        setup = read_setup.load(self.path)
        patch_setup.apply(setup, {"advancedSetup.aeroBalance.rearWing": 13})
        first = patch_setup.write(setup, self.path, backup=True)
        self.assertEqual(first, self.path + ".bak")
        self.assertEqual(read_setup.get(read_setup.load(first),
                                        "advancedSetup.aeroBalance.rearWing"), 10)
        patch_setup.apply(setup, {"advancedSetup.aeroBalance.rearWing": 14})
        patch_setup.write(setup, self.path, backup=True)
        self.assertEqual(read_setup.get(read_setup.load(self.path + ".bak"),
                                        "advancedSetup.aeroBalance.rearWing"), 10)

    def test_written_file_is_still_valid_json_the_game_shape(self):
        setup = read_setup.load(self.path)
        patch_setup.apply(setup, {"basicSetup.strategy.fuel": 62})
        out = os.path.join(self._tmp.name, "out.json")
        patch_setup.write(setup, out, backup=False)
        again = read_setup.load(out)
        self.assertIn("basicSetup", again)
        self.assertIn("advancedSetup", again)
        self.assertEqual(again["carName"], "test_gt3")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_setup_io -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'patch_setup'`

- [ ] **Step 3: Write minimal implementation**

`skills/sim-setup/scripts/patch_setup.py`:

```python
"""Change clicks in an ACC setup file, safely.

Refuses the fields the game computes for itself (staticCamber, toeOutLinear,
rodLength): writing those would either be ignored or fight the game's own
recalculation, and either way it hides what actually changed.

Never picks a destination on its own. Either --out a new file or --in-place,
because "which setup did I just overwrite" is not a question anyone should have
to answer after the fact.

Usage:
    python patch_setup.py <setup.json> --set path=value [--set path=value ...]
                          (--out <file> | --in-place) [--json]
"""

import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import read_setup


class DerivedFieldError(Exception):
    """Raised when someone tries to write a value the game derives itself."""


def _leaf(path):
    return path.split(".")[-1].split("[")[0]


def _set(setup, path, value):
    parts = list(read_setup.steps(path))
    node = setup
    for step in parts[:-1]:
        node = node[step]
    last = parts[-1]
    if isinstance(node, list):
        if not isinstance(last, int) or last >= len(node):
            raise IndexError(path)
    elif last not in node:
        raise KeyError(path)
    node[last] = value


def apply(setup, changes):
    """Apply {path: value} in place. Returns [(path, before, after), ...].

    Validates everything before touching anything, so a rejected change set
    leaves the setup exactly as it was.
    """
    for path in changes:
        if _leaf(path) in read_setup.DERIVED_KEYS:
            raise DerivedFieldError(
                "{0} is computed by the game from the clicks; edit the clicks instead".format(path))
        read_setup.get(setup, path)      # raises KeyError / IndexError on a typo
    diff = []
    for path, value in changes.items():
        before = read_setup.get(setup, path)
        _set(setup, path, value)
        diff.append((path, before, value))
    return diff


def write(setup, out_path, backup):
    """Write the setup. Returns the backup path, or None when none was made.

    The backup is made once, like the logger does with neck.ini: a second run
    must not overwrite the only pristine copy with an already-patched one.
    """
    made = None
    if backup and os.path.exists(out_path):
        bak = out_path + ".bak"
        if not os.path.exists(bak):
            shutil.copy2(out_path, bak)
        made = bak
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(setup, fh, indent=4)
        fh.write("\n")
    return made


def _parse_value(raw):
    try:
        return int(raw)
    except ValueError:
        return float(raw)


def main():
    argv = sys.argv[1:]
    if not argv:
        print(__doc__)
        return 1
    src = argv[0]
    changes, out, in_place = {}, None, False
    i = 1
    while i < len(argv):
        if argv[i] == "--set":
            path, _, raw = argv[i + 1].partition("=")
            changes[path] = _parse_value(raw)
            i += 2
        elif argv[i] == "--out":
            out = argv[i + 1]
            i += 2
        elif argv[i] == "--in-place":
            in_place = True
            i += 1
        else:
            i += 1
    if not changes:
        print("nothing to change: pass --set path=value")
        return 1
    if bool(out) == in_place:
        print("pick exactly one destination: --out <file> or --in-place")
        return 1
    setup = read_setup.load(src)
    try:
        diff = apply(setup, changes)
    except DerivedFieldError as e:
        print("refused: {0}".format(e))
        return 2
    target = out or src
    bak = write(setup, target, backup=in_place)
    if "--json" in argv:
        print(json.dumps({"file": target, "backup": bak,
                          "changes": [{"path": p, "before": b, "after": a} for p, b, a in diff]},
                         indent=2))
    else:
        for path, before, after in diff:
            print("{0}: {1} -> {2}".format(path, before, after))
        print("written: {0}".format(target))
        if bak:
            print("backup:  {0}".format(bak))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_setup_io -v`
Expected: 14 tests PASS (6 з Task 5 + 8 нових)

- [ ] **Step 5: Перевірити відмову на похідному полі з командного рядка**

```bash
cp tests/fixtures/acc_setup.json /tmp/t.json
python skills/sim-setup/scripts/patch_setup.py /tmp/t.json --set basicSetup.alignment.staticCamber[0]=-4.0 --in-place; echo "exit=$?"
```
Expected: `refused: ... is computed by the game from the clicks`, `exit=2`, файл не змінено.

- [ ] **Step 6: Commit**

```bash
git add skills/sim-setup/scripts/patch_setup.py tests/test_setup_io.py
git commit -m "Patch ACC setup clicks with a one-time backup, refusing derived fields"
```

---

### Task 7: Перевірка готовності (`discover.py`)

**Files:**
- Create: `skills/sim-setup/scripts/discover.py`
- Test: `tests/test_discover.py`

**Interfaces:**
- Consumes: `logs_dir.resolve()`, `logger_state.read_state()`
- Produces: `discover.documents_dir() -> str`, `discover.acc_setups_dir() -> str|None`, `discover.coach_home() -> str`, `discover.seed_coach() -> list[str]` (створені файли), `discover.report() -> dict` з ключами `python`, `state`, `logs`, `acc_setups`, `analyzers`, `coach`, `logger_running`, `problems`

- [ ] **Step 1: Write the failing test**

`tests/test_discover.py`:

```python
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "skills", "sim-setup", "scripts"))

import discover


class TestDiscover(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._saved = {k: os.environ.get(k) for k in
                       ("STINT_LOGS", "STINTLOGGER_STATE_DIR", "SIM_COACH_HOME")}
        os.environ["STINTLOGGER_STATE_DIR"] = os.path.join(self._tmp.name, "state")
        os.environ["SIM_COACH_HOME"] = os.path.join(self._tmp.name, "coach")
        os.environ.pop("STINT_LOGS", None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()

    def test_documents_comes_from_the_registry(self):
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders") as k:
            expected = os.path.expandvars(winreg.QueryValueEx(k, "Personal")[0])
        self.assertEqual(os.path.normcase(discover.documents_dir()),
                         os.path.normcase(expected))

    def test_seed_creates_rules_and_profile(self):
        created = discover.seed_coach()
        home = os.environ["SIM_COACH_HOME"]
        self.assertTrue(os.path.isfile(os.path.join(home, "rules.md")))
        self.assertTrue(os.path.isfile(os.path.join(home, "profile.md")))
        self.assertTrue(os.path.isdir(os.path.join(home, "journal")))
        self.assertTrue(any("rules.md" in c for c in created))

    def test_seed_never_overwrites_existing_rules(self):
        discover.seed_coach()
        rules = os.path.join(os.environ["SIM_COACH_HOME"], "rules.md")
        with open(rules, "w", encoding="utf-8") as fh:
            fh.write("- [always] mine\n")
        discover.seed_coach()
        with open(rules, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "- [always] mine\n")

    def test_seeded_rules_carry_all_four_defaults_with_scopes(self):
        discover.seed_coach()
        with open(os.path.join(os.environ["SIM_COACH_HOME"], "rules.md"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertEqual(text.count("[always]"), 2)
        self.assertEqual(text.count("[fine]"), 1)
        self.assertEqual(text.count("[coarse]"), 1)

    def test_report_names_the_missing_logs_instead_of_crashing(self):
        rep = discover.report()
        self.assertIsNone(rep["logs"]["path"])
        self.assertTrue(any("лог" in p.lower() for p in rep["problems"]))

    def test_report_is_json_serialisable(self):
        json.dumps(discover.report())

    def test_report_sees_the_analyzers_in_this_checkout(self):
        rep = discover.report()
        self.assertTrue(rep["analyzers"]["found"])
        self.assertIn("trail_report.py", rep["analyzers"]["names"])

    def test_report_reads_state_when_present(self):
        import logger_state
        logs = os.path.join(self._tmp.name, "logs")
        os.makedirs(logs)
        with open(os.path.join(logs, "a.csv"), "w", encoding="utf-8") as fh:
            fh.write("t,lap\n0,0\n")
        logger_state.write_state(logs, "1.1.0", "ACC")
        rep = discover.report()
        self.assertEqual(rep["state"]["version"], "1.1.0")
        self.assertEqual(rep["logs"]["source"], "state.json")
        self.assertEqual(rep["logs"]["csv_count"], 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_discover -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'discover'`

- [ ] **Step 3: Write minimal implementation**

`skills/sim-setup/scripts/discover.py`:

```python
"""Find everything the skill needs, and say plainly what is missing.

This is a script rather than instructions in SKILL.md on purpose: prose would
have every agent searching its own way and the result would not be reproducible.

Prints JSON. SKILL.md turns it into Ukrainian for the user.

    python discover.py            the report
    python discover.py --seed     the report, and create ~/.sim-coach if absent
"""

import glob
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
sys.path.insert(0, REPO)

import logger_state
import logs_dir

ANALYZERS = ["trail_report.py", "drift_report.py", "analyze_ac.py", "race_report.py"]

DEFAULT_RULES = """# Правила

Область дії в дужках: `always` — завжди, `coarse` — базовий сетап з нуля,
`fine` — тонка доводка. Дописуй свої рядки в тому ж вигляді.

- [always] Якщо сетапу немає — спитати, чи створювати. Якщо є — спитати, чи перезаписувати.
- [always] Перед записом показати diff у кліках: було -> стало.
- [fine] Одна зміна за раз. Наступна — тільки після заїзду й порівняння.
- [coarse] Можна крутити кілька параметрів, якщо вони з різних систем.
"""

DEFAULT_PROFILE = """# Стиль водіння

Порожньо. Скіл дописує сюди тільки з твого підтвердження, і кожне твердження
несе число й джерело — інакше профіль стає збіркою лестощів.
"""


def coach_home():
    return logs_dir.coach_home()


def documents_dir():
    """Documents as Windows knows it. Plenty of people have it redirected into
    OneDrive, and a hardcoded ~/Documents would tell them their setups do not
    exist."""
    try:
        import winreg
        key = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            value = os.path.expandvars(winreg.QueryValueEx(k, "Personal")[0])
        if os.path.isdir(value):
            return value
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), "Documents")


def acc_setups_dir():
    path = os.path.join(documents_dir(), "Assetto Corsa Competizione", "Setups")
    return path if os.path.isdir(path) else None


def seed_coach():
    """Create the personal state if absent. Never overwrites what is there."""
    home = coach_home()
    created = []
    os.makedirs(os.path.join(home, "journal"), exist_ok=True)
    for name, body in (("rules.md", DEFAULT_RULES), ("profile.md", DEFAULT_PROFILE)):
        path = os.path.join(home, name)
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(body)
            created.append(path)
    return created


def logger_running():
    """StintLogger.exe, or the source version under pythonw."""
    try:
        out = subprocess.run(["tasklist"], capture_output=True, text=True,
                             timeout=10).stdout.lower()
    except Exception:
        return None
    return "stintlogger.exe" in out or "pythonw.exe" in out


def report():
    state = logger_state.read_state()
    found = logs_dir.resolve()
    setups = acc_setups_dir()
    analyzers = [n for n in ANALYZERS if os.path.isfile(os.path.join(REPO, n))]
    cars = sorted(os.listdir(setups)) if setups else []

    problems = []
    if found["path"] is None:
        problems.append("Не знайдено логів. Перевірені місця: " + ", ".join(
            "{0} ({1})".format(t["source"], t["path"]) for t in found["tried"]))
    if state is None and found["path"]:
        problems.append("Логи є, але логер не залишив state.json — версія стара, "
                        "варто оновити: https://github.com/YuriiHeits/sim-telemetry/releases/latest")
    if state is None and not found["path"]:
        problems.append("Логера на цій машині не видно. Якщо репозиторій поряд — "
                        "`python stint_logger.pyw`; якщо ні — реліз: "
                        "https://github.com/YuriiHeits/sim-telemetry/releases/latest")
    if setups is None:
        problems.append("Папку сетапів ACC не знайдено в " + documents_dir())
    if len(analyzers) < len(ANALYZERS):
        problems.append("Аналізатори не всі на місці: є " + ", ".join(analyzers))

    return {
        "python": sys.version.split()[0],
        "state": state,
        "logs": {k: found[k] for k in ("path", "source", "csv_count", "tried")},
        "acc_setups": {"path": setups, "cars": cars},
        "analyzers": {"found": len(analyzers) == len(ANALYZERS), "names": analyzers},
        "coach": {"home": coach_home(), "exists": os.path.isdir(coach_home())},
        "logger_running": logger_running(),
        "problems": problems,
    }


def main():
    if "--seed" in sys.argv:
        seed_coach()
    print(json.dumps(report(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_discover -v`
Expected: 8 tests PASS

- [ ] **Step 5: Прогнати на реальній машині**

```bash
python skills/sim-setup/scripts/discover.py
```
Expected: `logs.source` = `state.json`, `acc_setups.cars` містить `maserati_mc20_gt2` і `nissan_gt_r_gt3_2018`, `analyzers.found` = `true`, `problems` порожній або з одним зрозумілим рядком.

- [ ] **Step 6: Commit**

```bash
git add skills/sim-setup/scripts/discover.py tests/test_discover.py
git commit -m "Discover logs, setups and personal state, and name what is missing"
```

---

### Task 8: `SKILL.md` і довідники

**Files:**
- Create: `skills/sim-setup/SKILL.md`, `skills/sim-setup/references/acc-setup-format.md`, `skills/sim-setup/references/diagnosis.md`

**Interfaces:**
- Consumes: `discover.py --seed`, `read_setup.py`, `patch_setup.py`, аналізатори з репо
- Produces: скіл, який видно як `/sim-setup` у Claude Code і `$sim-setup` у Codex

- [ ] **Step 1: Написати `SKILL.md`**

```markdown
---
name: sim-setup
description: Read StintLogger telemetry from Assetto Corsa and ACC, diagnose the driving and the car, and adjust ACC setup files. Use when the user asks about their lap times, braking, tyre pressures, fuel, car balance, or wants a setup changed for a track. Also use when they mention StintLogger, telemetry CSVs, or ask why a car feels unstable.
metadata:
  short-description: Setups and telemetry for AC / ACC
---

# sim-setup

Telemetry in, setup changes out. The logger half of this pair writes CSVs; this
half reads them, decides what to change, and edits ACC setup files.

**Talk to the user in Ukrainian.** These instructions are English because that
is the standard for skills; the conversation is not.

## Always start here

Run the readiness check and read its JSON:

```
python <repo>/skills/sim-setup/scripts/discover.py --seed
```

`<repo>` is the checkout this skill lives in. The report tells you where the
logs are, where ACC setups are, whether the logger is installed and running,
and what is missing. Retell `problems` in Ukrainian, plainly. Do not start
working around a missing piece while pretending everything is fine.

If `problems` says the logger is not there:

- repo is next to you (`stint_logger.pyw` exists in `<repo>`) -> tell the user
  to run `python stint_logger.pyw`. Do not offer a download; it is already here.
- repo absent -> give the release link and the command, warn that Windows
  SmartScreen and some antivirus products complain about any one-file
  PyInstaller build, and **wait for an explicit yes before downloading
  anything**. Never run a downloaded binary on your own initiative.

If `logger_running` is false and the user is about to drive, say so first:
telemetry only exists while they are on track and cannot be recovered after.

## Read the rules before proposing anything

`~/.sim-coach/rules.md` (path in `coach.home`). Each rule carries a scope:

- `[always]` - in force at all times
- `[coarse]` - building a base setup, several parameters may move
- `[fine]` - fine tuning, and this is where "one change at a time" belongs

Ask the user which mode you are in when it is not obvious. Do not decide for
them: one change per session and several changes per session are different jobs,
and confusing them destroys the ability to attribute a result to a cause.

A user rule outranks your own judgement. When you disagree, say so out loud and
follow the rule anyway.

## Diagnose from the logs

Pick the analyzer, run it yourself, and retell the finding. The user does not
need to know these scripts exist.

| what they ask | run |
|---|---|
| braking, entry, lap time | `trail_report.py <csv>` |
| drift, angles, transitions | `drift_report.py <csv>` |
| general stint summary | `analyze_ac.py <csv>` |
| laps within a stint, pressures per lap | `race_report.py <csv>` |

Always pass the CSV path explicitly, from `logs.path` in the report. Read the
CSV header before making claims about a column: an older logger has no
`valid_lap`, and then you say nothing about lap validity rather than computing
nonsense. `references/diagnosis.md` maps symptoms to setup parameters.

## Change a setup

ACC only for now. AC setups are not written by this skill: the click ranges live
inside each mod's encrypted `data.acd`, so we would be guessing at limits.

1. Read the current file: `read_setup.py <setup.json>`. Values are **clicks**,
   not physical units.
2. Decide the change from the diagnosis, honouring the rules and the mode.
   `fine` means 1-2 clicks on one parameter. `coarse` may move more, but then
   name the absolute target value and tell the user the per-car ranges are
   unknown to us, so it is worth checking against the game's menu.
3. Never invent a value. Read what is there, move relative to it.
4. Show the diff in clicks and ask before writing, unless a rule says otherwise.
5. Write: `patch_setup.py <file> --set <path>=<value> --out <new.json>` for a new
   setup, or `--in-place` to change the existing one (a one-time `.bak` is kept).
6. Never touch `staticCamber`, `toeOutLinear` or `rodLength`. The game computes
   those from the clicks. The script refuses them; do not work around it.

Fuel comes from telemetry, not from a guess: `fuel_x_lap` in the CSV feeds
`basicSetup.strategy.fuelPerLap` and `fuel`.

## Write down what you changed

`~/.sim-coach/journal/<game>-<car>-<track>.md`. Record the change, the reason,
and what to look for in the next run. After the next session, close the entry
with what the telemetry actually did. A change nobody verified is a guess with
better manners.

## The driving profile

`~/.sim-coach/profile.md`. You may draft entries from the logs, but **ask before
writing**. Every claim carries a number and a source:

    - Trail braking 3-11% across cars and tracks - systematic, not a one-off.
      (12 logs, latest 2026-08-05, trail_report.py)

One bad session must not become a permanent fact about the driver.
```

- [ ] **Step 2: Написати `references/acc-setup-format.md`**

```markdown
# ACC setup files

`<Documents>/Assetto Corsa Competizione/Setups/<car>/<track>/<name>.json`.
Find `<Documents>` through `discover.py`, not through `~/Documents`: it is often
redirected into OneDrive.

Two halves: `basicSetup` (tyres, alignment, electronics, strategy) and
`advancedSetup` (mechanicalBalance, dampers, aeroBalance, drivetrain).

## Everything is clicks

`camber: [0, 0, 0, 0]` is not zero degrees, it is the first notch in the menu.
The same holds for pressures, toe, ARB, wing, ride height and the dampers. So:
read the current value, move relative to it, never write an absolute number from
memory. Per-car ranges are not documented anywhere we can read, so a value out of
range is either clamped by the game or ignored - and only the user sees that, in
the menu.

## What not to write

| field | why |
|---|---|
| `staticCamber` | degrees the game computed from the camber clicks |
| `toeOutLinear` | the same for toe |
| `rodLength` | the same for ride height |

`patch_setup.py` refuses them. They are outputs; the game rewrites them.

## Fields worth knowing

| path | what it is |
|---|---|
| `basicSetup.tyres.tyrePressure[0..3]` | LF, RF, LR, RR - one click is roughly 0.1 psi |
| `basicSetup.alignment.camber[0..3]` | camber clicks |
| `basicSetup.alignment.toe[0..3]` | toe clicks |
| `basicSetup.electronics.tC1` / `tC2` / `abs` | traction control, TC cut, ABS |
| `basicSetup.strategy.fuel` | litres in the tank |
| `basicSetup.strategy.fuelPerLap` | consumption the game assumes - fill from telemetry |
| `advancedSetup.mechanicalBalance.aRBFront` / `aRBRear` | anti-roll bars |
| `advancedSetup.mechanicalBalance.brakeBias` | brake bias clicks |
| `advancedSetup.dampers.bumpSlow` etc. | four values per damper setting |
| `advancedSetup.aeroBalance.rearWing` | rear wing |
| `advancedSetup.aeroBalance.rideHeight[0..3]` | ride height clicks |
| `advancedSetup.drivetrain.preload` | differential preload |

## Telemetry that pairs with a setup change

Columns from the logger worth checking after a change: `press_*` and `ttemp_*`
for tyres, `btemp_*` for brakes (ACC only), `slip_*` for grip, `susp_*` for
travel, `gx`/`gz` for load, `valid_lap` to throw away laps that do not count.
The canonical description of every column is the repository README - do not
restate it here, it would drift.
```

- [ ] **Step 3: Написати `references/diagnosis.md`**

```markdown
# Symptom to parameter

**These are heuristics, not physics.** They come from common sim-racing practice
and they are wrong often enough that a change must be verified against telemetry
before it is believed. That is what the journal and "one change at a time" are
for. When you state a change, also state what should move in the data if you are
right - a claim nobody can falsify is worthless.

## Entry

| symptom in telemetry | likely levers |
|---|---|
| understeer on entry: steering rises, `gz` does not follow | softer front ARB, more front camber, brake bias rearward by 1-2 clicks |
| oversteer on entry, especially trailing the brake | brake bias forward, stiffer rear ARB, less rear rebound |
| front tyres over temperature (`ttemp_fl/fr` high vs rear) | lower front pressure, less front camber, softer front |
| brake temps climbing over a stint (`btemp_*`) | more brake ducts, softer pad compound |

## Mid corner

| symptom | likely levers |
|---|---|
| balance changes with steering angle, car "falls" mid corner | ride height and bump stop window, wheel rate front to rear |
| inner front locking, `slip_fl` spikes | differential preload down, brake bias forward |
| pressures out of the window (`press_*` far from 27.5 psi hot for GT3) | set cold pressure so hot lands in the window |

## Exit

| symptom | likely levers |
|---|---|
| wheelspin on exit, `slip_rl/rr` high with high `gas` | more rear wing, softer rear, preload up, TC up as a crutch not a fix |
| car pushes wide under power | softer rear ARB, more rear camber |

## Not a setup problem

Some findings belong in the profile, not in the setup:

- **Trail braking share consistently low across cars and tracks.** That is
  technique. Say it, do not soften the car to hide it.
- **Qualifying pace far off race pace.** Also technique, or tyre preparation.
- **Slow lap with no off-track excursion** distorts fuel averages; it is not a
  balance problem.
```

- [ ] **Step 4: Перевірити, що frontmatter валідний і скіл видно**

```bash
python - <<'EOF'
import io, re
s = io.open("skills/sim-setup/SKILL.md", encoding="utf-8").read()
m = re.match(r"^---\n(.*?)\n---\n", s, re.S)
assert m, "frontmatter missing"
body = m.group(1)
name = re.search(r"^name:\s*(\S+)", body, re.M).group(1)
desc = re.search(r"^description:\s*(.+)$", body, re.M).group(1)
assert re.fullmatch(r"[a-z0-9-]{1,64}", name), name
assert len(desc) <= 1024, len(desc)
print("name:", name, "| description chars:", len(desc))
EOF
```
Expected: `name: sim-setup`, довжина опису в межах 1024.

- [ ] **Step 5: Поставити скіл для обох агентів і перевірити видимість**

```bash
mkdir -p ~/.agents/skills
ln -s "$HOME/sim-telemetry/skills/sim-setup" ~/.agents/skills/sim-setup
ln -s "$HOME/.agents/skills/sim-setup" ~/.claude/skills/sim-setup
ln -s "$HOME/.agents/skills/sim-setup" ~/.codex/skills/sim-setup
ls -la ~/.claude/skills/sim-setup ~/.codex/skills/sim-setup
```
Expected: обидва симлінки ведуть на один каталог у репо. Далі в новій сесії Claude Code `/sim-setup` присутній у списку скілів.

- [ ] **Step 6: Commit**

```bash
git add skills/sim-setup/SKILL.md skills/sim-setup/references
git commit -m "Add the sim-setup skill instructions and its two reference sheets"
```

---

### Task 9: README і фінальна перевірка

**Files:**
- Modify: `README.md`
- Test: повний прогін набору + перевірки, які вимагають гри

**Interfaces:**
- Consumes: усе попереднє
- Produces: нічого нового

- [ ] **Step 1: Додати розділ у README перед «## Тести»**

```markdown
## Скіл для Claude Code і Codex

У репозиторії лежить скіл `sim-setup`: він читає логи, ставить діагноз і править
сетапи ACC. Аналізатори запускає сам — знати їхні імена не потрібно.

Установка (один каталог, симлінки для обох агентів):

```
git clone https://github.com/YuriiHeits/sim-telemetry.git
mkdir -p ~/.agents/skills
ln -s "$PWD/sim-telemetry/skills/sim-setup" ~/.agents/skills/sim-setup
ln -s ~/.agents/skills/sim-setup ~/.claude/skills/sim-setup   # Claude Code
ln -s ~/.agents/skills/sim-setup ~/.codex/skills/sim-setup    # Codex
```

Далі `/sim-setup` у Claude Code або `$sim-setup` у Codex.

**Скілу потрібен Python 3, логеру — ні.** Логер роздається як exe саме для того,
щоб нічого не ставити; скіл — це скрипти, і без Python вони не працюють.

Особисті дані скіл тримає **поза репозиторієм**, у `~/.sim-coach/`: правила
(`rules.md`), профіль стилю водіння (`profile.md`) і журнал змін. У git вони не
потрапляють ніколи, тому скіл можна віддавати далі, не віддаючи разом із ним
свій профіль.

Логер, зі свого боку, залишає `~/.stintlogger/state.json` — адресу папки з логами
й свою версію. Завдяки цьому скіл не вгадує, де шукати телеметрію.
```

- [ ] **Step 2: Прогнати весь набір тестів**

Run: `python -m unittest discover tests -v`
Expected: усі PASS. Орієнтир: 37 наявних + 8 (`logger_state`) + 7 (`logs_dir`) + 14 (`setup_io`) + 8 (`discover`).

- [ ] **Step 3: Перевірити GUI-smoke, бо логер змінювався**

Run: `python tests/smoke_gui.py | tail -6`
Expected: `OK`, вигляди перемикаються як раніше.

- [ ] **Step 4: Пройти сценарій «чужа машина» (крит. 8.7)**

```bash
export SIM_COACH_HOME=/tmp/fresh-coach STINTLOGGER_STATE_DIR=/tmp/fresh-state
python skills/sim-setup/scripts/discover.py --seed | python -c "import json,sys; r=json.load(sys.stdin); print('problems:', r['problems']); print('coach:', r['coach'])"
ls /tmp/fresh-coach
unset SIM_COACH_HOME STINTLOGGER_STATE_DIR
```
Expected: створені `rules.md`, `profile.md`, `journal/`; у `problems` зрозумілі рядки про відсутній `state.json`, а не стектрейс.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "README: how to install the skill, and why it needs Python while the logger does not"
```

- [ ] **Step 6: Перевірки, які вимагають гри — віддати власнику**

Ці чотири критерії неможливо закрити без ACC і без сесії. Виписати їх власнику
списком і **не позначати виконаними** до підтвердження:

- **8.3** — записаний `patch_setup.py` сетап відкривається в ACC і показує в меню
  саме те значення, яке ставили.
- **8.5** — у `fine` з правилом «одна зміна за раз» скіл пропонує рівно одну зміну
  і відмовляється склеїти дві; у `coarse` пропонує кілька. З транскриптом.
- **8.11** — прохід від «розберись з гальмуванням» до діагнозу без того, щоб
  користувач назвав ім'я скрипта.
- **8.14** — коли логер не запущений, скіл каже про це до того, як радити їхати.

---

## Self-Review

**Spec coverage.** Пройдено по розділах спеки:

| розділ спеки | задача |
|---|---|
| §1 Структура | Task 5–8 (файли скіла), Task 7 (`~/.sim-coach/`) |
| §1.1 Контракт, `state.json` | Task 1, Task 2 |
| §1.1 Старий логер, відсутні колонки | Task 7 (`problems`), Task 8 (`SKILL.md` — перевірка заголовка CSV) |
| §2 Цикл роботи, журнал | Task 8 (`SKILL.md`, розділ про журнал) |
| §3 Правила з областями | Task 7 (засів `rules.md`), Task 8 (як їх читати й підкорятись) |
| §4 Профіль | Task 7 (`profile.md`), Task 8 (підтвердження, число + джерело) |
| §5 Правка сетапів, похідні поля, крок | Task 6, Task 8 |
| §6 Виправлення в аналізаторах | Task 3, Task 4 |
| §7 Один вхід, виявлення, готовність, установка логера | Task 7, Task 8 |
| §7 README | Task 9 |
| §8 Критерії 1,2 | Task 6 (тести) |
| §8 Критерії 3,5,11,14 | Task 9 Step 6 (за власником) |
| §8 Критерій 4 | Task 4 Step 5 |
| §8 Критерії 6,7,8,9,10,12,13 | Task 7 (тести й `problems`), Task 8 |
| §8 Критерії 15,16,17 | Task 2 Step 5, Task 7 (`problems`), Task 8 |
| §9 Ризики | покриті тими ж задачами |

Прогалин не знайдено. Критерій 8.10 («шлях питається один раз») реалізований
`logs_dir._remembered()` у Task 3 і перевірений тестом `test_remembered_answer_is_third`;
сам запис `config.json` робить скіл за інструкцією в `SKILL.md`.

**Placeholder scan.** «TBD», «TODO», «implement later», «add error handling»,
«similar to Task N» — немає. Кожен крок із кодом містить код.

**Type consistency.** Назви й підписи звірені між задачами: `logger_state.write_state`
/ `read_state` (Task 1) використовуються в Task 2 і Task 3 з тими самими аргументами;
`logs_dir.resolve()` повертає той самий словник, який читають Task 4 і Task 7;
`read_setup.load` / `flatten` / `get` / `DERIVED_KEYS` (Task 5) — саме ті імена, що в
Task 6; `patch_setup.apply` / `write` / `DerivedFieldError` (Task 6) — ті, що в
`SKILL.md` Task 8. `read_setup.steps` — публічна функція розбору шляху, якою користується
`patch_setup._set`: розбір існує в одному місці, і це не приватне ім'я через
межу модуля.
