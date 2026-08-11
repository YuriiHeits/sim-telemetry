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
