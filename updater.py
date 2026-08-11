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
