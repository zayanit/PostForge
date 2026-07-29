from __future__ import annotations

from backend.app.services.brand_kit_store import derive_summary


def test_derive_summary_is_deterministic_and_includes_all_answers():
    answers = {
        "tagline": "  Innovation   for everyone ",
        "tone": "professional",
        "audience": " Small business owners aged 25-45 ",
        "colors": ["#ff5733", "#3498db"],
        "avoid_words": " cheap,   discount ",
    }

    assert derive_summary("  My   Brand ", answers) == "\n".join(
        (
            "Brand: My Brand",
            "Tagline: Innovation for everyone",
            "Tone: professional",
            "Audience: Small business owners aged 25-45",
            "Colors: #FF5733, #3498DB",
            "Avoid words: cheap, discount",
        )
    )


def test_derive_summary_uses_none_specified_for_omitted_optional_answers():
    assert derive_summary(
        "My Brand",
        {
            "tone": "professional",
            "audience": "Small business owners aged 25-45",
            "colors": ["#FF5733"],
        },
    ) == "\n".join(
        (
            "Brand: My Brand",
            "Tagline: None specified",
            "Tone: professional",
            "Audience: Small business owners aged 25-45",
            "Colors: #FF5733",
            "Avoid words: None specified",
        )
    )
