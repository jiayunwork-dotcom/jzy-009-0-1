"""领域核算规则测试（不经 HTTP，直接打核心模块）。"""
from __future__ import annotations

import math

import pytest

from app.config import RESIDUAL_TOLERANCE
from app.errors import (
    RegimeNotModeledError,
    RootConvergenceError,
    ValidationError,
)
from app.regimes import Regime, classify
from app.service import compute_friction
from app.turbulence import colebrook_residual, solve_turbulent_friction


# ---------- 层流 ----------

def test_laminar_friction_equals_64_over_re():
    for re in (1.0, 500.0, 1000.0, 2299.999):
        result = compute_friction(re, 0.0)
        assert result.regime == "laminar"
        assert result.friction_factor == pytest.approx(64.0 / re)
        assert result.residual_abs is None  # 闭式解，没有隐式残差


def test_laminar_doubling_re_halves_f():
    f1 = compute_friction(800.0, 0.001).friction_factor
    f2 = compute_friction(1600.0, 0.001).friction_factor
    assert f2 == pytest.approx(f1 / 2.0)


def test_laminar_never_uses_turbulent_equation():
    # 层流公式与粗糙度无关：粗糙度变化不影响 f=64/Re。
    f_smooth = compute_friction(1200.0, 0.0).friction_factor
    f_rough = compute_friction(1200.0, 0.05).friction_factor
    assert f_smooth == pytest.approx(f_rough) == pytest.approx(64.0 / 1200.0)


# ---------- 过渡区 ----------

def test_transition_is_flagged_not_modeled():
    for re in (2300.0, 3000.0, 3999.999):
        with pytest.raises(RegimeNotModeledError) as exc:
            compute_friction(re, 0.0)
        assert exc.value.code == "transition_not_modeled"


def test_regime_boundaries():
    assert classify(2299.999) is Regime.LAMINAR
    assert classify(2300.0) is Regime.TRANSITION
    assert classify(3999.999) is Regime.TRANSITION
    assert classify(4000.0) is Regime.TURBULENT


# ---------- 湍流求根 ----------

@pytest.mark.parametrize(
    "re,eps",
    [
        (4000.0, 0.0),       # 光滑、湍流下界
        (1e5, 0.00015),      # 预置算例量级
        (1e7, 0.0),          # 光滑高 Re
        (5e4, 0.005),        # 粗糙
        (1e8, 1e-6),
        (4000.0, 0.5),       # 近极限粗糙度
    ],
)
def test_turbulent_residual_closure(re, eps):
    f, residual, _ = solve_turbulent_friction(re, eps)
    # 把求得的 f 代回题目钉死的残差定义，必须落在容差内。
    check = abs(colebrook_residual(f, re, eps))
    assert residual <= RESIDUAL_TOLERANCE
    assert check <= RESIDUAL_TOLERANCE
    # 物理范围健全性
    assert 0.0 < f < 1.0


def test_turbulent_log_is_base_10():
    # 以十为底与以 e 为底的结果必须可区分：直接核对一个已知点，
    # Re=1e5, eps=0.00015 时 Moody 图 f≈0.0188（base-10）；
    # 若误用自然对数会得到显著不同的数。
    result = compute_friction(1e5, 0.00015)
    assert result.friction_factor == pytest.approx(0.01876, abs=5e-5)


def test_roughness_increase_raises_turbulent_friction():
    re = 100_000.0
    fs = [compute_friction(re, eps).friction_factor for eps in (0.0, 1e-4, 1e-3, 1e-2)]
    assert fs == sorted(fs)
    assert fs[0] < fs[-1]


def test_smooth_pipe_friction_keeps_decreasing_at_high_re():
    # 光滑管（eps=0）高雷诺数下 f 必须继续随 Re 下降，不能退化成常数。
    res = [1e6, 2e6, 5e6, 1e7, 1e8]
    fs = [compute_friction(re, 0.0).friction_factor for re in res]
    for a, b in zip(fs, fs[1:]):
        assert b < a
    # 且仍然显著满足残差（Prandtl 光滑管规律，不是常数）。
    assert fs[-1] < fs[0] * 0.8


def test_root_non_convergence_is_an_error(monkeypatch):
    # 求根不收敛时必须抛 RootConvergenceError，而不是返回残差很大的数。
    def boom(re, eps):
        raise RootConvergenceError("模拟不收敛", residual=1.23)

    monkeypatch.setattr("app.service.solve_turbulent_friction", boom)
    with pytest.raises(RootConvergenceError):
        compute_friction(1e5, 0.00015)


# ---------- 压降 ----------

def _dp(length, velocity, **over):
    params = dict(length=length, diameter=0.5, velocity=velocity, density=1000.0)
    params.update(over)
    return compute_friction(1e5, 0.00015, **params).pressure_drop_pa


def test_pressure_drop_proportional_to_length():
    base = _dp(100.0, 2.0)
    assert _dp(200.0, 2.0) == pytest.approx(2 * base)


def test_pressure_drop_quadratic_in_velocity():
    base = _dp(100.0, 2.0)
    assert _dp(100.0, 4.0) == pytest.approx(4 * base)


def test_pressure_drop_inverse_in_diameter():
    base = _dp(100.0, 2.0, diameter=0.5)
    assert _dp(100.0, 2.0, diameter=1.0) == pytest.approx(base / 2)


def test_pressure_drop_without_optional_fields_is_none():
    result = compute_friction(1e5, 0.00015)
    assert result.pressure_drop_pa is None


@pytest.mark.parametrize(
    "bad",
    [
        dict(length=0, diameter=0.5, velocity=2, density=1000),
        dict(length=-1, diameter=0.5, velocity=2, density=1000),
        dict(length=100, diameter=0, velocity=2, density=1000),
        dict(length=100, diameter=0.5, velocity=-2, density=1000),
        dict(length=100, diameter=0.5, velocity=2, density=0),
    ],
)
def test_pressure_drop_rejects_non_positive(bad):
    with pytest.raises(ValidationError):
        compute_friction(1e5, 0.00015, **bad)


def test_pressure_drop_partial_fields_rejected():
    with pytest.raises(ValidationError) as exc:
        compute_friction(1e5, 0.00015, length=100, diameter=0.5)
    assert exc.value.code == "incomplete_pressure_inputs"


# ---------- 输入校验 ----------

@pytest.mark.parametrize(
    "re,eps",
    [
        (0.0, 0.0),
        (-1.0, 0.0),
        (1000.0, -0.0001),
        (1000.0, 1.0),
        (1000.0, 5.0),
        (float("nan"), 0.0),
        (float("inf"), 0.0),
        (1000.0, float("nan")),
        ("1000", 0.0),
        (None, 0.0),
        (True, 0.0),
        (1000.0, None),
    ],
)
def test_invalid_core_inputs_rejected(re, eps):
    with pytest.raises(ValidationError):
        compute_friction(re, eps)


def test_forced_turbulent_in_laminar_regime_conflicts():
    with pytest.raises(ValidationError) as exc:
        compute_friction(1000.0, 0.0, regime="turbulent")
    assert exc.value.code == "regime_conflict"


def test_forced_laminar_in_turbulent_regime_conflicts():
    with pytest.raises(ValidationError) as exc:
        compute_friction(10000.0, 0.0, regime="laminar")
    assert exc.value.code == "regime_conflict"


def test_forced_regime_matches_actual_regime_ok():
    assert compute_friction(1000.0, 0.0, regime="laminar").regime == "laminar"
    assert compute_friction(10000.0, 0.0, regime="turbulent").regime == "turbulent"


def test_transition_cannot_be_forced():
    with pytest.raises(ValidationError):
        compute_friction(3000.0, 0.0, regime="transition")
