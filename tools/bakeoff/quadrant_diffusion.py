#!/usr/bin/env python3
"""Tiny dilated masked denoiser for 20x36 half-block route topology."""
from __future__ import annotations
import argparse,json,math,random,time
from pathlib import Path
import numpy as np
from quadrant_bakeoff import MASK,H,W,collect,fixed

def mods():
    import torch,torch.nn as nn,torch.nn.functional as F
    return torch,nn,F

def model(channels=40):
    torch,nn,F=mods()
    class Block(nn.Module):
        def __init__(self,c,d):
            super().__init__(); self.net=nn.Sequential(nn.Conv2d(c,c,3,padding=d,dilation=d),nn.GroupNorm(5,c),nn.GELU(),nn.Conv2d(c,c,3,padding=d,dilation=d),nn.GroupNorm(5,c)); self.act=nn.GELU()
        def forward(self,x): return self.act(x+self.net(x))
    class M(nn.Module):
        def __init__(self):
            super().__init__(); self.emb=nn.Embedding(5,channels); self.inp=nn.Conv2d(channels+4,channels,3,padding=1); self.blocks=nn.Sequential(Block(channels,1),Block(channels,2),Block(channels,4),Block(channels,2),Block(channels,1)); self.out=nn.Conv2d(channels,4,1)
        def forward(self,tokens,ratio,fmask):
            b=tokens.shape[0]; e=self.emb(tokens).permute(0,3,1,2); yy=torch.linspace(-1,1,H)[None,None,:,None].expand(b,1,H,W); xx=torch.linspace(-1,1,W)[None,None,None,:].expand(b,1,H,W); rr=ratio[:,None,None,None].expand(b,1,H,W); fm=fmask[:,None].float(); x=torch.cat([e,rr,fm,xx,yy],1); return self.out(self.blocks(self.inp(x)))
    return M()

def train(sources,out,steps=2200,seed=2026):
    torch,nn,F=mods(); random.seed(seed);np.random.seed(seed);torch.manual_seed(seed); corpus=collect(sources); data=torch.tensor(corpus.windows,dtype=torch.long); m=model(); opt=torch.optim.AdamW(m.parameters(),lr=1.5e-3,weight_decay=1e-4)
    counts=torch.bincount(data.reshape(-1),minlength=4).float(); weights=(counts.sum()/counts.clamp_min(1)).sqrt(); weights/=weights.mean()
    losses=[]; t=time.perf_counter()
    for step in range(steps):
        idx=torch.randint(0,len(data),(24,)); target=data[idx].clone(); ratios=torch.empty(24).uniform_(0.08,1); mask=torch.rand_like(target.float())<ratios[:,None,None]; mask[:,0,0]=True; noisy=target.clone(); noisy[mask]=MASK; fixedmask=~mask
        logits=m(noisy,ratios,fixedmask); lm=F.cross_entropy(logits,target,reduction="none",weight=weights); loss=lm[mask].mean(); opt.zero_grad(set_to_none=True); loss.backward(); nn.utils.clip_grad_norm_(m.parameters(),1); opt.step(); losses.append(float(loss))
        if (step+1)%250==0: print(step+1,sum(losses[-250:])/250)
    payload={"state_dict":m.state_dict(),"channels":40,"steps":steps,"parameter_count":sum(p.numel() for p in m.parameters()),"training_seconds":time.perf_counter()-t,"final_loss":sum(losses[-100:])/100,"class_counts":counts.tolist()}; out.parent.mkdir(parents=True,exist_ok=True); torch.save(payload,out); out.with_suffix(".json").write_text(json.dumps({k:v for k,v in payload.items() if k!="state_dict"},indent=2)+"\n")

def load_sampler(path,base,corpus):
    torch,nn,F=mods(); p=torch.load(path,map_location="cpu",weights_only=False); m=model(); m.load_state_dict(p["state_dict"]);m.eval()
    def sample(seed):
        torch.manual_seed(seed); tokens=torch.full((1,H,W),MASK,dtype=torch.long); fm=torch.zeros((1,H,W),dtype=torch.bool)
        for (x,y),v in fixed(base,seed).items():tokens[0,y,x]=v;fm[0,y,x]=True
        total=int((~fm).sum());committed=0;stages=24
        with torch.no_grad():
            for st in range(stages):
                masked=tokens==MASK;rem=int(masked.sum())
                if not rem:break
                ratio=torch.tensor([rem/max(1,total)],dtype=torch.float32); probs=F.softmax(m(tokens,ratio,fm)/(1.15-.5*st/(stages-1)),1); samples=torch.multinomial(probs.permute(0,2,3,1).reshape(-1,4),1).reshape(1,H,W); conf=probs.max(1).values;conf[~masked]=-1; target=math.ceil(total*(st+1)/stages);n=max(1,target-committed);flat=conf.reshape(-1);cand=torch.nonzero(flat>=0,as_tuple=False).reshape(-1)
                if len(cand)>n:_,local=torch.topk(flat[cand],n);sel=cand[local]
                else:sel=cand
                tf=tokens.reshape(-1);sf=samples.reshape(-1);tf[sel]=sf[sel];committed+=len(sel)
        tokens[tokens==MASK]=2; return tokens[0].numpy().astype(np.int64)
    return sample

def main():
    p=argparse.ArgumentParser();p.add_argument("--base",required=True);p.add_argument("--source",action="append",default=[]);p.add_argument("--output",required=True);p.add_argument("--steps",type=int,default=2200);a=p.parse_args();sources=[("pokered",Path(a.base))]
    for spec in a.source:name,path=spec.split("=",1);sources.append((name,Path(path)))
    train(sources,Path(a.output),a.steps);return 0
if __name__=="__main__":raise SystemExit(main())
