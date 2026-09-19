#!/usr/bin/env python3
"""Semantic multi-corpus route generator bake-off.

External Gen 1 hacks are normalized into four topology classes before training:
SOLID, MIXED, OPEN, and GRASS. No foreign block IDs are ever materialized into
Infinite Red; the generated semantic layout is translated back into base
pokered OVERWORLD blocks through an adjacency-constrained materializer.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
import time
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from pokered_native import NativeMap, load_blockset, load_map, parse_header, render_map
from bakeoff import (
    TARGET_H,
    TARGET_W,
    choose_north_exit,
    fixed_constraints,
    repair_connectivity,
    tile_connectivity,
)

SOLID = 0
MIXED = 1
OPEN = 2
GRASS = 3
MASK = 4
CLASS_NAMES = {SOLID: "solid", MIXED: "mixed", OPEN: "open", GRASS: "grass"}


@dataclass
class SemanticCorpus:
    windows: np.ndarray
    sources: list[str]
    maps: list[str]


def _parse_hexes(text: str) -> list[int]:
    return [int(v, 16) for v in re.findall(r"\$([0-9a-fA-F]{1,2})", text)]


def overworld_semantics(repo: Path):
    collision_text = (repo / "data" / "tilesets" / "collision_tile_ids.asm").read_text(
        encoding="utf-8"
    )
    match = re.search(
        r"Overworld_Coll::\s*\n\s*coll_tiles\s+([^\n]+)",
        collision_text,
        re.MULTILINE,
    )
    if not match:
        raise ValueError(f"Overworld_Coll not found in {repo}")
    walkable = set(_parse_hexes(match.group(1)))

    headers = (repo / "data" / "tilesets" / "tileset_headers.asm").read_text(
        encoding="utf-8"
    )
    match = re.search(
        r"^\s*tileset\s+Overworld,\s*[^\n]*?,\s*(\$[0-9a-fA-F]+|-1),\s*TILEANIM_",
        headers,
        re.MULTILINE,
    )
    if not match:
        raise ValueError(f"Overworld grass tile not found in {repo}")
    grass_text = match.group(1)
    grass = None if grass_text == "-1" else int(grass_text[1:], 16)

    blockset = (repo / "gfx" / "blocksets" / "overworld.bst").read_bytes()
    if len(blockset) % 16:
        raise ValueError(f"invalid overworld blockset length in {repo}")
    return walkable, grass, blockset


def block_class(blockset: bytes, walkable: set[int], grass: int | None, block_id: int) -> int:
    off = block_id * 16
    tiles = blockset[off : off + 16]
    if len(tiles) != 16:
        return SOLID
    walk_fraction = sum(t in walkable for t in tiles) / 16.0
    grass_fraction = 0.0 if grass is None else sum(t == grass for t in tiles) / 16.0
    if grass_fraction >= 0.25:
        return GRASS
    if walk_fraction >= 0.75:
        return OPEN
    if walk_fraction <= 0.25:
        return SOLID
    return MIXED


def route_semantic_maps(repo: Path, source_name: str):
    walkable, grass, blockset = overworld_semantics(repo)
    results = []
    for header in sorted((repo / "data" / "maps" / "headers").glob("*.asm")):
        try:
            name, map_id, tileset, _ = parse_header(header)
        except ValueError:
            continue
        if tileset != "OVERWORLD" or not map_id.startswith("ROUTE_"):
            continue
        try:
            native = load_map(repo, name)
        except (ValueError, FileNotFoundError):
            continue
        raw = np.frombuffer(native.block_bytes, dtype=np.uint8).reshape(
            native.height, native.width
        )
        semantic = np.zeros_like(raw, dtype=np.int64)
        for y in range(native.height):
            for x in range(native.width):
                semantic[y, x] = block_class(
                    blockset, walkable, grass, int(raw[y, x])
                )
        results.append((source_name, name, semantic))
    return results


def _windows(grid: np.ndarray):
    variants = [grid, np.fliplr(grid), np.flipud(grid), np.flipud(np.fliplr(grid))]
    for g in variants:
        h, w = g.shape
        if h < TARGET_H or w < TARGET_W:
            continue
        ys = list(range(0, h - TARGET_H + 1, max(1, TARGET_H // 3)))
        xs = list(range(0, w - TARGET_W + 1, max(1, TARGET_W // 3)))
        if ys[-1] != h - TARGET_H:
            ys.append(h - TARGET_H)
        if xs[-1] != w - TARGET_W:
            xs.append(w - TARGET_W)
        for y in ys:
            for x in xs:
                yield g[y : y + TARGET_H, x : x + TARGET_W].copy()


def collect_semantic_corpus(source_specs: list[tuple[str, Path]]) -> SemanticCorpus:
    windows, sources, maps = [], [], []
    for source_name, repo in source_specs:
        for src, map_name, grid in route_semantic_maps(repo, source_name):
            for window in _windows(grid):
                windows.append(window)
                sources.append(src)
                maps.append(map_name)
    if not windows:
        raise RuntimeError("semantic route corpus is empty")
    return SemanticCorpus(np.stack(windows), sources, maps)


def semantic_fixed(seed: int) -> dict[tuple[int, int], int]:
    fixed = {}
    # Model the authored Pallet seam semantically as open/mixed connection area.
    for x in range(TARGET_W):
        fixed[(x, TARGET_H - 1)] = MIXED if x in (0, 9) else OPEN
    exit_x = choose_north_exit(seed)
    fixed[(exit_x, 0)] = OPEN
    fixed[(exit_x + 1, 0)] = OPEN
    return fixed


def apply_semantic_fixed(grid: np.ndarray, seed: int):
    for (x, y), value in semantic_fixed(seed).items():
        grid[y, x] = value


def semantic_repair(grid: np.ndarray, seed: int):
    start = (2, TARGET_H - 1)
    exit_x = choose_north_exit(seed)
    targets = {(exit_x, 0), (exit_x + 1, 0)}
    cost = {OPEN: 0, GRASS: 0, MIXED: 1, SOLID: 3}
    dist = {start: 0}
    prev = {}
    q = [(0, start)]
    import heapq
    target = None
    while q:
        d, pos = heapq.heappop(q)
        if d != dist[pos]:
            continue
        if pos in targets:
            target = pos
            break
        x, y = pos
        for nx, ny in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
            if not (0 <= nx < TARGET_W and 0 <= ny < TARGET_H):
                continue
            nd = d + cost[int(grid[ny, nx])]
            if nd < dist.get((nx, ny), 10**9):
                dist[(nx, ny)] = nd
                prev[(nx, ny)] = pos
                heapq.heappush(q, (nd, (nx, ny)))
    if target is None:
        return grid, 0
    out = grid.copy()
    repairs = 0
    cur = target
    fixed = semantic_fixed(seed)
    while cur != start:
        x, y = cur
        if cur not in fixed and out[y, x] in (SOLID, MIXED):
            out[y, x] = OPEN
            repairs += 1
        cur = prev[cur]
    apply_semantic_fixed(out, seed)
    return out, repairs


def semantic_connected(grid: np.ndarray, seed: int):
    start = (2, TARGET_H - 1)
    exit_x = choose_north_exit(seed)
    targets = {(exit_x,0),(exit_x+1,0)}
    q = deque([start])
    seen = {start}
    while q:
        x,y=q.popleft()
        if (x,y) in targets:
            return True
        for nx,ny in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
            if (
                0 <= nx < TARGET_W
                and 0 <= ny < TARGET_H
                and int(grid[ny,nx]) in (OPEN,GRASS)
                and (nx,ny) not in seen
            ):
                seen.add((nx,ny)); q.append((nx,ny))
    return False


def semantic_graph(seed: int):
    rng = random.Random(seed)
    grid = np.full((TARGET_H, TARGET_W), GRASS, dtype=np.int64)
    grid[:,0] = SOLID; grid[:,-1] = SOLID
    exit_x = choose_north_exit(seed)
    nodes=[(2,TARGET_H-2)]
    for y in (14,11,8,5,2):
        nodes.append((rng.randint(1,7),y))
    nodes.append((exit_x,0))
    def carve(a,b):
        x,y=a; tx,ty=b
        while (x,y)!=(tx,ty):
            grid[y,x]=OPEN
            if x+1<TARGET_W-1: grid[y,x+1]=OPEN
            if x!=tx and (y==ty or rng.random()<0.5):
                x += 1 if tx>x else -1
            elif y!=ty:
                y += 1 if ty>y else -1
    for a,b in zip(nodes,nodes[1:]): carve(a,b)
    for _ in range(rng.randint(3,6)):
        cx,cy=rng.randint(2,7),rng.randint(2,14)
        for y in range(max(1,cy-1),min(TARGET_H-1,cy+2)):
            for x in range(max(1,cx-1),min(TARGET_W-1,cx+2)):
                if grid[y,x]!=OPEN and rng.random()<0.75: grid[y,x]=SOLID
    # Branch/rejoin loop.
    y1,y2=rng.randint(9,13),rng.randint(4,7)
    side=1 if rng.random()<0.5 else 7
    for y in range(y2,y1+1): grid[y,side]=OPEN
    for x in range(min(side,nodes[2][0]),max(side,nodes[2][0])+1): grid[y1,x]=OPEN
    for x in range(min(side,nodes[4][0]),max(side,nodes[4][0])+1): grid[y2,x]=OPEN
    apply_semantic_fixed(grid,seed)
    return grid


def semantic_wfc(corpus: SemanticCorpus, seed: int, retries=20):
    vocab={SOLID,MIXED,OPEN,GRASS}
    freq=Counter(int(x) for x in corpus.windows.reshape(-1))
    adj={k:defaultdict(set) for k in ("l","r","u","d")}
    for g in corpus.windows:
        for y in range(TARGET_H):
            for x in range(TARGET_W):
                v=int(g[y,x])
                if x: adj["l"][v].add(int(g[y,x-1]))
                if x+1<TARGET_W: adj["r"][v].add(int(g[y,x+1]))
                if y: adj["u"][v].add(int(g[y-1,x]))
                if y+1<TARGET_H: adj["d"][v].add(int(g[y+1,x]))
    dirs=[(-1,0,"l"),(1,0,"r"),(0,-1,"u"),(0,1,"d")]
    fixed=semantic_fixed(seed)
    for attempt in range(retries):
        rng=random.Random(seed*997+attempt)
        poss=[[set(vocab) for _ in range(TARGET_W)] for _ in range(TARGET_H)]
        for (x,y),v in fixed.items(): poss[y][x]={v}
        queue=deque(fixed.keys()); failed=False
        while True:
            while queue and not failed:
                x,y=queue.popleft(); cur=poss[y][x]
                for dx,dy,k in dirs:
                    nx,ny=x+dx,y+dy
                    if not (0<=nx<TARGET_W and 0<=ny<TARGET_H): continue
                    allowed=set()
                    for v in cur: allowed.update(adj[k].get(v,vocab))
                    new=poss[ny][nx]&allowed
                    if not new: failed=True; break
                    if new!=poss[ny][nx]: poss[ny][nx]=new; queue.append((nx,ny))
            if failed: break
            unresolved=[(len(poss[y][x]),x,y) for y in range(TARGET_H) for x in range(TARGET_W) if len(poss[y][x])>1]
            if not unresolved:
                return np.array([[next(iter(poss[y][x])) for x in range(TARGET_W)] for y in range(TARGET_H)],dtype=np.int64)
            ent=min(v[0] for v in unresolved)
            cells=[(x,y) for n,x,y in unresolved if n==ent]
            x,y=rng.choice(cells)
            vals=sorted(poss[y][x]); weights=[freq[v]+1 for v in vals]
            poss[y][x]={rng.choices(vals,weights=weights,k=1)[0]}; queue.append((x,y))
    g=semantic_graph(seed); apply_semantic_fixed(g,seed); return g


def base_materializer(base_repo: Path, semantic: np.ndarray, seed: int):
    # Candidate block IDs are learned from base pokered route usage and bucketed
    # by the same semantic classifier.
    walkable, grass, blockset = overworld_semantics(base_repo)
    used=set()
    raw_maps=[]
    for _,name,_ in route_semantic_maps(base_repo,"base"):
        try:
            m=load_map(base_repo,name)
        except Exception:
            continue
        arr=np.frombuffer(m.block_bytes,dtype=np.uint8).reshape(m.height,m.width)
        raw_maps.append(arr)
        used.update(int(v) for v in arr.reshape(-1))
    buckets=defaultdict(list)
    for bid in sorted(used):
        buckets[block_class(blockset,walkable,grass,bid)].append(bid)
    defaults={SOLID:0x4F,MIXED:0x1C,OPEN:0x31,GRASS:0x0B}
    rng=random.Random(seed)
    out=np.zeros((TARGET_H,TARGET_W),dtype=np.int64)
    for y in range(TARGET_H):
        for x in range(TARGET_W):
            cls=int(semantic[y,x])
            vals=buckets.get(cls) or [defaults[cls]]
            out[y,x]=vals[(seed*31+x*7+y*13+rng.randrange(len(vals)))%len(vals)]
    # Exact native seam and exit constraints remain authoritative.
    for (x,y),v in fixed_constraints(base_repo,seed).items(): out[y,x]=v
    native,repairs,_=repair_connectivity(base_repo,out,seed)
    return native,repairs


def semantic_metrics(grid: np.ndarray, corpus: SemanticCorpus, seed: int, repairs: int, native_repairs: int, elapsed: float):
    nearest=float(np.max(np.mean(corpus.windows==grid[None,:,:],axis=(1,2))))
    patterns=set()
    for src in corpus.windows:
        for y in range(TARGET_H-1):
            for x in range(TARGET_W-1):
                patterns.add(tuple(int(v) for v in src[y:y+2,x:x+2].reshape(-1)))
    gp=[tuple(int(v) for v in grid[y:y+2,x:x+2].reshape(-1)) for y in range(TARGET_H-1) for x in range(TARGET_W-1)]
    return {
        "connected": semantic_connected(grid,seed),
        "semantic_repairs": repairs,
        "native_repairs": native_repairs,
        "nearest_source_similarity": round(nearest,4),
        "pattern_novelty": round(sum(p not in patterns for p in gp)/len(gp),4),
        "solid_fraction": round(float(np.mean(grid==SOLID)),4),
        "mixed_fraction": round(float(np.mean(grid==MIXED)),4),
        "open_fraction": round(float(np.mean(grid==OPEN)),4),
        "grass_fraction": round(float(np.mean(grid==GRASS)),4),
        "seconds": round(elapsed,4),
    }


def semantic_contact_sheet(images, output):
    opened=[(label,Image.open(path).convert("RGB")) for label,path in images]
    cols=4; w=max(i.width for _,i in opened); h=max(i.height for _,i in opened); lh=24
    sheet=Image.new("RGB",(cols*w,math.ceil(len(opened)/cols)*(h+lh)),"white")
    draw=ImageDraw.Draw(sheet)
    for i,(label,img) in enumerate(opened):
        x=(i%cols)*w; y=(i//cols)*(h+lh)
        draw.text((x+3,y+3),label,fill="black"); sheet.paste(img,(x,y+lh))
    sheet.save(output)


def run_method(base_repo: Path, corpus: SemanticCorpus, name: str, fn, seeds, output):
    rows=[]; images=[]; d=output/name; d.mkdir(parents=True,exist_ok=True)
    for seed in seeds:
        t=time.perf_counter(); raw=fn(seed); repaired,srep=semantic_repair(raw,seed)
        native,nrep=base_materializer(base_repo,repaired,seed); elapsed=time.perf_counter()-t
        png=d/f"seed-{seed}.png"; render_map(base_repo,NativeMap(
            name="Semantic",map_id=load_map(base_repo,"Route1").map_id,width=TARGET_W,height=TARGET_H,
            tileset="OVERWORLD",border_block=load_map(base_repo,"Route1").border_block,
            connections=load_map(base_repo,"Route1").connections,warps=[],backgrounds=[],objects=[],
            block_bytes=native.astype(np.uint8).tobytes()),png,2)
        np.save(d/f"seed-{seed}.semantic.npy",repaired)
        rows.append({"generator":name,"seed":seed,**semantic_metrics(repaired,corpus,seed,srep,nrep,elapsed),"native_connected":tile_connectivity(base_repo,native,seed)})
        images.append((f"{name}/{seed}",png))
    semantic_contact_sheet(images,output/f"{name}-contact-sheet.png")
    return rows


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--base",required=True)
    p.add_argument("--source",action="append",default=[],help="name=/path/to/repo")
    p.add_argument("--output",required=True)
    p.add_argument("--seeds",default="41,42,43,44,45,46,47,48")
    p.add_argument("--checkpoint")
    args=p.parse_args()
    base=Path(args.base)
    sources=[("pokered",base)]
    for spec in args.source:
        name,path=spec.split("=",1); sources.append((name,Path(path)))
    corpus=collect_semantic_corpus(sources)
    output=Path(args.output); output.mkdir(parents=True,exist_ok=True)
    seeds=[int(v) for v in args.seeds.split(",")]
    results=[]
    results+=run_method(base,corpus,"semantic-graph",lambda seed: semantic_graph(seed),seeds,output)
    results+=run_method(base,corpus,"semantic-wfc",lambda seed: semantic_wfc(corpus,seed),seeds,output)
    if args.checkpoint:
        from semantic_diffusion import load_sampler
        sampler=load_sampler(Path(args.checkpoint),corpus)
        results+=run_method(base,corpus,"semantic-diffusion",sampler,seeds,output)
    meta={"windows":len(corpus.windows),"sources":Counter(corpus.sources),"maps":len(set(zip(corpus.sources,corpus.maps)))}
    (output/"corpus.json").write_text(json.dumps(meta,indent=2,default=dict)+"\n")
    (output/"results.json").write_text(json.dumps(results,indent=2)+"\n")
    by=defaultdict(list)
    for row in results: by[row["generator"]].append(row)
    lines=["# Semantic multi-corpus bake-off","",f"Windows: **{len(corpus.windows)}** from **{len(set(zip(corpus.sources,corpus.maps)))}** source route maps.","","| Generator | Native connected | Semantic repairs | Native repairs | Nearest source | 2x2 novelty | sec/map |","| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for name,rows in by.items():
        avg=lambda k: sum(float(r[k]) for r in rows)/len(rows)
        lines.append(f"| {name} | {avg('native_connected'):.2f} | {avg('semantic_repairs'):.2f} | {avg('native_repairs'):.2f} | {avg('nearest_source_similarity'):.3f} | {avg('pattern_novelty'):.3f} | {avg('seconds'):.3f} |")
    (output/"report.md").write_text("\n".join(lines)+"\n")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
