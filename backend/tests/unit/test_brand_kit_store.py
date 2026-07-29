from __future__ import annotations

from uuid import UUID

import pytest


BRAND_ID = UUID("22222222-2222-2222-2222-222222222222")
BRAND_NAME = "My Brand"
COMPLETE_ANSWERS = {
    "tagline": "Innovation for everyone",
    "tone": "professional",
    "audience": "Small business owners aged 25-45",
    "colors": ["#FF5733", "#3498DB"],
    "avoid_words": "cheap, discount",
}


@pytest.mark.skip(reason="BrandKitStore behavior starts in Phase 2")
def test_brand_kit_store_scaffold() -> None:
    assert BRAND_ID
    assert BRAND_NAME
    assert COMPLETE_ANSWERS
