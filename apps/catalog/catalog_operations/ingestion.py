from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO
from uuid import uuid4

import pandas as pd

from .contracts import CatalogItem, IngestionResult, ValidationMessage
from .enums import Severity
from .rules import SKU_PATTERN, VENDOR_PATTERN, SUPPORTED_CATEGORIES, is_blank, is_valid_gtin, parse_price

CANONICAL_ALIASES = {
    "sku": ("sku", "product_id"),
    "vendor_id": ("vendor_id",),
    "vendor_name": ("vendor_name", "seller_name"),
    "product_name": ("product_name", "title"),
    "brand": ("brand",),
    "category": ("category",),
    "description": ("description",),
    "price": ("price",),
    "gtin": ("gtin", "ean", "upc"),
    "image_url": ("image_url", "image"),
    "colour": ("colour", "color"),
    "size": ("size",),
    "material": ("material",),
    "submitted_at": ("submitted_at",),
}

REQUIRED_FIELDS = ("sku", "vendor_id", "product_name", "category", "price")
KNOWN_AUDIT_FIELDS = {"vendor_approved"}


def read_tabular(source: str | Path | BinaryIO, filename: str | None = None) -> pd.DataFrame:
    name = (filename or getattr(source, "name", str(source))).lower()
    if name.endswith(".xlsx"):
        return pd.read_excel(source)
    if not name.endswith(".csv"):
        raise ValueError("Only CSV and Excel (.xlsx) files are supported.")
    try:
        frame = pd.read_csv(source)
        if frame.shape[1] == 1 and hasattr(source, "seek"):
            for separator in (";", "\t"):
                source.seek(0)
                candidate = pd.read_csv(source, sep=separator)
                if candidate.shape[1] > 1:
                    return candidate
        return frame
    except (UnicodeDecodeError, pd.errors.ParserError) as exc:
        raise ValueError(f"Could not parse input file: {exc}") from exc


def _resolve_columns(columns: list[str]) -> tuple[dict[str, str], list[ValidationMessage]]:
    normalized = {str(c).strip().lower(): str(c) for c in columns}
    mapping: dict[str, str] = {}
    messages: list[ValidationMessage] = []
    for canonical, aliases in CANONICAL_ALIASES.items():
        matches = [normalized[a] for a in aliases if a in normalized]
        if len(matches) > 1:
            messages.append(ValidationMessage(canonical, "AMBIGUOUS_COLUMN", f"Multiple columns map to {canonical}: {matches}"))
        elif matches:
            mapping[canonical] = matches[0]
    return mapping, messages


def ingest_dataframe(df: pd.DataFrame, workflow_run_id: str | None = None) -> IngestionResult:
    run_id = workflow_run_id or str(uuid4())
    mapping, errors = _resolve_columns(list(df.columns))
    warnings: list[ValidationMessage] = []
    currency_columns=[column for column in df if str(column).strip().lower()=="currency"]
    if currency_columns:
        invalid=~df[currency_columns[0]].fillna("").astype(str).str.strip().str.upper().eq("INR")
        if invalid.any():
            errors.append(ValidationMessage("currency","INR_REQUIRED",f"{int(invalid.sum())} rows have missing or non-INR currency. Supply INR amounts; no conversion is performed."))
    items: list[CatalogItem] = []
    originals = df.where(pd.notna(df), None).to_dict(orient="records")
    if any(error.code == "INR_REQUIRED" for error in errors):
        return IngestionResult(run_id, [], errors, warnings, originals)

    for field in REQUIRED_FIELDS:
        if field not in mapping:
            errors.append(ValidationMessage(field, "MISSING_COLUMN", f"Required column for '{field}' was not supplied."))
    if any(e.code == "MISSING_COLUMN" for e in errors):
        return IngestionResult(run_id, [], errors, warnings, originals)

    seen: set[str] = set()
    known_sources = set(mapping.values())
    for unknown in sorted(set(df.columns) - known_sources - KNOWN_AUDIT_FIELDS):
        warnings.append(ValidationMessage(str(unknown), "UNKNOWN_COLUMN", "Column preserved in source_record but not mapped to the canonical contract.", Severity.WARNING))

    for index, raw in enumerate(originals, start=2):
        values = {field: raw.get(source) for field, source in mapping.items()}
        sku = "" if is_blank(values.get("sku")) else str(values["sku"]).strip()
        vendor_id = "" if is_blank(values.get("vendor_id")) else str(values["vendor_id"]).strip()
        category = "" if is_blank(values.get("category")) else str(values["category"]).strip()
        row_errors: list[ValidationMessage] = []
        if not sku:
            row_errors.append(ValidationMessage("sku", "MISSING_SKU", f"Row {index}: SKU is required."))
        elif not SKU_PATTERN.fullmatch(sku):
            row_errors.append(ValidationMessage("sku", "INVALID_SKU", f"Row {index}: SKU format is invalid."))
        elif sku.casefold() in seen:
            row_errors.append(ValidationMessage("sku", "DUPLICATE_SKU", f"Row {index}: duplicate SKU '{sku}' in this workflow run."))
        if not vendor_id or not VENDOR_PATTERN.fullmatch(vendor_id):
            row_errors.append(ValidationMessage("vendor_id", "INVALID_VENDOR_ID", f"Row {index}: vendor_id is missing or malformed."))
        price = parse_price(values.get("price"))
        if price is None or price < 0:
            row_errors.append(ValidationMessage("price", "INVALID_PRICE", f"Row {index}: price must be a non-negative number."))
        gtin = "" if is_blank(values.get("gtin")) else str(values["gtin"]).strip()
        if not is_valid_gtin(gtin):
            row_errors.append(ValidationMessage("gtin", "INVALID_GTIN", f"Row {index}: GTIN checksum or length is invalid."))
        if category.casefold() not in SUPPORTED_CATEGORIES:
            row_errors.append(ValidationMessage("category", "UNSUPPORTED_CATEGORY", f"Row {index}: unsupported category '{category}'."))
        for field in ("product_name",):
            if is_blank(values.get(field)):
                row_errors.append(ValidationMessage(field, "MISSING_REQUIRED_VALUE", f"Row {index}: {field} is required."))
        errors.extend(row_errors)
        if row_errors:
            continue
        seen.add(sku.casefold())
        submitted = pd.to_datetime(values.get("submitted_at"), utc=True, errors="coerce")
        submitted_at = submitted.to_pydatetime() if not pd.isna(submitted) else datetime.now(timezone.utc)
        text = lambda field: "" if is_blank(values.get(field)) else str(values[field]).strip()
        items.append(CatalogItem(
            sku=sku, vendor_id=vendor_id, vendor_name=text("vendor_name"),
            product_name=text("product_name"), brand=text("brand"), category=category,
            description=text("description"), price=price, gtin=gtin,
            image_url=text("image_url"), colour=text("colour"), size=text("size"),
            material=text("material"), submitted_at=submitted_at,
            workflow_run_id=run_id, source_record=raw,
        ))
    return IngestionResult(run_id, items, errors, warnings, originals)
