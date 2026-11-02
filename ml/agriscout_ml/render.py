"""PNG rendering for the dashboard and PDF report."""
from __future__ import annotations

from pathlib import Path

import matplotlib
import numpy as np
from PIL import Image
from scipy import ndimage

_inferno = matplotlib.colormaps["inferno"]
_viridis = matplotlib.colormaps["RdYlGn"]


def save_rgb(rgb: np.ndarray, path: Path) -> None:
    Image.fromarray(np.moveaxis(rgb, 0, -1)).save(path)


def save_heat(score: np.ndarray, path: Path, alpha_max: float = 0.85) -> None:
    """RGBA heatmap: fully transparent where the score is 0."""
    rgba = (_inferno(np.clip(score, 0, 1)) * 255).astype(np.uint8)
    a = np.clip(score * 3.0, 0, 1) * alpha_max
    rgba[..., 3] = (a * 255).astype(np.uint8)
    Image.fromarray(rgba, "RGBA").save(path)


def save_index(x: np.ndarray, valid: np.ndarray, path: Path, lo: float, hi: float) -> None:
    n = np.clip((x - lo) / (hi - lo), 0, 1)
    rgba = (_viridis(n) * 255).astype(np.uint8)
    rgba[..., 3] = np.where(valid, 255, 0).astype(np.uint8)
    Image.fromarray(rgba, "RGBA").save(path)


def save_overlay(rgb: np.ndarray, hotspot_mask: np.ndarray, path: Path) -> None:
    """RGB with hotspot outlines (final marking is done by the UI from GeoJSON)."""
    base = np.moveaxis(rgb, 0, -1).copy()
    edge = hotspot_mask & ~ndimage.binary_erosion(hotspot_mask, iterations=2)
    base[edge] = (255, 235, 59)
    Image.fromarray(base).save(path)
