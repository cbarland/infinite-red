#!/usr/bin/env python3
"""Tiny masked categorical denoiser for native Pokémon Red route blocks."""
from __future__ import annotations

import argparse
import json
import math
import random
import time
from pathlib import Path

import numpy as np

from bakeoff import (
    MASK_TOKEN,
    TARGET_H,
    TARGET_W,
    Corpus,
    collect_route_corpus,
    fixed_constraints,
)


def require_torch():
    try:
        import torch
        import torch.nn as nn
        import torch.nn.functional as F
    except ImportError as exc:
        raise RuntimeError("PyTorch is required for the diffusion experiment") from exc
    return torch, nn, F


def make_model(channels: int = 48, depth: int = 4):
    torch, nn, _ = require_torch()

    class Block(nn.Module):
        def __init__(self, c):
            super().__init__()
            self.net = nn.Sequential(
                nn.Conv2d(c, c, 3, padding=1),
                nn.GroupNorm(4, c),
                nn.GELU(),
                nn.Conv2d(c, c, 3, padding=1),
                nn.GroupNorm(4, c),
            )
            self.act = nn.GELU()

        def forward(self, x):
            return self.act(x + self.net(x))

    class Model(nn.Module):
        def __init__(self):
            super().__init__()
            self.embedding = nn.Embedding(MASK_TOKEN + 1, channels)
            self.input = nn.Conv2d(channels + 2, channels, 3, padding=1)
            self.blocks = nn.Sequential(*[Block(channels) for _ in range(depth)])
            self.output = nn.Conv2d(channels, MASK_TOKEN, 1)

        def forward(self, tokens, mask_ratio, fixed_mask):
            x = self.embedding(tokens).permute(0, 3, 1, 2)
            ratio = mask_ratio[:, None, None, None].expand(-1, 1, TARGET_H, TARGET_W)
            fixed = fixed_mask[:, None, :, :].float()
            x = torch.cat([x, ratio, fixed], dim=1)
            x = self.input(x)
            x = self.blocks(x)
            return self.output(x)

    return Model()


def model_size(model) -> int:
    return sum(p.numel() for p in model.parameters())


def train(repo: Path, output: Path, steps: int, channels: int, depth: int, batch_size: int, seed: int):
    torch, _, F = require_torch()
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)

    corpus = collect_route_corpus(repo)
    data = torch.tensor(corpus.windows, dtype=torch.long)
    model = make_model(channels, depth)
    optimizer = torch.optim.AdamW(model.parameters(), lr=2e-3, weight_decay=1e-4)
    model.train()

    losses = []
    started = time.perf_counter()
    for step in range(steps):
        idx = torch.randint(0, len(data), (batch_size,))
        target = data[idx].clone()
        ratios = torch.empty(batch_size).uniform_(0.12, 1.0)
        mask = torch.rand_like(target.float()) < ratios[:, None, None]
        mask[:, 0, 0] = True
        noisy = target.clone()
        noisy[mask] = MASK_TOKEN
        fixed_mask = ~mask
        logits = model(noisy, ratios, fixed_mask)
        loss_map = F.cross_entropy(logits, target, reduction="none")
        loss = loss_map[mask].mean()
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        losses.append(float(loss))
        if (step + 1) % 100 == 0:
            print(f"step={step+1} loss={sum(losses[-100:]) / min(100, len(losses)):.4f}")

    elapsed = time.perf_counter() - started
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "state_dict": model.state_dict(),
        "channels": channels,
        "depth": depth,
        "vocab": corpus.vocab,
        "steps": steps,
        "parameter_count": model_size(model),
        "training_seconds": elapsed,
        "final_loss": sum(losses[-50:]) / min(50, len(losses)),
    }
    torch.save(payload, output)
    metadata = {k: v for k, v in payload.items() if k != "state_dict"}
    output.with_suffix(".json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps(metadata, indent=2))


def load_sampler(checkpoint: Path, repo: Path, corpus: Corpus):
    torch, _, F = require_torch()
    payload = torch.load(checkpoint, map_location="cpu", weights_only=False)
    model = make_model(int(payload["channels"]), int(payload["depth"]))
    model.load_state_dict(payload["state_dict"])
    model.eval()
    vocab = [int(v) for v in payload["vocab"]]
    vocab_tensor = torch.tensor(vocab, dtype=torch.long)

    def sample(seed: int) -> np.ndarray:
        torch.manual_seed(seed)
        tokens = torch.full((1, TARGET_H, TARGET_W), MASK_TOKEN, dtype=torch.long)
        fixed = fixed_constraints(repo, seed)
        fixed_mask = torch.zeros((1, TARGET_H, TARGET_W), dtype=torch.bool)
        for (x, y), value in fixed.items():
            tokens[0, y, x] = value
            fixed_mask[0, y, x] = True

        total_free = int((~fixed_mask).sum())
        committed = 0
        stages = 14
        with torch.no_grad():
            for stage in range(stages):
                masked = tokens == MASK_TOKEN
                remaining = int(masked.sum())
                if remaining == 0:
                    break
                ratio = torch.tensor([remaining / max(1, total_free)], dtype=torch.float32)
                logits = model(tokens, ratio, fixed_mask)
                restricted = logits[:, vocab_tensor, :, :]
                temperature = 1.15 - 0.45 * (stage / max(1, stages - 1))
                probs = F.softmax(restricted / temperature, dim=1)
                sampled_idx = torch.multinomial(
                    probs.permute(0, 2, 3, 1).reshape(-1, len(vocab)), 1
                ).reshape(1, TARGET_H, TARGET_W)
                sampled = vocab_tensor[sampled_idx]
                confidence = probs.max(dim=1).values
                confidence[~masked] = -1

                commit_target = math.ceil(total_free * ((stage + 1) / stages))
                to_commit = max(1, commit_target - committed)
                flat = confidence.reshape(-1)
                candidates = torch.nonzero(flat >= 0, as_tuple=False).reshape(-1)
                if len(candidates) <= to_commit:
                    selected = candidates
                else:
                    _, local = torch.topk(flat[candidates], to_commit)
                    selected = candidates[local]
                token_flat = tokens.reshape(-1)
                sample_flat = sampled.reshape(-1)
                token_flat[selected] = sample_flat[selected]
                committed += len(selected)

        tokens[tokens == MASK_TOKEN] = 0x31
        return tokens[0].cpu().numpy().astype(np.int64)

    return sample


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--steps", type=int, default=800)
    parser.add_argument("--channels", type=int, default=48)
    parser.add_argument("--depth", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()
    train(Path(args.repo), Path(args.output), args.steps, args.channels, args.depth, args.batch_size, args.seed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
