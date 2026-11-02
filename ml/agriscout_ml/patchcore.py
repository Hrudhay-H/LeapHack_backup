"""Minimal PatchCore for RGB canopy anomaly localisation.

Pretrained ImageNet ResNet-18 (layer2 + layer3) patch features, a greedy
k-center coreset memory bank of *normal* patches, and nearest-neighbour distance
as the anomaly score. Own implementation (not anomalib) to keep dependencies
pinned and the Windows install reliable.

Scores are in feature-distance units. Convert to 0..1 with `Calibration`, which
is fitted on held-out NORMAL imagery so a healthy field scores ~0 everywhere.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
import torchvision
from scipy import ndimage

TILE = 256
STRIDE = 128
FEAT_STRIDE = 8  # layer2 stride
_MEAN = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
_STD = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)


def _device() -> torch.device:
    # The 2 GB MX550 is not worth the CUDA overhead for ResNet-18 on small tiles.
    return torch.device("cpu")


class FeatureExtractor(torch.nn.Module):
    def __init__(self, out_dim: int = 128):
        super().__init__()
        net = torchvision.models.resnet18(weights=torchvision.models.ResNet18_Weights.IMAGENET1K_V1)
        self.stem = torch.nn.Sequential(net.conv1, net.bn1, net.relu, net.maxpool)
        self.l1, self.l2, self.l3 = net.layer1, net.layer2, net.layer3
        self.out_dim = out_dim
        self.eval()
        for p in self.parameters():
            p.requires_grad_(False)

    @torch.no_grad()
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = (x - _MEAN) / _STD
        x = self.l1(self.stem(x))
        f2 = self.l2(x)
        f3 = self.l3(f2)
        # Local neighbourhood aggregation, as in PatchCore.
        f2 = F.avg_pool2d(f2, 3, 1, 1)
        f3 = F.avg_pool2d(f3, 3, 1, 1)
        f3 = F.interpolate(f3, size=f2.shape[-2:], mode="bilinear", align_corners=False)
        f = torch.cat([f2, f3], dim=1)  # (B, 384, h, w)
        b, c, h, w = f.shape
        f = f.permute(0, 2, 3, 1).reshape(b * h * w, 1, c)
        f = F.adaptive_avg_pool1d(f, self.out_dim).reshape(b, h, w, self.out_dim)
        return f


def _tile_origins(n: int) -> list[int]:
    if n <= TILE:
        return [0]
    o = list(range(0, n - TILE + 1, STRIDE))
    if o[-1] != n - TILE:
        o.append(n - TILE)
    return o


def _tiles(rgb: np.ndarray):
    """Yield (y, x, tensor[1,3,TILE,TILE]) covering the image (padded if smaller)."""
    _, h, w = rgb.shape
    ph, pw = max(TILE - h, 0), max(TILE - w, 0)
    if ph or pw:
        rgb = np.pad(rgb, ((0, 0), (0, ph), (0, pw)), mode="reflect")
    _, H, W = rgb.shape
    for y in _tile_origins(H):
        for x in _tile_origins(W):
            t = torch.from_numpy(rgb[:, y : y + TILE, x : x + TILE].astype(np.float32) / 255.0)[None]
            yield y, x, t


def _greedy_coreset(feats: torch.Tensor, k: int, seed: int = 0) -> torch.Tensor:
    """Greedy k-center on a random projection (PatchCore approximation)."""
    n = feats.shape[0]
    if k >= n:
        return feats
    g = torch.Generator().manual_seed(seed)
    proj = torch.randn(feats.shape[1], 64, generator=g) / 8.0
    z = feats @ proj
    sel = [int(torch.randint(0, n, (1,), generator=g))]
    mind = torch.cdist(z, z[sel[0]][None]).squeeze(1)
    for _ in range(k - 1):
        i = int(torch.argmax(mind))
        sel.append(i)
        mind = torch.minimum(mind, torch.cdist(z, z[i][None]).squeeze(1))
    return feats[torch.tensor(sel)]


@dataclass
class Calibration:
    """Maps raw distances to 0..1 using NORMAL held-out score statistics."""

    floor: float  # score at/below this -> 0 (p99.5 of normal pixels)
    span: float  # distance above floor mapped to 1.0

    def to_unit(self, raw: np.ndarray) -> np.ndarray:
        return np.clip((raw - self.floor) / self.span, 0.0, 1.0).astype(np.float32)


class PatchCore:
    def __init__(self, coreset_ratio: float = 0.1, max_samples: int = 60000, seed: int = 0):
        self.fx = FeatureExtractor()
        self.coreset_ratio = coreset_ratio
        self.max_samples = max_samples
        self.seed = seed
        self.bank: torch.Tensor | None = None
        self.calibration: Calibration | None = None

    # ---- training: normal imagery only ----------------------------------
    def _features(self, rgb: np.ndarray, crop: np.ndarray | None):
        feats = []
        for y, x, t in _tiles(rgb):
            f = self.fx(t)[0]  # (h, w, C)
            if crop is not None:
                c = crop[y : y + TILE, x : x + TILE]
                if c.shape != (TILE, TILE):
                    continue
                cm = torch.from_numpy(c.astype(np.float32))[None, None]
                cov = F.avg_pool2d(cm, FEAT_STRIDE)[0, 0]
                f = f[cov > 0.9]
            else:
                f = f.reshape(-1, f.shape[-1])
            feats.append(f)
        return torch.cat(feats) if feats else torch.empty(0, self.fx.out_dim)

    def fit(self, rgbs: list[np.ndarray], crops: list[np.ndarray]) -> int:
        feats = torch.cat([self._features(r, c) for r, c in zip(rgbs, crops)])
        if feats.shape[0] == 0:
            raise ValueError("no normal crop patches to build a memory bank from")
        g = torch.Generator().manual_seed(self.seed)
        if feats.shape[0] > self.max_samples:
            feats = feats[torch.randperm(feats.shape[0], generator=g)[: self.max_samples]]
        k = max(int(feats.shape[0] * self.coreset_ratio), 256)
        self.bank = _greedy_coreset(feats, k, self.seed)
        return int(self.bank.shape[0])

    # ---- inference -----------------------------------------------------
    def score_map(self, rgb: np.ndarray) -> np.ndarray:
        """Raw anomaly distance per pixel (H, W)."""
        assert self.bank is not None, "fit() or load() first"
        _, h, w = rgb.shape
        ph, pw = max(TILE - h, 0), max(TILE - w, 0)
        H, W = h + ph, w + pw
        acc = np.zeros((H, W), np.float32)
        cnt = np.zeros((H, W), np.float32)
        win = np.outer(np.hanning(TILE + 2)[1:-1], np.hanning(TILE + 2)[1:-1]).astype(np.float32) + 1e-3
        for y, x, t in _tiles(rgb):
            f = self.fx(t)[0]
            hh, ww, c = f.shape
            d = torch.cdist(f.reshape(-1, c), self.bank).min(dim=1).values.reshape(1, 1, hh, ww)
            up = F.interpolate(d, size=(TILE, TILE), mode="bilinear", align_corners=False)[0, 0].numpy()
            acc[y : y + TILE, x : x + TILE] += up * win
            cnt[y : y + TILE, x : x + TILE] += win
        out = acc / np.maximum(cnt, 1e-6)
        out = ndimage.gaussian_filter(out, 4.0)
        return out[:h, :w]

    def calibrate(self, rgb: np.ndarray, crop: np.ndarray) -> Calibration:
        """Fit the 0..1 mapping on held-out NORMAL imagery (not used for the bank)."""
        s = self.score_map(rgb)[crop]
        floor = float(np.percentile(s, 99.5))
        median = float(np.median(s))
        span = max(floor - median, 1e-3) * 2.0
        self.calibration = Calibration(floor=floor, span=span)
        return self.calibration

    def unit_map(self, rgb: np.ndarray, crop: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        assert self.calibration is not None, "calibrate() first"
        raw = self.score_map(rgb)
        return np.where(crop, self.calibration.to_unit(raw), 0.0).astype(np.float32), raw

    # ---- persistence ---------------------------------------------------
    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(
            {"bank": self.bank, "cal": self.calibration.__dict__ if self.calibration else None},
            path,
        )

    @classmethod
    def load(cls, path: Path) -> "PatchCore":
        d = torch.load(path, weights_only=False)
        m = cls()
        m.bank = d["bank"]
        m.calibration = Calibration(**d["cal"]) if d["cal"] else None
        return m
