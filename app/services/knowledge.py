"""
Knowledge base and casting database reader for the Qwen smart classifier.

Reads from two JSON files that were built and iterated on during the
nbt-automation project:

  data/knowledge_base.json  — casting status rules, schedule patterns, call logic notes
  data/casting_database.json — full role lists per production, dancer index

These files provide context that the Qwen prompt needs to disambiguate
TYPE 1 vs TYPE 2 calls (e.g. "Dew Drop" is a role, "Act 2" is a scene).
"""

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Data files live at the repo root under data/
_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


def _load_json(filename: str) -> dict:
    """Load a JSON file from the data/ directory. Returns {} on failure."""
    path = _DATA_DIR / filename
    if not path.exists():
        logger.warning("Data file not found: %s", path)
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        logger.exception("Failed to load %s", path)
        return {}


# ---------------------------------------------------------------------------
# Knowledge base
# ---------------------------------------------------------------------------

def get_casting_status_rules() -> dict:
    """Return the casting status rules (provisional vs final signals)."""
    kb = _load_json("knowledge_base.json")
    return kb.get("casting_status_rules", {})


def get_schedule_patterns() -> dict:
    """Return observed schedule patterns."""
    kb = _load_json("knowledge_base.json")
    return kb.get("schedule_patterns", {})


def get_call_logic_notes() -> dict:
    """Return the call logic notes (hard-won rules)."""
    kb = _load_json("knowledge_base.json")
    return kb.get("call_logic_notes", {})


# ---------------------------------------------------------------------------
# Casting database
# ---------------------------------------------------------------------------

def get_all_production_roles() -> dict[str, list[str]]:
    """Get the full list of role names for every production.

    Returns: {"production_key": ["Role 1", "Role 2", ...], ...}

    This is the critical data that lets the AI distinguish role names (TYPE 1)
    from scene/act names (TYPE 2). "Dew Drop" appears in the role list →
    TYPE 1 → NOT_CALLED for Zach. "Act 2" does not → TYPE 2 → CALLED.
    """
    db = _load_json("casting_database.json")
    result = {}
    for prod_key, prod_data in db.get("productions", {}).items():
        roles = prod_data.get("roles", {})
        result[prod_key] = list(roles.keys())
    return result


def get_user_roles(
    user_name_variations: Optional[list[str]] = None,
) -> dict[str, list[str]]:
    """Get all roles for the configured user across all productions.

    Returns: {"production_key": ["Role 1", "Role 2", ...], ...}
    """
    if user_name_variations is None:
        user_name_variations = [
            "Zachary Brickson",
            "Zach Brickson",
            "Brickson",
        ]

    db = _load_json("casting_database.json")
    dancer_index = db.get("dancer_index", {})

    user_roles: dict[str, list[str]] = {}
    for name_variant in user_name_variations:
        if name_variant in dancer_index:
            for prod, roles in dancer_index[name_variant].items():
                if prod not in user_roles:
                    user_roles[prod] = []
                user_roles[prod].extend(roles)

    # Deduplicate
    for prod in user_roles:
        user_roles[prod] = list(set(user_roles[prod]))

    return user_roles


def update_casting_db(
    production_key: str,
    roles_data: dict,
    source_email_id: Optional[str] = None,
) -> dict:
    """Update the casting database with new role data from a Qwen interpretation.

    This mirrors the logic from nbt-automation/helpers.py but writes to
    data/casting_database.json in the repo.
    """
    from datetime import datetime

    db = _load_json("casting_database.json")

    # Update production
    db["productions"][production_key] = {
        "updated": datetime.now().isoformat(),
        "source_email_id": source_email_id,
        "roles": roles_data,
    }

    # Rebuild dancer index
    db["dancer_index"] = {}
    for prod_name, prod_data in db.get("productions", {}).items():
        for role_name, role_data in prod_data.get("roles", {}).items():
            all_dancers: set[str] = set()
            if isinstance(role_data, dict):
                for key in ["dancers", "covers", "cast_a", "cast_b", "cast_c"]:
                    val = role_data.get(key, [])
                    if isinstance(val, list):
                        all_dancers.update(val)
                    elif isinstance(val, str) and val:
                        all_dancers.add(val)

            for dancer in all_dancers:
                if dancer not in db["dancer_index"]:
                    db["dancer_index"][dancer] = {}
                if prod_name not in db["dancer_index"][dancer]:
                    db["dancer_index"][dancer][prod_name] = []
                if role_name not in db["dancer_index"][dancer][prod_name]:
                    db["dancer_index"][dancer][prod_name].append(role_name)

    db["last_updated"] = datetime.now().isoformat()

    # Write back
    path = _DATA_DIR / "casting_database.json"
    with open(path, "w") as f:
        json.dump(db, f, indent=2)

    return db
