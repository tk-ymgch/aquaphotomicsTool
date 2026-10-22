"""Artificial numerical contracts for the extended spectral preprocessing API."""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
from aquap2py.preprocessing import detrend, emsc, gap_derivative, preprocess, preprocess_spectra, resample_nir


def fixture():
    waves = np.arange(1300.0, 1342.0, 2.0)
    z = (waves - waves.mean()) / 20
    x = np.array([.3 + .2 * np.exp(-z*z) + .01 * i * np.sin(3*z) + .003 * i * z for i in range(5)])
    return x, waves


def test_detrend_removes_known_lines_and_records_physical_coefficients():
    waves = np.array([1300., 1302., 1307., 1310., 1320.])
    intercepts = np.array([.2, -.3, .7])
    slopes = np.array([.001, -.002, .003])
    x = intercepts[:, None] + slopes[:, None] * waves
    result = detrend(x, waves)
    np.testing.assert_allclose(result["matrix"], 0, atol=2e-14)
    np.testing.assert_allclose(result["model"]["coefficients"], np.column_stack([intercepts, slopes]), atol=2e-13)
    np.testing.assert_array_equal(result["wavelengths"], waves)
    assert result["model"]["aquap2ExportModel"] is None


def test_detrend_partial_target_leaves_other_cells_bitwise_unchanged():
    x, waves = fixture()
    result = detrend(x, waves, src=[1301, 1329], trg=[1311, 1339])
    source = np.flatnonzero((waves >= 1301) & (waves <= 1329))
    target = np.flatnonzero((waves >= 1311) & (waves <= 1339))
    outside = np.setdiff1d(np.arange(len(waves)), target)
    np.testing.assert_array_equal(result["matrix"][:, outside], x[:, outside])
    design = np.column_stack([np.ones(len(source)), waves[source]])
    coef = np.linalg.lstsq(design, x[:, source].T, rcond=None)[0]
    np.testing.assert_allclose(result["matrix"][:, target], x[:, target] - coef[0, :, None] - coef[1, :, None] * waves[target], atol=1e-13)
    assert result["model"]["sourceIndices"] == source.tolist()
    assert result["model"]["targetIndices"] == target.tolist()
    assert np.any(result["matrix"][:, target] != x[:, target])


def test_detrend_src_default_vs_all_and_null_target():
    x, waves = fixture()
    partial = detrend(x, waves, src=[1310, 1330])
    assert partial["model"]["targetIndices"] == partial["model"]["sourceIndices"]
    full = detrend(x, waves, src=[1310, 1330], trg="all")
    null = detrend(x, waves, src=[1310, 1330], trg=None)
    np.testing.assert_array_equal(partial["matrix"], null["matrix"])
    assert len(full["model"]["targetIndices"]) == len(waves)


@pytest.mark.parametrize("options", [
    {"src": [1299, 1320]}, {"src": [1320, 1310]}, {"src": [1300.1, 1301.9]},
    {"src": [1300, 1300.5]}, {"src": [1300, float("nan")]}, {"trg": "unknown"},
    {"trg": [1300.1, 1301.9]}, {"trg": [1300, 1300.5]}, {"src": ["1300", "1320"]},
])
def test_detrend_invalid_ranges_are_explicitly_rejected(options):
    x, waves = fixture()
    with pytest.raises(ValueError):
        detrend(x, waves, **options)


@pytest.mark.parametrize("effects_count", [1, 2])
def test_emsc_recovers_reference_and_known_nuisance_coefficients(effects_count):
    z = np.linspace(-1, 1, 31)
    base = .4 + .2 * np.exp(-z*z)
    effects = np.column_stack([np.sin(z * 3), np.cos(z * 4) - z])[:, :effects_count]
    intercepts = np.array([-.2, -.1, .1, .2])
    scales = np.array([.8, .9, 1.1, 1.2])
    beta = np.column_stack([[-.3, -.2, .2, .3], [.1, -.2, -.1, .2]])[:, :effects_count]
    x = intercepts[:, None] + scales[:, None] * base + beta @ effects.T
    result = emsc(x, effects)
    np.testing.assert_allclose(result["matrix"], np.broadcast_to(base, x.shape), atol=2e-14)
    np.testing.assert_allclose(result["model"]["reference"], base, atol=1e-15)
    np.testing.assert_allclose(result["model"]["coefficients"], np.column_stack([intercepts, scales, beta]), atol=2e-14)
    assert result["wavelengths"] is None
    assert result["model"]["aquap2ExportModel"] is None
    json.dumps(result["model"], allow_nan=False)


@pytest.mark.parametrize("bad", ["too_many", "wrong_length", "nan", "constant", "collinear"])
def test_emsc_invalid_or_singular_effects_are_refused(bad):
    x, _ = fixture()
    z = np.linspace(-1, 1, x.shape[1])
    effects = {"too_many": np.column_stack([z, z*z, z*z*z]), "wrong_length": z[:-1],
               "nan": np.where(z == 0, np.nan, z), "constant": np.ones(len(z)),
               "collinear": np.column_stack([z, z])}[bad]
    with pytest.raises(ValueError):
        emsc(x, effects)


@pytest.mark.parametrize("order", [1, 2, 3, 4])
def test_gap_derivative_polynomial_units_filter_and_shortened_wavelengths(order):
    z = np.arange(-20., 21.)
    waves = 1400 + 2 * z
    x = np.array([z ** order, 2 * z ** order + 3])
    result = gap_derivative(x, waves, m=order, w=3, s=3, delta_w=2)
    half = (order * 3 + (order + 1) * 3 - 1) // 2
    expected = np.repeat(np.array([1., 2.])[:, None] * math.factorial(order) / 2 ** order,
                         len(waves) - 2 * half, axis=1)
    np.testing.assert_allclose(result["matrix"], expected, atol=5e-11, rtol=1e-10)
    np.testing.assert_array_equal(result["wavelengths"], waves[half:-half])
    assert result["model"]["removedPerSide"] == half
    assert result["model"]["boundaryPolicy"] == "valid-only-no-endpoint-duplication"


@pytest.mark.parametrize("options", [{"m": 0}, {"m": 5}, {"m": True}, {"w": 2}, {"s": 2},
                                       {"w": 501}, {"delta_w": 0}, {"delta_w": -1}, {"delta_w": float("inf")},
                                       {"m": 4, "delta_w": 1e308}, {"m": 4, "delta_w": 1e-308}])
def test_gap_derivative_invalid_widths_orders_and_spacing_fail(options):
    x, waves = fixture()
    with pytest.raises(ValueError):
        gap_derivative(x, waves, **options)


def test_resample_constant_and_nearest_have_r_tie_and_endpoint_policy():
    waves = [1300., 1310., 1330.]
    x = [[1., 2., 5.], [2., 4., 10.]]
    targets = [1300., 1305., 1310., 1320., 1330.]
    constant = resample_nir(x, waves, target_wavelengths=targets, method="constant")
    nearest = resample_nir(x, waves, target_wavelengths=targets, method="nearest")
    np.testing.assert_array_equal(constant["matrix"][0], [1, 1, 2, 2, 5])
    np.testing.assert_array_equal(nearest["matrix"][0], [1, 2, 2, 5, 5])


def test_resample_spline_reconstructs_cubic_and_pchip_preserves_monotonicity():
    z = np.array([0., 1., 3., 5., 6.])
    targets = np.arange(0, 6.1, .2)
    result = resample_nir([z ** 3, 2 * z ** 3 + 1], 1300 + z,
                          target_wavelengths=1300 + targets, method="spline")
    np.testing.assert_allclose(result["matrix"], [targets ** 3, 2 * targets ** 3 + 1], atol=2e-12)
    cubic = resample_nir([np.log1p(z)], 1300 + z, target_wavelengths=1300 + targets)
    assert np.all(np.diff(cubic["matrix"][0]) >= 0)
    assert cubic["matrix"][0, 0] == 0
    np.testing.assert_allclose(cubic["matrix"][0, -1], np.log(7))


def test_resample_default_grid_rounds_endpoints_to_even_nm_before_tby():
    x = [[1., 2., 3.], [2., 3., 4.]]
    result = resample_nir(x, [1300.25, 1305.25, 1310.25])
    np.testing.assert_array_equal(result["wavelengths"], np.arange(1302., 1310.1, .5))
    assert result["model"]["defaultGrid"]


@pytest.mark.parametrize("options", [
    {"target_wavelengths": [1299., 1310.]}, {"target_wavelengths": [1310., 1300.]},
    {"target_wavelengths": [1300., 1300.]}, {"target_wavelengths": [1300., float("nan")]},
    {"target_wavelengths": [1300.]}, {"tby": 0}, {"tby": 1e-300},
    {"method": "unknown"}, {"method": ["linear"]},
])
def test_resample_refuses_extrapolation_invalid_grids_and_unbounded_size(options):
    x, waves = fixture()
    with pytest.raises(ValueError):
        resample_nir(x, waves, **options)


def test_resample_refuses_three_point_spline_and_short_dimension_overflow():
    with pytest.raises(ValueError, match="4"):
        resample_nir([[1, 2, 3]], [1300, 1310, 1320], method="spline")
    with pytest.raises(ValueError):
        resample_nir(np.ones((1001, 3)), [1300, 1310, 1320], target_wavelengths=np.linspace(1300, 1320, 1001))


@pytest.mark.parametrize("bad_waves", [[1300]*21, list(range(21))[::-1], [float("nan")]*21, [True]*21])
def test_all_wavelength_aware_apis_validate_coordinates(bad_waves):
    x, _ = fixture()
    for function in [detrend, gap_derivative, resample_nir, lambda matrix, w: preprocess_spectra(matrix, w, [])]:
        with pytest.raises(ValueError):
            function(x, bad_waves)


def test_sequence_tracks_grid_order_and_diagnostic_models_without_mutation():
    x, waves = fixture()
    steps = [{"method": "resample", "tby": 1.0, "interpolation": "linear"},
             {"method": "gap_derivative", "m": 1}, {"method": "detrend"}, {"method": "snv"}]
    saved_x, saved_waves, saved_steps = x.copy(), waves.copy(), copy.deepcopy(steps)
    actual = preprocess_spectra(x, waves, steps)
    first = resample_nir(x, waves, tby=1.0, method="linear")
    second = gap_derivative(first["matrix"], first["wavelengths"])
    third = detrend(second["matrix"], second["wavelengths"])
    expected = preprocess(third["matrix"], [{"method": "snv"}])
    np.testing.assert_allclose(actual["matrix"], expected)
    np.testing.assert_array_equal(actual["wavelengths"], third["wavelengths"])
    assert [m["method"] for m in actual["models"]] == [step["method"] for step in steps]
    json.dumps(actual["models"], allow_nan=False)
    np.testing.assert_array_equal(x, saved_x)
    np.testing.assert_array_equal(waves, saved_waves)
    assert steps == saved_steps
    assert isinstance(preprocess(x, [{"method": "snv"}]), np.ndarray)


@pytest.mark.parametrize("steps", [[{"method": "resample", "secret": "unexpected"}],
                                    [{"method": "detrend", "degree": 2}], [{"method": "emsc"}],
                                    [{"method": "unknown"}], [{"method": "snv", "secret": "unexpected"}]])
def test_sequence_rejects_unknown_or_missing_options(steps):
    x, waves = fixture()
    with pytest.raises(ValueError):
        preprocess_spectra(x, waves, steps)
