from __future__ import annotations

from uuid import UUID

import pytest


BRAND_ID = UUID("22222222-2222-2222-2222-222222222222")
OWNER_USER_ID = "11111111-1111-1111-1111-111111111111"
COMPLETE_ANSWERS = {
    "tagline": "Innovation for everyone",
    "tone": "professional",
    "audience": "Small business owners aged 25-45",
    "colors": ["#FF5733", "#3498DB"],
    "avoid_words": "cheap, discount",
}


@pytest.mark.skip(reason="Brand Kit API behavior starts in Phase 2")
def test_brand_kit_contract_scaffold() -> None:
    assert BRAND_ID
    assert OWNER_USER_ID
    assert COMPLETE_ANSWERS
