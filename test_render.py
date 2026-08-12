#!/usr/bin/env python3
"""Render sample payloads through tokendiet.py and check each state.

Run it to test (exit 1 on failure); run it with -v to also see the output,
which is how the examples in the README are generated.

    python3 test_render.py -v
"""
import json
import os
import pathlib
import subprocess
import sys

SCRIPT = pathlib.Path(__file__).with_name("tokendiet.py")
VERBOSE = "-v" in sys.argv

failures = []


def render(payload, **env):
    e = {**os.environ, "NO_COLOR": "1", **env}
    r = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(payload), capture_output=True, text=True, env=e,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def check(name, payload, expect, absent=(), **env):
    line = render(payload, **env)
    missing = [s for s in expect if s not in line]
    present = [s for s in absent if s in line]
    if missing or present:
        failures.append(f"{name}: missing {missing} unexpected {present} in {line!r}")
        print(f"FAIL  {name}\n      {line}")
    else:
        print(f"ok    {name}" + (f"\n      {line}" if VERBOSE else ""))


def payload(used_pct, size=1_000_000, cost=None, cwd="/nonexistent/demo"):
    d = {
        "model": {"display_name": "Opus 5"},
        "cwd": cwd,
        "context_window": {"context_window_size": size, "used_percentage": used_pct},
    }
    if cost is not None:
        d["cost"] = {"total_cost_usd": cost}
    return d


# Under WARN: green bar, no nudge to /clear.
check("green    (40K)", payload(4.0, cost=0.62),
      expect=["Opus 5", "40K/1.0M", "$0.62", "░░░░░░░░░░"], absent=["/clear"])

# Past WARN: the soft nudge, but not the hard one.
check("warn     (185K)", payload(18.5, cost=3.42),
      expect=["185K/1.0M", "◐ /clear when this task ends"], absent=["⚠"])

# Past HIGH: the hard warning.
check("high     (620K)", payload(62.0, cost=18.40),
      expect=["620K/1.0M", "██████░░░░", "⚠ /clear"], absent=["◐"])

# No used_percentage: fall back to summing this turn's input tokens.
check("fallback (325K)", {
    "model": {"display_name": "Opus 5"},
    "cwd": "/nonexistent/demo",
    "context_window": {
        "context_window_size": 1_000_000,
        "current_usage": {
            "input_tokens": 5_000,
            "cache_creation_input_tokens": 20_000,
            "cache_read_input_tokens": 300_000,
        },
    },
}, expect=["325K/1.0M", "◐ /clear"])

# Thresholds are configurable, and they are absolute token counts.
check("env      (185K, WARN=200K)", payload(18.5),
      expect=["185K/1.0M"], absent=["/clear"], TOKENDIET_WARN="200000")

# Windows: stdout to a pipe uses the locale codepage, which has no bar glyphs.
# Without the reconfigure in tokendiet.py this raises UnicodeEncodeError and the
# bar silently comes out empty.
check("codepage (cp1252 stdout)", payload(18.5),
      expect=["185K/1.0M", "█", "◐"], PYTHONIOENCODING="cp1252")

# A payload missing everything must not crash or print junk.
check("sparse   (no context)", {"model": {"display_name": "Opus 5"}},
      expect=["Opus 5"], absent=["/clear", "░"])

# Malformed stdin exits quietly rather than spraying a traceback into the bar.
if render_junk := subprocess.run(
    [sys.executable, str(SCRIPT)], input="not json",
    capture_output=True, text=True,
).stdout.strip():
    failures.append(f"junk stdin printed {render_junk!r}")
    print("FAIL  junk     (invalid stdin)")
else:
    print("ok    junk     (invalid stdin)")

print()
if failures:
    print(f"{len(failures)} failed")
    sys.exit(1)
print("all passed")
