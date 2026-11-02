"""Top-down paddy test on the Thai UAV bacterial-leaf-blight dataset (1.1 cm, expert severity masks).

Dataset structure (found by clustering patch coordinates): cluster 1 = healthy site (no blight pixels),
cluster 0 = blight site (no healthy-rice pixels). The authors' random patch split leaks across 50%-overlapping
neighbours, so this script splits by SPACE inside the healthy site instead.

Tests (pixel AUROC, 0.5 = chance):
  A. blight pixels (blight site) vs held-out healthy pixels (healthy site)       <- confounded by site
  B. high-severity vs low-severity pixels, both inside the blight site          <- no site confound
  C. 'others' (non-rice) pixels, blight site vs healthy site                     <- measures the site effect itself
References are built only from healthy pixels in the fit region of the healthy site.

  uv run python ml/experiments/blb_eval.py
"""
from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

import numpy as np
import rasterio
from scipy import ndimage
from scipy.stats import rankdata

from agriscout_ml.patchcore import PatchCore

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
R = Path("data/raw/blb/data/D1")
rows = json.load(open("data/raw/blb/positions.json"))
cluster = np.load("data/raw/blb/cluster.npy")
x = np.array([r[2] for r in rows]); y = np.array([r[3] for r in rows])
rng = np.random.default_rng(0)
SIG = 5.0
OTHERS, LOW, HIGH, HEALTHY = 1, 2, 3, 4


def load(i):
    sp, name = rows[i][0], rows[i][1]
    with rasterio.open(R / sp / name) as s:
        b = s.read().astype(np.float32)  # D1 order per the dataset README: B, G, R, red-edge, NIR
    with rasterio.open(R / f"{sp}_labels" / name.replace("image_patch", "label_patch")) as s:
        m = np.rint(s.read(1)).astype(np.int64)
    return b, m


def auroc(score, pos):
    if pos.sum() < 20 or (~pos).sum() < 20:
        return float("nan")
    r = rankdata(score)
    n1, n0 = int(pos.sum()), int((~pos).sum())
    return float((r[pos].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def feats(b):
    blue, green, red, re_, nir = b
    nd = lambda a, c: (a - c) / (a + c + 1e-6)
    vari = np.clip((green - red) / (green + red - blue + 1e-3), -1, 1)
    sm = lambda a: ndimage.gaussian_filter(a, SIG)
    return {"ndre": sm(nd(nir, re_)), "ndvi": sm(nd(nir, red)), "vari": sm(vari)}


# ---- split the healthy site by space: fit on the low-x 60%, hold out the high-x 30%, drop the 10% between
c1 = np.flatnonzero(cluster == 1)
c0 = np.flatnonzero(cluster == 0)
ax = x if np.ptp(x[c1]) >= np.ptp(y[c1]) else y
q60, q70 = np.quantile(ax[c1], [0.6, 0.7])
fit_idx = [i for i in c1 if ax[i] <= q60]
held_idx = [i for i in c1 if ax[i] >= q70]
print(f"healthy site: {len(c1)} patches -> fit region {len(fit_idx)}, held-out {len(held_idx)}; blight site {len(c0)} patches", flush=True)

# ---- reference from healthy pixels of the fit region
t0 = time.time()
fit_sel = rng.choice(fit_idx, min(400, len(fit_idx)), replace=False)
ref_vals = {k: [] for k in ("ndre", "ndvi", "vari")}
fit_rgbs, fit_crops, raws = [], [], []
for i in fit_sel:
    b, m = load(i)
    healthy = m == HEALTHY
    if healthy.mean() < 0.8:
        continue
    f = feats(b)
    for k in ref_vals:
        ref_vals[k].append(f[k][healthy][::17])
    raws.append(b[[2, 1, 0]]); fit_crops.append(healthy)
ref = {k: (float(np.median(np.concatenate(v))), float(1.4826 * np.median(np.abs(np.concatenate(v) - np.median(np.concatenate(v)))))) for k, v in ref_vals.items()}
gain = 255.0 / float(np.percentile(np.concatenate([r.ravel()[::50] for r in raws]), 99.5))
to8 = lambda b: np.clip(b[[2, 1, 0]] * gain, 0, 255).astype(np.uint8)
print("band means (B,G,R,RE,NIR) of a healthy fit patch:", [round(float(v), 3) for v in load(fit_sel[0])[0].mean(axis=(1, 2))], "| ref (median, MAD):", {k: tuple(round(a, 3) for a in v) for k, v in ref.items()}, flush=True)

pc = PatchCore(coreset_ratio=0.1)
bank = pc.fit([to8(r_) if False else np.clip(r_ * gain, 0, 255).astype(np.uint8) for r_ in raws], fit_crops)
print(f"PatchCore fitted on {len(raws)} healthy patches, bank {bank}, {time.time() - t0:.0f}s", flush=True)


def score_patch(b):
    f = feats(b)
    z = {k: (ref[k][0] - f[k]) / (ref[k][1] + 1e-6) for k in f}  # positive = lower than healthy reference
    return {
        "spectral": (z["ndre"] + z["ndvi"]) / 2,
        "ndre": z["ndre"],
        "vari": z["vari"],
        "patchcore": pc.score_map(to8(b)),
    }


def collect(idx_list, classes, per_patch=1500):
    out = {k: [] for k in ("spectral", "ndre", "vari", "patchcore")}
    cls = []
    for i in idx_list:
        b, m = load(i)
        sel = np.isin(m, classes)
        if sel.sum() < 200:
            continue
        s = score_patch(b)
        pix = np.flatnonzero(sel.ravel())
        pix = rng.choice(pix, min(per_patch, pix.size), replace=False)
        for k in out:
            out[k].append(s[k].ravel()[pix])
        cls.append(m.ravel()[pix])
    return {k: np.concatenate(v) for k, v in out.items()}, np.concatenate(cls)


held = list(rng.choice(held_idx, min(150, len(held_idx)), replace=False))
blight_patches = [i for i in c0]
rng.shuffle(blight_patches)
# keep patches that actually contain blight pixels
blight_patches = blight_patches[:400]

res = {"n_fit_patches": len(raws), "bank": bank}
t0 = time.time()
H, _ = collect(held, [HEALTHY])
B, bc = collect(blight_patches, [LOW, HIGH])
print(f"scored: healthy-held {len(H['spectral'])} px, blight {len(B['spectral'])} px ({time.time() - t0:.0f}s)", flush=True)
O1, _ = collect(held, [OTHERS])
O0, _ = collect(blight_patches, [OTHERS])

for k in ("spectral", "ndre", "vari", "patchcore"):
    a = np.concatenate([B[k], H[k]]); lab = np.r_[np.ones(len(B[k]), bool), np.zeros(len(H[k]), bool)]
    a_hi = np.concatenate([B[k][bc == HIGH], H[k]]); l_hi = np.r_[np.ones((bc == HIGH).sum(), bool), np.zeros(len(H[k]), bool)]
    a_lo = np.concatenate([B[k][bc == LOW], H[k]]); l_lo = np.r_[np.ones((bc == LOW).sum(), bool), np.zeros(len(H[k]), bool)]
    sev = np.concatenate([B[k][bc == HIGH], B[k][bc == LOW]]); l_sev = np.r_[np.ones((bc == HIGH).sum(), bool), np.zeros((bc == LOW).sum(), bool)]
    oo = np.concatenate([O0[k], O1[k]]); l_oo = np.r_[np.ones(len(O0[k]), bool), np.zeros(len(O1[k]), bool)]
    res[k] = {
        "A_blight_vs_healthy": round(auroc(a, lab), 3),
        "A_high_vs_healthy": round(auroc(a_hi, l_hi), 3),
        "A_low_vs_healthy": round(auroc(a_lo, l_lo), 3),
        "B_high_vs_low_severity_within_blight_site": round(auroc(sev, l_sev), 3),
        "C_same_class_others_site0_vs_site1": round(auroc(oo, l_oo), 3),
    }
res["pixels"] = {"healthy_held": len(H["spectral"]), "blight_low": int((bc == LOW).sum()), "blight_high": int((bc == HIGH).sum())}
Path("data/experiments").mkdir(parents=True, exist_ok=True)
Path("data/experiments/blb_eval.json").write_text(json.dumps(res, indent=2))
print(json.dumps(res, indent=2))
