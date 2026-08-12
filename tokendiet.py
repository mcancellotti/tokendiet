#!/usr/bin/env python3
"""tokendiet - a Claude Code statusline that shows what a session is costing.

Reads the session JSON payload on stdin, prints one line to the terminal.
Nothing is ever sent to the model, so this costs zero tokens.
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

# Thresholds are in ABSOLUTE tokens, not percentage of the context window.
# Per-turn cost scales with absolute context: 500K tokens in a 1M window is
# "only half full", but every turn re-pays for 500K instead of 200K.
WARN = int(os.environ.get("TOKENDIET_WARN", 150_000))
HIGH = int(os.environ.get("TOKENDIET_HIGH", 350_000))

# On Windows, stdout to a pipe uses the locale codepage (cp1252 and friends),
# which has no bar glyphs. Printing one would raise UnicodeEncodeError and the
# statusline would just come out empty, with nowhere to see the error.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

# The second line reports what the last turn cost and how that compares with
# the first turn of the session. Set TOKENDIET_TURN=0 to keep one line only.
TURN_LINE = os.environ.get("TOKENDIET_TURN", "1").lower() not in ("0", "false", "no")

# Per-session scratch state. Temporary by design: it is only meaningful while
# the session is alive, and losing it costs a single turn's comparison.
STATE_DIR = pathlib.Path(tempfile.gettempdir()) / "tokendiet"

if os.environ.get("NO_COLOR"):
    RESET = DIM = GREEN = YELLOW = RED = BLUE = ""
else:
    RESET, DIM = "\033[0m", "\033[2m"
    GREEN, YELLOW, RED, BLUE = "\033[32m", "\033[33m", "\033[31m", "\033[34m"


def human(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


def git_branch(cwd):
    try:
        r = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=1,
        )
        if r.returncode:
            return ""
        branch = r.stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", cwd, "status", "--porcelain"],
            capture_output=True, text=True, timeout=1,
        )
        return branch + ("*" if dirty.stdout.strip() else "")
    except Exception:
        return ""


def save_state(path, state):
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(state), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass  # a statusline must never fail loudly over a scratch file


def prune_state(days=3):
    cutoff = time.time() - days * 86400
    try:
        for f in STATE_DIR.glob("*.json"):
            if f.stat().st_mtime < cutoff:
                f.unlink()
    except OSError:
        pass


def turn_delta(session_id, prompt_id, cost, used):
    """What the last completed turn added, and how it compares with the first.

    The statusline re-renders many times within a single turn, so the deltas
    are computed once, when prompt_id changes, and then replayed from the
    state file until the next turn begins. Returns (cost, tokens, ratio) with
    ratio None until there is a first turn to compare against.
    """
    path = STATE_DIR / f"{session_id}.json"
    try:
        s = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        s = {}

    if prompt_id and s.get("prompt_id") != prompt_id:
        if "cost" in s:
            s["dcost"] = max(0.0, cost - s["cost"])
            s["dtokens"] = used - s.get("used", 0)
            # The first turn that actually cost something is the baseline the
            # ratio is read against - the whole point is growth since then.
            if not s.get("first") and s["dcost"] > 0:
                s["first"] = s["dcost"]
        s.update(prompt_id=prompt_id, cost=cost, used=used)
        save_state(path, s)
        prune_state()

    if "dcost" not in s:
        return None
    first, dcost = s.get("first"), s["dcost"]
    return dcost, s.get("dtokens", 0), (dcost / first if first and dcost else None)


def human_duration(ms):
    minutes = int(ms // 60_000)
    if minutes < 60:
        return f"{minutes}m"
    return f"{minutes // 60}h{minutes % 60:02d}m"


def main():
    try:
        d = json.load(sys.stdin)
    except Exception:
        return

    parts = []

    model = (d.get("model") or {}).get("display_name", "")
    if model:
        parts.append(f"{BLUE}{model}{RESET}")

    cwd = d.get("cwd") or (d.get("workspace") or {}).get("current_dir") or ""
    if cwd:
        home = os.path.expanduser("~")
        parts.append(cwd.replace(home, "~", 1) if cwd.startswith(home) else cwd)

    if cwd and (branch := git_branch(cwd)):
        parts.append(f"{DIM}{branch}{RESET}")

    cw = d.get("context_window") or {}
    size = cw.get("context_window_size") or 0
    pct = cw.get("used_percentage")

    if pct is not None and size:
        used = int(size * pct / 100)
    else:
        # Fallback: the live context is the sum of this turn's input tokens.
        # Cache reads belong in the total - cached or not, you pay for them.
        u = cw.get("current_usage") or {}
        used = (
            u.get("input_tokens", 0)
            + u.get("cache_creation_input_tokens", 0)
            + u.get("cache_read_input_tokens", 0)
        )
        if size:
            pct = used / size * 100

    if used:
        color = RED if used >= HIGH else YELLOW if used >= WARN else GREEN
        filled = min(10, int((pct or 0) / 10))
        bar = "█" * filled + "░" * (10 - filled)
        label = human(used)
        if size:
            label += f"/{human(size)}"
        parts.append(f"{color}{bar}{RESET} {label}")

    cost_info = d.get("cost") or {}
    cost = cost_info.get("total_cost_usd")
    if cost:
        parts.append(f"{DIM}${cost:.2f}{RESET}")

    if used >= HIGH:
        parts.append(f"{RED}⚠ /clear{RESET}")
    elif used >= WARN:
        parts.append(f"{YELLOW}◐ /clear when this task ends{RESET}")

    sep = f" {DIM}·{RESET} "
    print(sep.join(parts))

    if TURN_LINE and (second := turn_parts(d, cost_info, cost or 0.0, used)):
        print(sep.join(second))


def turn_parts(d, cost_info, cost, used):
    """The second line: what the last turn added, and how it compares.

    A session that has grown expensive says so here in the only unit that
    settles the argument - what the next question will cost you.
    """
    session_id = d.get("session_id")
    if not session_id:
        return []

    delta = turn_delta(session_id, d.get("prompt_id"), cost, used)
    if not delta:
        return []
    dcost, dtokens, ratio = delta

    bits = [f"{DIM}turn {'+' if dtokens >= 0 else '-'}{human(abs(dtokens))}{RESET}"]
    if dcost:
        bits.append(f"{DIM}${dcost:.2f}{RESET}")
    # Below ~1.15x the ratio is noise, and printing "1.0x" every turn trains
    # people to stop reading the line.
    if ratio and ratio >= 1.15:
        color = RED if ratio >= 4 else YELLOW if ratio >= 2 else DIM
        bits.append(f"{color}{ratio:.1f}× vs first turn{RESET}")
    if ms := cost_info.get("total_duration_ms"):
        bits.append(f"{DIM}{human_duration(ms)}{RESET}")
    return bits


if __name__ == "__main__":
    main()
