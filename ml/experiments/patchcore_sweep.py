"""Cross-field PatchCore diagnosis on the real Zenodo maize mosaics.

Fit on one field, score the OTHER (no leakage), compare against the dataset's pseudo-labels at pixel and
1 m block level, next to a spectral z-score and an RGB-only VARI z-score.

  uv run python ml/experiments/patchcore_sweep.py
"""
from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from scipy import ndimage
from scipy.stats import rankdata, spearmanr

from agriscout_ml.io import _to_grid, load_survey
from agriscout_ml.patchcore import PatchCore
from agriscout_ml.spectral import crop_mask, indices, robust_z, spectral_anomaly

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
RAW = Path("data/raw")
MASKS = RAW / "zenodo_maize/patches"
LABELS = {  # field -> (mask tif, positive classes, negative classes)
    "water": (MASKS / "water_2025/full_masks/water_full_mask_corrected.tif", [1, 2], [3]),
    "rust": (MASKS / "rust_2025/full_masks/rust_full_mask_corrected.tif", [1], [2]),
}
OUT = Path("data/experiments")
OUT.mkdir(parents=True, exist_ok=True)


def auroc(score, pos):
    if pos.sum() == 0 or (~pos).sum() == 0:
        return float("nan")
    r = rankdata(score)
    n1, n0 = int(pos.sum()), int((~pos).sum())
    return float((r[pos].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def vari_z(rgb: np.ndarray, crop: np.ndarray) -> np.ndarray:
    """RGB-only vegetation index VARI = (G-R)/(G+R-B); low = anomalous. Returns positive-is-worse z."""
    r, g, b = [rgb[i].astype(np.float32) / 255.0 for i in range(3)]
    v = (g - r) / (g + r - b + 1e-3)
    v = np.clip(v, -1, 1)
    v = ndimage.gaussian_filter(v, 3)
    return -robust_z(v, crop)


class Field:
    def __init__(self, name: str, tag: str):
        self.name, self.tag = name, tag
        self.s = load_survey(RAW / f"maize_{name}{tag}", target_gsd_m=None)
        idx = indices(self.s.ms)
        self.crop = crop_mask(idx, self.s.field_mask)
        self.spec_z = spectral_anomaly(idx, self.crop)["z"]
        self.vari = vari_z(self.s.rgb, self.crop)
        mask, pos, neg = LABELS[name]
        with rasterio.open(mask) as m:
            crs = m.crs
        lab = _to_grid(mask, 1, self.s.shape, self.s.transform, crs, Resampling.mode, np.uint8)[0]
        self.pos = np.isin(lab, pos) & self.crop
        self.neg = np.isin(lab, neg) & self.crop
        self.gsd = self.s.gsd_m

    def metrics(self, name: str, score: np.ndarray, block_m: float = 1.0, thr: float = 0.25, rng=np.random.default_rng(0)):
        lab_px = self.pos | self.neg
        idx = np.flatnonzero(lab_px.ravel())
        if idx.size > 300_000:
            idx = rng.choice(idx, 300_000, replace=False)
        px = auroc(score.ravel()[idx], self.pos.ravel()[idx])
        b = max(int(round(block_m / self.gsd)), 1)
        h, w = score.shape
        h2, w2 = h // b * b, w // b * b

        def blk(a):
            return a[:h2, :w2].reshape(h2 // b, b, w2 // b, b).sum(axis=(1, 3))

        n_lab = blk(lab_px.astype(np.float32))
        n_pos = blk(self.pos.astype(np.float32))
        n_crop = blk(self.crop.astype(np.float32))
        s_sum = blk(np.where(self.crop, score, 0).astype(np.float32))
        ok = (n_lab >= 0.5 * b * b) & (n_crop > 0)
        frac = n_pos[ok] / n_lab[ok]
        sc = s_sum[ok] / n_crop[ok]
        return {
            "px_auroc": round(px, 3),
            "blk_auroc": round(auroc(sc, frac >= thr), 3),
            "blk_spearman": round(float(spearmanr(sc, frac).statistic), 3),
            "blk_pos": int((frac >= thr).sum()),
            "blk_n": int(ok.sum()),
        }


def main():
    rows = []
    for tag, label in (("", "5cm"), ("_g02", "2cm")):
        fields = {n: Field(n, tag) for n in ("water", "rust")}
        for n, f in fields.items():
            print(f"[{label}] {n}: {f.s.shape}, crop {f.crop.mean():.2f}, pos {f.pos.sum()}, neg {f.neg.sum()}", flush=True)
        for n, f in fields.items():
            for nm, sc in (("spectral_z", f.spec_z), ("vari_z", f.vari)):
                r = {"gsd": label, "fit": "-", "test": n, "model": nm, **f.metrics(nm, sc)}
                rows.append(r); print(r, flush=True)
        for fit_n, test_n in (("water", "rust"), ("rust", "water")):
            for cr in (0.1, 0.5):
                t0 = time.time()
                pc = PatchCore(coreset_ratio=cr)
                fit = fields[fit_n]
                bank = pc.fit([fit.s.rgb], [fit.crop])
                test = fields[test_n]
                raw = pc.score_map(test.s.rgb)
                r = {"gsd": label, "fit": fit_n, "test": test_n, "model": f"patchcore_cr{cr}", "bank": bank,
                     "secs": round(time.time() - t0), **test.metrics("pc", raw)}
                rows.append(r); print(r, flush=True)
                with open(OUT / "patchcore_sweep.jsonl", "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(r) + "\n")
    print("done", flush=True)


if __name__ == "__main__":
    main()
