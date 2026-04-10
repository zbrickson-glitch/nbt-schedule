"""
Casting PDF parser using LLM (qwen3-max via DashScope API).

Extracts role-to-dancer mappings from variably-formatted casting PDFs.
Falls back to raw text preview if LLM extraction fails.
"""

import io
import json
import logging
import os
from typing import Optional

import pdfplumber

logger = logging.getLogger(__name__)

DASHSCOPE_API_KEY = os.environ.get("DASHSCOPE_API_KEY", "")
DASHSCOPE_BASE_URL = os.environ.get("DASHSCOPE_BASE_URL", "https://coding-intl.dashscope.aliyuncs.com/v1")
DASHSCOPE_MODEL = os.environ.get("DASHSCOPE_MODEL", "qwen3-max")
FILTER_DANCER = os.environ.get("FILTER_DANCER", "BRICKSON")

SYSTEM_PROMPT = """You are a ballet casting document parser. Given the text of a casting PDF, extract structured data.

Return ONLY valid JSON (no markdown, no explanation) with this schema:
{
  "show": "Name of the production/show",
  "roster": [
    {
      "role": "Role or part name",
      "dancers": ["Last, First", "Last, First"]
    }
  ],
  "notes": "Any relevant notes about the casting (optional)"
}

Rules:
- Extract ALL roles and their assigned dancers
- Use the exact names as written in the document
- If a dancer has multiple roles, they should appear in each role's dancer list
- If you see cast designations like "Cast A", "Cast B", "1st Cast", "2nd Cast", include them in the role name
- If the document has multiple acts or scenes, include the act/scene in the role name
- Preserve the original formatting of names (Last, First or First Last)
- If you cannot parse the document, return {"show": "Unknown", "roster": [], "notes": "Could not parse casting document"}
"""


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract all text from a PDF using pdfplumber."""
    text_parts = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)

            # Also try extracting tables for structured data
            tables = page.extract_tables()
            for table in tables:
                if table:
                    for row in table:
                        if row and any(row):
                            cells = [str(c) for c in row if c]
                            if cells:
                                text_parts.append(' | '.join(cells))

    return '\n'.join(text_parts)


def call_llm(text: str) -> Optional[dict]:
    """Call DashScope API (OpenAI-compatible) to extract casting data."""
    if not DASHSCOPE_API_KEY:
        logger.warning("DASHSCOPE_API_KEY not set, skipping LLM extraction")
        return None

    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=DASHSCOPE_API_KEY,
            base_url=DASHSCOPE_BASE_URL,
        )

        # Truncate text if too long (stay within reasonable context)
        max_chars = 15000
        if len(text) > max_chars:
            text = text[:max_chars] + "\n\n[... truncated ...]"

        response = client.chat.completions.create(
            model=DASHSCOPE_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Parse this casting document:\n\n{text}"},
            ],
            temperature=0.1,
            max_tokens=4000,
        )

        content = response.choices[0].message.content.strip()

        # Strip markdown code fences if present
        if content.startswith("```"):
            lines = content.split('\n')
            # Remove first line (```json or ```) and last line (```)
            lines = [l for l in lines if not l.strip().startswith("```")]
            content = '\n'.join(lines)

        return json.loads(content)

    except json.JSONDecodeError as e:
        logger.error("LLM returned invalid JSON: %s", e)
        return None
    except Exception as e:
        logger.error("LLM call failed: %s", e)
        return None


def parse_casting_pdf(pdf_bytes: bytes, filename: str) -> dict:
    """
    Parse a casting PDF using LLM extraction.

    Args:
        pdf_bytes: Raw PDF file content
        filename: Original filename

    Returns:
        {
            "roster": [{"role": str, "dancers": [str]}],
            "your_roles": [str],
            "show": str,
            "preview": str,  # Raw text fallback if LLM fails
            "llm_used": bool,
            "error": str or None
        }
    """
    # Extract text from PDF
    raw_text = extract_pdf_text(pdf_bytes)
    if not raw_text.strip():
        return {
            "roster": [],
            "your_roles": [],
            "show": "Unknown",
            "preview": "(Empty PDF - no text extracted)",
            "llm_used": False,
            "error": "No text extracted from PDF",
        }

    # Try LLM extraction
    llm_result = call_llm(raw_text)

    if llm_result and llm_result.get("roster"):
        roster = llm_result["roster"]
        show = llm_result.get("show", "Unknown")

        # Find roles where BRICKSON appears
        filter_lower = FILTER_DANCER.lower()
        your_roles = []
        for entry in roster:
            for dancer in entry.get("dancers", []):
                if filter_lower in dancer.lower():
                    your_roles.append(entry["role"])
                    break

        return {
            "roster": roster,
            "your_roles": your_roles,
            "show": show,
            "notes": llm_result.get("notes", ""),
            "llm_used": True,
            "error": None,
        }
    else:
        # Fallback: return raw text preview
        preview_text = raw_text[:2000]
        if len(raw_text) > 2000:
            preview_text += "\n\n[... truncated ...]"

        return {
            "roster": [],
            "your_roles": [],
            "show": filename.replace('.pdf', '').replace('.PDF', ''),
            "preview": preview_text,
            "llm_used": False,
            "error": "LLM extraction failed, returning raw text",
        }
