#!/usr/bin/env python3
"""Tiny semantic masked denoiser for multi-source Gen 1 route topology."""
from __future__ import annotations
import argparse, json, math, random, time
from pathlib import Path
import numpy as np
from semantic_bakeoff import MASK, TARGET_H, TARGET_W, collect_semantic_corpus, semantic_fixed

def torchmods():
    import torch, torch.nn as nn, torch.nn.functional as F
    return torch,nn,F

def make_model(channels=32,depth=4):
    torch,nn,F=torchmods()
    class Block(nn.Module):
        def __init__(self,c):
            super().__init__()
            self.net=nn.Sequential(nn.Conv2d(c,c,3,padding=1),nn.GroupNorm(4,c),nn.GELU(),nn.Conv2d(c,c,3,padding=1),nn.GroupNorm(4,c))
            self.act=nn.GELU()
        def forward(self,x): return self.act(x+self.net(x))
    class Model(nn.Module):
        def __init__(self):
            super().__init__()
            self.emb=nn.Embedding(5,channels)
            self.inp=nn.Conv2d(channels+2,channels,3,padding=1)
            self.blocks=nn.Sequential(*[Block(channels) for _ in range(depth)])
            self.out=nn.Conv2d(channels,4,1)
        def forward(self,tokens,ratio,fixed):
            x=self.emb(tokens).permute(0,3,1,2)
            r=ratio[:,None,None,None].expand(-1,1,TARGET_H,TARGET_W)
            x=torch.cat([x,r,fixed[:,None].float()],1)
            return self.out(self.blocks(self.inp(x)))
    return Model()

def train(sources,output,steps=1200,channels=32,depth=4,batch=32,seed=2026):
    torch,nn,F=torchmods(); random.seed(seed); np.random.seed(seed); torch.manual_seed(seed)
    corpus=collect_semantic_corpus(sources); data=torch.tensor(corpus.windows,dtype=torch.long)
    model=make_model(channels,depth); opt=torch.optim.AdamW(model.parameters(),lr=2e-3,weight_decay=1e-4)
    losses=[]; started=time.perf_counter()
    for step in range(steps):
        idx=torch.randint(0,len(data),(batch,)); target=data[idx].clone()
        ratios=torch.empty(batch).uniform_(0.08,1.0)
        mask=torch.rand_like(target.float())<ratios[:,None,None]; mask[:,0,0]=True
        noisy=target.clone(); noisy[mask]=MASK; fixed=~mask
        logits=model(noisy,ratios,fixed); lm=F.cross_entropy(logits,target,reduction="none")
        loss=lm[mask].mean(); opt.zero_grad(set_to_none=True); loss.backward(); nn.utils.clip_grad_norm_(model.parameters(),1.0); opt.step()
        losses.append(float(loss))
        if (step+1)%200==0: print(step+1,sum(losses[-200:])/200)
    payload={"state_dict":model.state_dict(),"channels":channels,"depth":depth,"steps":steps,"parameter_count":sum(p.numel() for p in model.parameters()),"training_seconds":time.perf_counter()-started,"final_loss":sum(losses[-100:])/min(100,len(losses))}
    output.parent.mkdir(parents=True,exist_ok=True); torch.save(payload,output)
    output.with_suffix(".json").write_text(json.dumps({k:v for k,v in payload.items() if k!="state_dict"},indent=2)+"\n")

def load_sampler(path,corpus):
    torch,nn,F=torchmods(); p=torch.load(path,map_location="cpu",weights_only=False)
    model=make_model(int(p["channels"]),int(p["depth"])); model.load_state_dict(p["state_dict"]); model.eval()
    def sample(seed):
        torch.manual_seed(seed)
        tokens=torch.full((1,TARGET_H,TARGET_W),MASK,dtype=torch.long)
        fixedmask=torch.zeros((1,TARGET_H,TARGET_W),dtype=torch.bool)
        for (x,y),v in semantic_fixed(seed).items(): tokens[0,y,x]=v; fixedmask[0,y,x]=True
        total=int((~fixedmask).sum()); committed=0; stages=18
        with torch.no_grad():
            for stage in range(stages):
                masked=tokens==MASK; remaining=int(masked.sum())
                if not remaining: break
                ratio=torch.tensor([remaining/max(1,total)],dtype=torch.float32)
                probs=F.softmax(model(tokens,ratio,fixedmask)/(1.1-0.45*stage/(stages-1)),1)
                sampled=torch.multinomial(probs.permute(0,2,3,1).reshape(-1,4),1).reshape(1,TARGET_H,TARGET_W)
                conf=probs.max(1).values; conf[~masked]=-1
                target=math.ceil(total*(stage+1)/stages); n=max(1,target-committed)
                flat=conf.reshape(-1); cand=torch.nonzero(flat>=0,as_tuple=False).reshape(-1)
                if len(cand)>n:
                    _,local=torch.topk(flat[cand],n); sel=cand[local]
                else: sel=cand
                tf=tokens.reshape(-1); sf=sampled.reshape(-1); tf[sel]=sf[sel]; committed+=len(sel)
        tokens[tokens==MASK]=2
        return tokens[0].numpy().astype(np.int64)
    return sample

def main():
    p=argparse.ArgumentParser(); p.add_argument("--base",required=True); p.add_argument("--source",action="append",default=[]); p.add_argument("--output",required=True); p.add_argument("--steps",type=int,default=1200)
    a=p.parse_args(); sources=[("pokered",Path(a.base))]
    for spec in a.source:
        name,path=spec.split("=",1); sources.append((name,Path(path)))
    train(sources,Path(a.output),steps=a.steps)
    return 0
if __name__=="__main__": raise SystemExit(main())
