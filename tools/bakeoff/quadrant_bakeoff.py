#!/usr/bin/env python3
"""Half-block semantic route bake-off for Infinite Red.

Each 4x4-tile native block is represented as a 2x2 grid of semantic quadrants.
This gives a 10x18 block route a 20x36 topology canvas while retaining exact
native-block materialization downstream.
"""
from __future__ import annotations

import argparse
import heapq
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
from bakeoff import choose_north_exit, tile_connectivity

SOLID = 0
MIXED = 1
OPEN = 2
GRASS = 3
MASK = 4

BLOCK_W = 10
BLOCK_H = 18
W = BLOCK_W * 2
H = BLOCK_H * 2

STYLE_BLOCKS = {
    "woodland_trail": (
        0x0A, 0x0B, 0x1C, 0x31, 0x4D, 0x4E, 0x4F, 0x50,
        0x51, 0x52, 0x62, 0x63, 0x6D, 0x6E, 0x6F, 0x74,
    ),
    "open_meadow": (
        0x0A, 0x0B, 0x31, 0x4D, 0x4E, 0x4F, 0x50,
        0x51, 0x52, 0x62, 0x63, 0x74,
    ),
    "scrub_route": (
        0x0A, 0x0B, 0x1C, 0x31, 0x4D, 0x4E, 0x4F, 0x50,
        0x51, 0x52, 0x62, 0x63, 0x6F,
    ),
}


@dataclass
class Corpus:
    windows: np.ndarray
    sources: list[str]
    maps: list[str]


def _hexes(text: str) -> list[int]:
    return [int(v, 16) for v in re.findall(r"\$([0-9a-fA-F]{1,2})", text)]


def semantics(repo: Path):
    collision = (repo / "data" / "tilesets" / "collision_tile_ids.asm").read_text()
    m = re.search(r"Overworld_Coll::\s*\n\s*coll_tiles\s+([^\n]+)", collision)
    if not m:
        raise ValueError(f"no Overworld_Coll in {repo}")
    walk = set(_hexes(m.group(1)))
    headers = (repo / "data" / "tilesets" / "tileset_headers.asm").read_text()
    m = re.search(
        r"^\s*tileset\s+Overworld,\s*[^\n]*?,\s*(\$[0-9a-fA-F]+|-1),\s*TILEANIM_",
        headers,
        re.MULTILINE,
    )
    if not m:
        raise ValueError(f"no Overworld grass definition in {repo}")
    grass = None if m.group(1) == "-1" else int(m.group(1)[1:], 16)
    blocks = (repo / "gfx" / "blocksets" / "overworld.bst").read_bytes()
    return walk, grass, blocks


def quadrant_class(tiles: list[int], walk: set[int], grass: int | None) -> int:
    if grass is not None and sum(t == grass for t in tiles) >= 2:
        return GRASS
    wf = sum(t in walk for t in tiles) / 4.0
    if wf >= 0.75:
        return OPEN
    if wf <= 0.25:
        return SOLID
    return MIXED


def block_signature(blockset: bytes, walk: set[int], grass: int | None, block_id: int):
    off = block_id * 16
    b = blockset[off : off + 16]
    if len(b) != 16:
        return (SOLID,) * 4
    quadrants = []
    for qy in range(2):
        for qx in range(2):
            tiles = []
            for ty in range(2):
                for tx in range(2):
                    tiles.append(b[(qy * 2 + ty) * 4 + (qx * 2 + tx)])
            quadrants.append(quadrant_class(tiles, walk, grass))
    return tuple(quadrants)


def expand_semantic(raw: np.ndarray, blockset: bytes, walk: set[int], grass: int | None):
    h, w = raw.shape
    out = np.zeros((h * 2, w * 2), dtype=np.int64)
    for y in range(h):
        for x in range(w):
            sig = block_signature(blockset, walk, grass, int(raw[y, x]))
            out[y * 2, x * 2] = sig[0]
            out[y * 2, x * 2 + 1] = sig[1]
            out[y * 2 + 1, x * 2] = sig[2]
            out[y * 2 + 1, x * 2 + 1] = sig[3]
    return out


def source_routes(repo: Path, source: str):
    walk, grass, blockset = semantics(repo)
    result = []
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
        result.append((source, name, expand_semantic(raw, blockset, walk, grass)))
    return result


def crop_windows(grid: np.ndarray):
    variants = [grid, np.fliplr(grid), np.flipud(grid), np.flipud(np.fliplr(grid))]
    for g in variants:
        h, w = g.shape
        if h < H or w < W:
            continue
        ys = list(range(0, h - H + 1, max(1, H // 3)))
        xs = list(range(0, w - W + 1, max(1, W // 3)))
        if ys[-1] != h - H:
            ys.append(h - H)
        if xs[-1] != w - W:
            xs.append(w - W)
        for y in ys:
            for x in xs:
                yield g[y : y + H, x : x + W].copy()


def collect(sources: list[tuple[str, Path]]) -> Corpus:
    windows, srcs, maps = [], [], []
    for source, repo in sources:
        for src, name, grid in source_routes(repo, source):
            for win in crop_windows(grid):
                windows.append(win)
                srcs.append(src)
                maps.append(name)
    if not windows:
        raise RuntimeError("half-block corpus empty")
    return Corpus(np.stack(windows), srcs, maps)


def north_exit(seed: int):
    # Align exactly with the native block-level validator/materializer.
    return choose_north_exit(seed) * 2


def base_seam(base: Path):
    walk, grass, blockset = semantics(base)
    route = load_map(base, "Route1")
    raw = np.frombuffer(route.block_bytes[-BLOCK_W:], dtype=np.uint8).reshape(1, BLOCK_W)
    return expand_semantic(raw, blockset, walk, grass)[-2:]


def fixed(base: Path, seed: int):
    seam = base_seam(base)
    result = {}
    for yy in range(2):
        for x in range(W):
            result[(x, H - 2 + yy)] = int(seam[yy, x])
    ex = north_exit(seed)
    for x in range(ex, ex + 4):
        result[(x, 0)] = OPEN
        result[(x, 1)] = OPEN
    return result


def apply_fixed(base: Path, grid: np.ndarray, seed: int):
    for (x, y), value in fixed(base, seed).items():
        grid[y, x] = value


def connected(grid: np.ndarray, seed: int):
    starts = [(x, H - 1) for x in range(W) if int(grid[H - 1, x]) in (OPEN, GRASS)]
    ex = north_exit(seed)
    targets = {(x, 0) for x in range(ex, ex + 4)}
    if not starts:
        return False
    q = deque(starts)
    seen = set(starts)
    while q:
        x, y = q.popleft()
        if (x, y) in targets:
            return True
        for nx, ny in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
            if (
                0 <= nx < W
                and 0 <= ny < H
                and int(grid[ny,nx]) in (OPEN,GRASS)
                and (nx,ny) not in seen
            ):
                seen.add((nx,ny)); q.append((nx,ny))
    return False


def repair(base: Path, grid: np.ndarray, seed: int):
    starts = [(x, H - 1) for x in range(W) if int(grid[H - 1, x]) in (OPEN, GRASS)]
    start = starts[len(starts)//2] if starts else (4,H-1)
    ex = north_exit(seed); targets={(x,0) for x in range(ex,ex+4)}
    cost={OPEN:0,GRASS:0,MIXED:1,SOLID:4}
    dist={start:0}; prev={}; heap=[(0,start)]; target=None
    while heap:
        d,pos=heapq.heappop(heap)
        if d!=dist[pos]: continue
        if pos in targets: target=pos; break
        x,y=pos
        for nx,ny in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
            if not (0<=nx<W and 0<=ny<H): continue
            nd=d+cost[int(grid[ny,nx])]
            if nd<dist.get((nx,ny),10**9):
                dist[(nx,ny)]=nd; prev[(nx,ny)]=pos; heapq.heappush(heap,(nd,(nx,ny)))
    if target is None:
        return grid,0
    out=grid.copy(); n=0; cur=target; fx=fixed(base,seed)
    while cur!=start:
        x,y=cur
        if cur not in fx and int(out[y,x]) in (SOLID,MIXED):
            out[y,x]=OPEN; n+=1
        cur=prev[cur]
    apply_fixed(base,out,seed)
    return out,n


def graph(base: Path, seed: int):
    rng=random.Random(seed)
    g=np.full((H,W),GRASS,dtype=np.int64)
    # Strong irregular border masses.
    g[:,0:2]=SOLID; g[:,-2:]=SOLID
    ex=north_exit(seed)
    nodes=[(4,H-3)]
    for y in (30,24,18,12,6):
        nodes.append((rng.randint(3,W-7),y))
    nodes.append((ex,0))
    def carve(a,b,width=None):
        x,y=a; tx,ty=b; width=width or rng.choice((2,3,4))
        while (x,y)!=(tx,ty):
            for dx in range(width):
                if 1<=x+dx<W-1: g[y,x+dx]=OPEN
            if x!=tx and (y==ty or rng.random()<0.5): x += 1 if tx>x else -1
            elif y!=ty: y += 1 if ty>y else -1
        for dx in range(width):
            if 1<=x+dx<W-1: g[y,x+dx]=OPEN
    for a,b in zip(nodes,nodes[1:]): carve(a,b)
    # Two branch/rejoin candidates.
    for _ in range(2):
        y1=rng.randint(18,29); y2=rng.randint(6,15)
        side=rng.choice((2,W-5))
        carve((nodes[2][0],y1),(side,y1),2)
        carve((side,y1),(side,y2),2)
        carve((side,y2),(nodes[4][0],y2),2)
    # Terrain islands and open clearings.
    for _ in range(rng.randint(6,11)):
        cx,cy=rng.randint(3,W-4),rng.randint(3,H-5)
        rx,ry=rng.choice((2,3,4)),rng.choice((2,3,5))
        cls=rng.choice((SOLID,SOLID,GRASS,OPEN))
        for y in range(max(2,cy-ry),min(H-2,cy+ry+1)):
            for x in range(max(2,cx-rx),min(W-2,cx+rx+1)):
                if ((x-cx)/max(1,rx))**2+((y-cy)/max(1,ry))**2 <= 1 and rng.random()<0.85:
                    if g[y,x]!=OPEN or cls==OPEN: g[y,x]=cls
    apply_fixed(base,g,seed)
    return g


def adjacency(corpus: Corpus):
    adj={k:defaultdict(set) for k in ("l","r","u","d")}; freq=Counter(int(v) for v in corpus.windows.reshape(-1))
    for g in corpus.windows:
        for y in range(H):
            for x in range(W):
                v=int(g[y,x])
                if x: adj["l"][v].add(int(g[y,x-1]))
                if x+1<W: adj["r"][v].add(int(g[y,x+1]))
                if y: adj["u"][v].add(int(g[y-1,x]))
                if y+1<H: adj["d"][v].add(int(g[y+1,x]))
    return adj,freq


def wfc(base: Path, corpus: Corpus, seed: int, retries=15):
    vocab={SOLID,MIXED,OPEN,GRASS}; adj,freq=adjacency(corpus); fx=fixed(base,seed)
    dirs=[(-1,0,"l"),(1,0,"r"),(0,-1,"u"),(0,1,"d")]
    for attempt in range(retries):
        rng=random.Random(seed*2003+attempt); poss=[[set(vocab) for _ in range(W)] for _ in range(H)]
        for (x,y),v in fx.items(): poss[y][x]={v}
        q=deque(fx.keys()); bad=False
        while True:
            while q and not bad:
                x,y=q.popleft()
                for dx,dy,k in dirs:
                    nx,ny=x+dx,y+dy
                    if not (0<=nx<W and 0<=ny<H): continue
                    allowed=set()
                    for v in poss[y][x]: allowed.update(adj[k].get(v,vocab))
                    new=poss[ny][nx]&allowed
                    if not new: bad=True; break
                    if new!=poss[ny][nx]: poss[ny][nx]=new; q.append((nx,ny))
            if bad: break
            unresolved=[(len(poss[y][x]),x,y) for y in range(H) for x in range(W) if len(poss[y][x])>1]
            if not unresolved:
                return np.array([[next(iter(poss[y][x])) for x in range(W)] for y in range(H)],dtype=np.int64)
            ent=min(v[0] for v in unresolved); cells=[(x,y) for n,x,y in unresolved if n==ent]; x,y=rng.choice(cells)
            vals=sorted(poss[y][x]); poss[y][x]={rng.choices(vals,weights=[freq[v]+1 for v in vals],k=1)[0]}; q.append((x,y))
    return graph(base,seed)


def style_candidates(base: Path, profile: str):
    walk,grass,blockset=semantics(base)
    result=[]
    for bid in STYLE_BLOCKS[profile]:
        result.append((bid,block_signature(blockset,walk,grass,bid)))
    return result


def hard_carve_native_path(base: Path, blocks: np.ndarray, sem: np.ndarray, seed: int):
    """Last-resort tile-safe path using fully walkable native ground blocks."""
    if tile_connectivity(base, blocks, seed):
        return blocks, 0

    start = (2, BLOCK_H - 1)
    target_x = choose_north_exit(seed)
    targets = {(target_x, 0), (target_x + 1, 0)}
    dist = {start: 0.0}
    prev = {}
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
            if not (0 <= nx < BLOCK_W and 0 <= ny < BLOCK_H):
                continue
            quad = sem[ny * 2 : ny * 2 + 2, nx * 2 : nx * 2 + 2]
            openish = float(np.mean(np.isin(quad, (OPEN, GRASS))))
            step = 1.0 - 0.8 * openish
            nd = cost + step
            if nd < dist.get((nx, ny), 1e9):
                dist[(nx, ny)] = nd
                prev[(nx, ny)] = pos
                heapq.heappush(heap, (nd, (nx, ny)))

    if target is None:
        raise AssertionError("could not derive final native connectivity path")

    path = []
    cur = target
    while cur != start:
        path.append(cur)
        cur = prev[cur]
    path.append(start)
    path.reverse()

    out = blocks.copy()
    changes = 0
    for x, y in path:
        if y == BLOCK_H - 1:
            continue
        if int(out[y, x]) != 0x31:
            out[y, x] = 0x31
            changes += 1

    if not tile_connectivity(base, out, seed):
        raise AssertionError("hard native path still failed tile connectivity")
    return out, changes

def materialize(base: Path, sem: np.ndarray, seed: int, profile: str):
    candidates=style_candidates(base,profile)
    blocks=np.zeros((BLOCK_H,BLOCK_W),dtype=np.int64)
    for by in range(BLOCK_H):
        for bx in range(BLOCK_W):
            desired=(
                int(sem[by*2,bx*2]),int(sem[by*2,bx*2+1]),
                int(sem[by*2+1,bx*2]),int(sem[by*2+1,bx*2+1]),
            )
            scored=[]
            for bid,sig in candidates:
                mismatch=sum(a!=b for a,b in zip(desired,sig))
                # Prefer exact grass/open surfaces when desired is uniform.
                bonus=0
                if len(set(desired))==1 and desired[0] in (OPEN,GRASS) and sig==desired: bonus=-2
                scored.append((mismatch*10+bonus+(bid+seed+bx*3+by*5)%3,bid))
            blocks[by,bx]=min(scored)[1]
    # Exact base seam remains authoritative.
    route=load_map(base,"Route1")
    blocks[-1,:]=np.frombuffer(route.block_bytes[-BLOCK_W:],dtype=np.uint8)
    native,repairs,_=__import__("bakeoff").repair_connectivity(base,blocks,seed)
    native,hard_repairs=hard_carve_native_path(base,native,sem,seed)
    return native,repairs+hard_repairs


def render_native(base: Path, blocks: np.ndarray, path: Path):
    slot=load_map(base,"Route1")
    native=NativeMap(name="Quadrant",map_id=slot.map_id,width=BLOCK_W,height=BLOCK_H,tileset="OVERWORLD",border_block=slot.border_block,connections=slot.connections,warps=[],backgrounds=[],objects=[],block_bytes=blocks.astype(np.uint8).tobytes())
    render_map(base,native,path,2)


def metrics(grid: np.ndarray, corpus: Corpus, seed: int, srep: int, nrep: int, elapsed: float):
    nearest=float(np.max(np.mean(corpus.windows==grid[None,:,:],axis=(1,2))))
    return {"connected":connected(grid,seed),"semantic_repairs":srep,"native_repairs":nrep,"nearest_source_similarity":round(nearest,4),"solid_fraction":round(float(np.mean(grid==SOLID)),4),"mixed_fraction":round(float(np.mean(grid==MIXED)),4),"open_fraction":round(float(np.mean(grid==OPEN)),4),"grass_fraction":round(float(np.mean(grid==GRASS)),4),"seconds":round(elapsed,4)}


def sheet(images,output):
    opened=[(l,Image.open(p).convert("RGB")) for l,p in images]; cols=4; w=max(i.width for _,i in opened); h=max(i.height for _,i in opened); lh=22
    out=Image.new("RGB",(cols*w,math.ceil(len(opened)/cols)*(h+lh)),"white"); d=ImageDraw.Draw(out)
    for i,(label,img) in enumerate(opened): x=i%cols*w; y=i//cols*(h+lh); d.text((x+3,y+3),label,fill="black"); out.paste(img,(x,y+lh))
    out.save(output)


def run(base,corpus,name,fn,seeds,output,profile):
    rows=[]; images=[]; d=output/name; d.mkdir(parents=True,exist_ok=True)
    for seed in seeds:
        t=time.perf_counter(); raw=fn(seed); fixedgrid,srep=repair(base,raw,seed); native,nrep=materialize(base,fixedgrid,seed,profile); elapsed=time.perf_counter()-t
        png=d/f"seed-{seed}.png"; render_native(base,native,png); np.save(d/f"seed-{seed}.semantic.npy",fixedgrid)
        rows.append({"generator":name,"seed":seed,**metrics(fixedgrid,corpus,seed,srep,nrep,elapsed),"native_connected":tile_connectivity(base,native,seed)})
        images.append((f"{name}/{seed}",png))
    sheet(images,output/f"{name}-contact-sheet.png"); return rows


def main():
    p=argparse.ArgumentParser(); p.add_argument("--base",required=True); p.add_argument("--source",action="append",default=[]); p.add_argument("--output",required=True); p.add_argument("--seeds",default="41,42,43,44,45,46,47,48"); p.add_argument("--checkpoint"); p.add_argument("--style-profile",choices=sorted(STYLE_BLOCKS),default="woodland_trail")
    a=p.parse_args(); base=Path(a.base); sources=[("pokered",base)]
    for spec in a.source: name,path=spec.split("=",1); sources.append((name,Path(path)))
    corpus=collect(sources); seeds=[int(v) for v in a.seeds.split(",")]; output=Path(a.output); output.mkdir(parents=True,exist_ok=True)
    rows=[]; rows+=run(base,corpus,"quadrant-graph",lambda seed:graph(base,seed),seeds,output,a.style_profile); rows+=run(base,corpus,"quadrant-wfc",lambda seed:wfc(base,corpus,seed),seeds,output,a.style_profile)
    if a.checkpoint:
        from quadrant_diffusion import load_sampler
        rows+=run(base,corpus,"quadrant-diffusion",load_sampler(Path(a.checkpoint),base,corpus),seeds,output,a.style_profile)
    (output/"results.json").write_text(json.dumps(rows,indent=2)+"\n")
    meta={"windows":len(corpus.windows),"maps":len(set(zip(corpus.sources,corpus.maps))),"sources":Counter(corpus.sources),"style_profile":a.style_profile}; (output/"corpus.json").write_text(json.dumps(meta,indent=2,default=dict)+"\n")
    by=defaultdict(list)
    for row in rows: by[row["generator"]].append(row)
    lines=["# Half-block semantic bake-off","",f"Windows: **{len(corpus.windows)}**, maps: **{meta['maps']}**.","","| Generator | Native connected | Semantic repairs | Native repairs | Nearest source | sec/map |","| --- | ---: | ---: | ---: | ---: | ---: |"]
    for name,rs in by.items():
        avg=lambda k:sum(float(r[k]) for r in rs)/len(rs); lines.append(f"| {name} | {avg('native_connected'):.2f} | {avg('semantic_repairs'):.2f} | {avg('native_repairs'):.2f} | {avg('nearest_source_similarity'):.3f} | {avg('seconds'):.3f} |")
    (output/"report.md").write_text("\n".join(lines)+"\n"); return 0
if __name__=="__main__": raise SystemExit(main())
