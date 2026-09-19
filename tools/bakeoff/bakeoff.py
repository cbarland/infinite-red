#!/usr/bin/env python3
"""Generator bake-off for Infinite Red native outdoor routes.

All contestants operate on native OVERWORLD block IDs. The same Pallet-facing
south seam and north-exit requirement are imposed on each candidate, then a
deterministic repair/validator guarantees traversability before rendering.
"""
from __future__ import annotations

import argparse
import heapq
import json
import math
import random
import time
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image, ImageDraw

from pokered_native import (
    BLOCK_TILES,
    NativeMap,
    OVERWORLD_GRASS,
    OVERWORLD_LEDGE_TILES,
    OVERWORLD_WALKABLE,
    OVERWORLD_WARP_TILES,
    expand_blocks,
    load_blockset,
    load_map,
    parse_header,
    render_map,
)

TARGET_W = 10
TARGET_H = 18
PATH_BLOCKS = (0x0A, 0x31)
GRASS_BLOCK = 0x0B
LEFT_EDGE = (0x4E, 0x6D)
RIGHT_EDGE = (0x4D, 0x6E)
OBSTACLE_BLOCKS = (0x1C, 0x52, 0x6F, 0x4F, 0x50, 0x62, 0x63)
MASK_TOKEN = 128


@dataclass
class Corpus:
    windows: np.ndarray
    vocab: list[int]
    source_names: list[str]


def collect_route_corpus(repo: Path) -> Corpus:
    windows: list[np.ndarray] = []
    names: list[str] = []
    header_dir = repo / "data" / "maps" / "headers"
    for header in sorted(header_dir.glob("*.asm")):
        try:
            name, map_id, tileset, _ = parse_header(header)
        except ValueError:
            continue
        if tileset != "OVERWORLD" or not map_id.startswith("ROUTE_"):
            continue
        try:
            native = load_map(repo, name)
        except (FileNotFoundError, ValueError):
            continue
        grid = np.frombuffer(native.block_bytes, dtype=np.uint8).reshape(
            native.height, native.width
        )
        transforms = [
            grid,
            np.fliplr(grid),
            np.flipud(grid),
            np.flipud(np.fliplr(grid)),
            np.rot90(grid, 1),
            np.rot90(grid, 3),
        ]
        before = len(windows)
        for transformed in transforms:
            h, w = transformed.shape
            if h < TARGET_H or w < TARGET_W:
                continue
            y_positions = list(range(0, h - TARGET_H + 1, max(1, TARGET_H // 2)))
            x_positions = list(range(0, w - TARGET_W + 1, max(1, TARGET_W // 2)))
            if y_positions[-1] != h - TARGET_H:
                y_positions.append(h - TARGET_H)
            if x_positions[-1] != w - TARGET_W:
                x_positions.append(w - TARGET_W)
            for y in y_positions:
                for x in x_positions:
                    windows.append(
                        transformed[y : y + TARGET_H, x : x + TARGET_W].copy()
                    )
                    names.append(name)
        if len(windows) == before:
            for transformed in transforms:
                h, w = transformed.shape
                if h == 0 or w == 0:
                    continue
                tiled = np.tile(
                    transformed,
                    (
                        math.ceil(TARGET_H / h),
                        math.ceil(TARGET_W / w),
                    ),
                )
                windows.append(tiled[:TARGET_H, :TARGET_W].copy())
                names.append(name)

    if not windows:
        raise RuntimeError("no OVERWORLD route training windows extracted")
    data = np.stack(windows).astype(np.int64)
    vocab = sorted({int(v) for v in data.reshape(-1)})
    return Corpus(data, vocab, names)


def block_tiles(blockset: bytes, block_id: int) -> bytes:
    offset = block_id * 16
    return blockset[offset : offset + 16]


def block_walk_fraction(blockset: bytes, block_id: int) -> float:
    tiles = block_tiles(blockset, block_id)
    return sum(tile in OVERWORLD_WALKABLE for tile in tiles) / 16.0


def choose_north_exit(seed: int) -> int:
    rng = random.Random(seed ^ 0xA91E)
    return rng.randint(2, 6)


def fixed_constraints(repo: Path, seed: int) -> dict[tuple[int, int], int]:
    route1 = load_map(repo, "Route1")
    seam = route1.block_bytes[-TARGET_W:]
    fixed = {(x, TARGET_H - 1): int(seam[x]) for x in range(TARGET_W)}
    exit_x = choose_north_exit(seed)
    fixed[(exit_x, 0)] = PATH_BLOCKS[1]
    fixed[(exit_x + 1, 0)] = PATH_BLOCKS[1]
    return fixed


def apply_fixed(grid: np.ndarray, fixed: dict[tuple[int, int], int]) -> None:
    for (x, y), value in fixed.items():
        grid[y, x] = value


def block_cell_cost(blockset: bytes, block_id: int) -> float:
    frac = block_walk_fraction(blockset, int(block_id))
    if frac >= 0.75:
        return 0.0
    if frac >= 0.25:
        return 0.5
    return 1.0


def repair_connectivity(
    repo: Path, grid: np.ndarray, seed: int
) -> tuple[np.ndarray, int, bool]:
    blockset = load_blockset(repo, "OVERWORLD")
    start = (2, TARGET_H - 1)
    exit_x = choose_north_exit(seed)
    targets = {(exit_x, 0), (exit_x + 1, 0)}

    dist = {start: 0.0}
    prev: dict[tuple[int, int], tuple[int, int]] = {}
    heap = [(0.0, start)]
    target = None
    while heap:
        cost, pos = heapq.heappop(heap)
        if cost != dist[pos]:
            continue
        if pos in targets:
            target = pos
            break
        x, y = pos
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if not (0 <= nx < TARGET_W and 0 <= ny < TARGET_H):
                continue
            step = block_cell_cost(blockset, int(grid[ny, nx]))
            new = cost + step
            if new < dist.get((nx, ny), 1e9):
                dist[(nx, ny)] = new
                prev[(nx, ny)] = pos
                heapq.heappush(heap, (new, (nx, ny)))

    if target is None:
        return grid, 0, False

    path = []
    cur = target
    while cur != start:
        path.append(cur)
        cur = prev[cur]
    path.append(start)
    path.reverse()

    fixed = fixed_constraints(repo, seed)
    repairs = 0
    out = grid.copy()
    for i, (x, y) in enumerate(path):
        if (x, y) in fixed:
            continue
        if block_cell_cost(blockset, int(out[y, x])) > 0:
            out[y, x] = PATH_BLOCKS[(seed + x + y + i) % len(PATH_BLOCKS)]
            repairs += 1
    apply_fixed(out, fixed)
    return out, repairs, True


def tile_connectivity(repo: Path, grid: np.ndarray, seed: int) -> bool:
    slot = load_map(repo, "Route1")
    native = NativeMap(
        name="GeneratedRoute",
        map_id=slot.map_id,
        width=TARGET_W,
        height=TARGET_H,
        tileset="OVERWORLD",
        border_block=slot.border_block,
        connections=slot.connections,
        warps=[],
        backgrounds=[],
        objects=[],
        block_bytes=grid.astype(np.uint8).tobytes(),
    )
    blockset = load_blockset(repo, "OVERWORLD")
    tiles = expand_blocks(native, blockset)
    walk = [[tile in OVERWORLD_WALKABLE for tile in row] for row in tiles]
    sx, sy = 2 * BLOCK_TILES + 1, TARGET_H * BLOCK_TILES - 2
    if not walk[sy][sx]:
        return False
    exit_x = choose_north_exit(seed)
    targets = {
        (exit_x * BLOCK_TILES + dx, 0)
        for dx in range(BLOCK_TILES * 2)
    }
    q = deque([(sx, sy)])
    seen = {(sx, sy)}
    while q:
        x, y = q.popleft()
        if (x, y) in targets:
            return True
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if (
                0 <= ny < len(walk)
                and 0 <= nx < len(walk[0])
                and walk[ny][nx]
                and (nx, ny) not in seen
            ):
                seen.add((nx, ny))
                q.append((nx, ny))
    return False


def graph_generator(repo: Path, seed: int) -> np.ndarray:
    rng = random.Random(seed)
    grid = np.full((TARGET_H, TARGET_W), GRASS_BLOCK, dtype=np.int64)

    for y in range(TARGET_H - 1):
        grid[y, 0] = rng.choice(LEFT_EDGE)
        grid[y, TARGET_W - 1] = rng.choice(RIGHT_EDGE)

    exit_x = choose_north_exit(seed)
    nodes = [(2, TARGET_H - 2)]
    for y in [14, 10, 6, 2]:
        nodes.append((rng.randint(1, TARGET_W - 3), y))
    nodes.append((exit_x, 0))

    def carve(a: tuple[int, int], b: tuple[int, int], width: int = 2) -> None:
        x, y = a
        tx, ty = b
        while (x, y) != (tx, ty):
            for dx in range(width):
                if 0 <= x + dx < TARGET_W:
                    grid[y, x + dx] = rng.choice(PATH_BLOCKS)
            if x != tx and (y == ty or rng.random() < 0.45):
                x += 1 if tx > x else -1
            elif y != ty:
                y += 1 if ty > y else -1
            else:
                x += 1 if tx > x else -1
        for dx in range(width):
            if 0 <= x + dx < TARGET_W:
                grid[y, x + dx] = rng.choice(PATH_BLOCKS)

    for a, b in zip(nodes, nodes[1:]):
        carve(a, b)

    y1 = rng.randint(7, 11)
    y2 = max(3, y1 - rng.randint(3, 5))
    main_x = min(TARGET_W - 3, max(1, nodes[2][0]))
    alt_x = 1 if main_x >= TARGET_W // 2 else TARGET_W - 3
    carve((main_x, y1), (alt_x, y1), 1)
    carve((alt_x, y1), (alt_x, y2), 1)
    carve((alt_x, y2), (nodes[3][0], y2), 1)

    for _ in range(rng.randint(3, 6)):
        cx, cy = rng.randint(2, 7), rng.randint(2, 14)
        radius = rng.choice((1, 1, 2))
        for y in range(max(1, cy - radius), min(TARGET_H - 1, cy + radius + 1)):
            for x in range(max(1, cx - radius), min(TARGET_W - 1, cx + radius + 1)):
                if grid[y, x] not in PATH_BLOCKS and rng.random() < 0.7:
                    grid[y, x] = rng.choice(OBSTACLE_BLOCKS)

    apply_fixed(grid, fixed_constraints(repo, seed))
    return grid


def build_adjacency(corpus: Corpus):
    allowed = {
        "left": defaultdict(set),
        "right": defaultdict(set),
        "up": defaultdict(set),
        "down": defaultdict(set),
    }
    freq = Counter(int(x) for x in corpus.windows.reshape(-1))
    for grid in corpus.windows:
        for y in range(TARGET_H):
            for x in range(TARGET_W):
                v = int(grid[y, x])
                if x > 0:
                    allowed["left"][v].add(int(grid[y, x - 1]))
                if x + 1 < TARGET_W:
                    allowed["right"][v].add(int(grid[y, x + 1]))
                if y > 0:
                    allowed["up"][v].add(int(grid[y - 1, x]))
                if y + 1 < TARGET_H:
                    allowed["down"][v].add(int(grid[y + 1, x]))
    return allowed, freq


def wfc_generator(repo: Path, corpus: Corpus, seed: int, retries: int = 30) -> np.ndarray:
    allowed, freq = build_adjacency(corpus)
    vocab = set(corpus.vocab)
    fixed = fixed_constraints(repo, seed)
    directions = [
        (-1, 0, "left"),
        (1, 0, "right"),
        (0, -1, "up"),
        (0, 1, "down"),
    ]

    for attempt in range(retries):
        rng = random.Random(seed * 1009 + attempt)
        poss = [[set(vocab) for _ in range(TARGET_W)] for _ in range(TARGET_H)]
        for (x, y), value in fixed.items():
            poss[y][x] = {value}

        queue = deque(fixed.keys())
        failed = False
        while True:
            while queue and not failed:
                x, y = queue.popleft()
                current = poss[y][x]
                for dx, dy, key in directions:
                    nx, ny = x + dx, y + dy
                    if not (0 <= nx < TARGET_W and 0 <= ny < TARGET_H):
                        continue
                    neighbor_allowed = set()
                    for v in current:
                        neighbor_allowed.update(allowed[key].get(v, vocab))
                    reduced = poss[ny][nx] & neighbor_allowed
                    if not reduced:
                        failed = True
                        break
                    if reduced != poss[ny][nx]:
                        poss[ny][nx] = reduced
                        queue.append((nx, ny))
            if failed:
                break

            unresolved = [
                (len(poss[y][x]), x, y)
                for y in range(TARGET_H)
                for x in range(TARGET_W)
                if len(poss[y][x]) > 1
            ]
            if not unresolved:
                return np.array(
                    [[next(iter(poss[y][x])) for x in range(TARGET_W)] for y in range(TARGET_H)],
                    dtype=np.int64,
                )
            entropy = min(v[0] for v in unresolved)
            cells = [(x, y) for n, x, y in unresolved if n == entropy]
            x, y = rng.choice(cells)
            choices = sorted(poss[y][x])
            weights = [freq[c] for c in choices]
            poss[y][x] = {rng.choices(choices, weights=weights, k=1)[0]}
            queue.append((x, y))

    rng = random.Random(seed ^ 0x55AA)
    grid = corpus.windows[rng.randrange(len(corpus.windows))].copy()
    apply_fixed(grid, fixed)
    return grid


def nearest_source_similarity(grid: np.ndarray, corpus: Corpus) -> float:
    return float(np.max(np.mean(corpus.windows == grid[None, :, :], axis=(1, 2))))


def pattern_novelty(grid: np.ndarray, corpus: Corpus) -> float:
    source_patterns = set()
    for src in corpus.windows:
        for y in range(TARGET_H - 1):
            for x in range(TARGET_W - 1):
                source_patterns.add(tuple(int(v) for v in src[y : y + 2, x : x + 2].reshape(-1)))
    patterns = []
    for y in range(TARGET_H - 1):
        for x in range(TARGET_W - 1):
            patterns.append(tuple(int(v) for v in grid[y : y + 2, x : x + 2].reshape(-1)))
    return sum(p not in source_patterns for p in patterns) / max(1, len(patterns))


def component_count(mask: np.ndarray) -> int:
    seen = set()
    count = 0
    h, w = mask.shape
    for y in range(h):
        for x in range(w):
            if not mask[y, x] or (x, y) in seen:
                continue
            count += 1
            stack = [(x, y)]
            seen.add((x, y))
            while stack:
                cx, cy = stack.pop()
                for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                    if 0 <= nx < w and 0 <= ny < h and mask[ny, nx] and (nx, ny) not in seen:
                        seen.add((nx, ny))
                        stack.append((nx, ny))
    return count


def layout_metrics(repo: Path, grid: np.ndarray, corpus: Corpus, seed: int, repairs: int, elapsed: float):
    blockset = load_blockset(repo, "OVERWORLD")
    walk_frac = np.array(
        [[block_walk_fraction(blockset, int(grid[y, x])) for x in range(TARGET_W)] for y in range(TARGET_H)]
    )
    grass = np.array(
        [[OVERWORLD_GRASS in block_tiles(blockset, int(grid[y, x])) for x in range(TARGET_W)] for y in range(TARGET_H)]
    )
    obstacles = walk_frac < 0.5
    open_cells = walk_frac >= 0.75
    return {
        "connected": tile_connectivity(repo, grid, seed),
        "repair_blocks": repairs,
        "nearest_source_similarity": round(nearest_source_similarity(grid, corpus), 4),
        "pattern_novelty": round(pattern_novelty(grid, corpus), 4),
        "unique_blocks": int(len(set(int(v) for v in grid.reshape(-1)))),
        "grass_regions": component_count(grass),
        "obstacle_regions": component_count(obstacles),
        "open_fraction": round(float(np.mean(open_cells)), 4),
        "grass_fraction": round(float(np.mean(grass)), 4),
        "seconds": round(elapsed, 4),
    }


def native_from_grid(repo: Path, grid: np.ndarray) -> NativeMap:
    slot = load_map(repo, "Route1")
    return NativeMap(
        name="Bakeoff",
        map_id=slot.map_id,
        width=TARGET_W,
        height=TARGET_H,
        tileset="OVERWORLD",
        border_block=slot.border_block,
        connections=slot.connections,
        warps=[],
        backgrounds=[],
        objects=[],
        block_bytes=grid.astype(np.uint8).tobytes(),
    )


def render_candidate(repo: Path, grid: np.ndarray, path: Path, scale: int = 2) -> None:
    render_map(repo, native_from_grid(repo, grid), path, scale)


def contact_sheet(images: list[tuple[str, Path]], output: Path) -> None:
    opened = [(label, Image.open(path).convert("RGB")) for label, path in images]
    if not opened:
        return
    thumb_w = max(img.width for _, img in opened)
    thumb_h = max(img.height for _, img in opened)
    cols = 4
    rows = math.ceil(len(opened) / cols)
    label_h = 26
    sheet = Image.new("RGB", (cols * thumb_w, rows * (thumb_h + label_h)), "white")
    draw = ImageDraw.Draw(sheet)
    for i, (label, img) in enumerate(opened):
        x = (i % cols) * thumb_w
        y = (i // cols) * (thumb_h + label_h)
        sheet.paste(img, (x, y + label_h))
        draw.text((x + 4, y + 5), label, fill="black")
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)


def run_generator(
    repo: Path,
    corpus: Corpus,
    name: str,
    fn: Callable[[int], np.ndarray],
    seeds: list[int],
    out_dir: Path,
):
    results = []
    images = []
    generator_dir = out_dir / name
    generator_dir.mkdir(parents=True, exist_ok=True)
    for seed in seeds:
        started = time.perf_counter()
        raw = fn(seed)
        repaired, repairs, path_found = repair_connectivity(repo, raw, seed)
        elapsed = time.perf_counter() - started
        apply_fixed(repaired, fixed_constraints(repo, seed))
        metrics = layout_metrics(repo, repaired, corpus, seed, repairs, elapsed)
        metrics["repair_path_found"] = path_found
        png = generator_dir / f"seed-{seed}.png"
        render_candidate(repo, repaired, png)
        np.save(generator_dir / f"seed-{seed}.npy", repaired)
        images.append((f"{name} / {seed}", png))
        results.append({"generator": name, "seed": seed, **metrics})
    contact_sheet(images, out_dir / f"{name}-contact-sheet.png")
    return results


def summarize(results: list[dict]) -> dict:
    by = defaultdict(list)
    for row in results:
        by[row["generator"]].append(row)
    summary = {}
    numeric = [
        "connected",
        "repair_blocks",
        "nearest_source_similarity",
        "pattern_novelty",
        "unique_blocks",
        "grass_regions",
        "obstacle_regions",
        "open_fraction",
        "grass_fraction",
        "seconds",
    ]
    for name, rows in by.items():
        summary[name] = {}
        for key in numeric:
            vals = [float(r[key]) for r in rows]
            summary[name][key] = round(sum(vals) / len(vals), 4)
    return summary


def write_report(corpus: Corpus, results: list[dict], output: Path) -> None:
    summary = summarize(results)
    lines = [
        "# Infinite Red route-generator bake-off",
        "",
        f"Training windows: **{len(corpus.windows)}** from **{len(set(corpus.source_names))}** source routes.",
        f"Native block vocabulary: **{len(corpus.vocab)}** IDs.",
        "",
        "All candidates share the same Pallet seam and north-exit constraint and pass through the same deterministic connectivity repair.",
        "",
        "| Generator | Connected | Repair blocks | Nearest-source similarity | 2x2 novelty | Unique blocks | Grass regions | Obstacle regions | sec/map |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, m in summary.items():
        lines.append(
            f"| {name} | {m['connected']:.2f} | {m['repair_blocks']:.2f} | "
            f"{m['nearest_source_similarity']:.3f} | {m['pattern_novelty']:.3f} | "
            f"{m['unique_blocks']:.2f} | {m['grass_regions']:.2f} | "
            f"{m['obstacle_regions']:.2f} | {m['seconds']:.3f} |"
        )
    lines += [
        "",
        "Lower nearest-source similarity is better if the result remains coherent. Higher 2x2 novelty indicates new local composition. Fewer repair blocks means the generator understood connectivity rather than outsourcing it to the solver.",
        "",
        "Visual contact sheets remain the primary composition check; these metrics are guardrails.",
    ]
    output.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seeds", default="41,42,43,44,45,46,47,48")
    parser.add_argument("--diffusion-checkpoint")
    args = parser.parse_args()

    repo = Path(args.repo)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    seeds = [int(v.strip()) for v in args.seeds.split(",") if v.strip()]
    corpus = collect_route_corpus(repo)

    metadata = {
        "windows": len(corpus.windows),
        "source_routes": sorted(set(corpus.source_names)),
        "vocab": corpus.vocab,
    }
    (output / "corpus.json").write_text(json.dumps(metadata, indent=2) + "\n")

    results = []
    results += run_generator(repo, corpus, "graph", lambda seed: graph_generator(repo, seed), seeds, output)
    results += run_generator(repo, corpus, "wfc", lambda seed: wfc_generator(repo, corpus, seed), seeds, output)

    if args.diffusion_checkpoint:
        from tiny_diffusion import load_sampler
        sampler = load_sampler(Path(args.diffusion_checkpoint), repo, corpus)
        results += run_generator(repo, corpus, "diffusion", sampler, seeds, output)

    (output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    write_report(corpus, results, output / "report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
