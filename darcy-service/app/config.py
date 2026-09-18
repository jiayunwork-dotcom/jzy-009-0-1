"""领域常量：区制阈值与湍流求根的钉死容差。

这些值是核算规则的一部分，单独放在一处，便于：
- 求根器据此判断收敛；
- 配置查询接口原样回显给调用方；
- 测试按同一口径断言。
"""
from __future__ import annotations

# 雷诺数区制边界（含/不含语义见 regimes.classify）
LAMINAR_RE_MAX: float = 2300.0
TURBULENT_RE_MIN: float = 4000.0

# 相对粗糙度合法范围：0 <= eps/d < 1
RELATIVE_ROUGHNESS_MIN: float = 0.0
RELATIVE_ROUGHNESS_MAX_EXCLUSIVE: float = 1.0

# 湍流隐式求根（Colebrook-White 形方程）配置。
# 残差以十为底的 Colebrook 变换定义，见 app.turbulence。
RESIDUAL_TOLERANCE: float = 1.0e-10
ROOT_MAX_ITERATIONS: int = 100

# Darcy-Weisbach 压降量在物理上必须为正。
PRESSURE_DROP_FIELDS: tuple[str, ...] = ("length", "diameter", "velocity", "density")

# 预置算例：商用钢管量级相对粗糙度、雷诺数十万，f 应在 0.018 量级。
# 商用新钢管典型 eps/D 约 1.5e-4；Re=1e5 时 Colebrook f≈0.0188。
PRESET_EXAMPLE: dict[str, float] = {
    "reynolds_number": 100_000.0,
    "relative_roughness": 0.00015,
}
