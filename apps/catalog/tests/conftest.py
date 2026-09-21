import pandas as pd
import pytest

from catalog_operations.persistence.repository import CatalogRepository


@pytest.fixture
def valid_row():
    return {
        "sku": "SKU-1001", "vendor_id": "V001", "vendor_name": "Demo Vendor",
        "product_name": "Classic Cotton Kurti", "brand": "DemoBrand", "category": "Fashion",
        "description": "Soft cotton kurti designed for comfortable everyday wear.", "price": 799,
        "gtin": "", "image_url": "https://example.com/item.jpg", "colour": "Blue",
        "size": "M", "material": "Cotton", "vendor_approved": True,
    }


@pytest.fixture
def valid_df(valid_row):
    return pd.DataFrame([valid_row])


@pytest.fixture
def repository(tmp_path):
    return CatalogRepository(f"sqlite:///{(tmp_path / 'catalog.db').as_posix()}")
