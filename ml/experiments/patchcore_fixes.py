"""Test two PatchCore fixes offline: ignore the field-edge band; score relative to local surroundings."""
import io, sys
import numpy as np
from scipy import ndimage
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
sys.path.insert(0, "ml/experiments")
from patchcore_sweep import Field, auroc
from agriscout_ml.patchcore import PatchCore
from scipy.stats import rankdata

TAG = "_g02"
fields = {n: Field(n, TAG) for n in ("water", "rust")}

def local_contrast(raw, crop, sigma_m):
    s = sigma_m / fields["water"].gsd
    w = ndimage.gaussian_filter(crop.astype(np.float32), s) + 1e-6
    bg = ndimage.gaussian_filter(np.where(crop, raw, 0).astype(np.float32), s) / w
    return raw - bg

def pix_auroc(f, score, interior):
    ev = (f.pos | f.neg) & interior
    idx = np.flatnonzero(ev.ravel())
    idx = np.random.default_rng(0).choice(idx, min(300000, idx.size), replace=False)
    return round(auroc(score.ravel()[idx], f.pos.ravel()[idx]), 3)

for fit_n, test_n in (("rust", "water"), ("water", "rust")):
    pc = PatchCore(coreset_ratio=0.1)
    pc.fit([fields[fit_n].s.rgb], [fields[fit_n].crop])
    f = fields[test_n]
    raw = pc.score_map(f.s.rgb)
    dist_m = ndimage.distance_transform_edt(f.s.field_mask) * f.gsd
    interior = dist_m > 1.0
    print(f"--- fit {fit_n} -> test {test_n}: share of labelled crop pixels kept after dropping 1 m edge band: "
          f"{((f.pos|f.neg)&interior).sum()/(f.pos|f.neg).sum():.2f}")
    print("raw PatchCore, all pixels          ", pix_auroc(f, raw, np.ones_like(interior)))
    print("raw PatchCore, interior only       ", pix_auroc(f, raw, interior))
    for sig in (2.0, 5.0):
        lc = local_contrast(raw, f.crop & interior, sig)
        print(f"local contrast (sigma {sig} m), interior", pix_auroc(f, lc, interior))
    lc = local_contrast(raw, f.crop & interior, 5.0)
    print("spectral z, interior               ", pix_auroc(f, f.spec_z, interior))
    fused = (rankdata(f.spec_z.ravel()) + rankdata(lc.ravel())) / (2 * lc.size)
    print("rank fusion spectral + PC(contrast)", pix_auroc(f, fused.reshape(lc.shape), interior))
    mx = np.maximum(rankdata(f.spec_z.ravel()), rankdata(lc.ravel())) / lc.size
    print("max-rank fusion                    ", pix_auroc(f, mx.reshape(lc.shape), interior))
