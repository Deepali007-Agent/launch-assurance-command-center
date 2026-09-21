"""Business-date parsing shared by validation and KPI calculations."""
from __future__ import annotations

from datetime import datetime
import pandas as pd


def parse_business_date(value):
    """Accept ISO and common spreadsheet day-first dates, including leading apostrophes."""
    text = str(value or "").strip().strip("'\"")
    if not text:
        return None
    for parser in (
        lambda item: datetime.fromisoformat(item).date(),
        lambda item: datetime.strptime(item, "%d-%m-%Y").date(),
        lambda item: datetime.strptime(item, "%d/%m/%Y").date(),
    ):
        try:
            return parser(text)
        except ValueError:
            continue
    return None


def parse_business_dates(values: pd.Series) -> pd.Series:
    parsed = values.map(parse_business_date)
    return pd.to_datetime(parsed, errors="coerce", utc=True)
