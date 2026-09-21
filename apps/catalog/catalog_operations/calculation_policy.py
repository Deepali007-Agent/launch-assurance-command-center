from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class CalculationPolicy:
    """Versioned retail-operations assumptions used by every intelligence view."""

    version: str = "retail-ops-policy-1.0"
    currency: str = "INR"

    health_readiness_weight: float = 0.45
    health_completeness_weight: float = 0.35
    health_blocker_free_weight: float = 0.20

    critical_revenue_factor: float = 0.35
    warning_revenue_factor: float = 0.12
    extra_defect_uplift: float = 0.05
    critical_revenue_factor_cap: float = 0.55
    warning_revenue_factor_cap: float = 0.25
    critical_recovery_rate: float = 0.55
    warning_recovery_rate: float = 0.70
    fallback_monthly_units: float = 10.0
    fallback_gross_margin_pct: float = 35.0

    portfolio_hold_critical_rate_pct: float = 20.0
    portfolio_hold_critical_exposure_pct: float = 25.0

    cx_field_weights: dict[str, float] = field(default_factory=lambda: {
        "image_url": 30.0, "description": 25.0, "product_name": 20.0,
        "brand": 12.0, "colour": 8.0, "size": 10.0, "material": 10.0,
    })
    cx_return_baseline_pct: float = 5.0
    cx_return_multiplier: float = 2.0
    cx_return_cap: float = 20.0
    cx_rating_target: float = 4.2
    cx_rating_multiplier: float = 12.5
    cx_rating_cap: float = 15.0
    cx_medium_threshold: float = 20.0
    cx_high_threshold: float = 40.0

    group_affected_weight: float = 0.30
    group_critical_weight: float = 0.25
    group_sla_weight: float = 0.20
    group_return_weight: float = 0.10
    group_exposure_weight: float = 0.15
    group_sla_target_pct: float = 95.0
    group_sla_full_risk_shortfall: float = 20.0
    group_return_baseline_pct: float = 5.0
    group_return_full_risk_gap: float = 10.0
    group_high_threshold: float = 60.0
    group_medium_threshold: float = 30.0

    def as_contract(self) -> dict:
        return asdict(self)


POLICY = CalculationPolicy()
