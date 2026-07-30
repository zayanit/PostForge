from __future__ import annotations

from backend.app.models.brand_kit import BrandKitUpsert
from backend.app.services.brand_kit_store import BrandKitStore, derive_summary


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


def test_merge_answers_preserves_omitted_values_and_clears_explicit_values():
    existing = {
        "tagline": "Keep this",
        "tone": "friendly",
        "audience": "Small teams",
        "colors": ["#123456"],
        "avoid_words": "cheap",
    }

    preserved = BrandKitStore._merged_answers(
        existing,
        BrandKitUpsert.model_validate({"name": "My Brand", "answers": {"tone": "formal"}}),
    )
    cleared = BrandKitStore._merged_answers(
        existing,
        BrandKitUpsert.model_validate(
            {"name": "My Brand", "answers": {"tagline": None, "colors": []}}
        ),
    )

    assert preserved.tagline == "Keep this"
    assert preserved.tone.value == "formal"
    assert cleared.tagline is None
    assert cleared.colors == []


def test_saved_answer_detection_distinguishes_lifecycle_states():
    assert not BrandKitStore._has_saved_answer(
        BrandKitUpsert.model_validate({"name": "My Brand"}).answers
    )
    assert BrandKitStore._has_saved_answer(
        BrandKitUpsert.model_validate(
            {"name": "My Brand", "answers": {"tagline": "Saved"}}
        ).answers
    )


def test_status_for_answers_covers_not_started_partial_and_complete():
    empty = BrandKitUpsert.model_validate({"name": "My Brand"}).answers
    partial = BrandKitUpsert.model_validate(
        {"name": "My Brand", "answers": {"audience": "Small teams"}}
    ).answers
    complete = BrandKitUpsert.model_validate(
        {
            "name": "My Brand",
            "answers": {
                "tone": "friendly",
                "audience": "Small teams",
                "colors": ["#123456"],
            },
        }
    ).answers

    assert BrandKitStore._status_for_answers(empty).value == "not_started"
    assert BrandKitStore._status_for_answers(partial).value == "in_progress"
    assert BrandKitStore._status_for_answers(complete).value == "complete"
