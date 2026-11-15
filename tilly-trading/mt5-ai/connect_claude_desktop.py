"""Adds the `mt5` MCP server to Claude Desktop's config on Windows, keeping a backup
and every other server already there. Demo-only: MT5_AI_ALLOW_LIVE is never set.

    <venv python> connect_claude_desktop.py [--config PATH] [--python PATH] [--home C:\\mt5-ai] [--kronos-dir C:\\tilly-kronos]

Kronos is NOT enabled: it measured worse than a coin on this symbol (see README).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import sys
import time


def candidate_paths(env=os.environ) -> list[str]:
    out = []
    if env.get("APPDATA"):
        out.append(os.path.join(env["APPDATA"], "Claude", "claude_desktop_config.json"))
    if env.get("LOCALAPPDATA"):  # Microsoft Store build keeps its config in a package folder
        out += glob.glob(os.path.join(env["LOCALAPPDATA"], "Packages", "Claude_*", "LocalCache", "Roaming", "Claude", "claude_desktop_config.json"))
    return out


def server_entry(python: str, home: str, kronos_dir: str | None, symbols: str) -> dict:
    env = {"PYTHONPATH": home, "MT5_AI_SYMBOLS": symbols, "MT5_AI_MAX_RISK_PCT": "1.0"}
    if kronos_dir:
        env["MT5_AI_KRONOS_DIR"] = kronos_dir
    return {"command": python, "args": ["-m", "mt5_ai"], "env": env}


def merge(path: str, entry: dict) -> str | None:
    """Returns the backup path (None if the file didn't exist)."""
    data, backup = {}, None
    if os.path.exists(path):
        backup = f"{path}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
        shutil.copy2(path, backup)
        with open(path, encoding="utf-8-sig") as f:
            text = f.read().strip()
        data = json.loads(text) if text else {}
        if not isinstance(data, dict):
            raise SystemExit(f"{path} is not a JSON object; left untouched (backup at {backup}).")
    data.setdefault("mcpServers", {})["mt5"] = entry
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return backup


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--home", default=r"C:\mt5-ai")
    ap.add_argument("--kronos-dir", default=r"C:\tilly-kronos")
    ap.add_argument("--symbols", default="XAUUSD*")
    a = ap.parse_args()

    path = a.config
    if not path:
        existing = [p for p in candidate_paths() if os.path.exists(p)]
        if not existing:
            raise SystemExit("Claude Desktop's config file wasn't found. Open Claude Desktop > Settings > Developer > Edit Config "
                             "(that creates it), close the app, then run this again.")
        path = existing[0]
    backup = merge(path, server_entry(a.python, a.home, a.kronos_dir, a.symbols))
    print(f"Added the 'mt5' server to {path}")
    if backup:
        print(f"Backup of the old file: {backup}")
    print("Now fully quit Claude Desktop (system tray -> Quit) and open it again.")


if __name__ == "__main__":
    main()
