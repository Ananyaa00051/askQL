"""
Keeps SQLite for this demo, but the surface area is intentionally small
(get_full_schema / run_query) so swapping in psycopg2 (Postgres) or
mysql-connector later only means changing this file.
"""
import sqlite3
from contextlib import contextmanager
from app.config import DB_PATH, MAX_ROWS_RETURNED


@contextmanager
def get_connection(db_path: str | None = None):
    """Open a connection to db_path, or fall back to the configured DB_PATH."""
    path = db_path or DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def get_full_schema(db_path: str | None = None) -> dict:
    """
    Returns {table_name: [ (col_name, col_type), ... ]} for every table.
    Small demo DB -> we just load the whole schema. For a real enterprise
    DB with 100s of tables, replace this with a vector-search retriever
    (see README "Scaling schema retrieval" section) that only returns
    tables relevant to the question.
    """
    schema = {}
    with get_connection(db_path) as conn:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        tables = [row["name"] for row in cur.fetchall()]
        for table in tables:
            cur.execute(f"PRAGMA table_info({table})")
            schema[table] = [(row["name"], row["type"]) for row in cur.fetchall()]
    return schema


def schema_to_prompt_string(schema: dict) -> str:
    lines = []
    for table, cols in schema.items():
        col_str = ", ".join(f"{name} ({dtype})" for name, dtype in cols)
        lines.append(f"- {table}: {col_str}")
    return "\n".join(lines)


def run_query(sql: str, db_path: str | None = None) -> dict:
    """
    Executes a validated read-only SQL statement.
    Returns {columns: [...], rows: [...], row_count: int}
    Raises sqlite3.Error on failure -- callers should catch this.
    """
    with get_connection(db_path) as conn:
        cur = conn.cursor()
        cur.execute(sql)
        columns = [desc[0] for desc in cur.description] if cur.description else []
        rows = cur.fetchmany(MAX_ROWS_RETURNED)
        rows_as_dicts = [dict(row) for row in rows]
        return {
            "columns": columns,
            "rows": rows_as_dicts,
            "row_count": len(rows_as_dicts),
        }
