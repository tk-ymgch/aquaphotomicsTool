"""Independent PLS identities; installed aquap2 evidence is a separate oracle."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
from aquap2py.plsr import plsr, predict_plsr
from aquap2py.preprocessing import preprocess


def fixture(n=18, p=13):
    rng = np.random.default_rng(20261024)
    x = rng.normal(0, .3, (n, p)) + np.arange(p) / p + 2
    y = 3 + 1.7 * x[:, 0] - .8 * x[:, 1] + rng.normal(0, .08, n)
    return x, y


def one_component(x, y, new):
    xc, yc = x - x.mean(0), y - y.mean()
    w = xc.T @ yc
    w /= np.linalg.norm(w)
    t = xc @ w
    b = w * (t @ yc / (t @ t))
    return (new - x.mean(0)) @ b + y.mean(), b


def test_one_component_coefficients_and_all_rows_loo_adjustment_independently():
    x, y = fixture()
    out = plsr(x, y, ncomp=1)
    manual, b = one_component(x, y, x)
    np.testing.assert_allclose(out["coefficients"]["values"], b, atol=1e-13)
    np.testing.assert_allclose(out["predictedCalibration"], manual, atol=1e-13)
    predicted = np.zeros(len(y)); adj = 0
    for i in range(len(y)):
        keep = np.arange(len(y)) != i
        all_rows, _ = one_component(x[keep], y[keep], x)
        predicted[i] = all_rows[i]
        adj += np.sum((all_rows - y) ** 2) / len(y) ** 2
    np.testing.assert_allclose(out["predictedCV"], predicted, atol=1e-13)
    cv = np.mean((predicted - y) ** 2)
    train = np.mean((manual - y) ** 2)
    assert out["metrics"]["rmseCV"] == pytest.approx(np.sqrt(cv))
    assert out["metrics"]["rmseAdjCV"] == pytest.approx(np.sqrt(cv + train - adj))
    assert out["model"]["validation"]["adj"][0] == pytest.approx(adj)


def test_all_components_reconstruct_lstsq_and_centered_affine_prediction():
    # modelPlus needs three extra variables; selected3 uses a rank3 signal plus
    # independent small variables, so the independent comparison is NIPALS.
    sklearn = pytest.importorskip("sklearn.cross_decomposition")
    x, y = fixture(24, 9)
    out = plsr(x, y, ncomp=3)
    ref = sklearn.PLSRegression(n_components=3, scale=False, tol=1e-12, max_iter=1000).fit(x, y)
    np.testing.assert_allclose(out["predictedCalibration"], ref.predict(x).ravel(), atol=2e-12)
    shift = np.arange(x.shape[1]) * 10
    changed = plsr(x + shift, y + 5, ncomp=3)
    np.testing.assert_allclose(changed["predictedCV"], np.array(out["predictedCV"]) + 5, atol=2e-12)
    np.testing.assert_allclose(out["coefficients"]["values"], changed["coefficients"]["values"], atol=2e-12)


def test_group_cv_excludes_entire_unequal_groups_and_matches_direct_replay():
    x, y = fixture()
    groups = ['対照,"A"'] * 5 + ["B\n群"] * 6 + ["global"] * 7
    out = plsr(x, y, ncomp=1, validation="group", cv_groups=groups)
    segs = out["model"]["validation"]["segments"]
    assert list(map(len, segs)) == [5, 6, 7]
    for fold, seg in enumerate(segs, 1):
        train = np.ones(len(y), bool); train[seg] = False
        expected, _ = one_component(x[train], y[train], x[seg])
        np.testing.assert_allclose(np.array(out["predictedCV"])[seg], expected, atol=2e-13)
        assert {out["fold"][s] for s in seg} == {fold}
    replay = plsr(x, y, ncomp=1, validation="group", cv_groups=groups, segments_schedule=[segs])
    assert replay["predictedCV"] == out["predictedCV"]


def test_auto_loo_is_seven_native_adjcv_trials_mode_and_small_data_candidate_branch():
    x, y = fixture(16, 13)
    y = 3 + 2 * x.mean(1) + np.random.default_rng(771).normal(0, .3, 16)
    out = plsr(x, y)
    selection = out["selection"]
    assert selection["iterations"] == 7 and selection["batches"] == 1
    assert len(selection["trials"]) == 7
    assert selection["candidateLimitBeforeCV"] == 13  # not round(16*.25)=4
    assert selection["counts"] == [{"components": out["selectedComponents"], "count": 7}]
    for trial in selection["trials"]:
        assert trial["components"] == int(np.argmin(trial["rmseAdjCV"])) + 1
    assert out["provenance"]["validationScope"] == "native-CV-not-nested-CV"


def test_automatic_candidate_limit_unique_y_branch():
    x, _ = fixture(32, 17)
    y = np.tile(np.arange(4), 8).astype(float)
    out = plsr(x, y, validation="group", cv_groups=[str(i // 8) for i in range(32)])
    assert out["selection"]["candidateLimitBeforeCV"] == 4


def test_predict_roundtrip_all_prefix_coefficients_and_no_implicit_preprocessing():
    x, y = fixture()
    transformed = preprocess(x, [{"method": "snv"}])
    out = plsr(transformed, y, ncomp=2)
    saved = json.loads(json.dumps(out, allow_nan=False))
    for a in range(1, saved["selectedComponents"] + 1):
        np.testing.assert_allclose(predict_plsr(saved, transformed, ncomp=a), np.array(saved["model"]["fitted"])[:, a - 1], atol=2e-13)
    assert not np.allclose(predict_plsr(saved, x), saved["predictedCalibration"])
    np.testing.assert_allclose(np.array(out["residuals"]), y - out["predictedCV"], atol=0)


def test_random_cv_has_explicit_no_r_seed_parity_and_reproducibility():
    x, y = fixture(18, 13)
    samples = [str(i // 2) for i in range(18)]
    out = plsr(x, y, ncomp=1, validation=4, sample_ids=samples, seed=83)
    other = plsr(x, y, ncomp=1, validation=4, sample_ids=samples, seed=83)
    assert out == other
    assert out["provenance"]["rSeedParity"] is False
    assert out["provenance"]["rng"] == "numpy-PCG64" and out["warnings"]
    for sample in set(samples):
        assert len({out["fold"][i] for i, v in enumerate(samples) if v == sample}) == 1


def test_input_copies_json_and_export_convenience_fields():
    x, y = fixture()
    xx, yy = x.copy(), y.copy()
    out = plsr(x, y, ncomp=2)
    np.testing.assert_array_equal(x, xx); np.testing.assert_array_equal(y, yy)
    json.dumps(out, allow_nan=False)
    np.testing.assert_array_equal(out["predictedCV"], np.array(out["model"]["validation"]["pred"])[:, -1])
    assert out["curve"][-1] == out["modelPlus"]["curve"][-1]
    assert len(out["modelPlus"]["curve"]) == 6


@pytest.mark.parametrize("change,match", [
    ({"y": [1.] * 18}, "一定"),
    ({"y": [np.nan] + [1.] * 17}, "欠損"),
    ({"ncomp": 0}, "成分数"),
    ({"ncomp": True}, "成分数"),
    ({"validation": "CV"}, "検証法"),
    ({"validation": True}, "検証法"),
    ({"validation": "group"}, "2群"),
    ({"scale": True}, "未対応"),
    ({"method": "simpls"}, "未対応"),
    ({"outlier_removal": True}, "未対応"),
    ({"seed": -1}, "seed"),
])
def test_bad_inputs_are_explicit(change, match):
    x, y = fixture(); options = {"ncomp": 1, **change}
    y = options.pop("y", y)
    with pytest.raises(ValueError, match=match):
        plsr(x, y, **options)


def test_rank_excess_missing_spectra_and_model_plus_overflow_rejected():
    x, y = fixture()
    with pytest.raises(ValueError, match="ランク"):
        plsr(np.tile(x[:, :1], (1, 13)), y, ncomp=2)
    x[0, 0] = np.nan
    with pytest.raises(ValueError, match="欠損"):
        plsr(x, y, ncomp=1)
    x, y = fixture(6, 8)
    with pytest.raises(ValueError, match="追加成分"):
        plsr(x, y, ncomp=3)


def test_schedule_bad_partitions_incomplete_or_extra_and_split_groups_rejected():
    x, y = fixture()
    loo = [[i] for i in range(18)]
    for bad in [[[[i] for i in range(17)]], [[[0], list(range(1, 17)) + [0]]]]:
        with pytest.raises(ValueError, match="欠落|重複"):
            plsr(x, y, ncomp=1, segments_schedule=bad)
    with pytest.raises(ValueError, match="未使用"):
        plsr(x, y, ncomp=1, segments_schedule=[loo, loo])
    with pytest.raises(ValueError, match="不足"):
        plsr(x, y, segments_schedule=[loo])
    with pytest.raises(ValueError, match="分離|各群"):
        plsr(x, y, ncomp=1, validation="group", cv_groups=[str(i // 6) for i in range(18)], segments_schedule=[loo])


def test_too_small_group_train_noncontiguous_samples_and_bad_saved_model():
    x, y = fixture()
    with pytest.raises(ValueError, match="3試料"):
        plsr(x, y, ncomp=1, validation="group", cv_groups=["A"] * 16 + ["B"] * 2)
    with pytest.raises(ValueError, match="連続"):
        plsr(x, y, ncomp=1, validation=3, sample_ids=[str(i % 3) for i in range(18)])
    out = plsr(x, y, ncomp=1)
    broken = copy.deepcopy(out)
    broken["model"]["coefficients"][0][0] = np.inf
    with pytest.raises(ValueError, match="係数"):
        predict_plsr(broken, x)
    with pytest.raises(ValueError, match="変数数"):
        predict_plsr(out, x[:, :-1])


def test_native_baseline_is_loo_intercept_definition_and_r2_uses_sst():
    x, y = fixture()
    out = plsr(x, y, ncomp=1, validation="group", cv_groups=[str(i // 6) for i in range(18)])
    n = len(y)
    expected_press0 = np.var(y, ddof=1) * n * n / (n - 1)
    assert out["model"]["validation"]["PRESS0"] == pytest.approx(expected_press0)
    assert out["metrics"]["baselineRmseCV"] == pytest.approx(np.sqrt(expected_press0 / n))
    sst = np.sum((y - y.mean()) ** 2)
    assert out["metrics"]["r2CV"] == pytest.approx(1 - np.sum(np.array(out["residuals"]) ** 2) / sst)


def test_constant_target_in_one_training_fold_is_rejected():
    x, _ = fixture()
    y = np.r_[np.zeros(12), np.arange(1., 7.)]
    with pytest.raises(ValueError, match="学習分割.*一定"):
        plsr(x, y, ncomp=1, validation="group", cv_groups=["A"] * 12 + ["B"] * 6)


def test_computation_and_replay_memory_caps_fail_before_heavy_work(monkeypatch):
    import importlib
    module = importlib.import_module("aquap2py.plsr")
    x, y = fixture()
    monkeypatch.setattr(module, "MAX_WORK", 1)
    with pytest.raises(ValueError, match="計算量上限"):
        plsr(x, y, ncomp=1)
    with pytest.raises(ValueError, match="20万"):
        plsr(x, y, ncomp=1, segments_schedule=[[]] * 12000)


def test_partial_scope_and_guard_differences_are_machine_readable():
    x, y = fixture()
    out = plsr(x, y, ncomp=1)
    assert out["provenance"]["completeCompatibility"] is False
    guards = out["provenance"]["guardDifferencesFromR"]
    assert guards["automaticCandidateRankLimit"] is True
    assert guards["missingY"].startswith("reject")
    assert out["provenance"]["preprocessingScope"] == "all-X-before-CV; input-already-processed"
