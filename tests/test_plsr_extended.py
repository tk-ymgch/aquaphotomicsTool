"""Tukey-hinge identities and one-pass native PLSR filtering (not nested CV)."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
from aquap2py.plsr import plsr, plsr_outlier_indices, predict_plsr


def fixture():
    rng = np.random.default_rng(20261027)
    y = np.repeat(np.arange(1., 7.), 10)
    axis = np.linspace(-1, 1, 17)
    x = 2 + .3 * axis[None, :] + .08 * y[:, None] * axis[None, :]
    x += rng.normal(0, .009, x.shape)
    x[3] += .5 * axis
    groups = [str(i % 5) for i in range(len(y))]
    return x, y, groups


def stub(observed, predictions):
    return {"observed": observed, "model": {"ncomp": 1, "validation": {"pred": [[value] for value in predictions]}}}


def test_hinges_match_order_statistic_definition_not_numpy_interpolated_quartiles():
    result = plsr_outlier_indices(stub([1.] * 6, [0., 1., 2., 3., 4., 9.]))
    group = result["groupsByObservedY"][0]
    assert group["lowerHinge"] == 1 and group["upperHinge"] == 4
    assert group["lowerHinge"] != np.quantile([0., 1., 2., 3., 4., 9.], .25)
    assert group["lowerFence"] == -.5 and group["upperFence"] == 5.5
    assert result["excludedIndices"] == [5]
    assert result["outInd"] == [True, True, True, True, True, False]


def test_grouping_is_equal_numeric_y_not_prediction_order_and_unique_y_has_no_outliers():
    model = stub([2., 1., 2., 1., 2., 1., 2., 1., 2., 1.], [10., 0., 11., 1., 12., 2., 13., 3., 50., 4.])
    before = copy.deepcopy(model)
    result = plsr_outlier_indices(model)
    assert result["excludedIndices"] == [8]
    assert result["keepMask"] == result["outInd"]
    assert model == before
    assert not any(plsr_outlier_indices(stub(list(range(5)), [1e9, -1e9, 0, 4, 2]))["excludedMask"])


def test_zero_range_disables_exclusion_and_fences_use_strict_inequalities():
    result = plsr_outlier_indices(stub([1.] * 6, [0, 1, 2, 3, 4, 100]), detection_range=0)
    assert result["excludedIndices"] == []
    boundary = plsr_outlier_indices(stub([1.] * 6, [-.5, 1, 2, 3, 4, 5.5]))
    assert boundary["excludedIndices"] == []


@pytest.mark.parametrize("validation", ["LOO", "group"])
def test_one_pass_filter_then_refit_matches_manual_native_fit_and_original_rows(validation):
    x, y, groups = fixture()
    xx, yy = x.copy(), y.copy()
    options = {"ncomp": 2, "validation": validation, "cv_groups": groups if validation == "group" else None}
    initial = plsr(x, y, **options)
    rule = plsr_outlier_indices(initial)
    retained = rule["retainedIndices"]
    assert 3 in rule["excludedIndices"] and 4 <= len(retained) < len(y)
    result = plsr(x, y, exclude_outliers=True, **options)
    manual_options = {**options, "cv_groups": [groups[i] for i in retained] if validation == "group" else None}
    if validation == "group":
        levels = list(dict.fromkeys(groups))
        manual_options["segments_schedule"] = [[[j for j, original in enumerate(retained) if groups[original] == level] for level in levels]]
    manual = plsr(x[retained], y[retained], **manual_options)
    for key in ["coefficients", "model", "modelPlus", "predictedCV", "observed"]:
        assert result[key] == manual[key]
    assert result["outlierFiltering"]["retainedIndices"] == retained
    assert result["outlierFiltering"]["passes"] == 1
    assert result["outlierFiltering"]["preprocessingRefitted"] is False
    assert result["provenance"]["outlierRemoval"] is True
    assert result["provenance"]["completeCompatibility"] is False
    np.testing.assert_array_equal(x, xx); np.testing.assert_array_equal(y, yy)
    np.testing.assert_allclose(predict_plsr(result, x[retained]), result["predictedCalibration"], atol=1e-12)
    json.dumps(result, allow_nan=False)


def test_no_excluded_rows_still_performs_one_native_refit():
    x, y, _ = fixture()
    y = y + np.arange(len(y)) * .00001
    result = plsr(x, y, ncomp=2, exclude_outliers=True)
    assert result["outlierFiltering"]["excludedIndices"] == []
    assert result["outlierFiltering"]["refitted"] is True
    assert result["outlierFiltering"]["retainedIndices"] == list(range(len(y)))


@pytest.mark.parametrize("change", [{"detection_range": -1}, {"detection_range": True}, {"detection_range": np.inf}, {"detection_range": "0.5"}])
def test_invalid_boxplot_ranges_rejected(change):
    with pytest.raises(ValueError, match="range"):
        plsr_outlier_indices(stub([1, 1], [1, 2]), **change)


def test_random_cv_replay_unknown_alias_and_broken_predictions_are_explicitly_rejected():
    x, y, _ = fixture()
    for options in [{"validation": 5}, {"segments_schedule": [[[i] for i in range(len(y))]]}]:
        with pytest.raises(ValueError, match="LOO・群CV"):
            plsr(x, y, ncomp=2, exclude_outliers=True, **options)
    with pytest.raises(ValueError, match="true/false"):
        plsr(x, y, ncomp=2, exclude_outliers="true")
    with pytest.raises(ValueError, match="未対応"):
        plsr(x, y, ncomp=2, outlier_removal=True)
    for broken in [{}, {"model": {"ncomp": 1}, "observed": [1]}, stub([1, 2], [1, np.nan]), stub([1], [1, 2])]:
        with pytest.raises(ValueError):
            plsr_outlier_indices(broken)
