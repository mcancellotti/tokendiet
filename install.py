#!/usr/bin/env python3
"""Install tokendiet as your Claude Code statusline.

    python3 install.py     (macOS, Linux)
    python install.py      (Windows)

Copies tokendiet.py into your Claude Code config directory and sets the
statusLine block in settings.json, leaving every other setting alone.
"""
import json
import os
import pathlib
import shutil
import stat
import sys

HERE = pathlib.Path(__file__).resolve().parent


def main():
    claude_dir = pathlib.Path(
        os.environ.get("CLAUDE_CONFIG_DIR") or pathlib.Path.home() / ".claude"
    )
    claude_dir.mkdir(parents=True, exist_ok=True)

    src = HERE / "tokendiet.py"
    if not src.exists():
        sys.exit(f"{src} not found — run this from a checkout of the repo")

    dest = claude_dir / "tokendiet.py"
    shutil.copyfile(src, dest)
    dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"installed {dest}")

    settings = claude_dir / "settings.json"
    config = {}
    if settings.exists():
        backup = settings.parent / (settings.name + ".bak")
        shutil.copyfile(settings, backup)
        print(f"backup    {backup}")
        try:
            config = json.loads(settings.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            sys.exit(f"{settings} is not valid JSON ({e}) — fix it and re-run")

    # as_posix(): this path ends up inside JSON, where a Windows backslash
    # would start an escape sequence and break the file.
    runner = "python" if os.name == "nt" else "python3"
    wanted = {"type": "command", "command": f"{runner} {dest.as_posix()}", "padding": 0}

    previous = config.get("statusLine")
    if previous and previous != wanted:
        print(f"replaced  previous statusLine: {json.dumps(previous)}")

    config["statusLine"] = wanted
    settings.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"wired     {settings}")
    print("done — start a new Claude Code session to see the bar")


if __name__ == "__main__":
    main()
