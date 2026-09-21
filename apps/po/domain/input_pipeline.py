"""PO upload normalization and schema validation."""

from dataclasses import dataclass, field

import pandas as pd


REQUIRED_COLUMNS = [
    "Vendor ID",
    "Vendor Name",
    "Division",
    "Class",
    "Sub-Class",
    "Vendor Style",
    "Description",
    "Color",
    "Case-pack",
    "Cost",
    "Reg Retail",
    "Original Retail",
    "Total Quantity",
    "Location",
    "Ship Dates",
    "Cancel Dates",
    "PO_ID",
]


COLUMN_ALIASES = {
    "vendor_id": "Vendor ID",
    "vendor name": "Vendor Name",
    "vendor_name": "Vendor Name",
    "division": "Division",
    "class": "Class",
    "sub_class": "Sub-Class",
    "subclass": "Sub-Class",
    "vendor_style": "Vendor Style",
    "description": "Description",
    "color": "Color",
    "case_pack": "Case-pack",
    "casepack": "Case-pack",
    "cost": "Cost",
    "regular_retail": "Reg Retail",
    "reg_retail": "Reg Retail",
    "original_retail": "Original Retail",
    "total_quantity": "Total Quantity",
    "quantity": "Total Quantity",
    "location": "Location",
    "ship_date": "Ship Dates",
    "ship_dates": "Ship Dates",
    "cancel_date": "Cancel Dates",
    "cancel_dates": "Cancel Dates",
    "po_id": "PO_ID",
    "brand_name": "Brand Name",
}


@dataclass
class InputValidation:
    dataframe: pd.DataFrame
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    identifiers: dict[str, str] = field(default_factory=dict)

    @property
    def valid(self) -> bool:
        return not self.errors


def _column_key(name: object) -> str:
    return (
        str(name)
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.copy()
    rename_map: dict[object, str] = {}

    for column in normalized.columns:
        stripped = str(column).strip()
        alias = COLUMN_ALIASES.get(_column_key(stripped))
        rename_map[column] = alias or stripped

    return normalized.rename(columns=rename_map)


def validate_upload(df: pd.DataFrame) -> InputValidation:
    normalized = normalize_columns(df)
    errors: list[str] = []
    warnings: list[str] = []

    duplicate_columns = normalized.columns[
        normalized.columns.duplicated()
    ].tolist()
    if duplicate_columns:
        errors.append(
            "Duplicate columns found: " + ", ".join(map(str, duplicate_columns))
        )

    missing_columns = [
        column for column in REQUIRED_COLUMNS if column not in normalized.columns
    ]
    if missing_columns:
        errors.append(
            "Missing required columns: " + ", ".join(missing_columns)
        )

    if normalized.empty:
        errors.append("The uploaded buysheet contains no data rows.")

    sku_column = next(
        (
            column
            for column in ("sku", "SKU", "product_id", "Product ID")
            if column in normalized.columns
        ),
        None,
    )
    if sku_column is None:
        warnings.append(
            "No SKU/product_id column was supplied. PO validation can run, "
            "but CatalogIQ cross-domain matching will remain NOT_EVALUATED."
        )

    identifiers = {
        "vendor_id": "Vendor ID",
        "po_id": "PO_ID",
        "sku": sku_column or "",
        "style_id": "Vendor Style",
    }

    if "Vendor ID" in normalized.columns:
        normalized["vendor_id"] = normalized["Vendor ID"].astype(str).str.strip()
    if "PO_ID" in normalized.columns:
        normalized["po_id"] = normalized["PO_ID"].astype(str).str.strip()
    if "Vendor Style" in normalized.columns:
        normalized["style_id"] = (
            normalized["Vendor Style"].astype(str).str.strip()
        )
    if sku_column:
        normalized["sku"] = normalized[sku_column].astype(str).str.strip()

    return InputValidation(
        dataframe=normalized,
        errors=errors,
        warnings=warnings,
        identifiers=identifiers,
    )
