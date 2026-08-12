#!/usr/bin/env python3
"""tokendiet - a Claude Code statusline that shows what a session is costing.

Reads the session JSON payload on stdin, prints one line to the terminal.
Nothing is ever sent to the model, so this costs zero tokens.
"""
import json
import os
import subprocess
import sys

# Thresholds are in ABSOLUTE tokens, not percentage of the context window.
# Per-turn cost scales with absolute context: 500K tokens in a 1M window is
# "only half full", but every turn re-pays for 500K instead of 200K.
WARN = int(os.environ.get("TOKENDIET_WARN", 150_000))
HIGH = int(os.environ.get("TOKENDIET_HIGH", 350_000))

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

    cost = (d.get("cost") or {}).get("total_cost_usd")
    if cost:
        parts.append(f"{DIM}${cost:.2f}{RESET}")

    if used >= HIGH:
        parts.append(f"{RED}⚠ /clear{RESET}")
    elif used >= WARN:
        parts.append(f"{YELLOW}◐ /clear when this task ends{RESET}")

    print(f" {DIM}·{RESET} ".join(parts))


if __name__ == "__main__":
    main()
