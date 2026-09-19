#!/usr/bin/env python3
"""Native Pokémon Red map parser/materializer for Infinite Red.

This module reads a local checkout of pret/pokered at the revision pinned by
config/pokered-source.toml. It deliberately operates on the decomp's native
map/block/object formats rather than introducing a parallel map format.
"""
from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import random
import re
from dataclasses import asdict, dataclass
from pathlib import Path

TILE_PX = 8
BLOCK_TILES = 4
BLOCK_PX = TILE_PX * BLOCK_TILES
TILES_PER_BLOCK = BLOCK_TILES * BLOCK_TILES

# Pinned OVERWORLD semantics from pret/pokered at config/pokered-source.toml.
# The first generated Route 1 conservatively preserves the exact walkability
# and grass masks of the original map. Blocks containing warp/ledge special
# tiles are never substituted.
OVERWORLD_WALKABLE = {
    0x00, 0x10, 0x1B, 0x20, 0x21, 0x23, 0x2C, 0x2D, 0x2E, 0x30,
    0x31, 0x33, 0x39, 0x3C, 0x3E, 0x52, 0x54, 0x58, 0x5B,
}
OVERWORLD_GRASS = 0x52
OVERWORLD_WARP_TILES = {0x1B, 0x58}
OVERWORLD_LEDGE_TILES = {0x37, 0x36, 0x27, 0x0D, 0x1D}

FIRST_ROUTE_GROUND = 0x0A
FIRST_ROUTE_PATH = 0x31
FIRST_ROUTE_GRASS = 0x0B
FIRST_ROUTE_LEFT_EDGE = (0x4E, 0x6D)
FIRST_ROUTE_RIGHT_EDGE = (0x4D, 0x6E)

SEM_SOLID = 0
SEM_MIXED = 1
SEM_OPEN = 2
SEM_GRASS = 3
SEM_W = 20
SEM_H = 36

WOODLAND_ROUTE_BLOCKS = (
    0x0A, 0x0B, 0x1C, 0x31, 0x4D, 0x4E, 0x4F, 0x50,
    0x51, 0x52, 0x62, 0x63, 0x6D, 0x6E, 0x6F, 0x74,
)

NAME_PREFIXES = (
    "CEDAR", "AMBER", "MIST", "WILLOW", "FERN", "PINE", "SILVER", "MOSS",
    "STONE", "MAPLE", "BIRCH", "CLOVER", "HAZEL", "IVY", "RAVEN", "GOLDEN",
)
ROUTE_SUFFIXES = ("PATH", "TRAIL", "PASS", "ROAD", "WAY", "RIDGE", "RUN")
SETTLEMENT_SUFFIXES = ("TOWN", "CITY", "VALE", "HAVEN")

MAP_CONST_RE = re.compile(
    r"^\s*map_const\s+(?P<id>[A-Z0-9_]+),\s*(?P<width>\d+),\s*(?P<height>\d+)",
    re.MULTILINE,
)
MAP_HEADER_RE = re.compile(
    r"^\s*map_header\s+(?P<name>[A-Za-z0-9_]+),\s*(?P<id>[A-Z0-9_]+),\s*(?P<tileset>[A-Z0-9_]+)",
    re.MULTILINE,
)
CONNECTION_RE = re.compile(
    r"^\s*connection\s+(?P<direction>north|south|east|west),\s*"
    r"(?P<target_name>[A-Za-z0-9_]+),\s*(?P<target_id>[A-Z0-9_]+),\s*"
    r"(?P<offset>-?\d+)",
    re.MULTILINE,
)
BORDER_RE = re.compile(
    r"^\s*db\s+(?P<value>\$[0-9a-fA-F]+|\d+)\s*;\s*border block",
    re.MULTILINE,
)
EVENT_RE = re.compile(
    r"^\s*(?P<kind>warp_event|bg_event|object_event)\s+(?P<args>[^;\n]+)",
    re.MULTILINE,
)


@dataclass(frozen=True)
class MapConstant:
    map_id: str
    width: int
    height: int


@dataclass(frozen=True)
class Connection:
    direction: str
    target_name: str
    target_id: str
    offset: int


@dataclass(frozen=True)
class Event:
    kind: str
    args: list[str]


@dataclass(frozen=True)
class NativeMap:
    name: str
    map_id: str
    width: int
    height: int
    tileset: str
    border_block: int
    connections: list[Connection]
    warps: list[Event]
    backgrounds: list[Event]
    objects: list[Event]
    block_bytes: bytes

    @property
    def block_count(self) -> int:
        return len(self.block_bytes)

    def manifest(self) -> dict:
        data = asdict(self)
        data.pop("block_bytes")
        data["block_count"] = self.block_count
        data["block_sha256"] = hashlib.sha256(self.block_bytes).hexdigest()
        return data


def _parse_int(text: str) -> int:
    text = text.strip()
    return int(text[1:], 16) if text.startswith("$") else int(text, 10)


def _split_args(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


def parse_map_constants(path: Path) -> dict[str, MapConstant]:
    text = path.read_text(encoding="utf-8")
    result: dict[str, MapConstant] = {}
    for match in MAP_CONST_RE.finditer(text):
        item = MapConstant(
            map_id=match.group("id"),
            width=int(match.group("width")),
            height=int(match.group("height")),
        )
        result[item.map_id] = item
    if not result:
        raise ValueError(f"no map_const entries found in {path}")
    return result


def parse_header(path: Path) -> tuple[str, str, str, list[Connection]]:
    text = path.read_text(encoding="utf-8")
    match = MAP_HEADER_RE.search(text)
    if not match:
        raise ValueError(f"no map_header found in {path}")
    connections = [
        Connection(
            direction=m.group("direction"),
            target_name=m.group("target_name"),
            target_id=m.group("target_id"),
            offset=int(m.group("offset")),
        )
        for m in CONNECTION_RE.finditer(text)
    ]
    return (
        match.group("name"),
        match.group("id"),
        match.group("tileset"),
        connections,
    )


def parse_objects(path: Path) -> tuple[int, list[Event], list[Event], list[Event]]:
    text = path.read_text(encoding="utf-8")
    border_match = BORDER_RE.search(text)
    if not border_match:
        raise ValueError(f"no border block found in {path}")
    border = _parse_int(border_match.group("value"))

    warps: list[Event] = []
    backgrounds: list[Event] = []
    objects: list[Event] = []
    for match in EVENT_RE.finditer(text):
        event = Event(kind=match.group("kind"), args=_split_args(match.group("args")))
        if event.kind == "warp_event":
            warps.append(event)
        elif event.kind == "bg_event":
            backgrounds.append(event)
        else:
            objects.append(event)
    return border, warps, backgrounds, objects


def load_map(repo: Path, map_name: str) -> NativeMap:
    header_path = repo / "data" / "maps" / "headers" / f"{map_name}.asm"
    object_path = repo / "data" / "maps" / "objects" / f"{map_name}.asm"
    blocks_path = repo / "maps" / f"{map_name}.blk"

    name, map_id, tileset, connections = parse_header(header_path)
    constants = parse_map_constants(repo / "constants" / "map_constants.asm")
    if map_id not in constants:
        raise ValueError(f"{map_id} missing from map_constants.asm")
    dims = constants[map_id]
    border, warps, backgrounds, objects = parse_objects(object_path)
    block_bytes = blocks_path.read_bytes()

    expected = dims.width * dims.height
    if len(block_bytes) != expected:
        raise ValueError(
            f"{map_name}.blk has {len(block_bytes)} bytes, expected "
            f"{dims.width}x{dims.height}={expected}"
        )

    return NativeMap(
        name=name,
        map_id=map_id,
        width=dims.width,
        height=dims.height,
        tileset=tileset,
        border_block=border,
        connections=connections,
        warps=warps,
        backgrounds=backgrounds,
        objects=objects,
        block_bytes=block_bytes,
    )


def _tileset_stem(tileset: str) -> str:
    aliases = {
        "OVERWORLD": "overworld",
        "REDS_HOUSE_1": "reds_house",
        "REDS_HOUSE_2": "reds_house",
        "FOREST_GATE": "gate",
        "POKECENTER": "pokecenter",
        "SHIP_PORT": "ship_port",
    }
    return aliases.get(tileset, tileset.lower())


def blockset_path(repo: Path, tileset: str) -> Path:
    return repo / "gfx" / "blocksets" / f"{_tileset_stem(tileset)}.bst"


def tileset_png_path(repo: Path, tileset: str) -> Path:
    return repo / "gfx" / "tilesets" / f"{_tileset_stem(tileset)}.png"


def load_blockset(repo: Path, tileset: str) -> bytes:
    path = blockset_path(repo, tileset)
    data = path.read_bytes()
    if len(data) % TILES_PER_BLOCK:
        raise ValueError(
            f"{path} length {len(data)} is not divisible by {TILES_PER_BLOCK}"
        )
    return data


def expand_blocks(native_map: NativeMap, blockset: bytes) -> list[list[int]]:
    """Expand native block IDs into a rectangular grid of native 8x8 tile IDs."""
    block_total = len(blockset) // TILES_PER_BLOCK
    tile_width = native_map.width * BLOCK_TILES
    tile_height = native_map.height * BLOCK_TILES
    grid = [[0 for _ in range(tile_width)] for _ in range(tile_height)]

    for by in range(native_map.height):
        for bx in range(native_map.width):
            block_id = native_map.block_bytes[by * native_map.width + bx]
            if block_id >= block_total:
                raise ValueError(
                    f"block ${block_id:02x} exceeds {block_total} blocks in "
                    f"{native_map.tileset}"
                )
            offset = block_id * TILES_PER_BLOCK
            block = blockset[offset : offset + TILES_PER_BLOCK]
            for ty in range(BLOCK_TILES):
                for tx in range(BLOCK_TILES):
                    grid[by * BLOCK_TILES + ty][bx * BLOCK_TILES + tx] = block[
                        ty * BLOCK_TILES + tx
                    ]
    return grid


def render_map(repo: Path, native_map: NativeMap, output: Path, scale: int = 1) -> None:
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            "rendering requires Pillow; install tools/native/requirements.txt"
        ) from exc

    sheet_path = tileset_png_path(repo, native_map.tileset)
    sheet = Image.open(sheet_path).convert("RGBA")
    if sheet.width % TILE_PX or sheet.height % TILE_PX:
        raise ValueError(f"tileset sheet {sheet_path} is not aligned to 8x8 tiles")

    tiles_per_row = sheet.width // TILE_PX
    tile_count = tiles_per_row * (sheet.height // TILE_PX)
    blockset = load_blockset(repo, native_map.tileset)
    tile_grid = expand_blocks(native_map, blockset)
    max_tile = max(max(row) for row in tile_grid)
    if max_tile >= tile_count:
        raise ValueError(
            f"map references tile ${max_tile:02x}, but {sheet_path} has "
            f"{tile_count} 8x8 tiles"
        )

    out = Image.new(
        "RGBA",
        (native_map.width * BLOCK_PX, native_map.height * BLOCK_PX),
    )
    for y, row in enumerate(tile_grid):
        for x, tile_id in enumerate(row):
            sx = (tile_id % tiles_per_row) * TILE_PX
            sy = (tile_id // tiles_per_row) * TILE_PX
            tile = sheet.crop((sx, sy, sx + TILE_PX, sy + TILE_PX))
            out.paste(tile, (x * TILE_PX, y * TILE_PX))

    if scale > 1:
        out = out.resize(
            (out.width * scale, out.height * scale),
            resample=Image.Resampling.NEAREST,
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    out.save(output)


def _block_tiles(blockset: bytes, block_id: int) -> bytes:
    block_total = len(blockset) // TILES_PER_BLOCK
    if block_id >= block_total:
        raise ValueError(f"block id {block_id} outside blockset ({block_total} blocks)")
    offset = block_id * TILES_PER_BLOCK
    return blockset[offset : offset + TILES_PER_BLOCK]


def _route_safe_signature(blockset: bytes, block_id: int) -> tuple | None:
    tiles = _block_tiles(blockset, block_id)
    specials = OVERWORLD_WARP_TILES | OVERWORLD_LEDGE_TILES
    if any(tile in specials for tile in tiles):
        return None
    walkability = tuple(tile in OVERWORLD_WALKABLE for tile in tiles)
    grass = tuple(tile == OVERWORLD_GRASS for tile in tiles)
    return walkability, grass


def _stable_index(seed: int, x: int, y: int, block_id: int, count: int) -> int:
    payload = f"{seed}:{x}:{y}:{block_id}".encode("ascii")
    digest = hashlib.blake2s(payload, digest_size=8).digest()
    return int.from_bytes(digest, "little") % count


def _stable_choice(seed: int, namespace: str, values: tuple[str, ...]) -> str:
    payload = f"{seed}:{namespace}".encode("ascii")
    digest = hashlib.blake2s(payload, digest_size=8).digest()
    return values[int.from_bytes(digest, "little") % len(values)]


def generate_location_names(seed: int) -> dict[str, str]:
    route_prefix = _stable_choice(seed, "route-prefix", NAME_PREFIXES)
    settlement_prefix = _stable_choice(seed, "settlement-prefix", NAME_PREFIXES)
    if settlement_prefix == route_prefix:
        index = (NAME_PREFIXES.index(settlement_prefix) + 5) % len(NAME_PREFIXES)
        settlement_prefix = NAME_PREFIXES[index]

    route = f"{route_prefix} {_stable_choice(seed, 'route-suffix', ROUTE_SUFFIXES)}"
    settlement = (
        f"{settlement_prefix} "
        f"{_stable_choice(seed, 'settlement-suffix', SETTLEMENT_SUFFIXES)}"
    )
    if len(route) > 18 or len(settlement) > 18:
        raise AssertionError("generated location name exceeds Red display budget")
    return {"route": route, "settlement": settlement}


def _semantic_quadrant_class(tiles: list[int]) -> int:
    if sum(tile == OVERWORLD_GRASS for tile in tiles) >= 2:
        return SEM_GRASS
    walk_fraction = sum(tile in OVERWORLD_WALKABLE for tile in tiles) / 4.0
    if walk_fraction >= 0.75:
        return SEM_OPEN
    if walk_fraction <= 0.25:
        return SEM_SOLID
    return SEM_MIXED


def _native_block_semantic_signature(blockset: bytes, block_id: int) -> tuple[int, ...]:
    block = _block_tiles(blockset, block_id)
    result: list[int] = []
    for qy in range(2):
        for qx in range(2):
            tiles = [
                block[(qy * 2 + ty) * 4 + (qx * 2 + tx)]
                for ty in range(2)
                for tx in range(2)
            ]
            result.append(_semantic_quadrant_class(tiles))
    return tuple(result)


def _semantic_south_seam(slot: NativeMap, blockset: bytes) -> list[list[int]]:
    seam = [[SEM_SOLID for _ in range(SEM_W)] for _ in range(2)]
    y = slot.height - 1
    for bx in range(slot.width):
        block_id = slot.block_bytes[y * slot.width + bx]
        sig = _native_block_semantic_signature(blockset, block_id)
        seam[0][bx * 2] = sig[0]
        seam[0][bx * 2 + 1] = sig[1]
        seam[1][bx * 2] = sig[2]
        seam[1][bx * 2 + 1] = sig[3]
    return seam


def _block_edge_reachable_columns(
    blockset: bytes, block_id: int, from_bottom: bool
) -> set[int]:
    block = _block_tiles(blockset, block_id)
    walk = [
        [block[y * 4 + x] in OVERWORLD_WALKABLE for x in range(4)]
        for y in range(4)
    ]
    starts = [
        (x, 3 if from_bottom else 0)
        for x in range(4)
        if walk[3 if from_bottom else 0][x]
    ]
    seen = set(starts)
    stack = list(starts)
    target_y = 0 if from_bottom else 3
    result: set[int] = set()
    while stack:
        x, y = stack.pop()
        if y == target_y:
            result.add(x)
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if (
                0 <= nx < 4
                and 0 <= ny < 4
                and walk[ny][nx]
                and (nx, ny) not in seen
            ):
                seen.add((nx, ny))
                stack.append((nx, ny))
    return result


def _pallet_route_entry_block(repo: Path, slot: NativeMap, blockset: bytes) -> int:
    pallet = load_map(repo, "PalletTown")
    if pallet.width != slot.width:
        raise ValueError("first route expects Pallet and route widths to match")

    candidates: list[int] = []
    for bx in range(slot.width):
        pallet_id = pallet.block_bytes[bx]
        route_id = slot.block_bytes[(slot.height - 1) * slot.width + bx]
        pallet_cols = _block_edge_reachable_columns(
            blockset, pallet_id, from_bottom=True
        )
        route_cols = _block_edge_reachable_columns(
            blockset, route_id, from_bottom=True
        )
        if pallet_cols & route_cols:
            candidates.append(bx)
    if not candidates:
        raise AssertionError("Pallet seam has no vertically traversable connection block")
    center = (slot.width - 1) / 2.0
    return min(candidates, key=lambda x: (abs(x - center), x))


def _semantic_exit_block(seed: int, width: int) -> int:
    return 2 + _stable_index(seed, 991, 7, 0x31, max(1, width - 5))


def _carve_semantic(
    grid: list[list[int]],
    rng: random.Random,
    start: tuple[int, int],
    end: tuple[int, int],
    width: int,
) -> None:
    x, y = start
    tx, ty = end
    while (x, y) != (tx, ty):
        for dx in range(width):
            px = x + dx
            if 1 <= px < SEM_W - 1 and 0 <= y < SEM_H - 2:
                grid[y][px] = SEM_OPEN
        if x != tx and (y == ty or rng.random() < 0.48):
            x += 1 if tx > x else -1
        elif y != ty:
            y += 1 if ty > y else -1
        else:
            x += 1 if tx > x else -1
    for dx in range(width):
        px = x + dx
        if 1 <= px < SEM_W - 1 and 0 <= y < SEM_H - 2:
            grid[y][px] = SEM_OPEN


def _paint_semantic_ellipse(
    grid: list[list[int]],
    cx: int,
    cy: int,
    rx: int,
    ry: int,
    center_class: int,
    preserve_open: bool,
) -> None:
    for y in range(max(2, cy - ry), min(SEM_H - 2, cy + ry + 1)):
        for x in range(max(2, cx - rx), min(SEM_W - 2, cx + rx + 1)):
            distance = ((x - cx) / max(1, rx)) ** 2 + ((y - cy) / max(1, ry)) ** 2
            if distance > 1.0:
                continue
            if preserve_open and grid[y][x] == SEM_OPEN:
                continue
            if center_class == SEM_SOLID and distance > 0.72:
                grid[y][x] = SEM_MIXED
            else:
                grid[y][x] = center_class


def _nearest_semantic_open(
    grid: list[list[int]], target_x: int, target_y: int
) -> tuple[int, int]:
    best: tuple[int, int, int] | None = None
    for y in range(1, SEM_H - 2):
        for x in range(1, SEM_W - 1):
            if grid[y][x] != SEM_OPEN:
                continue
            distance = abs(x - target_x) + abs(y - target_y)
            candidate = (distance, x, y)
            if best is None or candidate < best:
                best = candidate
    if best is None:
        raise AssertionError("generated semantic route contains no open placement cell")
    return best[1], best[2]


def _generate_semantic_route(
    slot: NativeMap, blockset: bytes, seed: int, entry_block: int, exit_block: int
) -> tuple[list[list[int]], dict]:
    rng = random.Random(seed)
    grid = [[SEM_GRASS for _ in range(SEM_W)] for _ in range(SEM_H)]

    for y in range(SEM_H - 2):
        grid[y][0] = SEM_SOLID
        grid[y][1] = SEM_SOLID
        grid[y][SEM_W - 2] = SEM_SOLID
        grid[y][SEM_W - 1] = SEM_SOLID

    start_x = entry_block * 2
    exit_x = exit_block * 2
    nodes: list[tuple[int, int]] = [(start_x, SEM_H - 3)]
    for y in (30, 24, 18, 12, 6):
        nodes.append((rng.randint(3, SEM_W - 7), y))
    nodes.append((exit_x, 0))

    for a, b in zip(nodes, nodes[1:]):
        _carve_semantic(grid, rng, a, b, rng.choice((2, 3, 4)))

    branches: list[dict] = []
    for _ in range(2):
        lower_index = rng.choice((1, 2, 3))
        upper_index = min(lower_index + rng.choice((1, 2)), len(nodes) - 2)
        y1 = nodes[lower_index][1]
        y2 = nodes[upper_index][1]
        side = 2 if rng.random() < 0.5 else SEM_W - 5
        _carve_semantic(grid, rng, nodes[lower_index], (side, y1), 2)
        _carve_semantic(grid, rng, (side, y1), (side, y2), 2)
        _carve_semantic(grid, rng, (side, y2), nodes[upper_index], 2)
        branches.append({"from": nodes[lower_index], "via": [side, y1, y2], "to": nodes[upper_index]})

    clearings: list[tuple[int, int, int, int]] = []
    for node_x, node_y in rng.sample(nodes[1:-1], k=2):
        rx = rng.choice((2, 3, 4))
        ry = rng.choice((2, 3))
        _paint_semantic_ellipse(grid, node_x + 1, node_y, rx, ry, SEM_OPEN, False)
        clearings.append((node_x + 1, node_y, rx, ry))

    for _ in range(rng.randint(5, 8)):
        cx = rng.randint(3, SEM_W - 4)
        cy = rng.randint(4, SEM_H - 6)
        rx = rng.choice((2, 3, 4))
        ry = rng.choice((2, 3, 4))
        _paint_semantic_ellipse(grid, cx, cy, rx, ry, SEM_SOLID, True)

    seam = _semantic_south_seam(slot, blockset)
    grid[SEM_H - 2] = seam[0]
    grid[SEM_H - 1] = seam[1]

    for y in (0, 1):
        for x in range(exit_x, min(SEM_W, exit_x + 4)):
            grid[y][x] = SEM_OPEN

    return grid, {
        "nodes": nodes,
        "branches": branches,
        "clearings": clearings,
        "entry_block": entry_block,
        "exit_block": exit_block,
    }


def _materialize_semantic_route(
    slot: NativeMap, blockset: bytes, semantic: list[list[int]], seed: int
) -> list[int]:
    signatures = {
        block_id: _native_block_semantic_signature(blockset, block_id)
        for block_id in WOODLAND_ROUTE_BLOCKS
    }
    result = [FIRST_ROUTE_GROUND] * (slot.width * slot.height)
    for by in range(slot.height):
        for bx in range(slot.width):
            if by == slot.height - 1:
                result[by * slot.width + bx] = slot.block_bytes[
                    by * slot.width + bx
                ]
                continue
            desired = (
                semantic[by * 2][bx * 2],
                semantic[by * 2][bx * 2 + 1],
                semantic[by * 2 + 1][bx * 2],
                semantic[by * 2 + 1][bx * 2 + 1],
            )
            scored: list[tuple[int, int, int]] = []
            for block_id, signature in signatures.items():
                mismatch = sum(a != b for a, b in zip(desired, signature))
                exact_surface_bonus = (
                    -8
                    if len(set(desired)) == 1
                    and desired[0] in (SEM_OPEN, SEM_GRASS)
                    and signature == desired
                    else 0
                )
                tie = _stable_index(seed, bx, by, block_id, 7)
                scored.append((mismatch * 10 + exact_surface_bonus, tie, block_id))
            result[by * slot.width + bx] = min(scored)[2]
    return result


def _native_route_connected(
    repo: Path,
    slot: NativeMap,
    blockset: bytes,
    blocks: list[int],
    entry_block: int,
    exit_block: int,
) -> bool:
    native = NativeMap(
        name=slot.name,
        map_id=slot.map_id,
        width=slot.width,
        height=slot.height,
        tileset=slot.tileset,
        border_block=slot.border_block,
        connections=slot.connections,
        warps=[],
        backgrounds=[],
        objects=[],
        block_bytes=bytes(blocks),
    )
    walkable = _walkable_tile_grid(native, blockset)
    pallet = load_map(repo, "PalletTown")
    pallet_walkable = _walkable_tile_grid(pallet, blockset)

    starts: list[tuple[int, int]] = []
    for local_x in range(4):
        global_x = entry_block * 4 + local_x
        if (
            walkable[-1][global_x]
            and pallet_walkable[0][global_x]
        ):
            starts.append((global_x, len(walkable) - 1))
    if not starts:
        return False

    targets = {
        (x, 0)
        for x in range(exit_block * 4, min(slot.width * 4, (exit_block + 2) * 4))
        if walkable[0][x]
    }
    if not targets:
        return False

    seen = set(starts)
    stack = list(starts)
    while stack:
        x, y = stack.pop()
        if (x, y) in targets:
            return True
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if (
                0 <= nx < len(walkable[0])
                and 0 <= ny < len(walkable)
                and walkable[ny][nx]
                and (nx, ny) not in seen
            ):
                seen.add((nx, ny))
                stack.append((nx, ny))
    return False


def _hard_repair_native_route(
    repo: Path,
    slot: NativeMap,
    blockset: bytes,
    semantic: list[list[int]],
    blocks: list[int],
    entry_block: int,
    exit_block: int,
) -> tuple[list[int], int]:
    if _native_route_connected(
        repo, slot, blockset, blocks, entry_block, exit_block
    ):
        return blocks, 0

    start = (entry_block, slot.height - 2)
    targets = {(exit_block, 0), (min(slot.width - 1, exit_block + 1), 0)}
    dist = {start: 0.0}
    prev: dict[tuple[int, int], tuple[int, int]] = {}
    heap: list[tuple[float, tuple[int, int]]] = [(0.0, start)]
    target: tuple[int, int] | None = None
    while heap:
        cost, pos = heapq.heappop(heap)
        if cost != dist[pos]:
            continue
        if pos in targets:
            target = pos
            break
        x, y = pos
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if not (0 <= nx < slot.width and 0 <= ny < slot.height - 1):
                continue
            quad = [
                semantic[ny * 2 + qy][nx * 2 + qx]
                for qy in range(2)
                for qx in range(2)
            ]
            openish = sum(v in (SEM_OPEN, SEM_GRASS) for v in quad) / 4.0
            new_cost = cost + (1.0 - 0.8 * openish)
            if new_cost < dist.get((nx, ny), 1e9):
                dist[(nx, ny)] = new_cost
                prev[(nx, ny)] = pos
                heapq.heappush(heap, (new_cost, (nx, ny)))

    if target is None:
        raise AssertionError("could not derive native fallback route")

    path: list[tuple[int, int]] = []
    cur = target
    while cur != start:
        path.append(cur)
        cur = prev[cur]
    path.append(start)

    repaired = list(blocks)
    changes = 0
    for x, y in path:
        index = y * slot.width + x
        if repaired[index] != FIRST_ROUTE_PATH:
            repaired[index] = FIRST_ROUTE_PATH
            changes += 1

    if not _native_route_connected(
        repo, slot, blockset, repaired, entry_block, exit_block
    ):
        raise AssertionError("native fallback failed to guarantee route connectivity")
    return repaired, changes


def _walkable_tile_grid(native_map: NativeMap, blockset: bytes) -> list[list[bool]]:
    tiles = expand_blocks(native_map, blockset)
    return [[tile in OVERWORLD_WALKABLE for tile in row] for row in tiles]


def generate_first_route(repo: Path, seed: int) -> tuple[NativeMap, bytes, dict]:
    """Generate the first post-Pallet route with half-block graph topology."""
    slot = load_map(repo, "Route1")
    if slot.tileset != "OVERWORLD" or (slot.width, slot.height) != (10, 18):
        raise ValueError("first route expects the ROUTE_1 10x18 OVERWORLD slot")

    blockset = load_blockset(repo, slot.tileset)
    entry_block = _pallet_route_entry_block(repo, slot, blockset)
    exit_block = _semantic_exit_block(seed, slot.width)
    semantic, topology = _generate_semantic_route(
        slot, blockset, seed, entry_block, exit_block
    )
    blocks = _materialize_semantic_route(slot, blockset, semantic, seed)
    blocks, hard_repairs = _hard_repair_native_route(
        repo, slot, blockset, semantic, blocks, entry_block, exit_block
    )
    generated = bytes(blocks)

    if generated == slot.block_bytes:
        raise AssertionError("generated geography unexpectedly matches original Route 1")
    same_cells = sum(a == b for a, b in zip(generated, slot.block_bytes))
    if same_cells > 70:
        raise AssertionError(
            f"generated route resembles source too closely ({same_cells}/180 cells same)"
        )

    names = generate_location_names(seed)
    first_clearing = topology["clearings"][0]
    sign_x, sign_y = _nearest_semantic_open(
        semantic, first_clearing[0], first_clearing[1]
    )
    npc1_x, npc1_y = _nearest_semantic_open(
        semantic, entry_block * 2 + 2, 25
    )
    npc2_x, npc2_y = _nearest_semantic_open(
        semantic, exit_block * 2 + 1, 9
    )

    manifest = {
        "seed": seed,
        "slot": "ROUTE_1",
        "generator": "half_block_graph_v1",
        "style_profile": "woodland_trail",
        "route_name": names["route"],
        "north_settlement_name": names["settlement"],
        "dimensions": [slot.width, slot.height],
        "semantic_dimensions": [SEM_W, SEM_H],
        "tileset": slot.tileset,
        "south_seam": "byte-identical to Route1 south row for PALLET_TOWN connection",
        "entry_block": entry_block,
        "north_exit_block": exit_block,
        "source_same_cells": same_cells,
        "hard_connectivity_repairs": hard_repairs,
        "main_nodes": topology["nodes"],
        "branches": topology["branches"],
        "clearings": topology["clearings"],
        "placements": {
            "sign": [sign_x, sign_y],
            "npc1": [npc1_x, npc1_y],
            "npc2": [npc2_x, npc2_y],
        },
        "generated_sha256": hashlib.sha256(generated).hexdigest(),
        "safety": "native_blocks; exact_pallet_seam; tile_bfs; hard_fallback",
    }
    return slot, generated, manifest


def _replace_name_label(text: str, label: str, value: str) -> str:
    lines = text.splitlines()
    matches = [i for i, line in enumerate(lines) if line.startswith(f"{label}:")]
    if len(matches) != 1:
        raise ValueError(f"expected one {label} entry, found {len(matches)}")
    lines[matches[0]] = f'{label}: db "{value}@"'
    ending = "\n" if text.endswith("\n") else ""
    return "\n".join(lines) + ending


def _generated_route_objects(manifest: dict) -> str:
    sign_x, sign_y = manifest["placements"]["sign"]
    npc1_x, npc1_y = manifest["placements"]["npc1"]
    npc2_x, npc2_y = manifest["placements"]["npc2"]
    return f"""\tobject_const_def
\tconst_export ROUTE1_YOUNGSTER1
\tconst_export ROUTE1_YOUNGSTER2

Route1_Object:
\tdb $b ; border block

\tdef_warp_events

\tdef_bg_events
\tbg_event {sign_x:2d}, {sign_y:2d}, TEXT_ROUTE1_SIGN

\tdef_object_events
\tobject_event {npc1_x:2d}, {npc1_y:2d}, SPRITE_YOUNGSTER, WALK, ANY_DIR, TEXT_ROUTE1_YOUNGSTER1
\tobject_event {npc2_x:2d}, {npc2_y:2d}, SPRITE_YOUNGSTER, WALK, ANY_DIR, TEXT_ROUTE1_YOUNGSTER2

\tdef_warps_to ROUTE_1
"""


def _generated_route_text(manifest: dict) -> str:
    route_name = manifest["route_name"]
    settlement = manifest["north_settlement_name"]
    return f"""_Route1Youngster1MartSampleText::
\ttext "Heading north?"
\tline "Take this POTION."

\tpara "The wilds beyond"
\tline "PALLET TOWN can"
\tcont "be unforgiving."
\tprompt

_Route1Youngster1GotPotionText::
\ttext "<PLAYER> got"
\tline "@"
\ttext_ram wStringBuffer
\ttext "!@"
\ttext_end

_Route1Youngster1AlsoGotPokeballsText::
\ttext "The trail changes"
\tline "every journey."
\tdone

_Route1Youngster1NoRoomText::
\ttext "You have too much"
\tline "stuff with you!"
\tdone

_Route1Youngster2Text::
\ttext "Nobody agrees"
\tline "what lies ahead."

\tpara "Around here, they"
\tline "call this road"
\tcont "{route_name}."
\tdone

_Route1SignText::
\ttext "{route_name}"
\tline "PALLET TOWN -"
\tcont "{settlement}"
\tdone
"""


def write_first_geography(repo: Path, seed: int, output_dir: Path) -> dict:
    slot, generated, manifest = generate_first_route(repo, seed)
    patch_root = output_dir / "patch"
    (patch_root / "maps").mkdir(parents=True, exist_ok=True)
    (patch_root / "data" / "maps" / "objects").mkdir(parents=True, exist_ok=True)
    (patch_root / "data" / "maps").mkdir(parents=True, exist_ok=True)
    (patch_root / "text").mkdir(parents=True, exist_ok=True)

    (patch_root / "maps" / "Route1.blk").write_bytes(generated)

    names_path = repo / "data" / "maps" / "names.asm"
    names_text = names_path.read_text(encoding="utf-8")
    names_text = _replace_name_label(names_text, "Route1Name", manifest["route_name"])
    names_text = _replace_name_label(
        names_text, "ViridianCityName", manifest["north_settlement_name"]
    )
    (patch_root / "data" / "maps" / "names.asm").write_text(
        names_text, encoding="utf-8"
    )
    (patch_root / "data" / "maps" / "objects" / "Route1.asm").write_text(
        _generated_route_objects(manifest), encoding="utf-8"
    )
    (patch_root / "text" / "Route1.asm").write_text(
        _generated_route_text(manifest), encoding="utf-8"
    )

    generated_map = NativeMap(
        name=slot.name,
        map_id=slot.map_id,
        width=slot.width,
        height=slot.height,
        tileset=slot.tileset,
        border_block=slot.border_block,
        connections=slot.connections,
        warps=[],
        backgrounds=[],
        objects=[],
        block_bytes=generated,
    )
    render_map(repo, generated_map, output_dir / "FirstRoute.generated.png", 3)
    (output_dir / "FirstGeography.generated.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def generate_route1_variant(repo: Path, seed: int) -> tuple[NativeMap, bytes, dict]:
    """Generate a conservative native Route 1 variant.

    Boundary blocks and special warp/ledge blocks are preserved. Interior
    blocks may be substituted only by block IDs already used by Route 1 that
    have the exact same 4x4 walkability mask and grass-tile positions.
    """
    route = load_map(repo, "Route1")
    if route.tileset != "OVERWORLD":
        raise ValueError("Route1 is expected to use OVERWORLD")

    blockset = load_blockset(repo, route.tileset)
    used_ids = sorted(set(route.block_bytes))
    groups: dict[tuple, list[int]] = {}
    for block_id in used_ids:
        signature = _route_safe_signature(blockset, block_id)
        if signature is not None:
            groups.setdefault(signature, []).append(block_id)

    result = bytearray(route.block_bytes)
    changes: list[dict] = []
    for y in range(1, route.height - 1):
        for x in range(1, route.width - 1):
            index = y * route.width + x
            original = result[index]
            signature = _route_safe_signature(blockset, original)
            if signature is None:
                continue
            candidates = groups.get(signature, [])
            if len(candidates) < 2:
                continue
            alternatives = [block for block in candidates if block != original]
            selected = alternatives[
                _stable_index(seed, x, y, original, len(alternatives))
            ]
            result[index] = selected
            changes.append(
                {
                    "x": x,
                    "y": y,
                    "from": original,
                    "to": selected,
                }
            )

    generated = bytes(result)
    if not changes:
        raise AssertionError("Route 1 generator produced no substitutions")

    # Hard safety gate: every cell must retain the same native collision/grass
    # signature, and all boundaries remain byte-identical.
    for y in range(route.height):
        for x in range(route.width):
            index = y * route.width + x
            original = route.block_bytes[index]
            replacement = generated[index]
            if x in (0, route.width - 1) or y in (0, route.height - 1):
                if replacement != original:
                    raise AssertionError("Route 1 generator modified map boundary")
            original_sig = _route_safe_signature(blockset, original)
            replacement_sig = _route_safe_signature(blockset, replacement)
            if original_sig is None:
                if replacement != original:
                    raise AssertionError("Route 1 generator modified special block")
            elif original_sig != replacement_sig:
                raise AssertionError("Route 1 generator changed collision/grass topology")

    manifest = {
        "map": "Route1",
        "seed": seed,
        "width": route.width,
        "height": route.height,
        "tileset": route.tileset,
        "changed_blocks": len(changes),
        "changes": changes,
        "source_sha256": hashlib.sha256(route.block_bytes).hexdigest(),
        "generated_sha256": hashlib.sha256(generated).hexdigest(),
        "safety": "exact_walkability_and_grass_mask_preserved",
    }
    return route, generated, manifest


def write_route1_variant(repo: Path, seed: int, output_dir: Path) -> tuple[Path, Path]:
    route, generated, manifest = generate_route1_variant(repo, seed)
    block_path = output_dir / "maps" / "Route1.blk"
    manifest_path = output_dir / "Route1.generated.json"
    block_path.parent.mkdir(parents=True, exist_ok=True)
    block_path.write_bytes(generated)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return block_path, manifest_path


def write_roundtrip(native_map: NativeMap, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    block_path = output_dir / f"{native_map.name}.blk"
    manifest_path = output_dir / f"{native_map.name}.json"
    block_path.write_bytes(native_map.block_bytes)
    manifest_path.write_text(
        json.dumps(native_map.manifest(), indent=2) + "\n",
        encoding="utf-8",
    )
    return block_path, manifest_path


def assert_pallet_town(repo: Path) -> NativeMap:
    native_map = load_map(repo, "PalletTown")
    expected = {
        "map_id": "PALLET_TOWN",
        "width": 10,
        "height": 9,
        "tileset": "OVERWORLD",
        "border_block": 0x0B,
        "block_count": 90,
        "connections": 2,
        "warps": 3,
        "backgrounds": 4,
        "objects": 3,
    }
    actual = {
        "map_id": native_map.map_id,
        "width": native_map.width,
        "height": native_map.height,
        "tileset": native_map.tileset,
        "border_block": native_map.border_block,
        "block_count": native_map.block_count,
        "connections": len(native_map.connections),
        "warps": len(native_map.warps),
        "backgrounds": len(native_map.backgrounds),
        "objects": len(native_map.objects),
    }
    if actual != expected:
        raise AssertionError(
            f"Pallet Town native contract mismatch:\n{actual}\n!=\n{expected}"
        )
    blockset = load_blockset(repo, native_map.tileset)
    expand_blocks(native_map, blockset)
    return native_map


def _cmd_inspect(args: argparse.Namespace) -> None:
    native_map = load_map(Path(args.repo), args.map)
    print(json.dumps(native_map.manifest(), indent=2))


def _cmd_roundtrip(args: argparse.Namespace) -> None:
    repo = Path(args.repo)
    native_map = load_map(repo, args.map)
    block_path, manifest_path = write_roundtrip(native_map, Path(args.output))
    original = repo / "maps" / f"{args.map}.blk"
    if original.read_bytes() != block_path.read_bytes():
        raise SystemExit("round-trip block bytes differ")
    print(f"round-trip ok: {block_path}")
    print(f"manifest: {manifest_path}")


def _cmd_render(args: argparse.Namespace) -> None:
    native_map = load_map(Path(args.repo), args.map)
    render_map(Path(args.repo), native_map, Path(args.output), args.scale)
    print(args.output)


def _cmd_generate_first_geography(args: argparse.Namespace) -> None:
    manifest = write_first_geography(Path(args.repo), args.seed, Path(args.output))
    print(json.dumps(manifest, indent=2))


def _cmd_generate_route1(args: argparse.Namespace) -> None:
    repo = Path(args.repo)
    output = Path(args.output)
    route, generated, manifest = generate_route1_variant(repo, args.seed)
    block_path, manifest_path = write_route1_variant(repo, args.seed, output)

    generated_map = NativeMap(
        name=route.name,
        map_id=route.map_id,
        width=route.width,
        height=route.height,
        tileset=route.tileset,
        border_block=route.border_block,
        connections=route.connections,
        warps=route.warps,
        backgrounds=route.backgrounds,
        objects=route.objects,
        block_bytes=generated,
    )
    render_map(repo, generated_map, output / "Route1.generated.png", args.scale)
    print(json.dumps(manifest, indent=2))
    print(f"native patch: {block_path}")
    print(f"manifest: {manifest_path}")


def _cmd_verify_pallet(args: argparse.Namespace) -> None:
    repo = Path(args.repo)
    native_map = assert_pallet_town(repo)
    if args.output:
        output_dir = Path(args.output)
        write_roundtrip(native_map, output_dir)
        render_map(repo, native_map, output_dir / "PalletTown.png", args.scale)
    print(json.dumps(native_map.manifest(), indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    inspect = sub.add_parser("inspect", help="parse a native map and print JSON")
    inspect.add_argument("--repo", required=True)
    inspect.add_argument("--map", required=True)
    inspect.set_defaults(func=_cmd_inspect)

    roundtrip = sub.add_parser(
        "roundtrip", help="emit exact native block bytes + manifest"
    )
    roundtrip.add_argument("--repo", required=True)
    roundtrip.add_argument("--map", required=True)
    roundtrip.add_argument("--output", required=True)
    roundtrip.set_defaults(func=_cmd_roundtrip)

    render = sub.add_parser("render", help="render .blk through native blockset/tileset")
    render.add_argument("--repo", required=True)
    render.add_argument("--map", required=True)
    render.add_argument("--output", required=True)
    render.add_argument("--scale", type=int, default=1)
    render.set_defaults(func=_cmd_render)

    pallet = sub.add_parser(
        "verify-pallet", help="assert the pinned Pallet Town contract"
    )
    pallet.add_argument("--repo", required=True)
    pallet.add_argument("--output")
    pallet.add_argument("--scale", type=int, default=2)
    pallet.set_defaults(func=_cmd_verify_pallet)

    route1 = sub.add_parser(
        "generate-route1",
        help="generate a conservative collision-equivalent native Route 1 variant",
    )
    route1.add_argument("--repo", required=True)
    route1.add_argument("--output", required=True)
    route1.add_argument("--seed", type=int, default=42)
    route1.add_argument("--scale", type=int, default=2)
    route1.set_defaults(func=_cmd_generate_route1)

    geography = sub.add_parser(
        "generate-first-geography",
        help="construct first post-Pallet geography and player-facing names",
    )
    geography.add_argument("--repo", required=True)
    geography.add_argument("--output", required=True)
    geography.add_argument("--seed", type=int, default=42)
    geography.set_defaults(func=_cmd_generate_first_geography)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
