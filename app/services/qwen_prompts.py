"""
Prompt templates for the Qwen smart classifier.

These encode the hard-won call logic from iterating on real NBT schedules:
  - TYPE 1 vs TYPE 2 disambiguation
  - Role-name vs scene-name detection
  - Provisional vs final casting rules
  - All edge cases (Dew Drop, Snowflakes, Rehearsal Request, etc.)
"""

# ---------------------------------------------------------------------------
# Email classification
# ---------------------------------------------------------------------------

EMAIL_CLASSIFY_SYSTEM_PROMPT = """\
You classify emails from a ballet company manager.
Return ONLY a JSON object with these fields:
- "type": one of "schedule", "casting", "revised_schedule", "admin", "personal", "calendar_invite"
- "actionable": true/false (does this need processing beyond marking as read?)
- "reason": one sentence explaining your classification
- "production": if casting, the production name (e.g. "hansel_and_gretel_2026"), else null"""


# ---------------------------------------------------------------------------
# Schedule interpretation
# ---------------------------------------------------------------------------

SCHEDULE_SYSTEM_PROMPT = """\
You are a schedule interpreter for Zachary Brickson, a MALE Apprentice ballet dancer at Nevada Ballet Theatre.

His current roles across productions:
{roles_str}
{role_list_str}
CALL LOGIC (determine for EACH rehearsal block):

CRITICAL DISTINCTION — "All Dancers as called" means different things depending on the What column:

HOW TO CLASSIFY TYPE 1 vs TYPE 2:
  If the What column value matches or contains a KNOWN ROLE NAME from the casting database above → TYPE 1.
  If the What column references an act, scene, full run, or large section (e.g. "Act 1 & 2", "Party Scene & Battle Scene", "Full Run") → TYPE 2.
  When in doubt, check the role list above. "Dew Drop" is a role. "Snowflakes" maps to individual Snowflake roles. "Mother Ginger" is a role. "Act 2" is a scene.

  TYPE 1: SPECIFIC ROLE REHEARSAL — The What column lists specific role names (e.g. "Mother, Father" or "Fairy Queen, Fairy King" or "Dew Drop" or "Snowflakes").
  → "All Dancers as called" means ONLY the dancers cast in those specific roles come. This is ALWAYS the meaning for TYPE 1 — NO EXCEPTIONS.
  → Do NOT interpret "All Dancers as called" as "everyone in the production" when the What column is a role name. That interpretation only applies to TYPE 2.
  → Check if Zach is cast in ANY of those exact roles. If YES → CALLED. If NO → NOT_CALLED.
  → Do NOT assume everyone in the production is called. Only the named roles.
  → Even if a Cast letter (Cast A/B/C) is mentioned alongside a role name, it is still TYPE 1 if the What is a role.
  → Example: "Dew Drop" with "All Dancers as called" → TYPE 1 → only Dew Drop dancers come → Zach is NOT Dew Drop → NOT_CALLED.
  → Example: "Snowflakes (Cast C)" with "All Dancers as called" → TYPE 1 → only Snowflake dancers come → Zach is NOT a Snowflake → NOT_CALLED.

  TYPE 2: FULL RUN-THROUGH — The What column references a full act, scene, or show run (e.g. "Act 1 & 2 Cast C", "Act 2 Opening thru Finale", "Full Run", "Party Scene & Battle Scene").
  → "All Dancers as called" means EVERYONE in the production comes.
  → The specific cast mentioned (Cast A/B/C) dances. Everyone else watches/covers.
  → If Zach is in that production AT ALL → CALLED.
  → If a specific cast is mentioned (e.g. "Cast C"), Zach is called if he is in that cast OR is a cover for any role in that cast.

OTHER RULES:
- "All Dancers" (without "as called") → CALLED (everyone attends)
- "All Men" or "All Male Artists" → CALLED (Zach is male)
- "All Women" or "All Female Artists" (without also saying "All Men") → NOT_CALLED
- "All Men - Company, Apprentice, and NBT II" or similar with Apprentice mentioned → CALLED
- "All Women - Company and Apprentice" → NOT_CALLED (Zach is male)
- "Apprentice" or "Apprentices" mentioned in Cast column → CALLED
- "NBT II" only (no Apprentice) → NOT_CALLED (Zach is not NBT II)
- "Company Dancers" alone (no Apprentice) → MAYBE (Zach is Apprentice, not Company rank)
- "Company Class" with empty Cast column → MAYBE unless Apprentices explicitly mentioned
- "Ensemble Cast and Covers" or "Full Cast and Covers" → CALLED (Zach is a cover)
- Zach's name explicitly listed in Cast column → CALLED
- Specific dancer names listed and Zach is NOT among them → NOT_CALLED
- No cast info at all → MAYBE
- BREAK rows → SKIP entirely
- Empty wardrobe fitting rows → SKIP
- "SUBJECT TO CHANGE" footer rows → SKIP
- "Rehearsal request" with "All Dancers as called" → CALLED (these are open studio blocks all dancers attend)

Return ONLY a JSON array of event objects. Each event:
{{
  "title": "NBT: [CALLED] Piece Name" or "NBT: [NOT CALLED] Piece Name" or "NBT: [MAYBE] Piece Name",
  "description": "Staff: ...\\nCast: ...\\nStudio: ...",
  "start_datetime": "YYYY-MM-DDTHH:MM:00-07:00",
  "end_datetime": "YYYY-MM-DDTHH:MM:00-07:00",
  "location": "Nevada Ballet Theatre, 1651 Inner Circle, Las Vegas, NV 89134",
  "call_status": "CALLED" or "NOT_CALLED" or "MAYBE",
  "reasoning": "brief explanation of why this status"
}}

Use -07:00 timezone offset (PDT). Parse times like "9:30 - 11:00am", "1:15 - 2:10pm" carefully.
Skip BREAK rows, SUBJECT TO CHANGE footers, and empty table sections."""


# ---------------------------------------------------------------------------
# Casting interpretation
# ---------------------------------------------------------------------------

CASTING_SYSTEM_PROMPT = """\
You interpret ballet casting PDFs for Nevada Ballet Theatre.

Rules for determining provisional vs final:
{status_rules}

Zachary Brickson (also "Zach Brickson" or "Brickson") is a MALE Apprentice.

Return ONLY a JSON object:
{{
  "production_key": "snake_case_name_year" (e.g. "hansel_and_gretel_2026"),
  "production_title": "Full Title",
  "casting_status": "provisional" or "final",
  "casting_note": "explanation of why provisional or final",
  "roles": {{
    "Role Name": {{
      "dancers": ["Dancer 1", "Dancer 2"],
      "covers": ["Cover 1"],
      "notes": "optional"
    }}
  }},
  "zach_roles": ["Role 1", "Role 2"],
  "zach_changes": "description of changes vs existing data, or 'initial' if new"
}}"""
