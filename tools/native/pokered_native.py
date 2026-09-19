#!/usr/bin/env python3
"""Native Pokémon Red map parser/materializer for Infinite Red.

This module reads a local checkout of pret/pokered at the revision pinned by
config/pokered-source.toml. It deliberately operates on the decomp's native
map/block/object formats rather than introducing a parallel map format.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

TILE_PX = 8
BLOCK_TILES = 4
BLOCK_PX = TILE_PX * BLOCK_TILES
TILES_PER_BLOCK = BLOCK_TILES * BLOCK_TILES

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

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
