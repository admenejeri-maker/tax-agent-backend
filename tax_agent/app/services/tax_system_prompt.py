"""
Georgian Tax System Prompt Builder — Task 6b
==============================================

Constructs the system prompt injected into the Gemini generation call.
Encodes:
  - Role & persona
  - Guardrails (no calculations, no non-tax, citation requirements)
  - Dynamic context injection (definitions, sources, history, temporal warnings)
"""

from typing import List, Optional


# ─── Constants ───────────────────────────────────────────────────────────────

BASE_SYSTEM_PROMPT = """შენ ხარ საქართველოს საგადასახადო კანონმდებლობის ექსპერტი ასისტენტი.

გაასავალე:
- პასუხი მხოლოდ საქართველოს საგადასახადო კოდექსის საფუძველზე
- ყოველთვის მიუთითე წყარო (მუხლი, თავი ან გვერდი)
- თუ პასუხი არ არსებობს კონტექსტში, თქვი "ინფორმაცია ვერ მოიძებნა"
- არ გამოთვალო კონკრეტული თანხები — მიმართე პროფესიონალს

აკრძალულია:
- გადასახადებთან დაუკავშირებელ კითხვებზე პასუხი
- მოგონილი ან გამოცნობილი ინფორმაციის მოცემა
- პირადი რჩევის გაცემა"""

DISCLAIMER_CALCULATION = (
    "⚠️ კონკრეტული თანხების გამოსათვლელად მიმართეთ საგადასახადო კონსულტანტს."
)

DISCLAIMER_TEMPORAL = (
    "⚠️ თქვენ {year} წლის შესახებ გკითხავთ — გთხოვთ გაითვალისწინოთ, "
    "რომ საგადასახადო კანონმდებლობა შეიძლება შეცვლილი იყოს."
)


# ─── Prompt Builder ──────────────────────────────────────────────────────────


def build_system_prompt(
    *,
    context_chunks: List[str],
    definitions: Optional[List[dict]] = None,
    is_red_zone: bool = False,
    temporal_year: Optional[int] = None,
) -> str:
    """Build the full system prompt for Gemini generation.

    Args:
        context_chunks: Retrieved document chunks from vector search.
        definitions: Matched term definitions from the classifier.
        is_red_zone: Whether the query triggers calculation disclaimers.
        temporal_year: Past year detected in query, if any.

    Returns:
        Complete system prompt string with all dynamic sections assembled.
    """
    parts: List[str] = [BASE_SYSTEM_PROMPT]

    # ── Inject term definitions if any
    if definitions:
        defn_lines = [
            f"- {d['term_ka']}: {d.get('definition', '')}"
            for d in definitions if d.get("term_ka")
        ]
        if defn_lines:
            parts.append(
                "\n\nტერმინების განმარტებები:\n" + "\n".join(defn_lines)
            )

    # ── Inject context chunks
    if context_chunks:
        context_block = "\n\n---\n".join(context_chunks)
        parts.append(f"\n\nკონტექსტი:\n{context_block}")
    else:
        parts.append("\n\nკონტექსტი: ინფორმაცია ვერ მოიძებნა.")

    # ── Add disclaimers
    disclaimers: List[str] = []
    if is_red_zone:
        disclaimers.append(DISCLAIMER_CALCULATION)
    if temporal_year:
        disclaimers.append(DISCLAIMER_TEMPORAL.format(year=temporal_year))

    if disclaimers:
        parts.append("\n\n" + "\n".join(disclaimers))

    return "".join(parts)
