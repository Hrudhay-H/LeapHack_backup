"""Pipeline tests on synthetic surveys. These check plumbing and the no-false-alarm behaviour;
they do NOT measure real-world pest-detection accuracy."""
import numpy as np
import pytest
from scipy import ndimage

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
    from agriscout_ml.simulate import Patch, inject_stress

    rng = np.random.default_rng(0)
    gsd = 0.05
    bands = np.stack([np.full((260, 260), v, np.float32) for v in (0.30, 0.38, 0.22, 0.49, 0.51)])  # B,G,R,RE,NIR
    bands += rng.normal(0, 0.002, bands.shape).astype(np.float32)
    plots = np.ones((260, 260), bool)
    out, truth = inject_stress(bands, plots, gsd, [Patch("t", 1.2, 0.8)], "now", seed=1)
    assert truth.sum() > 100
    far = ndimage.distance_transform_edt(~truth) * gsd > 2.0  # stress fades smoothly; anything 2 m away is untouched
    assert far.sum() > 1000
    assert np.allclose(out[:, far], bands[:, far])  # untouched away from the patch
    ndvi = lambda b: (b[4] - b[2]) / (b[4] + b[2])
    ndre = lambda b: (b[4] - b[3]) / (b[4] + b[3])
    assert ndvi(out)[truth].mean() < ndvi(bands)[truth].mean() - 0.1
    assert ndre(out)[truth].mean() < ndre(bands)[truth].mean() - 0.1  # NDRE must move too, not only NDVI


def test_stress_patch_has_an_irregular_outline_and_grows_between_surveys():
    from agriscout_ml.simulate import Patch, inject_stress

    bands = np.stack([np.full((300, 300), v, np.float32) for v in (0.30, 0.38, 0.22, 0.49, 0.51)])
    plots = np.ones((300, 300), bool)
    p = [Patch("t", 2.0, 0.8, earlier=(0.5, 0.7))]
    _, early = inject_stress(bands, plots, 0.05, p, "earlier", seed=3)
    _, late = inject_stress(bands, plots, 0.05, p, "now", seed=3)
    assert 0 < early.sum() < late.sum()
    assert (early & ~late).sum() < 0.1 * early.sum()  # the earlier patch sits inside the later one: same place, grown
    cvs = []
    for seed in range(1, 7):  # outline irregularity: spread of boundary distance from the centre (a perfect circle is 0.007)
        _, m = inject_stress(bands, plots, 0.05, [Patch("t", 2.0, 0.8)], "now", seed=seed)
        lab, _n = ndimage.label(m)
        m = lab == (np.argmax(np.bincount(lab.ravel())[1:]) + 1)
        cy, cx = ndimage.center_of_mass(m)
        ys, xs = np.nonzero(m & ~ndimage.binary_erosion(m))
        r = np.hypot(ys - cy, xs - cx)
        cvs.append(r.std() / r.mean())
    assert min(cvs) > 0.012 and np.median(cvs) > 0.02
    _, none = inject_stress(bands, plots, 0.05, [Patch("later", 1.0, 0.7)], "earlier", seed=3)
    assert none.sum() == 0  # a patch with no earlier state is absent at the earlier survey


def test_crop_mask_keeps_damage_that_reaches_a_plot_edge_but_not_a_wide_path():
    from agriscout_ml.spectral import crop_mask, indices

    gsd = 0.05
    n = 400
    ndvi_good = np.zeros((4, n, n), np.float32)
    red, green, re_, nir = 0.10, 0.12, 0.30, 0.55
    ms = np.stack([np.full((n, n), v, np.float32) for v in (red, green, re_, nir)])
    path = np.zeros((n, n), bool)
    path[:, 190:230] = True  # a 2 m wide path down the middle
    ms[0][path], ms[3][path] = 0.30, 0.30  # bare ground: low NDVI
    damage = np.zeros((n, n), bool)
    damage[100:160, 60:120] = True  # 3 m patch inside the left plot ...
    damage[130:136, 120:190] = True  # ... reaching the plot edge through a 0.3 m wide breach
    ms[0][damage], ms[3][damage] = 0.35, 0.28  # severely damaged: NDVI far below the crop floor
    idx = indices(ms)
    crop = crop_mask(idx, np.ones((n, n), bool), gsd_m=gsd)
    assert crop[damage & (np.arange(n)[None, :] < 130)].mean() > 0.9  # the damaged patch stays in the crop mask
    assert crop[path].mean() < 0.05  # the wide path does not
