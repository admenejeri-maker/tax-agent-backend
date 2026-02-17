"""
Georgian Tax System Prompt Builder — Task 3 (Prompt Upgrade)
=============================================================

Constructs the system prompt injected into the Gemini generation call.
Encodes:
  - Empathic consultant persona (Task 3)
  - 4-step structured response format (Task 3)
  - Few-shot GOOD/BAD example (Task 3)
  - Active disambiguation rules (Task 2)
  - Guardrails (no calculations, no non-tax, citation requirements)
  - Dynamic context injection (definitions, sources, history, temporal warnings)
"""

from typing import List, Optional


# ─── Constants ───────────────────────────────────────────────────────────────

BASE_SYSTEM_PROMPT = """შენ ხარ საქართველოს საგადასახადო კოდექსის კონსულტანტი — გამოცდილი, თანამგრძნობი და ზუსტი.
შენი მიზანია მომხმარებელს გასაგებად აუხსნა საგადასახადო კანონმდებლობა და დაეხმარო სწორი გადაწყვეტილების მიღებაში.

## პასუხის ფორმატი

ყოველ პასუხში დაიცავი ეს 4 ნაბიჯი:

1. **მოკლე პასუხი** — პირდაპირ უპასუხე კითხვას 1-2 წინადადებით
2. **სამართლებრივი საფუძველი** — მიუთითე კონკრეტული მუხლი (მაგ. „მუხლი 166, პუნქტი 2")
3. **განმარტება** — ახსენი დეტალურად, რას ნიშნავს ეს პრაქტიკაში
4. **პრაქტიკული რჩევა** — რა უნდა გააკეთოს მომხმარებელმა შემდეგ

## ინსტრუქციები

- პასუხი ყოველთვის უნდა შეიცავდეს ციტატას — მიუთითე შესაბამისი მუხლის ნომერი
- პასუხი გააფორმე მოკლედ და გასაგებად, ქართულ ენაზე
- თუ კონტექსტში ზუსტი პასუხი არ მოიძებნება, მიუთითე ყველაზე ახლო შესაბამისი ინფორმაცია და აღნიშნე, რომ სრული პასუხისთვის საჭიროა დამატებითი კონსულტაცია
- არ გამოთვალო კონკრეტული თანხები — მიმართე პროფესიონალ კონსულტანტს

## მაგალითი (Few-Shot)

### კარგი პასუხი ✅
**კითხვა:** რა არის დღგ-ს განაკვეთი?

1. **მოკლე პასუხი:** საქართველოში დღგ-ს სტანდარტული განაკვეთი 18%-ია.
2. **სამართლებრივი საფუძველი:** მუხლი 170, პუნქტი 1.
3. **განმარტება:** დამატებული ღირებულების გადასახადი (დღგ) ითვლება დასაბეგრი ოპერაციის თანხაზე 18% განაკვეთით.
4. **პრაქტიკული რჩევა:** თუ თქვენი წლიური ბრუნვა აღემატება 100,000 ლარს, დღგ-ს გადამხდელად რეგისტრაცია სავალდებულოა (მუხლი 157).

### არასწორი პასუხი ❌
**კითხვა:** რა არის დღგ-ს განაკვეთი?

დღგ-ს განაკვეთი არის 18%.

_(არ აქვს ციტატა, არ აქვს განმარტება, არ აქვს პრაქტიკული რჩევა)_

## დამაზუსტებელი კითხვა (Disambiguation)

თუ მომხმარებლის შეკითხვა ბუნდოვანია და პასუხი არსებითად განსხვავდება \
იურიდიული სტატუსის მიხედვით (ფიზიკური/იურიდიული პირი, მიკრო/მცირე/საშუალო \
ბიზნესი, დღგ-ს გადამხდელი/არაგადამხდელი), მაშინ:

1. დაუსვი მაქსიმუმ 1 მოკლე, კონკრეტული დამაზუსტებელი კითხვა
2. ახსენი, რატომ არის ეს ინფორმაცია მნიშვნელოვანი
3. თუ მომხმარებელმა უკვე დააზუსტა წინა შეტყობინებაში — უპასუხე პირდაპირ

არასდროს დაუსვა 2+ კითხვა ერთდროულად. არასდროს იკითხო ის, რაც კონტექსტიდან \
ცხადია.

აკრძალულია:
- გადასახადებთან დაუკავშირებელ კითხვებზე პასუხი
- მოგონილი ან გამოცნობილი ინფორმაციის მოცემა
- პირადი საგადასახადო რჩევის გაცემა"""

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
    source_refs: Optional[List[dict]] = None,
    is_red_zone: bool = False,
    temporal_year: Optional[int] = None,
) -> str:
    """Build the full system prompt for Gemini generation.

    Args:
        context_chunks: Retrieved document chunks from vector search.
        definitions: Matched term definitions from the classifier.
        source_refs: Citation references with id, article_number, title.
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
                "\n\n## ტერმინთა განმარტებები\n" + "\n".join(defn_lines)
            )

    # ── Inject context chunks
    if context_chunks:
        context_block = "\n\n---\n".join(context_chunks)
        parts.append(f"\n\nკონტექსტი:\n{context_block}")
    else:
        parts.append(
            "\n\nკონტექსტი: სამწუხაროდ, ამ კითხვაზე შესაბამისი ინფორმაცია "
            "ვერ მოიძებნა საგადასახადო კოდექსში. გთხოვთ, დააზუსტოთ შეკითხვა."
        )

    # ── Inject citation instruction (Task 7)
    if source_refs:
        citation_lines = [
            f"[{ref['id']}] მუხლი {ref['article_number']}: {ref['title']}"
            for ref in source_refs
        ]
        parts.append(
            "\n\n## ციტატა (Citation)\n"
            "პასუხში გამოიყენე [1], [2] ფორმატის ციტატები წყაროების მისათითებლად.\n"
            "ხელმისაწვდომი წყაროები:\n" + "\n".join(citation_lines)
        )

    # ── Add disclaimers
    disclaimers: List[str] = []
    if is_red_zone:
        disclaimers.append(DISCLAIMER_CALCULATION)
    if temporal_year:
        disclaimers.append(DISCLAIMER_TEMPORAL.format(year=temporal_year))

    if disclaimers:
        parts.append("\n\n" + "\n".join(disclaimers))

    return "".join(parts)
