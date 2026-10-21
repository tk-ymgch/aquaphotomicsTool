"""Independent numerical identities and strict supported-scope checks.

The installed R oracle is exercised by scripts/compare_aquap2py.py, separately
from these normal Python unit tests. Passing these tests alone is not R evidence.
"""
from __future__ import annotations
import copy
import json
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
import aquap2py as ap


def fixture():
    rng = np.random.default_rng(53171)
    t = np.linspace(-1, 1, 31)
    rows = []
    for i in range(18):
        rows.append((0.4 + 0.2 * np.exp(-t * t) + 0.03 * (i // 6) * t) *
                    (0.9 + 0.01 * i) + 0.002 * i + rng.normal(0, 0.002, len(t)))
    return np.array(rows), np.arange(1300, 1455, 5, dtype=float), ["A"] * 5 + ["B"] * 6 + ["C"] * 7


def test_snv_sample_sd_and_input_preservation():
    x = np.array([[1., 2, 4], [3, 7, 10]])
    old = x.copy()
    result = ap.preprocess(x, [{"method": "snv"}])
    np.testing.assert_allclose(result.mean(axis=1), 0, atol=1e-15)
    np.testing.assert_allclose(result.std(axis=1, ddof=1), 1, atol=1e-15)
    assert not np.allclose(result.std(axis=1, ddof=0), 1)
    np.testing.assert_array_equal(x, old)


def test_msc_known_affine_spectra_and_explicit_reference():
    ref = np.array([.4, .7, .9, .5, .2])
    x = np.array([ref, .3 + 1.2 * ref, -.1 + .8 * ref])
    np.testing.assert_allclose(ap.msc(x, ref), np.tile(ref, (3, 1)), atol=1e-14)
    # With the mean as reference, affine input spectra all reduce to that mean.
    np.testing.assert_allclose(ap.msc(x), np.tile(x.mean(0), (3, 1)), atol=1e-14)


@pytest.mark.parametrize("derivative", [0, 1, 2])
def test_sg_polynomial_derivatives_include_both_boundaries(derivative):
    t = np.arange(31, dtype=float)
    x = 1 + .03 * t + .002 * t * t + .00001 * t ** 3
    expected = [x, .03 + .004 * t + .00003 * t ** 2, .004 + .00006 * t][derivative]
    y = ap.sgolay(np.array([x]), window=9, polyorder=3, derivative=derivative)
    np.testing.assert_allclose(y[0], expected, atol=2e-12, rtol=2e-12)
    assert y.shape == (1, 31)


def test_steps_order_matters_and_is_exactly_the_requested_order():
    x, _, _ = fixture()
    sg = {"method": "sgolay", "window": 9, "polyorder": 2, "derivative": 0}
    a = ap.preprocess(x, [sg, {"method": "snv"}])
    b = ap.preprocess(x, [{"method": "snv"}, sg])
    np.testing.assert_allclose(a, ap.snv(ap.sgolay(x, window=9)), atol=1e-14)
    assert not np.allclose(a, b, atol=1e-6)


def test_pca_covariance_spectrum_orientation_reconstruction_and_translation():
    x, _, _ = fixture()
    x = x[:, :7]
    out = ap.pca(x, 7)
    scores, loadings = np.array(out["scores"]), np.array(out["loadings"])
    covariance = np.cov(x, rowvar=False)
    eigenvalues = np.linalg.eigvalsh(covariance)[::-1]
    np.testing.assert_allclose(out["explainedVariance"], eigenvalues / eigenvalues.sum(), atol=1e-11)
    np.testing.assert_allclose(loadings.T @ loadings, np.eye(7), atol=1e-14)
    np.testing.assert_allclose(scores @ loadings.T, x - x.mean(0), atol=1e-14)
    translated = ap.pca(x + np.arange(7), 7)
    np.testing.assert_allclose(translated["explainedVariance"], out["explainedVariance"], atol=1e-12)


def test_classic_and_control_are_sample_sd_group_averages_with_real_wavelength_order():
    x, w, groups = fixture()
    targets = w[[2, 13, 27]]
    aq = ap.classic_aquagram(x, w, groups, targets[::-1])
    assert aq["wavelengths"] == targets.tolist()
    selected = x[:, [2, 13, 27]]
    z = (selected - selected.mean(0)) / selected.std(0, ddof=1)
    for row in aq["groups"]:
        np.testing.assert_allclose(row["values"], z[np.array(groups) == row["name"]].mean(0), atol=2e-12)
    diff = ap.classic_aquagram(x, w, groups, targets, reference="group:B")
    np.testing.assert_allclose(diff["groups"][1]["values"], 0, atol=1e-15)
    np.testing.assert_allclose(diff["groups"][0]["values"],
                               np.array(aq["groups"][0]["values"]) - aq["groups"][1]["values"], atol=1e-15)
    assert diff["ddof"] == 1 and diff["mode"] == "classic-diff"


def test_dataset_copy_and_unicode_labels_gdmm_provenance_and_getcm_copy():
    x, w, _ = fixture()
    ids = [f"{i:03d}" for i in range(len(x))]
    ids[1] = '先頭, "引用"\n改行'
    groups = ["global"] * 5 + ["対照 群"] * 6 + ["C"] * 7
    x_before, w_before, ids_before = x.copy(), w.copy(), ids.copy()
    dataset = ap.ttap(x, w, ids, groups)
    steps = [{"method": "msc", "reference": x.mean(0)}, {"method": "sgolay", "window": 7}]
    cube = ap.gdmm(dataset, steps=steps, components=5, aquagram_wavelengths=w[[1, 12, 25]], reference="group:global")
    assert cube["provenance"]["rExecuted"] is False
    assert cube["provenance"]["version"] == ap.__version__ == "0.1.0"
    assert cube["provenance"]["sgTs"] == cube["provenance"]["snvDdof"] == 1
    json.dumps(cube, ensure_ascii=False, allow_nan=False)
    extracted = ap.getcm(cube, "pca")
    extracted["scores"][0][0] = 100
    assert cube["pca"]["scores"][0][0] != 100
    x[0, 0] = 999; w[0] = 999; ids[0] = "changed"
    np.testing.assert_array_equal(dataset.matrix, x_before)
    np.testing.assert_array_equal(dataset.wavelengths, w_before)
    assert dataset.ids == tuple(ids_before)
    assert not dataset.matrix.flags.writeable


@pytest.mark.parametrize("steps", [[{"method": "unknown"}], [{"method": "snv", "ddof": 0}],
                                  [{"method": "sgolay", "delta": 5}], [{"method": "sgolay", "window": 8}],
                                  [{"method": "sgolay", "polyorder": 7}], [{"method": "sgolay", "derivative": 3}],
                                  [{"method": "sgolay", "window": True}], None])
def test_unknown_or_invalid_preprocessing_fails_closed(steps):
    x, _, _ = fixture()
    with pytest.raises(ValueError): ap.preprocess(x, steps)


@pytest.mark.parametrize("matrix", [[[1, np.nan, 3], [2, 4, 5]], [[1, np.inf, 3], [2, 4, 5]],
                                   [["1", "2", "3"], ["2", "4", "5"]], [[True, False, True]]])
def test_non_numeric_non_finite_and_boolean_matrices_fail(matrix):
    with pytest.raises(ValueError): ap.preprocess(matrix, [])


def test_degenerate_cases_fail_explicitly():
    with pytest.raises(ValueError, match="SNV"): ap.snv([[.1, .1, .1]])
    with pytest.raises(ValueError, match="MSC"): ap.msc([[1, 1, 1], [2, 2, 2]])
    with pytest.raises(ValueError, match="PCA"): ap.pca(np.full((3, 4), .1), 2)
    with pytest.raises(ValueError, match="Aquagram"): ap.classic_aquagram(np.full((3, 4), .1), [1, 2, 3, 4], ["A"] * 3, [1, 2, 3])


def test_dataset_ids_wavelengths_caps_and_unsupported_models():
    x, w, groups = fixture()
    ids = [str(i) for i in range(len(x))]
    with pytest.raises(ValueError, match="重複"): ap.SpectralData(x, w, ["x"] * len(x), groups)
    with pytest.raises(ValueError, match="波長"): ap.SpectralData(x, w[::-1], ids, groups)
    with pytest.raises(ValueError): ap.preprocess(np.ones((2, 10001)), [])
    with pytest.raises(ValueError): ap.preprocess(np.ones((201, 10000)), [])
    with pytest.raises(ValueError, match="scale"): ap.pca(x, 5, scale=True)
    with pytest.raises(ValueError): ap.classic_aquagram(x, w, groups, w[[1, 2, 3]], reference="none")
    with pytest.raises(ValueError): ap.classic_aquagram(x, w, groups, [1305, 1310, 1314])
    with pytest.raises(ValueError): ap.getcm({}, "pls")
    with pytest.raises(ValueError): ap.gdmm(ap.ttap(x, w), aquagram_wavelengths=w[[1, 2, 3]], pls={"enabled": True})
