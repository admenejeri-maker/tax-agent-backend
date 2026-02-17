"""
Test System Prompt — Tasks 2, 3
================================

14 tests verifying system prompt construction:
- Base prompt, context injection, disclaimers, definitions, fallback (6 core)
- Disambiguation rules: section present, max-1-question, already-clarified (3 Task 2)
- Empathic persona, 4-step format, few-shot example (3 Task 3)
- Guardrails prohibition block, instructions section (2 QA hardening)
"""

from app.services.tax_system_prompt import (
    build_system_prompt,
    BASE_SYSTEM_PROMPT,
    DISCLAIMER_CALCULATION,
)


class TestBuildSystemPrompt:
    """Tests for system prompt construction."""

    def test_contains_base_prompt(self):
        """Generated prompt always starts with the base system prompt."""
        prompt = build_system_prompt(context_chunks=[])
        assert BASE_SYSTEM_PROMPT in prompt

    def test_context_injected(self):
        """Context chunks appear in the generated prompt."""
        chunks = ["მუხლი 1: საშემოსავლო გადასახადი"]
        prompt = build_system_prompt(context_chunks=chunks)
        assert "საშემოსავლო გადასახადი" in prompt

    def test_red_zone_disclaimer_added(self):
        """Red zone flag injects the calculation disclaimer."""
        prompt = build_system_prompt(
            context_chunks=["context"],
            is_red_zone=True,
        )
        assert DISCLAIMER_CALCULATION in prompt

    def test_temporal_warning_includes_year(self):
        """Temporal year renders the warning with the correct year."""
        prompt = build_system_prompt(
            context_chunks=["context"],
            temporal_year=2022,
        )
        assert "2022" in prompt
        assert "შეცვლილი" in prompt

    def test_definitions_injected(self):
        """Matched definitions appear in the prompt."""
        defs = [{"term_ka": "დღგ", "definition": "დამატებული ღირებულების გადასახადი"}]
        prompt = build_system_prompt(
            context_chunks=["context"],
            definitions=defs,
        )
        assert "დღგ" in prompt
        assert "დამატებული ღირებულების გადასახადი" in prompt

    def test_empty_context_shows_fallback(self):
        """Empty context injects a fallback message."""
        prompt = build_system_prompt(context_chunks=[])
        assert "ინფორმაცია ვერ მოიძებნა" in prompt

    # ── Task 2: Active Disambiguation ────────────────────────────────

    def test_disambiguation_section_present(self):
        """Disambiguation instruction is part of base system prompt."""
        assert "დამაზუსტებელი კითხვა" in BASE_SYSTEM_PROMPT

    def test_disambiguation_max_one_question_rule(self):
        """The 'max 1 question' rule is in the built prompt."""
        prompt = build_system_prompt(context_chunks=["context"])
        assert "მაქსიმუმ 1" in prompt

    def test_disambiguation_already_clarified_rule(self):
        """The 'already clarified → answer directly' rule is in the prompt."""
        prompt = build_system_prompt(context_chunks=["context"])
        assert "უკვე დააზუსტა" in prompt

    # ── Task 3: Prompt Upgrade ────────────────────────────────────────

    def test_empathic_persona_header(self):
        """Upgraded prompt contains empathic consultant persona."""
        prompt = build_system_prompt(context_chunks=["context"])
        assert "კონსულტანტი" in prompt  # NEW word, not in old prompt

    def test_response_format_four_steps(self):
        """Prompt contains the 4-step structured response format."""
        prompt = build_system_prompt(context_chunks=["context"])
        assert "მოკლე პასუხი" in prompt
        assert "სამართლებრივი საფუძველი" in prompt
        assert "განმარტება" in prompt
        assert "პრაქტიკული რჩევა" in prompt

    def test_few_shot_example_present(self):
        """Prompt contains GOOD/BAD few-shot example pair."""
        prompt = build_system_prompt(context_chunks=["context"])
        assert "კარგი პასუხი" in prompt   # GOOD marker
        assert "არასწორი პასუხი" in prompt  # BAD marker

    # ── QA Move 5: Hardening ──────────────────────────────────────────

    def test_prohibition_block_present(self):
        """Prohibition rules are in the base system prompt."""
        assert "აკრძალულია" in BASE_SYSTEM_PROMPT

    def test_instructions_section_present(self):
        """Instructions section with citation and brevity rules is present."""
        prompt = build_system_prompt(context_chunks=["context"])
        assert "## ინსტრუქციები" in prompt
        assert "ციტატას" in prompt  # citation requirement
