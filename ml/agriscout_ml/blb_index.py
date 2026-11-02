"""Prepare the Thai UAV bacterial-leaf-blight (BLB) dataset for the mosaic and evaluation scripts.

Dataset: figshare doi 10.6084/m9.figshare.26955862 (CC BY 4.0). Its files are hosted on Google Drive, so download the
folder in a browser (a scripted download is rate-limited); it arrives as several BLB_UAVdataset-*.zip parts.

Two steps (run from the repository root):

  python -m agriscout_ml.blb_index --zips "data/raw/blb/drive/*.zip"   # extract D1 patches, masks and the label CSV
  python -m agriscout_ml.blb_index                                       # build positions.json and cluster.npy

Outputs under data/raw/blb/:
  data/D1/{train,val,test}[_labels]/   extracted patches (image_patch_N.tif) and masks (label_patch_N.tif)
  positions.json                       [split, file name, centre x, centre y] for every patch
  cluster.npy                          0 = the blight site, 1 = the healthy site

The authors' patches overlap by 50% and their random train/val/test split puts every test patch beside a training
patch, so spatial structure is recovered from the patch coordinates. Patches fall into two disconnected sites: the
healthy site (no blight pixels) and the blight site (no healthy-rice pixels).
"""
from __future__ import annotations

import argparse
import glob
import json
import zipfile
from pathlib import Path

import numpy as np
import rasterio
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

ROOT = Path("data/raw/blb")
D1 = ROOT / "data/D1"
BLIGHT_CLASSES = (2, 3)  # low and high severity


def extract(zip_globs: list[str], out: Path = ROOT / "data") -> int:
    """Extract D1 patches/masks and the label CSV from the Google Drive zip parts."""
    n = 0
    for pattern in zip_globs:
        for z in sorted(glob.glob(pattern)):
            with zipfile.ZipFile(z) as zf:
                for m in zf.infolist():
                    if m.is_dir() or "/" not in m.filename:
                        continue
                    rel = m.filename.split("/", 1)[1]
                    if not (rel.startswith("D1/") or rel.endswith(".csv")):
                        continue
                    dst = (out / rel).resolve()
                    if out.resolve() not in dst.parents:
                        raise ValueError(f"unsafe path in archive: {m.filename}")
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(m) as src, open(dst, "wb") as f:
                        f.write(src.read())
                    n += 1
    return n


def _mask(split: str, name: str) -> np.ndarray:
    with rasterio.open(D1 / f"{split}_labels" / name.replace("image_patch", "label_patch")) as s:
        return np.rint(s.read(1)).astype(np.int64)


def build_index(d1: Path = D1) -> tuple[list[list], np.ndarray]:
    rows = []
    for split in ("train", "val", "test"):
        for f in sorted((d1 / split).glob("*.tif")):
            with rasterio.open(f) as s:
                b = s.bounds
                res = s.res[0]
            rows.append([split, f.name, (b.left + b.right) / 2, (b.bottom + b.top) / 2])
    if not rows:
        raise FileNotFoundError(f"no patches under {d1}; run with --zips first")
    xy = np.array([[r[2], r[3]] for r in rows])
    step = 256 * res
    pairs = np.array(sorted(cKDTree(xy).query_pairs(step * 0.8)))
    graph = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(len(rows),) * 2)
    n, lab = connected_components(graph, directed=False)
    if n != 2:
        raise RuntimeError(f"expected 2 disconnected sites, found {n}; check the extracted patches")
    # Name the sites by content, not by component order: 0 = the one holding blight pixels.
    has_blight = np.array([np.isin(_mask(r[0], r[1]), BLIGHT_CLASSES).any() for r in rows])
    blight_comp = int(np.bincount(lab[has_blight], minlength=2).argmax())
    cluster = np.where(lab == blight_comp, 0, 1).astype(lab.dtype)
    return rows, cluster


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zips", nargs="+", help="glob(s) of the downloaded BLB_UAVdataset zip parts to extract first")
    ap.add_argument("--out", type=Path, default=ROOT, help="where to write positions.json and cluster.npy")
    a = ap.parse_args()
    if a.zips:
        print("extracted", extract(a.zips), "files")
    rows, cluster = build_index()
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "positions.json").write_text(json.dumps(rows))
    np.save(a.out / "cluster.npy", cluster)
    print(f"{len(rows)} patches | site 0 (blight): {int((cluster == 0).sum())} | site 1 (healthy): {int((cluster == 1).sum())}")
