#!/usr/bin/env python3
"""Generate intentionally exotic native-Red outdoor maps for visual stress testing."""
from __future__ import annotations

import argparse, json, math, random
from collections import deque
from pathlib import Path
from PIL import Image, ImageDraw
from pokered_native import NativeMap, OVERWORLD_WALKABLE, TILES_PER_BLOCK, load_blockset, load_map, render_map

W, H = 10, 18
GROUND, GRASS, PATH = 0x0A, 0x0B, 0x31
LEFT_EDGE, RIGHT_EDGE = 0x4E, 0x4D
SOUTH_LEDGE_TILES = {0x36, 0x37}
LEFT_LEDGE_TILES = {0x27}
RIGHT_LEDGE_TILES = {0x0D, 0x1D}

def block_tiles(blockset, bid):
    return blockset[bid*TILES_PER_BLOCK:(bid+1)*TILES_PER_BLOCK]

def ledge_catalog(blockset):
    out={"south":[],"left":[],"right":[]}
    for bid in range(len(blockset)//TILES_PER_BLOCK):
        tiles=set(block_tiles(blockset,bid))
        if tiles&SOUTH_LEDGE_TILES: out["south"].append(bid)
        if tiles&LEFT_LEDGE_TILES: out["left"].append(bid)
        if tiles&RIGHT_LEDGE_TILES: out["right"].append(bid)
    return out

def choose_ledge(blockset, ids):
    if not ids: raise RuntimeError("missing ledge block")
    return max(ids,key=lambda bid:(sum(t in OVERWORLD_WALKABLE for t in block_tiles(blockset,bid)),-bid))

def base(fill=GRASS):
    g=[[fill for _ in range(W)] for _ in range(H)]
    for y in range(H): g[y][0]=LEFT_EDGE; g[y][-1]=RIGHT_EDGE
    return g

def carve(g, pts, width=1):
    for x,y in pts:
        for dx in range(-(width//2), width-width//2):
            xx=x+dx
            if 1<=xx<W-1 and 0<=y<H: g[y][xx]=PATH

def line(a,b):
    x,y=a; tx,ty=b; pts=[(x,y)]
    while (x,y)!=(tx,ty):
        if x!=tx: x += 1 if tx>x else -1
        elif y!=ty: y += 1 if ty>y else -1
        pts.append((x,y))
    return pts

def spiral_grove(rng, ledges):
    g=base(GRASS); pts=[]
    for i,(x0,y0,x1,y1) in enumerate(((1,1,8,16),(2,3,7,14),(3,5,6,12))):
        pts += [(x,y0) for x in range(x0,x1+1)]
        pts += [(x1,y) for y in range(y0,y1+1)]
        pts += [(x,y1) for x in range(x1,x0-1,-1)]
        if i<2: pts += [(x0,y) for y in range(y1,y0+1,-1)]
    carve(g,pts)
    for y in range(7,11):
        for x in range(4,6): g[y][x]=GROUND
    for x in (2,4,6): g[6][x]=ledges["south"]
    return g,{"archetype":"spiral_grove","ledge_count":3}

def terraced_basin(rng, ledges):
    g=base(GROUND)
    for y0,y1 in ((0,4),(6,10),(12,17)):
        for y in range(y0,y1+1):
            for x in range(2,8): g[y][x]=GRASS if (x+y)%3 else GROUND
    for x in range(2,8): g[5][x]=ledges["south"]; g[11][x]=ledges["south"]
    carve(g,line((2,17),(2,0))); carve(g,line((7,17),(7,0))); carve(g,line((2,9),(7,9)))
    return g,{"archetype":"terraced_basin","ledge_count":12}

def split_ravine(rng, ledges):
    g=base(GRASS)
    for y in range(2,16):
        g[y][4]=GROUND; g[y][5]=GROUND
    carve(g,line((2,17),(2,1))); carve(g,line((7,17),(7,1)))
    for y in (5,12): carve(g,line((2,y),(7,y)))
    for y in (3,8,14): g[y][3]=ledges["right"]; g[y][6]=ledges["left"]
    return g,{"archetype":"split_ravine","ledge_count":6}

def switchback_cliffs(rng, ledges):
    g=base(GROUND); y=16; direction=1
    while y>=2:
        xs=range(2,8) if direction>0 else range(7,1,-1)
        carve(g,[(x,y) for x in xs])
        if y-1>=0: g[y-1][7 if direction>0 else 2]=PATH
        if y-2>=0:
            for x in range(3,7): g[y-2][x]=ledges["south"]
        y-=3; direction*=-1
    carve(g,line((4,17),(4,16))); carve(g,line((4,1),(4,0)))
    n=sum(1 for row in g for v in row if v==ledges["south"])
    return g,{"archetype":"switchback_cliffs","ledge_count":n}

ARCHETYPES={"spiral_grove":spiral_grove,"terraced_basin":terraced_basin,"split_ravine":split_ravine,"switchback_cliffs":switchback_cliffs}

def tile_connected(blockset, blocks):
    tw,th=W*4,H*4; walk=[[False]*tw for _ in range(th)]
    for by in range(H):
        for bx in range(W):
            tiles=block_tiles(blockset,blocks[by][bx])
            for ty in range(4):
                for tx in range(4): walk[by*4+ty][bx*4+tx]=tiles[ty*4+tx] in OVERWORLD_WALKABLE
    starts=[(x,th-1) for x in range(tw) if walk[th-1][x]]
    targets={(x,0) for x in range(tw) if walk[0][x]}
    q=deque(starts); seen=set(starts)
    while q:
        p=q.popleft()
        if p in targets:return True
        x,y=p
        for nx,ny in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
            if 0<=nx<tw and 0<=ny<th and walk[ny][nx] and (nx,ny) not in seen:
                seen.add((nx,ny)); q.append((nx,ny))
    return False

def render_case(repo,out,name,seed,blocks,meta):
    slot=load_map(repo,"Route1"); flat=bytes(v for row in blocks for v in row)
    native=NativeMap(name=name,map_id=slot.map_id,width=W,height=H,tileset="OVERWORLD",
        border_block=slot.border_block,connections=[],warps=[],backgrounds=[],objects=[],block_bytes=flat)
    png=out/f"{name}-seed-{seed}.png"; render_map(repo,native,png,2)
    return {"archetype":name,"seed":seed,"png":png.name,
        "tile_connected_without_ledge_semantics":tile_connected(load_blockset(repo,"OVERWORLD"),blocks),**meta}

def sheet(out,rows):
    opened=[(r,Image.open(out/r["png"]).convert("RGB")) for r in rows]
    cols=4; w=max(im.width for _,im in opened); h=max(im.height for _,im in opened); lh=32
    img=Image.new("RGB",(cols*w,math.ceil(len(opened)/cols)*(h+lh)),"white"); d=ImageDraw.Draw(img)
    for i,(r,im) in enumerate(opened):
        x=(i%cols)*w; y=(i//cols)*(h+lh)
        d.text((x+4,y+3),f'{r["archetype"]} / {r["seed"]} / ledges {r["ledge_count"]}',fill="black")
        img.paste(im,(x,y+lh))
    img.save(out/"exotic-contact-sheet.png")

def main():
    p=argparse.ArgumentParser(); p.add_argument("--repo",required=True); p.add_argument("--output",required=True); p.add_argument("--seeds",default="101,202")
    a=p.parse_args(); repo=Path(a.repo); out=Path(a.output); out.mkdir(parents=True,exist_ok=True)
    blockset=load_blockset(repo,"OVERWORLD"); catalog=ledge_catalog(blockset)
    ledges={k:choose_ledge(blockset,v) for k,v in catalog.items()}
    rows=[]
    for name,fn in ARCHETYPES.items():
        for seed in [int(x) for x in a.seeds.split(",")]:
            blocks,meta=fn(random.Random(seed),ledges); rows.append(render_case(repo,out,name,seed,blocks,meta))
    sheet(out,rows)
    (out/"results.json").write_text(json.dumps({"selected_ledge_blocks":ledges,"ledge_catalog_sizes":{k:len(v) for k,v in catalog.items()},"cases":rows,
      "note":"Visual stress test only; directed ledge reachability validator is the next production step."},indent=2)+"\\n")
    return 0
if __name__=="__main__": raise SystemExit(main())
