"""Pipeline tests on synthetic surveys. These check plumbing and the no-false-alarm behaviour;
they do NOT measure real-world pest-detection accuracy."""
import numpy as np
import pytest

from agriscout_ml import pipeline
from agriscout_ml.io import load_survey
from agriscout_ml.spectral import robust_z
from agriscout_ml.synth import SynthConfig, default_patches, generate


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    b = tmp_path_factory.mktemp("synth")
    for name, cfg in {
        "ref1": SynthConfig(seed=1),
        "ref2": SynthConfig(seed=2),
        "stressed": SynthConfig(seed=7, patches=default_patches()),
        "healthy": SynthConfig(seed=11),
    }.items():
        generate(b / name, cfg)
    model = b / "m" / "pc.pt"
    pipeline.train([b / "ref1", b / "ref2"], model)
    return b, model


def test_healthy_field_yields_no_hotspots(world):
    b, model = world
    s = pipeline.run(b / "healthy", model, b / "out_h")
    assert s["summary"]["status"] == "no_significant_anomaly"
    assert s["summary"]["hotspots_detected"] == 0


def test_all_planted_patches_localised(world):
    b, model = world
    s = pipeline.run(b / "stressed", model, b / "out_s")
    chk = s["synthetic_check"]
    assert all(p["detected"] for p in chk["patches"])
    assert chk["pixel_recall"] > 0.9
    assert s["summary"]["hotspots_detected"] >= 3


def test_spectral_only_fallback_without_model(world):
    b, _ = world
    s = pipeline.run(b / "stressed", None, b / "out_ms")
    assert s["input_modalities"] == ["MULTISPECTRAL"]
    assert s["summary"]["hotspots_detected"] >= 3


def test_bunds_are_excluded_from_crop_area(world):
    b, model = world
    s = pipeline.run(b / "healthy", model, b / "out_h2")
    total_px = s["image"]["width_px"] * s["image"]["height_px"]
    crop_sqm = s["summary"]["valid_crop_area_sqm"]
    assert crop_sqm < total_px * s["image"]["gsd_m"] ** 2 * 0.97


def test_robust_z_is_not_dragged_by_outliers():
    x = np.concatenate([np.random.default_rng(0).normal(0.8, 0.01, 10_000), np.full(500, 0.2)])
    z = robust_z(x, np.ones_like(x, dtype=bool))
    assert abs(np.median(z)) < 0.05
    assert z[-1] < -20  # the stressed values stay clearly anomalous


def test_load_rejects_missing_files(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_survey(tmp_path)


def test_edge_free_excludes_boundary_band_but_not_image_border():
    mask = np.zeros((100, 100), bool)
    mask[:, 30:] = True  # field boundary at column 30; right/top/bottom touch the image border
    ok = pipeline.edge_free(mask, gsd_m=0.1, width_m=1.0)  # 1 m = 10 px
    assert not ok[50, 35]  # inside field but within 1 m of the boundary
    assert ok[50, 60]  # well inside
    assert ok[50, 99] and ok[0, 60]  # image border is not a field edge


def test_rgb_only_mode_flags_compact_patches_and_is_quiet_when_healthy(world, tmp_path):
    import shutil

    b, model = world
    for name in ("stressed", "healthy"):
        shutil.copytree(b / name, tmp_path / name)
        (tmp_path / name / "multispectral.tif").unlink()
    bad = pipeline.run(tmp_path / "stressed", model, tmp_path / "o1", "s")
    ok = pipeline.run(tmp_path / "healthy", model, tmp_path / "o2", "h")
    assert bad["input_modalities"] == ["RGB"]
    assert bad["branches"]["rgb_patchcore"] is not None  # PatchCore still participates
    assert bad["summary"]["hotspots_detected"] >= 2
    assert sum(p["detected"] for p in bad["synthetic_check"]["patches"]) >= 2
    assert ok["summary"]["hotspots_detected"] == 0
    assert ok["summary"]["status"] == "no_significant_anomaly"


def test_stress_injection_changes_bands_only_inside_the_patch_and_in_the_stress_direction():
    from agriscout_ml.simulate import Stress, inject_stress

    rng = np.random.default_rng(0)
    gsd = 0.05
    bands = np.stack([np.full((200, 200), v, np.float32) for v in (0.30, 0.38, 0.22, 0.49, 0.51)])  # B,G,R,RE,NIR
    bands += rng.normal(0, 0.002, bands.shape).astype(np.float32)
    crop = np.ones((200, 200), bool)
    out, truth = inject_stress(bands, crop, gsd, [Stress(1.0, 0.8, name="t")], seed=1)
    inside, outside = truth, ~ndilate(truth)
    assert truth.sum() > 100
    assert np.allclose(out[:, outside], bands[:, outside])  # untouched away from the patch
    ndvi = lambda b: (b[4] - b[2]) / (b[4] + b[2])
    ndre = lambda b: (b[4] - b[3]) / (b[4] + b[3])
    assert ndvi(out)[inside].mean() < ndvi(bands)[inside].mean() - 0.1
    assert ndre(out)[inside].mean() < ndre(bands)[inside].mean() - 0.1  # NDRE must move too, not only NDVI


def ndilate(m):
    from scipy import ndimage

    return ndimage.binary_dilation(m, iterations=6)
