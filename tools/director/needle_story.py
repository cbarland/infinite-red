#!/usr/bin/env python3
"""Invoke an externally installed Needle 3 runner for structured story planning.

Infinite Red does not vendor Needle binaries or weights. Set NEEDLE_BIN and
NEEDLE_MODEL, or place the needle runner on PATH and set NEEDLE_MODEL.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
TOOLS_SCHEMA = ROOT / "schemas" / "needle-story-tools.json"


def find_runner() -> str:
    configured = os.environ.get("NEEDLE_BIN")
    if configured:
        return configured
    found = shutil.which("needle")
    if not found:
        raise RuntimeError("Needle runner not found; set NEEDLE_BIN or add needle to PATH")
    return found


def run_story(prompt: str, world_state: str) -> dict:
    runner = find_runner()
    model = os.environ.get("NEEDLE_MODEL")
    if not model:
        raise RuntimeError("NEEDLE_MODEL must point to a Needle .cact weights file")

    schema = json.loads(TOOLS_SCHEMA.read_text(encoding="utf-8"))
    tools = schema["tools"]
    transcript = (
        "You are the local structured story planner for Infinite Red. "
        "Return only calls from the supplied tool set. "
        "Prefer callbacks and promise resolution when closure pressure is high.\n\n"
        f"WORLD STATE:\n{world_state}\n\nREQUEST:\n{prompt}"
    )

    with tempfile.TemporaryDirectory(prefix="infinite-red-needle-") as td:
        tools_path = Path(td) / "tools.json"
        tools_path.write_text(json.dumps(tools), encoding="utf-8")
        env = dict(os.environ)
        env.setdefault("NEEDLE_TELEMETRY", "0")
        env.setdefault("DO_NOT_TRACK", "1")
        proc = subprocess.run(
            [
                runner,
                "--model",
                model,
                "--tools",
                str(tools_path),
                "--prompt",
                transcript,
            ],
            capture_output=True,
            text=True,
            timeout=45,
            env=env,
        )
    if proc.returncode != 0:
        raise RuntimeError(f"Needle failed ({proc.returncode}): {proc.stderr.strip()}")

    text = proc.stdout.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        for line in reversed(text.splitlines()):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                return json.loads(line)
        raise RuntimeError(f"Needle did not emit JSON: {text[-800:]}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Needle story planning for Infinite Red")
    parser.add_argument("--prompt", required=True)
    parser.add_argument(
        "--state",
        help="World-state text/JSON file. If omitted, read world state from stdin.",
    )
    args = parser.parse_args()
    world_state = (
        Path(args.state).read_text(encoding="utf-8") if args.state else sys.stdin.read()
    )
    result = run_story(args.prompt, world_state)
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
