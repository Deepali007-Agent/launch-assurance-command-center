"""Deterministic purchase-order validation and decision engine."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from decimal import Decimal, InvalidOperation

import pandas as pd
import math

from .input_pipeline import REQUIRED_COLUMNS


@dataclass(frozen=True)
class EngineConfig:
    margin_floor_pct: float = 45.0
    minimum_sla_days: int = 14
    minimum_order_quantity: int = 15
    analyst_rate: float = 15.0
    batch_run_hours: float = 2.5
    rework_minutes: float = 45.0
    runs_per_month: int = 20


DEFAULT_CONFIG = EngineConfig()
VALID_DIVISIONS = {"Accessories", "Menswear", "Womenswear", "Kids"}
VALID_LOCATIONS = {"NJ", "TX", "NY", "LA", "CA", "IL", "FL"}
DIVISION_SUBCLASSES = {
    "Menswear": {"Jackets", "Shirts", "Pants", "Suits", "Shorts"},
    "Womenswear": {
        "Jackets",
        "Shirts",
        "Pants",
        "Dresses",
        "Skirts",
        "Shorts",
    },
    "Kids": {"Jackets", "Shirts", "Pants", "Dresses", "Shorts"},
    "Accessories": {
        "Bags",
        "Belts",
        "Hats",
        "Scarves",
        "Jewelry",
        "Jackets",
        "Pants",
        "Shirts",
        "Dresses",
    },
}


def parse_date(value: Any) -> datetime | None:
    for date_format in ("%d-%m-%Y", "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(value).strip(), date_format)
        except (TypeError, ValueError, OverflowError):
            continue
    return None


def risk_level(errors: list[str], warnings: list[str]) -> str:
    if len(errors) >= 2:
        return "HIGH"
    if len(errors) == 1 or len(warnings) >= 2:
        return "MEDIUM"
    if len(warnings) == 1:
        return "LOW"
    return "CLEAR"


def readiness_score(errors: list[str], warnings: list[str]) -> int:
    return max(0, 100 - len(errors) * 25 - len(warnings) * 10)


def whole_units(value: Any) -> int:
    """Accept integer-valued Excel/CSV cells without truncating fractions."""
    if isinstance(value, bool):
        raise ValueError('Boolean is not a unit count')
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError('Unit count must be numeric') from exc
    if not number.is_finite() or number != number.to_integral_value():
        raise ValueError('Unit count must be a finite whole number')
    return int(number)


def validate_row(
    row: pd.Series | dict[str, Any],
    index: int,
    config: EngineConfig = DEFAULT_CONFIG,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    error_types: list[str] = []
    label = (
        f"{row.get('PO_ID', '?')} · {row.get('Vendor ID', '?')} · "
        f"{row.get('Vendor Name', '?')}"
    )

    missing = []
    for field_name in REQUIRED_COLUMNS:
        value = row.get(field_name)
        if pd.isna(value) or str(value).strip() == "":
            errors.append(f"<b>{field_name}</b> is missing")
            missing.append(field_name)
    if missing:
        error_types.append("Missing Fields")

    division = str(row.get("Division", "")).strip()
    subclass = str(row.get("Sub-Class", "")).strip()
    if division and division not in VALID_DIVISIONS:
        errors.append(f"Unknown Division: <b>{division}</b>")
        error_types.append("Invalid Division")
    if (
        division in DIVISION_SUBCLASSES
        and subclass
        and subclass not in DIVISION_SUBCLASSES[division]
    ):
        warnings.append(
            f"Sub-Class <b>{subclass}</b> unusual for <b>{division}</b>"
        )
        error_types.append("Sub-Class Mismatch")

    currency_raw=row.get("currency",row.get("Currency","INR"))
    currency="" if pd.isna(currency_raw) else str(currency_raw).strip().upper()
    if currency!="INR":
        errors.append("Currency must be INR; correct missing/non-INR amounts before buying. No currency conversion is performed.")
        error_types.append("Invalid Currency")
    revenue = 0.0
    cost_value = 0.0
    margin_gap = 0.0
    margin_pct: float | None = None
    try:
        cost = float(row.get("Cost", 0))
        retail = float(row.get("Reg Retail", 0))
        original_retail = float(row.get("Original Retail", retail))
        quantity = whole_units(row.get("Total Quantity", 0))
        if quantity <= 0:
            raise ValueError('Quantity must be positive')
        if not all(math.isfinite(v) and v > 0 for v in (cost, retail, original_retail)):
            raise ValueError('Commercial amounts must be finite and positive')
        revenue = retail * quantity
        cost_value = cost * quantity
        if cost > 0 and retail > 0:
            margin_pct = (retail - cost) / retail * 100
            if margin_pct < config.margin_floor_pct:
                target_margin = config.margin_floor_pct / 100
                margin_gap = (
                    target_margin * retail - (retail - cost)
                ) * quantity
                warnings.append(
                    f"Margin <b>{margin_pct:.1f}%</b> below "
                    f"{config.margin_floor_pct:.0f}% floor "
                    f"(Cost INR {cost:.2f} · Retail INR {retail:.2f})"
                )
                error_types.append("Low Margin")
        if original_retail < retail:
            warnings.append(
                f"Original Retail INR {original_retail:.2f} < "
                f"Reg Retail INR {retail:.2f}"
            )
            error_types.append("Retail Discrepancy")
    except (TypeError, ValueError, OverflowError):
        errors.append("Cost/Retail/Quantity invalid: use finite positive amounts and an integer quantity")
        error_types.append("Data Error")

    if currency!="INR":
        revenue=cost_value=margin_gap=0.0
        margin_pct=None
    ship_raw = row.get("Ship Dates", "")
    cancel_raw = row.get("Cancel Dates", "")
    ship_date = parse_date(ship_raw)
    cancel_date = parse_date(cancel_raw)
    if not pd.isna(ship_raw) and str(ship_raw).strip() and ship_date is None:
        errors.append("Ship Date has an invalid format")
        error_types.append("Data Error")
    if not pd.isna(cancel_raw) and str(cancel_raw).strip() and cancel_date is None:
        errors.append("Cancel Date has an invalid format")
        error_types.append("Data Error")

    ship_month = ship_date.strftime("%Y-%m") if ship_date else None
    window_days: int | None = None
    if ship_date and cancel_date:
        window_days = (cancel_date - ship_date).days
        if window_days < 0:
            errors.append(
                "Cancel Date <b>before</b> Ship Date — critical scheduling error"
            )
            error_types.append("Cancel Before Ship")
        elif window_days < config.minimum_sla_days:
            warnings.append(
                f"Fulfilment window <b>{window_days} days</b> — below "
                f"{config.minimum_sla_days}-day SLA minimum"
            )
            error_types.append("Tight Fulfilment Window")

    quantity = None
    try:
        quantity = whole_units(row.get("Total Quantity", 0))
        if quantity <= 0:
            errors.append("Total Quantity must be > 0")
            error_types.append("Invalid Quantity")
        elif quantity < config.minimum_order_quantity:
            warnings.append(
                f"Quantity <b>{quantity}</b> below MOQ threshold of "
                f"{config.minimum_order_quantity}"
            )
            error_types.append("Low Quantity")
    except (TypeError, ValueError, OverflowError):
        errors.append("Total Quantity must be a finite whole number")
        error_types.append("Data Error")

    try:
        case_pack = whole_units(row.get("Case-pack", 0))
        if case_pack <= 0:
            errors.append("Case-pack must be > 0")
            error_types.append("Invalid Case-pack")
        elif case_pack == 1:
            warnings.append("Case-pack of <b>1</b> — verify with vendor")
            error_types.append("Case-pack = 1")
        if case_pack > 0 and quantity is not None and quantity > 0 and quantity % case_pack:
            errors.append(f"Total Quantity {quantity} must be divisible by Case-pack {case_pack}; correct the quantity or confirmed pack size.")
            error_types.append("Case-pack Divisibility")
    except (TypeError, ValueError, OverflowError):
        errors.append("Case-pack must be a finite whole number")
        error_types.append("Data Error")

    location = str(row.get("Location", "")).strip()
    if location and location not in VALID_LOCATIONS:
        warnings.append(f"Unrecognised DC location: <b>{location}</b>")
        error_types.append("Unknown Location")

    status = "FAIL" if errors else ("WARN" if warnings else "PASS")
    return {
        "currency": currency,
        "commercial_value_included": currency=="INR",
        "row_index": index,
        "label": label,
        "status": status,
        "risk": risk_level(errors, warnings),
        "readiness": readiness_score(errors, warnings),
        "errors": errors,
        "warnings": warnings,
        "error_types": sorted(set(error_types)),
        "vendor_id": str(row.get("Vendor ID", "")).strip(),
        "vendor_name": str(row.get("Vendor Name", "Unknown")).strip(),
        "po_id": str(row.get("PO_ID", "")).strip(),
        "sku": str(row.get("sku", "")).strip(),
        "style_id": str(row.get("Vendor Style", "")).strip(),
        "division": division,
        "revenue": revenue,
        "cost_val": cost_value,
        "gross_margin": revenue - cost_value,
        "margin_gap": max(0.0, margin_gap),
        "margin_pct": margin_pct,
        "ship_month": ship_month,
        "window_days": window_days,
        "is_flagged": status in {"FAIL", "WARN"},
    }


def build_financial(
    results: list[dict[str, Any]],
    config: EngineConfig = DEFAULT_CONFIG,
) -> dict[str, Any]:
    total_revenue = sum(row["revenue"] for row in results)
    total_cost = sum(row["cost_val"] for row in results)
    total_margin = sum(row["gross_margin"] for row in results)
    flagged = [row for row in results if row["is_flagged"]]
    po_statuses: dict[str, bool] = {}
    for row in results:
        po_id = row["po_id"] or "UNKNOWN"
        po_statuses.setdefault(po_id, True)
        if row["is_flagged"]:
            po_statuses[po_id] = False

    flagged_count = len(flagged)
    batch_hours = flagged_count * config.batch_run_hours
    rework_hours = flagged_count * config.rework_minutes / 60
    validation_hours = len(results) * (20 / 60)
    hours_saved = batch_hours + rework_hours + validation_hours
    cost_saved = hours_saved * config.analyst_rate

    return {
        "total_rev": total_revenue,
        "total_cost": total_cost,
        "total_gm": total_margin,
        "avg_margin": (
            total_margin / total_revenue * 100 if total_revenue > 0 else 0
        ),
        "at_risk_cost": sum(row["cost_val"] for row in flagged),
        "at_risk_rev": sum(row["revenue"] for row in flagged),
        "margin_gap": sum(row["margin_gap"] for row in results),
        "po_pass_rate": (
            sum(po_statuses.values()) / len(po_statuses) * 100
            if po_statuses
            else 0
        ),
        "unique_pos_at_risk": sum(not status for status in po_statuses.values()),
        "total_pos": len(po_statuses),
        "flagged_count": flagged_count,
        "total_hrs_saved": hours_saved,
        "cost_saved_run": cost_saved,
        "annual_saving": cost_saved * config.runs_per_month * 12,
        "batch_hrs_saved": batch_hours,
    }


def build_sla(
    results: list[dict[str, Any]],
    config: EngineConfig = DEFAULT_CONFIG,
) -> dict[str, Any]:
    windows = [
        row["window_days"]
        for row in results
        if row["window_days"] is not None
    ]
    meets = sum(window >= config.minimum_sla_days for window in windows)
    vendor_windows: dict[str, dict[str, Any]] = {}
    for row in results:
        vendor = row["vendor_name"]
        stats = vendor_windows.setdefault(
            vendor, {"windows": [], "flagged": 0, "total": 0}
        )
        if row["window_days"] is not None:
            stats["windows"].append(row["window_days"])
        stats["total"] += 1
        stats["flagged"] += int(row["is_flagged"])

    vendors = []
    for vendor, stats in vendor_windows.items():
        valid_windows = stats["windows"]
        vendor_meets = sum(
            window >= config.minimum_sla_days for window in valid_windows
        )
        vendors.append(
            {
                "vendor": vendor,
                "avg_window": (
                    sum(valid_windows) / len(valid_windows)
                    if valid_windows
                    else 0
                ),
                "compliance": (
                    vendor_meets / len(valid_windows) * 100
                    if valid_windows
                    else 0
                ),
                "total": stats["total"],
                "flagged": stats["flagged"],
            }
        )

    return {
        "sla_rate": meets / len(windows) * 100 if windows else 0,
        "avg_window": sum(windows) / len(windows) if windows else 0,
        "meets_14": meets,
        "tight": sum(0 <= window < config.minimum_sla_days for window in windows),
        "critical": sum(0 <= window < 7 for window in windows),
        "breached": sum(window < 0 for window in windows),
        "total_rows": len(windows),
        "vendors": sorted(vendors, key=lambda item: item["compliance"]),
    }


def _vendor_grade(error_rate: float) -> tuple[str, str]:
    if error_rate == 0:
        return "A", "p-a"
    if error_rate <= 25:
        return "B", "p-b"
    if error_rate <= 60:
        return "C", "p-c"
    return "D", "p-d"


def build_vendor_scorecard(
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    vendors: dict[str, dict[str, Any]] = {}
    for row in results:
        vendor = row["vendor_name"]
        stats = vendors.setdefault(
            vendor,
            {
                "total": 0,
                "flagged": 0,
                "errors": 0,
                "warnings": 0,
                "revenue": 0.0,
                "cost_val": 0.0,
                "margin_gap": 0.0,
                "gross_margin": 0.0,
                "margins": [],
            },
        )
        stats["total"] += 1
        stats["revenue"] += row["revenue"]
        stats["cost_val"] += row["cost_val"]
        stats["gross_margin"] += row["gross_margin"]
        stats["margin_gap"] += row["margin_gap"]
        if row["margin_pct"] is not None:
            stats["margins"].append(row["margin_pct"])
        if row["is_flagged"]:
            stats["flagged"] += 1
            stats["errors"] += len(row["errors"])
            stats["warnings"] += len(row["warnings"])

    output = []
    for vendor, stats in vendors.items():
        error_rate = stats["flagged"] / stats["total"] * 100
        average_margin = (
            sum(stats["margins"]) / len(stats["margins"])
            if stats["margins"]
            else 0
        )
        exposure_score = min(stats["revenue"] / 100000 * 10, 40)
        margin_score = (
            max(0, 30 - (average_margin - 45)) if average_margin < 50 else 0
        )
        risk_score = min(error_rate * 0.30 + exposure_score + margin_score, 100)
        grade, grade_class = _vendor_grade(error_rate)
        if error_rate >= 80:
            action = "Immediate vendor review — suspend new POs pending audit"
        elif error_rate >= 60:
            action = "Place on probation — mandatory training before next submission"
        elif error_rate >= 40:
            action = "Issue formal warning — require pre-submission check"
        elif error_rate >= 20:
            action = "Monitor closely — schedule vendor performance review"
        else:
            action = "Maintain — continue standard monitoring"
        output.append(
            {
                **stats,
                "vendor": vendor,
                "error_rate": error_rate,
                "avg_margin": average_margin,
                "risk_score": risk_score,
                "grade": grade,
                "grade_cls": grade_class,
                "action": action,
                "resubmissions": stats["errors"] + stats["warnings"],
            }
        )
    return sorted(output, key=lambda item: item["risk_score"], reverse=True)


def build_division(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    divisions: dict[str, dict[str, Any]] = {}
    for row in results:
        division = row["division"] or "Unknown"
        stats = divisions.setdefault(
            division,
            {
                "total": 0,
                "flagged": 0,
                "revenue": 0.0,
                "cost_val": 0.0,
                "gross_margin": 0.0,
                "margins": [],
                "margin_gaps": 0.0,
            },
        )
        stats["total"] += 1
        stats["flagged"] += int(row["is_flagged"])
        stats["revenue"] += row["revenue"]
        stats["cost_val"] += row["cost_val"]
        stats["gross_margin"] += row["gross_margin"]
        stats["margin_gaps"] += row["margin_gap"]
        if row["margin_pct"] is not None:
            stats["margins"].append(row["margin_pct"])

    output = []
    for division, stats in divisions.items():
        error_rate = stats["flagged"] / stats["total"] * 100
        average_margin = (
            sum(stats["margins"]) / len(stats["margins"])
            if stats["margins"]
            else 0
        )
        risk = (
            "HIGH"
            if error_rate >= 50 or average_margin < 45
            else ("MEDIUM" if error_rate >= 25 or average_margin < 47 else "LOW")
        )
        output.append(
            {
                **stats,
                "division": division,
                "error_rate": error_rate,
                "avg_margin": average_margin,
                "gm_pct": (
                    stats["gross_margin"] / stats["revenue"] * 100
                    if stats["revenue"] > 0
                    else 0
                ),
                "risk": risk,
            }
        )
    return sorted(output, key=lambda item: item["revenue"], reverse=True)


def build_decision_support(
    results: list[dict[str, Any]],
    vendor_scorecard: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    del vendor_scorecard
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in results:
        grouped.setdefault(row["po_id"] or "Unknown", []).append(row)

    decisions = []
    for po_id, rows in grouped.items():
        flagged = [row for row in rows if row["is_flagged"]]
        if not flagged:
            continue
        margin_gap = sum(row["margin_gap"] for row in rows)
        error_count = sum(len(row["errors"]) for row in rows)
        warning_count = sum(len(row["warnings"]) for row in rows)
        has_critical = any(
            row["window_days"] is not None and row["window_days"] < 0
            for row in rows
        )
        has_missing = any(
            "missing" in " ".join(row["errors"]).lower() for row in rows
        )
        if has_critical or has_missing or error_count > 0:
            recommendation = "HOLD"
            reason = "Critical errors present — fix before submitting."
        elif margin_gap > 5000:
            recommendation = "REVIEW"
            reason = f"INR {margin_gap:,.0f} margin gap — escalate before processing."
        elif warning_count > 0 and error_count == 0:
            recommendation = "PROCESS WITH FLAG"
            reason = "Warnings only — process with monitoring."
        else:
            recommendation = "PROCESS"
            reason = "All blocking checks passed."
        total_cost = sum(row["cost_val"] for row in rows)
        decisions.append(
            {
                "po_id": po_id,
                "lines": len(rows),
                "flagged": len(flagged),
                "total_cost": total_cost,
                "total_rev": sum(row["revenue"] for row in rows),
                "margin_gap": margin_gap,
                "readiness": sum(row["readiness"] for row in rows) / len(rows),
                "cost_of_submit": margin_gap + (37.5 if error_count else 0),
                "cost_of_hold": total_cost * 0.002,
                "recommendation": recommendation,
                "reason": reason,
                "error_count": error_count,
                "warn_count": warning_count,
            }
        )
    return sorted(decisions, key=lambda item: item["readiness"])
