"""核心核算规则测试（不经 HTTP，直接打领域层）。"""
from __future__ import annotations

import math

import pytest

from app.core import config
from app.core.errors import (
    NonConvergenceError,
    RegimeConflictError,
    TransitionNotModeledError,
    ValidationError,
)
from app.core.friction import (
    calculate_friction,
    colebrook_residual,
    laminar_friction,
    solve_turbulent,
)
from app.core.pressure import pressure_drop
from app.core.regime import Regime, classify_reynolds
from app.core.validation import (
    collect_pressure_inputs,
    validate_relative_roughness,
    validate_reynolds,
)


# ---------- 区制判定 ----------

@pytest.mark.parametrize(
    "re,expected",
    [
        (1.0, Regime.LAMINAR),
        (2299.99, Regime.LAMINAR),
        (2300.0, Regime.TRANSITION),
        (3000.0, Regime.TRANSITION),
        (3999.99, Regime.TRANSITION),
        (4000.0, Regime.TURBULENT),
        (1.0e8, Regime.TURBULENT),
    ],
)
def test_regime_boundaries(re, expected):
    assert classify_reynolds(re) is expected


# ---------- 层流 ----------

def test_laminar_closed_form():
    assert laminar_friction(1000.0) == pytest.approx(0.064)
    assert laminar_friction(64.0) == pytest.approx(1.0)
    regime, f, residual, iters = calculate_friction(1500.0, 0.001)
    assert regime is Regime.LAMINAR
    assert f == pytest.approx(64.0 / 1500.0)
    # 层流绝不套用湍流隐式方程
    assert residual is None and iters is None


def test_laminar_halves_when_reynolds_doubles():
    re_values = [100.0, 500.0, 1000.0, 2299.0]
    for re in re_values:
        f1 = calculate_friction(re, 0.0)[1]
        f2 = calculate_friction(2 * re, 0.0 if 2 * re < 2300 else 0.0)[1]
        if 2 * re < config.RE_LAMINAR_MAX:
            assert f2 == pytest.approx(f1 / 2.0)


# ---------- 过渡区 ----------

def test_transition_not_modeled():
    for re in (2300.0, 3000.0, 3999.5):
        regime, f, residual, iters = calculate_friction(re, 0.0)
        assert regime is Regime.TRANSITION
        assert f is None and residual is None and iters is None


# ---------- 湍流残差闭合 ----------

@pytest.mark.parametrize("re", [4000.0, 1.0e4, 1.0e5, 1.0e6, 1.0e8])
@pytest.mark.parametrize("rr", [0.0, 1.0e-5, 4.5e-5, 1.0e-3, 0.5])
def test_turbulent_residual_closure(re, rr):
    regime, f, residual, iters = calculate_friction(re, rr)
    assert regime is Regime.TURBULENT
    assert f is not None and 0.0 < f < 1.0
    # 把 f 代回需求定义的残差，必须落在钉死容差内
    assert abs(colebrook_residual(f, re, rr)) <= config.TOLERANCE
    assert abs(residual) <= config.TOLERANCE
    assert 1 <= iters <= config.MAX_ITERATIONS


def test_preset_example_commercial_steel():
    """预置算例：商用钢管量级粗糙度 + Re=1e5，f 落在 0.018 量级。"""
    regime, f, residual, _ = calculate_friction(
        config.EXAMPLE_REYNOLDS, config.EXAMPLE_RELATIVE_ROUGHNESS
    )
    assert regime is Regime.TURBULENT
    assert 0.017 <= f <= 0.019
    assert abs(residual) <= config.TOLERANCE


def test_higher_roughness_higher_friction():
    """只加大相对粗糙度，同一湍流 Re 下 f 必须升高（严格）。"""
    re = 1.0e5
    roughs = [0.0, 1.0e-5, 1.0e-4, 5.0e-4, 1.0e-3, 1.0e-2]
    frictions = [calculate_friction(re, rr)[1] for rr in roughs]
    for f_lo, f_hi in zip(frictions, frictions[1:]):
        assert f_hi > f_lo


def test_smooth_pipe_friction_decreases_at_high_reynolds():
    """光滑管高 Re 下 f 仍随 Re 升高而下降，不得退化为常数。"""
    re_list = [1.0e5, 1.0e6, 1.0e7, 1.0e8, 1.0e9]
    fs = [calculate_friction(re, 0.0)[1] for re in re_list]
    for f_lo, f_hi in zip(fs, fs[1:]):
        assert f_hi < f_lo
    # 与 Prandtl 光滑律量级一致（1e8 时 f 远小于 1e5 时）
    assert fs[-1] < 0.6 * fs[0]


def test_log_base_is_ten():
    """残差必须以 10 为底：f 满足 log10 残差~0，但同值 ln 残差不为 0。"""
    f, _, _ = solve_turbulent(1.0e5, 4.5e-5)
    x = 1.0 / math.sqrt(f)
    inside = 4.5e-5 / 3.7 + 2.51 * x / 1.0e5
    assert abs(x + 2.0 * math.log10(inside)) <= config.TOLERANCE
    # 若误用自然对数，残差会很大
    assert abs(x + 2.0 * math.log(inside)) > 1.0e-3


def test_nonconvergence_raises():
    """迭代次数被钉死到不可能收敛时，应抛不收敛错误而不是返回残差很大的数。"""
    with pytest.raises(NonConvergenceError):
        solve_turbulent(1.0e5, 4.5e-5, tolerance=1.0e-8, max_iterations=1)


# ---------- 压降 ----------

def _dp(f, L, D, V, rho):
    return pressure_drop(f, pipe_length=L, diameter=D, velocity=V, density=rho)


def test_pressure_drop_proportionality():
    f, L, D, V, rho = 0.02, 100.0, 0.5, 2.0, 1000.0
    base = _dp(f, L, D, V, rho)
    assert base == pytest.approx(f * (L / D) * 0.5 * rho * V * V)
    # 管长加倍 -> 压降加倍
    assert _dp(f, 2 * L, D, V, rho) == pytest.approx(2 * base)
    # 流速加倍 -> 压降四倍
    assert _dp(f, L, D, 2 * V, rho) == pytest.approx(4 * base)
    # 摩阻系数加倍 -> 压降加倍
    assert _dp(2 * f, L, D, V, rho) == pytest.approx(2 * base)
    # 内径加倍 -> 压降减半
    assert _dp(f, L, 2 * D, V, rho) == pytest.approx(base / 2)


# ---------- 输入校验 ----------

@pytest.mark.parametrize("bad", [0, -1, -1.0e9, float("nan"), float("inf"), -float("inf"), "1000", None, True])
def test_invalid_reynolds_rejected(bad):
    with pytest.raises(ValidationError):
        validate_reynolds(bad)


@pytest.mark.parametrize("bad", [-0.001, -1.0, 1.0, 2.0, float("nan"), float("inf"), "0.01", None])
def test_invalid_roughness_rejected(bad):
    with pytest.raises(ValidationError):
        validate_relative_roughness(bad)


def test_roughness_zero_is_valid():
    assert validate_relative_roughness(0.0) == 0.0


def test_pressure_inputs_optional_all_or_none():
    assert collect_pressure_inputs({}) == ({}, False)
    cleaned, ok = collect_pressure_inputs(
        {"pipe_length": 10, "diameter": 0.5, "velocity": 2.0, "density": 1000.0}
    )
    assert ok and cleaned["pipe_length"] == 10.0

    with pytest.raises(ValidationError) as ei:
        collect_pressure_inputs({"pipe_length": 10, "diameter": 0.5})
    assert "density" in ei.value.details["missing"] or "velocity" in ei.value.details["missing"]


@pytest.mark.parametrize("field", ["pipe_length", "diameter", "velocity", "density"])
def test_pressure_inputs_must_be_positive(field):
    base = {"pipe_length": 10.0, "diameter": 0.5, "velocity": 2.0, "density": 1000.0}
    base[field] = 0.0
    with pytest.raises(ValidationError) as ei:
        collect_pressure_inputs(base)
    assert ei.value.field == field


def test_force_regime_conflict():
    # 层流 Re 却强制湍流
    with pytest.raises(RegimeConflictError):
        from app.services.calculation import compute_case
        compute_case(reynolds=1000.0, relative_roughness=0.0, force_regime="turbulent", persist=False)
    # 湍流 Re 却强制层流
    with pytest.raises(RegimeConflictError):
        from app.services.calculation import compute_case
        compute_case(reynolds=1.0e5, relative_roughness=0.0, force_regime="laminar", persist=False)
    # 过渡区无论强制什么都矛盾
    with pytest.raises((RegimeConflictError, TransitionNotModeledError)):
        from app.services.calculation import compute_case
        compute_case(reynolds=3000.0, relative_roughness=0.0, force_regime="turbulent", persist=False)
