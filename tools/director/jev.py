#!/usr/bin/env python3
"""Thin Jev Decisions client for Infinite Red.

No fuzzy-calc dependency. The endpoint/model are configurable because the
OpenRouter Decisions surface is experimental.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

DEFAULT_ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
DEFAULT_MODEL = "typesafe/jev-1.13"


def noul(instructions: str, criteria: dict[str, str] | None = None) -> dict[str, Any]:
    q: dict[str, Any] = {"type": "noul", "instructions": instructions}
    if criteria:
        q["criteria"] = criteria
    return q


def choice(instructions: str, criteria: dict[str, str]) -> dict[str, Any]:
    return {"type": "choice", "instructions": instructions, "criteria": criteria}


def score(instructions: str, criteria: dict[str, str]) -> dict[str, Any]:
    return {"type": "score", "instructions": instructions, "criteria": criteria}


def decide(
    state: str,
    questions: dict[str, dict[str, Any]],
    *,
    model: str | None = None,
    endpoint: str | None = None,
) -> dict[str, Any]:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")

    payload = {
        "model": model or os.environ.get("INFINITE_RED_JEV_MODEL", DEFAULT_MODEL),
        "state": state,
        "questions": questions,
    }
    target = endpoint or os.environ.get("INFINITE_RED_JEV_ENDPOINT", DEFAULT_ENDPOINT)
    request = urllib.request.Request(
        target,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:800]
        raise RuntimeError(f"Jev request failed with HTTP {exc.code}: {detail}") from exc

    if "answers" not in body:
        raise RuntimeError(f"Jev response did not contain answers: {body}")
    return body


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Send a batched Infinite Red decision request to Jev."
    )
    parser.add_argument(
        "--input",
        help="JSON file containing {state, questions}; defaults to stdin",
    )
    args = parser.parse_args()

    raw = open(args.input, "r", encoding="utf-8").read() if args.input else sys.stdin.read()
    request = json.loads(raw)
    response = decide(str(request["state"]), dict(request["questions"]))
    json.dump(response, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
