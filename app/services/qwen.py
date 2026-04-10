"""
Qwen-powered smart classifier for NBT schedule and casting emails.

This is the AI reasoning layer that sits on top of the deterministic parsers.
It handles ambiguous cases that regex/pdfplumber can't resolve:
  - TYPE 1 vs TYPE 2 call logic ("All Dancers as called" disambiguation)
  - Role-name vs scene-name detection (e.g. "Dew Drop" = role, "Act 2" = scene)
  - Provisional vs final casting determination
  - Body-text-only emails (cancellations, cast changes)

Uses the Alibaba Cloud Coding Plan API (qwen3.5-plus) via OpenAI-compatible endpoint.
"""

import json
import logging
import urllib.request
from typing import Optional

from app.config import settings
from app.services.qwen_prompts import (
    SCHEDULE_SYSTEM_PROMPT,
    CASTING_SYSTEM_PROMPT,
    EMAIL_CLASSIFY_SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------

def call_qwen(
    messages: list[dict],
    temperature: float = 0.1,
    max_tokens: int = 4000,
) -> dict:
    """Call the Qwen API via OpenAI-compatible endpoint.

    Returns {"content": str, "usage": dict, "error": str|None}.
    """
    api_key = settings.qwen_api_key
    base_url = settings.qwen_api_base
    model = settings.qwen_model

    if not api_key:
        return {"content": None, "usage": {}, "error": "QWEN_API_KEY not configured"}

    url = f"{base_url}/chat/completions"

    payload = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "enable_thinking": False,
    }).encode("utf-8")

    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode())
            content = result["choices"][0]["message"]["content"]
            usage = result.get("usage", {})
            return {"content": content, "usage": usage, "error": None}
    except Exception as e:
        logger.exception("Qwen API call failed")
        return {"content": None, "usage": {}, "error": str(e)}


def _parse_json_response(raw: str) -> dict | list | None:
    """Extract JSON from a Qwen response, handling markdown code fences."""
    content = raw.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(content)


# ---------------------------------------------------------------------------
# Email classification
# ---------------------------------------------------------------------------

def classify_email_smart(
    subject: str,
    body: str,
    attachment_filenames: list[str],
) -> dict:
    """Use Qwen to classify an email from Brooke.

    Returns a dict with keys: type, actionable, reason, production.
    """
    messages = [
        {"role": "system", "content": EMAIL_CLASSIFY_SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"Subject: {subject}\n"
            f"Body: {body[:1000]}\n"
            f"Has PDF: {any(f.lower().endswith('.pdf') for f in attachment_filenames)}\n"
            f"Attachments: {json.dumps(attachment_filenames)}\n\n"
            f"Classify this email."
        )},
    ]

    result = call_qwen(messages, temperature=0.1, max_tokens=300)
    if result["error"]:
        return {
            "type": "error",
            "actionable": False,
            "reason": result["error"],
            "production": None,
        }

    try:
        return _parse_json_response(result["content"])
    except Exception:
        return {
            "type": "unknown",
            "actionable": True,
            "reason": f"Could not parse: {result['content'][:200]}",
            "production": None,
        }


# ---------------------------------------------------------------------------
# Schedule interpretation (the smart layer)
# ---------------------------------------------------------------------------

def interpret_schedule_smart(
    pdf_text: str,
    pdf_tables: list[dict],
    email_subject: str,
    user_roles: dict,
    production_roles: Optional[dict] = None,
) -> dict:
    """Use Qwen to interpret a schedule PDF and produce call-status-tagged events.

    This is the smart layer that resolves TYPE 1 vs TYPE 2 ambiguity using the
    full casting database role list.

    Args:
        pdf_text: Raw text extracted from the PDF.
        pdf_tables: List of {"page": int, "rows": [[str, ...], ...]} tables.
        email_subject: The email subject line.
        user_roles: Dict of {"production_key": ["Role 1", ...]} for Zach.
        production_roles: Dict of {"production_key": ["Role 1", ...]} for ALL roles
                          in each production. Used for TYPE 1 vs TYPE 2 disambiguation.

    Returns {"events": [...], "error": str|None, "usage": dict}.
    """
    roles_str = json.dumps(user_roles, indent=2)

    # Build the production role list block
    role_list_str = ""
    if production_roles:
        role_list_str = (
            "\n\nKNOWN ROLE NAMES FROM CASTING DATABASE "
            "(use this to distinguish TYPE 1 vs TYPE 2):\n"
        )
        for prod_key, roles in production_roles.items():
            display_name = prod_key.replace("_", " ").title()
            role_list_str += f"\n  {display_name}:\n"
            role_list_str += "    " + ", ".join(roles) + "\n"

    # Format tables
    tables_str = ""
    for t in pdf_tables:
        tables_str += f"\n--- Table (page {t['page']}) ---\n"
        for row in t["rows"]:
            tables_str += " | ".join(str(cell or "") for cell in row) + "\n"

    system_prompt = SCHEDULE_SYSTEM_PROMPT.format(
        roles_str=roles_str,
        role_list_str=role_list_str,
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": (
            f"Email subject: {email_subject}\n\n"
            f"PDF TEXT:\n{pdf_text}\n\n"
            f"PDF TABLES:\n{tables_str}\n\n"
            f"Parse this into calendar events with correct call status for Zach."
        )},
    ]

    result = call_qwen(messages, temperature=0.1, max_tokens=4000)
    if result["error"]:
        return {"events": [], "error": result["error"], "usage": result["usage"]}

    try:
        events = _parse_json_response(result["content"])
        return {"events": events, "error": None, "usage": result["usage"]}
    except Exception as e:
        return {
            "events": [],
            "error": f"Parse error: {e}\nRaw: {result['content'][:500]}",
            "usage": result["usage"],
        }


# ---------------------------------------------------------------------------
# Casting interpretation
# ---------------------------------------------------------------------------

def interpret_casting_smart(
    pdf_text: str,
    pdf_tables: list[dict],
    email_subject: str,
    email_body: str,
    existing_production: Optional[dict],
    casting_status_rules: Optional[dict] = None,
) -> dict:
    """Use Qwen to interpret a casting PDF and determine provisional vs final.

    Returns a dict with production_key, casting_status, roles, zach_roles, etc.
    """
    tables_str = ""
    for t in pdf_tables:
        tables_str += f"\n--- Table (page {t['page']}) ---\n"
        for row in t["rows"]:
            tables_str += " | ".join(str(cell or "") for cell in row) + "\n"

    existing_str = json.dumps(existing_production, indent=2) if existing_production else "No existing entry"
    rules_str = json.dumps(casting_status_rules or {}, indent=2)

    system_prompt = CASTING_SYSTEM_PROMPT.format(status_rules=rules_str)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": (
            f"Email subject: {email_subject}\n"
            f"Email body excerpt: {(email_body or '')[:500]}\n\n"
            f"Existing DB entry for this production:\n{existing_str}\n\n"
            f"PDF TEXT:\n{pdf_text}\n\n"
            f"PDF TABLES:\n{tables_str}\n\n"
            f"Parse this casting data."
        )},
    ]

    result = call_qwen(messages, temperature=0.1, max_tokens=8000)
    if result["error"]:
        return {"error": result["error"], "usage": result["usage"]}

    try:
        data = _parse_json_response(result["content"])
        data["usage"] = result["usage"]
        data["error"] = None
        return data
    except Exception as e:
        return {
            "error": f"Parse error: {e}\nRaw: {result['content'][:500]}",
            "usage": result["usage"],
        }
