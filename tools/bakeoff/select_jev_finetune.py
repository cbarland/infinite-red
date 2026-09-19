#!/usr/bin/env python3
"""Select Jev-labeled synthetic maps for conservative diffuser fine-tuning."""
from __future__ import annotations
import argparse, json
from pathlib import Path

def numeric(v):
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, dict):
        for key in ("score", "value", "probability"):
            if key in v and isinstance(v[key], (int, float)):
                return float(v[key])
    return None

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--labels",required=True)
    p.add_argument("--output",required=True)
    p.add_argument("--min-quality",type=float,default=0.72)
    p.add_argument("--max-per-style",type=int,default=128)
    a=p.parse_args()

    rows=[json.loads(line) for line in Path(a.labels).read_text().splitlines() if line.strip()]
    accepted=[]; counts={}
    for row in rows:
        s=row.get("summary",{})
        scores=[numeric(s.get(k)) for k in ("route_quality","exploration_interest","naturalness","visual_rhythm")]
        if any(v is None for v in scores): continue
        if min(scores)<a.min_quality: continue
        if s.get("fatal_issue") not in (None,"none"): continue
        style=str(s.get("style") or "unknown")
        if counts.get(style,0)>=a.max_per_style: continue
        counts[style]=counts.get(style,0)+1
        accepted.append(row)

    # Synthetic examples should remain a minority of any fine-tuning epoch.
    manifest={
        "selection_policy":{
            "min_each_core_score":a.min_quality,
            "fatal_issue":"none",
            "max_per_style":a.max_per_style,
            "recommended_synthetic_epoch_fraction":0.25,
            "recommended_human_authored_fraction":0.75,
        },
        "counts_by_style":counts,
        "accepted_ids":[r["id"] for r in accepted],
        "accepted":len(accepted),
        "total_labels":len(rows),
    }
    Path(a.output).write_text(json.dumps(manifest,indent=2)+"\n")
    print(json.dumps(manifest,indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
