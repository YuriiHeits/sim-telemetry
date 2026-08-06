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
