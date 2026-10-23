"""Temperature subset contracts; actual public-R oracle lives in compare_temperature.py."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
from aquap2py.temperature import temperature_aquagram, temperature_calibration, _polygon_area
from aquap2py.loess import robust_quadratic_loess


@pytest.fixture(scope="module")
def fixture():
    w = np.arange(1300., 1601.)
    g = lambda center, width: np.exp(-.5 * ((w - center) / width) ** 2)
    def spectrum(t, extra=0):
        z = t - 30
        return .06 + .00002 * (w - 1300) + (.35 + .003*z + .00012*z*z)*g(1445,65) + (.13-.0021*z+.00005*z**3)*g(1370,20) + (.09+.0014*z)*g(1510,24) + (.03+.0007*z*z)*g(1410,12) + extra*g(1475,15)
    temp = np.repeat(np.arange(28., 33.), 2)
    cal = np.array([spectrum(t, i % 2 * .0001) for i, t in enumerate(temp)])
    x = np.array([spectrum(29.5 + i/10, i*.0001) for i in range(8)])
    groups = ["global"]*3 + ['対照, "群"']*5
    return x, w, groups, cal, temp


def test_calibration_json_and_replication(fixture):
    _, w, _, cal, temp = fixture
    original = cal.copy()
    model = temperature_calibration(cal, w, temp)
    assert model["counts"] == [2]*5
    assert np.asarray(model["universalAuc"]).shape == (5,12)
    assert model["provenance"]["order"] == ["SG-full-spectrum", "cut-1300-1600", "mean-per-temperature", "polygon-AUC-ratio"]
    json.dumps(model, allow_nan=False)
    np.testing.assert_array_equal(cal, original)
    for i, t in enumerate(model["temperatures"]):
        np.testing.assert_allclose(model["rawTemperatureMeans"][i], cal[temp == t].mean(0))


def test_polygon_unsigned_translation_invariance():
    x, y = np.array([0.,2.,2.,0.]), np.array([0.,0.,3.,3.])
    assert _polygon_area(x,y) == 6
    assert _polygon_area(x[::-1], y[::-1]) == 6
    assert _polygon_area(x+5, y-8) == 6


@pytest.mark.parametrize("base", ["sfc", "aucs", "aucs.tn", "aucs.tn.dce", "aucs.dce"])
def test_diff_is_control_subtraction(fixture, base):
    x,w,groups,cal,temp = fixture
    model = temperature_calibration(cal,w,temp)
    kwargs = dict(t_calib=[28,32], t_exp=30, smooth_n=3)
    plain = temperature_aquagram(x,w,groups,model,mode=base,**kwargs)
    diff = temperature_aquagram(x,w,groups,model,mode=base+"-diff",reference="global",**kwargs)
    actual = np.array([v["values"] for v in diff["groups"]])
    values = np.array([v["values"] for v in plain["groups"]])
    np.testing.assert_allclose(actual, values-values[0], atol=1e-12)
    assert diff["groups"][0]["n"] == 3 and diff["groups"][1]["n"] == 5
    assert diff["provenance"]["currentRunComparedWithR"] is False
    json.dumps(diff, ensure_ascii=False, allow_nan=False)


def test_dce_and_tn_algebra_units_and_endpoint_only(fixture):
    x,w,groups,cal,temp = fixture
    model = temperature_calibration(cal,w,temp)
    call = lambda mode: temperature_aquagram(x,w,groups,model,mode=mode,t_calib=[28,32],t_exp=30,smooth_n=3)
    array = lambda result: np.array([g["values"] for g in result["groups"]])
    auc,tn,dce,tndce = [call(mode) for mode in ("aucs","aucs.tn","aucs.dce","aucs.tn.dce")]
    np.testing.assert_allclose(array(dce),array(auc)*.04+28)
    np.testing.assert_allclose(array(tndce),array(tn)*.04)
    np.testing.assert_allclose(array(tn),array(auc)-np.asarray(auc["provenance"]["temperatureBaselinePercent"]))
    endpoints = np.asarray(model["universalAuc"])[[0,-1]]
    np.testing.assert_allclose(auc["provenance"]["calibrationMinima"], endpoints.min(0))
    assert auc["unit"] == "percent" and tn["unit"] == "percentage-point"
    assert dce["unit"] == "degC-equivalent"
    assert auc["coordinateRanges"][0] == [1336,1348] and auc["wavelengths"][0] == 1342


def test_sfc_uses_measurement_rms_about_unsmoothed_foreign_center(fixture):
    x,w,groups,cal,temp = fixture
    model = temperature_calibration(cal,w,temp)
    targets = [1342,1426,1476]
    result = temperature_aquagram(x,w,groups,model,mode="sfc",t_calib=[28,32],t_exp=30,targets=targets,smooth_n=3)
    indices = [int(np.flatnonzero(w==t)[0]) for t in targets]
    center = cal.mean(0)[indices]
    centered = x[:,indices]-center
    denominator = np.sqrt((centered**2).sum(0)/(len(x)-1))
    expected = np.array([(centered/denominator)[:3].mean(0), (centered/denominator)[3:].mean(0)])
    np.testing.assert_allclose([g["values"] for g in result["groups"]], expected, atol=1e-10)
    assert not np.allclose(denominator, cal[:,indices].std(0,ddof=1))


def test_fifteen_bands_and_midpoint_axis(fixture):
    x,w,groups,cal,temp = fixture
    model = temperature_calibration(cal,w,temp,coordinate_system="ot1.15")
    result = temperature_aquagram(x,w,groups,model,t_calib=[28,32],t_exp=30,smooth_n=3)
    assert len(result["groups"][0]["values"]) == 15
    assert result["labels"][4:8] == ["C05a","C05b","C05c","C05d"]
    assert result["provenance"]["wavelengthAxis"].startswith("band-midpoints")


@pytest.mark.parametrize("kwargs", [{"t_exp":30.1},{"t_calib":[28.1,32]}, {"t_calib":"symm@1.2"}])
def test_unobserved_temperatures_refused_for_sparse_calibration(fixture,kwargs):
    x,w,groups,cal,temp = fixture
    model=temperature_calibration(cal,w,temp)
    with pytest.raises(ValueError,match="LOESS"):
        temperature_aquagram(x,w,groups,model,**{"t_calib":[28,32],"t_exp":30,**kwargs})


def test_loess_matches_installed_r_default_interpolated_symmetric_profile():
    # Golden predictions generated by unmodified R 4.6.1 stats::loess with the
    # exact synthetic data below. A direct local-polynomial smoother differs.
    x = np.arange(20., 41.)
    y = np.sin((x-20)/4) + .03*(x-30)**2
    y[8] += .7
    queries = [20.,20.01,22.25,28.,28.25,30.5,39.99,40.]
    expected = [2.9652425880805,2.9624641887643,2.36268910285376,
                1.01644217215659,.962732006216518,.49864707252621,
                1.9343850447399,1.94002120562187]
    original = y.copy()
    np.testing.assert_allclose(robust_quadratic_loess(x,y,queries),expected,rtol=0,atol=2e-13)
    np.testing.assert_array_equal(y,original)


@pytest.fixture(scope="module")
def dense_temperature_fixture(fixture):
    x,w,groups,_,_ = fixture
    temp = np.repeat(np.arange(20.,41.),3)
    gauss = lambda c,s: np.exp(-.5*((w-c)/s)**2)
    cal = np.array([.06+.00002*(w-1300)+(.35+.003*(t-30)+.00012*(t-30)**2)*gauss(1445,65)
                    +(.13-.0021*(t-30)+.00005*(t-30)**3)*gauss(1370,20)
                    +(.09+.0014*(t-30))*gauss(1510,24)+(.03+.0007*(t-30)**2)*gauss(1410,12)
                    +(i%3)*.00001*np.sin(w/21) for i,t in enumerate(temp)])
    return x,w,groups,temperature_calibration(cal,w,temp)


@pytest.mark.parametrize("mode", ["aucs","aucs-diff","aucs.tn","aucs.tn-diff",
    "aucs.dce","aucs.dce-diff","aucs.tn.dce","aucs.tn.dce-diff"])
def test_unobserved_temperatures_json_roundtrip_and_provenance(dense_temperature_fixture,mode):
    x,w,groups,model = dense_temperature_fixture
    result = temperature_aquagram(x,w,groups,json.loads(json.dumps(model)),mode=mode,
        t_calib=[28.25,32.75],t_exp=30.25,reference=groups[0] if mode.endswith("-diff") else None)
    assert result["provenance"]["endpointLoessUsed"] is True
    assert result["provenance"]["experimentLoessUsed"] is True
    assert result["provenance"]["observedTemperaturesOnly"] is False
    assert result["provenance"]["currentRunComparedWithR"] is False
    if mode.endswith("-diff"):
        np.testing.assert_allclose(result["groups"][0]["values"],0,atol=0)
    json.dumps(result,allow_nan=False)


def test_mixed_endpoint_predicts_both_but_observed_texp_uses_exact_row(dense_temperature_fixture):
    x,w,groups,model = dense_temperature_fixture
    result = temperature_aquagram(x,w,groups,model,mode="aucs.tn",t_calib=[28,32.25],t_exp=30)
    provenance = result["provenance"]
    assert provenance["endpointLoessUsed"] is True
    assert provenance["bothEndpointsPredictedWhenEitherIsUnobserved"] is True
    assert provenance["experimentLoessUsed"] is False
    # The observed endpoint is smoothed in this mixed branch, not taken from
    # its tabulated value. The baseline remains the unmodified observed row.
    table = np.asarray(model["universalAuc"])
    temperatures = np.asarray(model["temperatures"])
    predictions = np.array([robust_quadratic_loess(temperatures,y,[28,32.25]) for y in table.T]).T
    np.testing.assert_allclose(provenance["calibrationMinima"],predictions.min(0))
    lo,hi = predictions.min(0),predictions.max(0)
    expected = (table[temperatures==30][0]-lo)*100/(hi-lo)
    np.testing.assert_allclose(provenance["temperatureBaselinePercent"],expected)


def test_sfc_foreign_center_unchanged_by_unobserved_texp(dense_temperature_fixture):
    x,w,groups,model = dense_temperature_fixture
    observed = temperature_aquagram(x,w,groups,model,mode="sfc",t_calib=[28,32],t_exp=30)
    unobserved = temperature_aquagram(x,w,groups,model,mode="sfc",t_calib=[28,32],t_exp=30.25)
    assert unobserved["groups"] == observed["groups"]
    assert unobserved["provenance"]["experimentLoessUsed"] is True


@pytest.mark.parametrize("kwargs", [{"t_exp":19.99},{"t_exp":40.01},{"t_calib":[19.99,32]}])
def test_loess_extrapolation_explicitly_refused(dense_temperature_fixture,kwargs):
    x,w,groups,model = dense_temperature_fixture
    with pytest.raises(ValueError,match="温度範囲外"):
        temperature_aquagram(x,w,groups,model,**{"t_calib":[28,32],"t_exp":30,**kwargs})


def test_loess_sparse_singular_and_invalid_input_guards():
    with pytest.raises(ValueError,match="8〜"):
        robust_quadratic_loess(np.arange(7.),np.arange(7.)**2,[3.5])
    with pytest.raises(ValueError,match="昇順"):
        robust_quadratic_loess([0,1,2,3,4,5,6,6],np.arange(8.),[3.5])
    with pytest.raises(ValueError,match="範囲外"):
        robust_quadratic_loess(np.arange(8.),np.arange(8.)**2,[-.01])


@pytest.mark.parametrize("kwargs, message", [({"boot_ci":True},"未実装"),({"nr_corr":True},"未実装"),
    ({"mode":"aucs-diff","reference":"absent"},"対照群"),({"mode":"aucs","reference":"global"},"非diff"),
    ({"targets":[1342,1426,1476]},"固定帯"),({"t_calib":[27,32]},"温度範囲外")])
def test_unsupported_conditions_are_explicit(fixture,kwargs,message):
    x,w,groups,cal,temp=fixture
    model=temperature_calibration(cal,w,temp)
    with pytest.raises(ValueError,match=message):
        temperature_aquagram(x,w,groups,model,**{"t_calib":[28,32],"t_exp":30,**kwargs})


def test_calibration_degeneracy_and_corrupt_model(fixture):
    x,w,groups,cal,temp=fixture
    with pytest.raises(ValueError,match="面積"):
        temperature_calibration(np.tile(w,(len(temp),1)),w,temp)
    model=temperature_calibration(cal,w,temp)
    bad=copy.deepcopy(model); bad["universalAuc"][-1]=bad["universalAuc"][0]
    with pytest.raises(ValueError,match="両端"):
        temperature_aquagram(x,w,groups,bad,t_calib=[28,32],t_exp=30)
    with pytest.raises(ValueError,match="完全一致"):
        temperature_aquagram(x[:,1:],w[1:],groups,model,mode="sfc",t_calib=[28,32],t_exp=30)
