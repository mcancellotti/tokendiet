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
import tempfile

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

# -- the turn line --------------------------------------------------------
# It tracks state across renders, so it gets a scratch dir of its own. The
# first render of a session has no previous turn to compare against.
state = tempfile.mkdtemp()


def turn(prompt_id, pct, cost, ms=600_000, **env):
    return render({
        "session_id": "test", "prompt_id": prompt_id,
        "model": {"display_name": "Opus 5"},
        "context_window": {"context_window_size": 1_000_000, "used_percentage": pct},
        "cost": {"total_cost_usd": cost, "total_duration_ms": ms},
    }, TMPDIR=state, **env)


def expect(name, line, present=(), absent=()):
    missing = [s for s in present if s not in line]
    extra = [s for s in absent if s in line]
    if missing or extra:
        failures.append(f"{name}: missing {missing} unexpected {extra} in {line!r}")
        print(f"FAIL  {name}\n      {line}")
    else:
        print(f"ok    {name}" + (f"\n      {line}" if VERBOSE else ""))


expect("turn 1   (nothing to compare yet)", turn("p1", 5, 0.10), absent=["turn "])
expect("turn 2   (first delta is the baseline)", turn("p2", 9, 0.25),
       present=["turn +40K", "$0.15"], absent=["vs first"])
expect("turn 3   (ratio appears)", turn("p3", 18, 0.60, ms=1_800_000),
       present=["turn +90K", "$0.35", "2.3× vs first turn", "30m"])
expect("re-render (same turn, same numbers)", turn("p3", 18, 0.60, ms=1_860_000),
       present=["turn +90K", "$0.35", "2.3× vs first turn"])
expect("turn 4   (growth, hours)", turn("p4", 40, 1.50, ms=3_600_000),
       present=["6.0× vs first turn", "1h00m"])
expect("opt-out  (TOKENDIET_TURN=0)", turn("p5", 62, 3.30, TOKENDIET_TURN="0"),
       present=["620K/1.0M"], absent=["turn "])

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
