"""What is PatchCore responding to? Fit on the rust field, score the water field at 2 cm; save a heatmap
and correlate the score with brightness, spectral stress and distance to the crop-mask edge."""
import sys, io
import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.stats import spearmanr
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
sys.path.insert(0, "ml/experiments")
from patchcore_sweep import Field
from agriscout_ml.patchcore import PatchCore

OUT = sys.argv[1]
fit, test = Field("rust", "_g02"), Field("water", "_g02")
pc = PatchCore(coreset_ratio=0.1)
pc.fit([fit.s.rgb], [fit.crop])
raw = pc.score_map(test.s.rgb)
np.save(OUT + "/pc_water_raw.npy", raw.astype(np.float32))
c = test.crop
lum = test.s.rgb.astype(np.float32).mean(0)
edge = ndimage.distance_transform_edt(c)
idx = np.flatnonzero(c.ravel()); idx = np.random.default_rng(0).choice(idx, 200000, replace=False)
for name, v in (("brightness (dark=shadow)", lum), ("spectral stress z", test.spec_z), ("distance from crop-mask edge", edge)):
    print(f"spearman(PatchCore, {name}) = {spearmanr(raw.ravel()[idx], v.ravel()[idx]).statistic:+.2f}")
hi = raw >= np.percentile(raw[c], 99)
print("top 1% PatchCore pixels: mean brightness", round(float(lum[hi & c].mean()), 1), "vs crop mean", round(float(lum[c].mean()), 1),
      "| within 1 m of crop edge:", round(float((edge[hi & c] < 50).mean()), 2), "vs crop overall", round(float((edge[c] < 50).mean()), 2),
      "| share labelled stress:", round(float(test.pos[hi & c].mean()), 3), "vs crop overall", round(float(test.pos[c].mean()), 3))
# side-by-side figure: RGB | PatchCore | spectral
def norm(a, lo, hi): return (np.clip((a - lo) / (hi - lo + 1e-9), 0, 1) * 255).astype(np.uint8)
def heat(a, lo, hi):
    import matplotlib; matplotlib.use("Agg"); import matplotlib.cm as cm
    return (cm.magma(np.clip((a - lo) / (hi - lo + 1e-9), 0, 1))[..., :3] * 255).astype(np.uint8)
f = 3
rgb = test.s.rgb.transpose(1, 2, 0)[::f, ::f]
pcm = np.where(c, raw, np.nan)[::f, ::f]; lo, hi_ = np.nanpercentile(pcm, [5, 99.5])
pch = heat(np.nan_to_num(pcm, nan=lo), lo, hi_)
sp = heat(np.where(c, test.spec_z, 0)[::f, ::f], 0, 6)
Image.fromarray(np.concatenate([rgb, pch, sp], axis=0)).save(OUT + "/pc_diag.png")
print("saved")
