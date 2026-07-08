"""
Enterprise safety guardrail: only SELECT statements are ever allowed to
reach the database. This is a hard rule, not something the LLM can be
prompted around -- validation happens in plain Python after generation.
"""
import re

FORBIDDEN_KEYWORDS = [
    "DROP", "DELETE", "UPDATE", "ALTER", "TRUNCATE", "INSERT",
    "CREATE", "REPLACE", "GRANT", "REVOKE", "ATTACH", "DETACH",
    "PRAGMA", "VACUUM", "EXEC", "EXECUTE",
]


def validate_sql(sql: str) -> tuple[bool, str]:
    """Returns (is_valid, reason_if_invalid)."""
    if not sql or not sql.strip():
        return False, "Empty SQL statement."

    cleaned = sql.strip().rstrip(";")

    # Only one statement allowed -- blocks stacked queries like
    # "SELECT ...; DROP TABLE ..."
    if ";" in cleaned:
        return False, "Multiple statements are not allowed."

    if not re.match(r"^\s*(SELECT|WITH)\b", cleaned, re.IGNORECASE):
        return False, "Only SELECT (or WITH ... SELECT) statements are allowed."

    upper = cleaned.upper()
    for keyword in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{keyword}\b", upper):
            return False, f"Forbidden keyword detected: {keyword}"

    return True, ""
