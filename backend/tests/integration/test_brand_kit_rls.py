from __future__ import annotations

from uuid import UUID

import pytest


BRAND_ID = UUID("22222222-2222-2222-2222-222222222222")
OWNER_USER_ID = "11111111-1111-1111-1111-111111111111"
OTHER_USER_ID = "99999999-9999-9999-9999-999999999999"


@pytest.mark.skip(reason="Brand Kit RLS behavior starts in Phase 2")
def test_brand_kit_rls_scaffold() -> None:
    assert BRAND_ID
    assert OWNER_USER_ID != OTHER_USER_ID
