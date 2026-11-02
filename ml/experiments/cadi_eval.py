"""Non-circular test of the RGB branch on CADI-AI (human-drawn boxes on drone images of cashew).

PatchCore is fitted ONLY on tissue outside the boxes of training images, then scores unseen test images.
Question: do pixels inside abiotic / disease / insect boxes score higher than the rest of the same image?
Class ids inferred from label counts (0=abiotic, 1=disease, 2=insect); the README's listed order differs.

  uv run python ml/experiments/cadi_eval.py [N_TRAIN] [N_TEST]
"""
from __future__ import annotations

import glob
import io
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.stats import rankdata

from agriscout_ml.patchcore import PatchCore
from agriscout_ml.spectral import robust_z

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
ROOT = Path("data/raw/cadi")
CLASSES = {0: "abiotic", 1: "disease", 2: "insect"}
N_TRAIN = int(sys.argv[1]) if len(sys.argv) > 1 else 300
N_TEST = int(sys.argv[2]) if len(sys.argv) > 2 else 200
PAD = 4


def load(split: str, stem: str):
    img = np.asarray(Image.open(ROOT / split / "images" / f"{stem}.jpg").convert("RGB")).transpose(2, 0, 1).copy()
    _, h, w = img.shape
    masks = {k: np.zeros((h, w), bool) for k in CLASSES}
    p = ROOT / split / "labels" / f"{stem}.txt"
    for ln in p.read_text().splitlines():
        v = ln.split()
        if len(v) < 5:
            continue
        c, cx, cy, bw, bh = int(v[0]), *map(float, v[1:5])
        x0, x1 = int((cx - bw / 2) * w) - PAD, int((cx + bw / 2) * w) + PAD
        y0, y1 = int((cy - bh / 2) * h) - PAD, int((cy + bh / 2) * h) + PAD
        masks[c][max(y0, 0): y1, max(x0, 0): x1] = True
    return img, masks


def auroc(score, pos):
    if pos.sum() < 5 or (~pos).sum() < 5:
        return float("nan")
    r = rankdata(score)
    n1, n0 = int(pos.sum()), int((~pos).sum())
    return float((r[pos].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def vari_z(img: np.ndarray) -> np.ndarray:
    r, g, b = [img[i].astype(np.float32) / 255 for i in range(3)]
    v = ndimage.gaussian_filter(np.clip((g - r) / (g + r - b + 1e-3), -1, 1), 3)
    return -robust_z(v, np.ones(v.shape, bool))


def stems(split: str, n: int, seed: int):
    all_ = sorted(Path(f).stem for f in glob.glob(str(ROOT / split / "images" / "*.jpg")))
    rng = np.random.default_rng(seed)
    return list(rng.choice(all_, min(n, len(all_)), replace=False))


def main():
    t0 = time.time()
    tr = [load("train", s) for s in stems("train", N_TRAIN, 0)]
    pc = PatchCore(coreset_ratio=0.1)
    bank = pc.fit([i for i, _ in tr], [~(m[0] | m[1] | m[2]) for _, m in tr])
    print(f"fit on {len(tr)} train images, bank {bank}, {time.time() - t0:.0f}s", flush=True)

    names = list(CLASSES.values())
    pooled = {"pc": {k: [] for k in [*names, "any"]}, "vari": {k: [] for k in [*names, "any"]}}
    pool_lab = {k: [] for k in [*names, "any"]}
    within = {"pc": {k: [] for k in names}, "vari": {k: [] for k in names}}
    box_ratio = {k: [] for k in names}
    for n, stem in enumerate(stems("test", N_TEST, 1), 1):
        img, m = load("test", stem)
        raw = pc.score_map(img)
        vz = vari_z(img)
        anym = m[0] | m[1] | m[2]
        outside = ~anym
        sub = np.random.default_rng(n).random(raw.shape) < 0.1  # thin pooled pixels
        for k, c in CLASSES.items():
            other = outside | m[k]
            pos = m[k] & ~outside
            for key, sc in (("pc", raw), ("vari", vz)):
                a = auroc(sc[other], m[k][other]) if m[k].sum() > 50 else float("nan")
                if not np.isnan(a):
                    within[key][c].append(a)
            if m[k].sum() > 50:
                box_ratio[c].append(float(raw[m[k]].mean() / raw[outside].mean()))
        for key, sc in (("pc", raw), ("vari", vz)):
            for c in names:
                k = [kk for kk, v in CLASSES.items() if v == c][0]
                sel = (outside | m[k]) & sub
                pooled[key][c].append(sc[sel])
                if key == "pc":
                    pool_lab[c].append(m[k][sel])
            sel = sub
            pooled[key]["any"].append(sc[sel])
            if key == "pc":
                pool_lab["any"].append(anym[sel])
        if n % 50 == 0:
            print(f"scored {n} test images, {time.time() - t0:.0f}s", flush=True)

    out = {"n_train_images": len(tr), "n_test_images": N_TEST, "bank": bank, "classes_inferred": CLASSES}
    for key in ("pc", "vari"):
        out[key] = {}
        for c in [*names, "any"]:
            s, l = np.concatenate(pooled[key][c]), np.concatenate(pool_lab[c])
            out[key][c] = {"pooled_auroc": round(auroc(s, l), 3),
                           "within_image_auroc_mean": round(float(np.nanmean(within[key][c])), 3) if c in within[key] and within[key][c] else None,
                           "images_with_class": len(within[key][c]) if c in within[key] else None}
    out["pc_mean_score_inside_box_vs_outside_ratio"] = {c: round(float(np.mean(v)), 3) for c, v in box_ratio.items() if v}
    Path("data/experiments").mkdir(parents=True, exist_ok=True)
    Path("data/experiments/cadi_eval.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
