"""Threshold-free check of raw anomaly scores against a labelled class raster.

AUROC of 'positive class vs healthy' over crop pixels, for the spectral z-score,
PatchCore distance and their equal-weight rank average. 0.5 = no better than chance.

  python -m agriscout_ml.eval_labels --survey DIR --model M.pt --mask MASK.tif --pos 1 2 --neg 3
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from scipy.stats import rankdata

from .io import _to_grid, load_survey
from .patchcore import PatchCore
from .spectral import crop_mask, indices, spectral_anomaly


def auroc(score: np.ndarray, pos: np.ndarray) -> float:
    r = rankdata(score)
    n1, n0 = int(pos.sum()), int((~pos).sum())
    return float((r[pos].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def evaluate(survey: Path, model: Path, mask: Path, pos: list[int], neg: list[int], max_px: int = 400_000) -> dict:
    s = load_survey(survey)
    idx = indices(s.ms)
    crop = crop_mask(idx, s.field_mask)
    z = spectral_anomaly(idx, crop)["z"]
    pc = PatchCore.load(model)
    raw = pc.score_map(s.rgb)
    with rasterio.open(mask) as m:
        crs = m.crs
    lab = _to_grid(mask, 1, s.shape, s.transform, crs, Resampling.mode, np.uint8)[0]

    is_pos, is_neg = np.isin(lab, pos) & crop, np.isin(lab, neg) & crop
    keep = np.nonzero((is_pos | is_neg).ravel())[0]
    rng = np.random.default_rng(0)
    if keep.size > max_px:
        keep = rng.choice(keep, max_px, replace=False)
    y = is_pos.ravel()[keep]
    zs, rs = z.ravel()[keep], raw.ravel()[keep]
    fused = (rankdata(zs) + rankdata(rs)) / (2 * len(keep))
    return {
        "survey": survey.name,
        "crop_pixels": int(crop.sum()),
        "positive_pixels": int(is_pos.sum()),
        "negative_pixels": int(is_neg.sum()),
        "positive_share": round(float(y.mean()), 4),
        "auroc_spectral": round(auroc(zs, y), 3),
        "auroc_patchcore": round(auroc(rs, y), 3),
        "auroc_rank_fusion": round(auroc(fused, y), 3),
        "note": "Labels are vegetation-index-guided pseudo-labels, not expert ground truth; spectral AUROC is partly circular.",
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--survey", type=Path, required=True)
    ap.add_argument("--model", type=Path, required=True)
    ap.add_argument("--mask", type=Path, required=True)
    ap.add_argument("--pos", type=int, nargs="+", required=True)
    ap.add_argument("--neg", type=int, nargs="+", required=True)
    a = ap.parse_args()
    print(json.dumps(evaluate(a.survey, a.model, a.mask, a.pos, a.neg), indent=2))
