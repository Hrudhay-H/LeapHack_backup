"""Synthetic paddy survey generator.

Builds a georeferenced RGB + 4-band multispectral survey with *known* planted
stress patches. Used for pipeline tests, sensitivity-by-patch-size checks and
demos before real imagery is available. Output is always labelled synthetic.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin
from scipy import ndimage

# Roughly Mandya, Karnataka. UTM 43N keeps pixel sizes in metres.
CRS = "EPSG:32643"
ORIGIN_X, ORIGIN_Y = 656000.0, 1383000.0

BANDS = ["red", "green", "rededge", "nir"]


@dataclass
class Patch:
    cx: float  # fraction of width
    cy: float  # fraction of height
    radius_m: float
    severity: float  # 0..1
    kind: str = "compact"  # compact | elongated | edge


@dataclass
class SynthConfig:
    size: int = 768  # pixels per side
    gsd_m: float = 0.05  # 5 cm ground sampling distance
    seed: int = 7
    patches: list[Patch] = field(default_factory=list)
    bund_width_px: int = 10
    n_plots: int = 2  # field split into n x n plots by bunds


def default_patches() -> list[Patch]:
    return [
        Patch(0.28, 0.30, 1.6, 0.85, "compact"),
        Patch(0.68, 0.62, 1.1, 0.7, "compact"),
        Patch(0.50, 0.82, 2.6, 0.55, "elongated"),
    ]


def _smooth_noise(shape, sigma, rng):
    n = rng.normal(size=shape)
    n = ndimage.gaussian_filter(n, sigma)
    return (n - n.mean()) / (n.std() + 1e-9)


def _patch_mask(cfg: SynthConfig, p: Patch, rng) -> np.ndarray:
    n = cfg.size
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    r_px = p.radius_m / cfg.gsd_m
    dx = xx - p.cx * n
    dy = yy - p.cy * n
    if p.kind == "elongated":
        d = np.sqrt((dx / (r_px * 2.6)) ** 2 + (dy / (r_px * 0.55)) ** 2)
    else:
        d = np.sqrt((dx / r_px) ** 2 + (dy / r_px) ** 2)
    wobble = _smooth_noise((n, n), 12, rng) * 0.12
    return np.clip(1.0 - (d + wobble), 0, 1) > 0


def generate(out_dir: Path, cfg: SynthConfig | None = None, healthy: bool = False) -> dict:
    cfg = cfg or SynthConfig(patches=[] if healthy else default_patches())
    rng = np.random.default_rng(cfg.seed)
    n = cfg.size
    out_dir.mkdir(parents=True, exist_ok=True)

    # Healthy canopy variation (soil, water depth): unit-variance field.
    vn = 0.75 * _smooth_noise((n, n), 60, rng) + 0.45 * _smooth_noise((n, n), 8, rng)

    # Bunds (raised field dividers): non-crop strips.
    crop = np.ones((n, n), dtype=bool)
    step = n // cfg.n_plots
    for i in range(0, n, step):
        crop[max(i - cfg.bund_width_px // 2, 0): i + cfg.bund_width_px // 2, :] = False
        crop[:, max(i - cfg.bund_width_px // 2, 0): i + cfg.bund_width_px // 2] = False
    crop[: cfg.bund_width_px, :] = False
    crop[-cfg.bund_width_px:, :] = False
    crop[:, : cfg.bund_width_px] = False
    crop[:, -cfg.bund_width_px:] = False

    truth = np.zeros((n, n), dtype=np.uint8)
    stress = np.zeros((n, n), dtype=np.float32)
    for p in cfg.patches:
        m = _patch_mask(cfg, p, rng) & crop
        truth[m] = 1
        soft = ndimage.gaussian_filter(m.astype(np.float32), 2.0)
        stress = np.maximum(stress, soft * p.severity)

    # Reflectance: healthy canopy NDVI ~0.8; full-severity stress ~0.55.
    noise = lambda s: rng.normal(0, s, (n, n)).astype(np.float32)
    red = 0.05 + 0.004 * vn + 0.07 * stress + noise(0.004)
    green = 0.08 + 0.003 * vn + 0.04 * stress + noise(0.004)
    rededge = 0.20 + 0.008 * vn + 0.05 * stress + noise(0.006)
    nir = 0.45 + 0.02 * vn - 0.10 * stress + noise(0.010)

    # Bunds: bare soil/grass, brighter red, weaker NIR (NDVI ~0.1).
    soil = ~crop
    red[soil] = 0.22 + noise(0.01)[soil]
    green[soil] = 0.17 + noise(0.01)[soil]
    rededge[soil] = 0.27 + noise(0.01)[soil]
    nir[soil] = 0.28 + noise(0.015)[soil]

    ms = np.stack([red, green, rededge, nir]).clip(0.0, 1.0).astype(np.float32)

    # RGB: transplanted rows (~20 cm period) give canopy texture. Stress thins the
    # rows (lower amplitude), yellows the canopy and lets soil show through.
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    period_px = 0.2 / cfg.gsd_m
    rows = 0.5 + 0.5 * np.sin(2 * np.pi * (xx + 0.15 * yy) / period_px)
    row_amp = 0.05 * (1 - 0.7 * stress)
    tex = _smooth_noise((n, n), 1.2, rng) * 0.015
    r8 = (0.14 + 0.35 * stress + 0.01 * vn + row_amp * rows * 0.4 + tex).clip(0, 1)
    g8 = (0.34 - 0.10 * stress + 0.012 * vn + row_amp * rows + tex).clip(0, 1)
    b8 = (0.10 + 0.08 * stress + row_amp * rows * 0.2 + tex).clip(0, 1)
    r8[soil], g8[soil], b8[soil] = 0.45, 0.38, 0.28
    rgb = (np.stack([r8, g8, b8]) * 255).astype(np.uint8)

    transform = from_origin(ORIGIN_X, ORIGIN_Y, cfg.gsd_m, cfg.gsd_m)
    meta = dict(driver="GTiff", height=n, width=n, crs=CRS, transform=transform, compress="deflate")
    with rasterio.open(out_dir / "rgb.tif", "w", count=3, dtype="uint8", **meta) as dst:
        dst.write(rgb)
    with rasterio.open(out_dir / "multispectral.tif", "w", count=4, dtype="float32", **meta) as dst:
        dst.write(ms)
        dst.descriptions = tuple(BANDS)
    with rasterio.open(out_dir / "field_mask.tif", "w", count=1, dtype="uint8", **meta) as dst:
        dst.write(np.ones((1, n, n), dtype=np.uint8))
    with rasterio.open(out_dir / "truth_mask.tif", "w", count=1, dtype="uint8", **meta) as dst:
        dst.write(truth[None])

    info = {
        "data_source": "synthetic_demo",
        "crs": CRS,
        "gsd_m": cfg.gsd_m,
        "size_px": n,
        "bands": BANDS,
        "reflectance_calibrated": True,
        "planted_patches": [p.__dict__ for p in cfg.patches],
    }
    (out_dir / "survey.json").write_text(json.dumps(info, indent=2))
    return info


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--healthy", action="store_true")
    a = ap.parse_args()
    print(json.dumps(generate(a.out, healthy=a.healthy), indent=2))
