#!/usr/bin/env python3
"""Jev critic and style-director for synthetic Infinite Red route maps.

Jev sees compact semantic ASCII grids and typed metadata, not screenshots.
Its judgments are advisory labels used for reranking and research fine-tuning.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

from jev import choice, decide, score

SYMBOLS = {0: "#", 1: "+", 2: ".", 3: '"'}

STYLE_PROFILES = {
    "woodland_trail": "Tree/brush boundaries, irregular grass pockets, narrow natural clearings, moderate visual enclosure.",
    "open_meadow": "Broad grass/open-ground fields, sparse barriers, gentle path rhythm, occasional isolated landmarks.",
    "scrub_route": "Patchy mixed terrain and grass, broken sightlines, irregular small clearings, less formal path geometry.",
}

def ascii_grid(grid: np.ndarray) -> str:
    return "\n".join("".join(SYMBOLS[int(v)] for v in row) for row in grid)

def candidate_state(candidate: dict[str, Any]) -> str:
    metrics = candidate.get("metrics", {})
    context = candidate.get("context", {})
    return (
        "You are judging a synthetic Pokémon Red-style outdoor route layout.\n"
        "Legend: #=solid terrain, +=mixed edge terrain, .=open ground/path, \"=tall grass.\n"
        "The map must feel hand-authored, readable, exploratory, and plausible for Generation 1.\n"
        "Do not reward random noise or mere novelty. Prefer meaningful spatial composition: regions, "
        "clearings, chokepoints, optional branches, landmarks, visual rhythm, and a legible main traversal.\n\n"
        f"CONTEXT:\n{json.dumps(context, sort_keys=True)}\n\n"
        f"METRICS:\n{json.dumps(metrics, sort_keys=True)}\n\n"
        f"GRID:\n{candidate['ascii']}\n"
    )

def judge(candidate: dict[str, Any]) -> dict[str, Any]:
    questions = {
        "route_quality": score(
            "Score overall route layout quality from 0 to 1.",
            {
                "poor": "Corridor, noise, large bland bands, awkward composition, or little meaningful structure.",
                "excellent": "Feels intentionally designed with readable traversal, regions, choices, landmarks, and visual rhythm.",
            },
        ),
        "exploration_interest": score(
            "Score how interesting this would be to explore from 0 to 1.",
            {
                "poor": "Only one obvious corridor or empty field with little spatial discovery.",
                "excellent": "Main path plus meaningful optional spaces, branches, reveals, or alternate movement opportunities.",
            },
        ),
        "naturalness": score(
            "Score whether terrain masses and grass/open regions look naturally composed rather than procedurally noisy.",
            {
                "poor": "Checkerboard, speckle noise, repeated stripes, or arbitrary isolated cells.",
                "excellent": "Coherent regions with believable boundaries and varied but purposeful shapes.",
            },
        ),
        "visual_rhythm": score(
            "Score pacing of compression/opening and spatial variation from 0 to 1.",
            {
                "poor": "Same width/density throughout or abrupt arbitrary texture.",
                "excellent": "Alternates enclosure, clearings, bends, landmarks, and route-width changes in a deliberate rhythm.",
            },
        ),
        "originality": score(
            "Score originality relative to a typical vanilla Kanto route while remaining stylistically compatible.",
            {
                "poor": "Feels copied, trivial, or like a slight variation of a familiar route.",
                "excellent": "Clearly new composition that still looks like it belongs in Pokémon Red.",
            },
        ),
        "fatal_issue": choice(
            "Choose the most important structural problem, if any.",
            {
                "none": "No dominant fatal issue.",
                "corridor": "Mostly a single corridor without meaningful spatial structure.",
                "bands": "Large homogeneous bands or zones dominate the map.",
                "noise": "Terrain is noisy/speckled without coherent regions.",
                "empty": "Too much undifferentiated open or grass space.",
                "overblocked": "Too constrained or cluttered to read as a pleasant route.",
                "copylike": "Too close to an existing-looking vanilla layout.",
            },
        ),
    }
    return decide(candidate_state(candidate), questions)

def choose_style(candidate: dict[str, Any], previous_style: str | None = None) -> dict[str, Any]:
    state = candidate_state(candidate)
    if previous_style:
        state += f"\nPREVIOUS AREA STYLE: {previous_style}\n"
    questions = {
        "style": choice(
            "Choose the single native visual style profile that best fits this topology and world context.",
            STYLE_PROFILES,
        ),
        "boundary_density": choice(
            "Choose how visually dense boundaries/obstacles should be when materializing native blocks.",
            {
                "light": "Mostly open sightlines and sparse hard boundaries.",
                "medium": "Balanced open space and enclosing terrain.",
                "heavy": "Strong enclosure, terrain masses, and narrower views.",
            },
        ),
        "grass_pattern": choice(
            "Choose the preferred grass composition.",
            {
                "few_large": "A few large coherent grass fields.",
                "several_medium": "Several medium grass regions separated by path/open terrain.",
                "many_small": "Many small patches; use only if topology remains coherent.",
            },
        ),
        "path_formality": choice(
            "Choose the visual character of the path.",
            {
                "organic": "Irregular natural route with bends and variable width.",
                "balanced": "Readable route with some regularity and some natural variation.",
                "formal": "More ordered road-like structure, especially near settlements.",
            },
        ),
    }
    return decide(state, questions)

def extract_answer(response: dict[str, Any], key: str) -> Any:
    answers = response.get("answers", {})
    value = answers.get(key)
    if isinstance(value, dict):
        for field in ("value", "answer", "choice", "score"):
            if field in value:
                return value[field]
    return value

def label_directory(input_dir: Path, output: Path, previous_style: str | None) -> None:
    rows = []
    for path in sorted(input_dir.glob("*.semantic.npy")):
        grid = np.load(path)
        candidate = {
            "id": path.stem,
            "ascii": ascii_grid(grid),
            "metrics": {},
            "context": {"area_kind": "route"},
        }
        judgment = judge(candidate)
        style = choose_style(candidate, previous_style)
        rows.append(
            {
                "id": candidate["id"],
                "ascii": candidate["ascii"],
                "judgment": judgment,
                "style": style,
                "summary": {
                    "route_quality": extract_answer(judgment, "route_quality"),
                    "exploration_interest": extract_answer(judgment, "exploration_interest"),
                    "naturalness": extract_answer(judgment, "naturalness"),
                    "visual_rhythm": extract_answer(judgment, "visual_rhythm"),
                    "originality": extract_answer(judgment, "originality"),
                    "fatal_issue": extract_answer(judgment, "fatal_issue"),
                    "style": extract_answer(style, "style"),
                },
            }
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input-dir", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--previous-style")
    args = p.parse_args()
    label_directory(Path(args.input_dir), Path(args.output), args.previous_style)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
