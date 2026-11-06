from ai_workbench.core.user_persona_context import build_user_persona_context


def test_user_persona_context_trims_and_records_only_compact_metadata():
    result = build_user_persona_context(persona_id="user", content="  stable preference  ")
    assert "<user_background>\nstable preference\n</user_background>" in result.rendered_text
    assert "persona" not in result.rendered_text.lower()
    assert result.metadata == {
        "persona_id": "user", "injected": True, "content_chars": len("stable preference"), "skipped_reason": None,
    }
    assert "stable preference" not in str(result.metadata)


def test_empty_user_context_has_no_instruction_block():
    result = build_user_persona_context(persona_id="user", content=" \n ")
    assert result.rendered_text == ""
    assert result.metadata == {"persona_id": "user", "injected": False, "content_chars": 0, "skipped_reason": "empty"}
