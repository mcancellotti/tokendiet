#!/usr/bin/env bash
# Copies tokendiet.py into your Claude Code config dir and wires it into
# settings.json as the statusLine, leaving the rest of your settings alone.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/tokendiet.py"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
SETTINGS="$CLAUDE_DIR/settings.json"

command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }

mkdir -p "$CLAUDE_DIR"
install -m 0755 "$SRC" "$CLAUDE_DIR/tokendiet.py"
echo "installed $CLAUDE_DIR/tokendiet.py"

if [ -f "$SETTINGS" ]; then
  cp "$SETTINGS" "$SETTINGS.bak"
  echo "backup    $SETTINGS.bak"
fi

python3 - "$SETTINGS" "$CLAUDE_DIR/tokendiet.py" <<'PY'
import json, sys

settings_path, script_path = sys.argv[1], sys.argv[2]

try:
    with open(settings_path) as f:
        settings = json.load(f)
except FileNotFoundError:
    settings = {}
except json.JSONDecodeError as e:
    sys.exit(f"{settings_path} is not valid JSON ({e}) - fix it and re-run")

wanted = {"type": "command", "command": f"python3 {script_path}", "padding": 0}
previous = settings.get("statusLine")
if previous and previous != wanted:
    print(f"replaced  previous statusLine: {json.dumps(previous)}")

settings["statusLine"] = wanted
with open(settings_path, "w") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")
print(f"wired     {settings_path}")
PY

echo "done - start a new Claude Code session to see the bar"
