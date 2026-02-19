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
        """Prompt contains the 4-step thinking framework."""
        prompt = build_system_prompt(context_chunks=["context"])
        assert "პირდაპირი პასუხი" in prompt
        assert "ახსნა" in prompt
        assert "მაგალითი" in prompt
        assert "მოქმედება" in prompt

    def test_few_shot_example_present(self):
        """Prompt contains contrast-style few-shot example pair."""
        prompt = build_system_prompt(context_chunks=["context"])
        assert "ასე არა" in prompt    # BAD marker
        assert "ასე კი" in prompt     # GOOD marker

    # ── QA Move 5: Hardening ──────────────────────────────────────────

    def test_prohibition_block_present(self):
        """Prohibition rules are in the base system prompt."""
        assert "აკრძალულია" in BASE_SYSTEM_PROMPT

    def test_instructions_section_present(self):
        """Instructions section with citation and brevity rules is present."""
        prompt = build_system_prompt(context_chunks=["context"])
        assert "## ინსტრუქციები" in prompt
        assert "ციტატით" in prompt  # citation requirement

    # ── Step 5: CoL Logic Rules ───────────────────────────────────

    def test_logic_rules_injected(self):
        """Logic rules text appears in the generated prompt."""
        rules = "IF VAT > 100K THEN register"
        prompt = build_system_prompt(
            context_chunks=["context"],
            logic_rules=rules,
        )
        assert rules in prompt
        assert "ლოგიკის წესები" in prompt

    def test_logic_rules_none_no_section(self):
        """None logic_rules does not inject the section header."""
        prompt = build_system_prompt(
            context_chunks=["context"],
            logic_rules=None,
        )
        assert "ლოგიკის წესები" not in prompt

    def test_logic_rules_before_context(self):
        """Logic rules section appears before context section."""
        rules = "RULE_MARKER_FOR_ORDER_TEST"
        prompt = build_system_prompt(
            context_chunks=["CONTEXT_MARKER_FOR_ORDER_TEST"],
            logic_rules=rules,
        )
        rules_pos = prompt.index("ლოგიკის წესები")
        context_pos = prompt.index("CONTEXT_MARKER_FOR_ORDER_TEST")
        assert rules_pos < context_pos

    def test_logic_rules_georgian(self):
        """Georgian UTF-8 content in logic rules renders correctly."""
        rules = "თუ დღგ-ს ბრუნვა > 100,000 ლარი → რეგისტრაცია სავალდებულოა"
        prompt = build_system_prompt(
            context_chunks=["context"],
            logic_rules=rules,
        )
        assert "100,000 ლარი" in prompt

    # ── Domain Focus ──────────────────────────────────────────────────

    def test_domain_injected_for_vat(self):
        """Non-GENERAL domain renders the სფერო section."""
        prompt = build_system_prompt(
            context_chunks=["context"],
            domain="VAT",
        )
        assert "## სფერო: VAT" in prompt

    def test_domain_general_omitted(self):
        """GENERAL domain does NOT render the სფერო section."""
        prompt = build_system_prompt(
            context_chunks=["context"],
            domain="GENERAL",
        )
        assert "სფერო" not in prompt

    def test_domain_before_logic_rules(self):
        """Domain section appears before logic rules in the prompt."""
        prompt = build_system_prompt(
            context_chunks=["context"],
            domain="INDIVIDUAL_INCOME",
            logic_rules="RULE_MARKER",
        )
        domain_pos = prompt.index("სფერო")
        rules_pos = prompt.index("ლოგიკის წესები")
        assert domain_pos < rules_pos

    # ── Citation Format Regression Guard ──────────────────────────────

    def test_few_shot_citation_inline_and_footer(self):
        """Few-Shot ✅ uses [N] inline + '📚 წყაროები' heading at bottom."""
        good_section = BASE_SYSTEM_PROMPT.split("ასე კი")[1]
        assert "[1]" in good_section
        assert "[2]" in good_section
        footer = good_section.split("📚 წყაროები")[1]
        assert "მუხლი" in footer

    def test_instructions_use_bracket_n_format(self):
        """Instructions require [N] citation markers, not 'მუხლის ნომერი'."""
        assert "[N]" in BASE_SYSTEM_PROMPT
        assert "მუხლის ნომერი" not in BASE_SYSTEM_PROMPT

    def test_citation_injection_has_footer_template(self):
        """Citation injection section uses 📚 წყაროები format."""
        refs = [{"id": 1, "article_number": "89", "title": "T"}]
        prompt = build_system_prompt(context_chunks=["c"], source_refs=refs)
        citation_section = prompt.split("ციტატა")[1]
        assert "📚 წყაროები" in citation_section
        assert "მუხლი" in citation_section

    # ── 3-Layer Defense: Formatting Regression Guard ──────────────────

    def test_markdown_rule_in_tone(self):
        """Tone rules include Markdown formatting instruction."""
        assert "Markdown" in BASE_SYSTEM_PROMPT or "მუქი" in BASE_SYSTEM_PROMPT

    def test_few_shot_has_emoji_sources_heading(self):
        """Few-shot ✅ example uses 📚 წყაროები heading."""
        good_section = BASE_SYSTEM_PROMPT.split("ასე კი")[1]
        assert "📚 წყაროები" in good_section

    def test_citation_uses_bullet_format(self):
        """Citation template uses - (dash) bullet format."""
        refs = [{"id": 1, "article_number": "89", "title": "T"}]
        prompt = build_system_prompt(context_chunks=["c"], source_refs=refs)
        assert "- [1]" in prompt

    def test_tone_rule_3_consistent_with_template(self):
        """Tone rule 3 mentions 📚 წყაროები to match citation template."""
        assert "📚 წყაროები" in BASE_SYSTEM_PROMPT

    def test_few_shot_uses_markdown_formatting(self):
        """Few-shot ✅ example must use **bold** and - bullets in body."""
        good_section = BASE_SYSTEM_PROMPT.split("ასე კი")[1]
        assert "**" in good_section, "Few-shot must use **bold** markers"
        assert "\n- " in good_section, "Few-shot must use - (dash) bullet points"

