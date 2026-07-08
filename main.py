"""
QueryPilot AI backend.

Run: uvicorn main:app --reload --port 8000
"""
import io
import os
import re
import uuid
import sqlite3
import pandas as pd

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from app.graph import compiled_graph
from app.config import MAX_RETRIES

app = FastAPI(title="askQL")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Simple in-memory conversational memory, keyed by session_id.
SESSIONS: dict[str, list[dict]] = {}

UPLOAD_DIR = "data/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class AskRequest(BaseModel):
    question: str
    session_id: str | None = None
    db_path: str | None = None      # set by the frontend after a successful upload


class AskResponse(BaseModel):
    session_id: str
    needs_clarification: bool
    clarification_question: str | None = None
    generated_sql: str | None = None
    columns: list[str] | None = None
    rows: list[dict] | None = None
    row_count: int | None = None
    business_summary: str | None = None
    chart_spec: dict | None = None
    followup_questions: list[str] = []
    retry_count: int = 0
    error: str | None = None


class UploadResponse(BaseModel):
    db_path: str
    tables: list[str]           # all tables now in the DB (existing + newly added)
    new_tables: list[str]       # tables added by this upload
    message: str


class RemoveTableResponse(BaseModel):
    db_path: str
    tables: list[str]           # remaining tables after removal
    message: str


# ---------------------------------------------------------------------------
# Upload endpoint  (supports appending to an existing DB)
# ---------------------------------------------------------------------------

@app.post("/upload", response_model=UploadResponse)
def upload_data(
    file: UploadFile = File(...),
    existing_db_path: Optional[str] = Form(None),   # if set, append tables here
) -> UploadResponse:
    """
    Accept a CSV, Excel (.xlsx/.xls), or SQLite (.db/.sqlite) file.
    - CSV   → single table named after the file stem
    - Excel → one table per sheet
    - SQLite → all tables are merged into the session DB

    If existing_db_path is provided the new tables are APPENDED to that DB
    instead of creating a fresh one, enabling multi-file sessions.
    """
    filename = file.filename or "upload"
    stem = os.path.splitext(filename)[0]
    ext = os.path.splitext(filename)[1].lower()
    contents = file.file.read()

    # Determine target DB path
    if existing_db_path and os.path.isfile(existing_db_path):
        db_path = existing_db_path          # append mode
        tables_before = set(_list_tables(db_path))
    else:
        db_path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4().hex}_session.db")
        tables_before = set()

    if ext in (".db", ".sqlite"):
        # Merge all tables from the uploaded SQLite into the session DB
        _merge_sqlite(contents, db_path)

    elif ext == ".csv":
        try:
            df = pd.read_csv(io.BytesIO(contents))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Could not parse CSV: {e}")
        table_name = _unique_table_name(_sanitise_name(stem), db_path)
        df.columns = _sanitise_columns(df.columns.tolist())
        conn = sqlite3.connect(db_path)
        df.to_sql(table_name, conn, if_exists="replace", index=False)
        conn.close()

    elif ext in (".xlsx", ".xls"):
        try:
            sheets = pd.read_excel(io.BytesIO(contents), sheet_name=None)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Could not parse Excel file: {e}")
        conn = sqlite3.connect(db_path)
        for sheet_name, df in sheets.items():
            table_name = _unique_table_name(_sanitise_name(sheet_name), db_path)
            df.columns = _sanitise_columns(df.columns.tolist())
            df.to_sql(table_name, conn, if_exists="replace", index=False)
        conn.close()

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Please upload a .csv, .xlsx, or .db file.",
        )

    all_tables = _list_tables(db_path)
    new_tables = [t for t in all_tables if t not in tables_before]

    return UploadResponse(
        db_path=db_path,
        tables=all_tables,
        new_tables=new_tables,
        message=(
            f"Added {len(new_tables)} table(s) from '{filename}'. "
            f"Session now has {len(all_tables)} table(s) ready to query."
        ),
    )


# ---------------------------------------------------------------------------
# Remove a single table from the session DB
# ---------------------------------------------------------------------------

@app.delete("/tables/{table_name}", response_model=RemoveTableResponse)
def remove_table(table_name: str, db_path: str) -> RemoveTableResponse:
    """Drop a single table from the session DB."""
    if not db_path or not os.path.isfile(db_path):
        raise HTTPException(status_code=404, detail="Session database not found.")

    existing = _list_tables(db_path)
    if table_name not in existing:
        raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found.")

    conn = sqlite3.connect(db_path)
    conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
    conn.commit()
    conn.close()

    remaining = _list_tables(db_path)
    return RemoveTableResponse(
        db_path=db_path,
        tables=remaining,
        message=f"Removed table '{table_name}'. {len(remaining)} table(s) remaining.",
    )


# ---------------------------------------------------------------------------
# Schema + stats endpoint — powers the data summary panel in the UI
# ---------------------------------------------------------------------------

@app.get("/schema")
def get_schema(db_path: str | None = None) -> dict:
    """
    Return schema + basic stats for every table in the DB.
    Each table entry includes:
      - columns: [{name, type, null_count}]
      - row_count
      - sample_rows: up to 3 rows as list of dicts
    """
    from app.config import DB_PATH as DEFAULT_DB_PATH
    path = db_path or DEFAULT_DB_PATH

    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Database not found.")

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    tables = [row["name"] for row in cur.fetchall()]

    result = {}
    for table in tables:
        # Column info
        cur.execute(f"PRAGMA table_info(\"{table}\")")
        columns_raw = cur.fetchall()
        col_names = [c["name"] for c in columns_raw]
        col_types = [c["type"] or "TEXT" for c in columns_raw]

        # Row count
        cur.execute(f'SELECT COUNT(*) FROM "{table}"')
        row_count = cur.fetchone()[0]

        # Null counts per column
        null_counts = {}
        for col in col_names:
            cur.execute(f'SELECT COUNT(*) FROM "{table}" WHERE "{col}" IS NULL')
            null_counts[col] = cur.fetchone()[0]

        # Sample rows (up to 3)
        cur.execute(f'SELECT * FROM "{table}" LIMIT 3')
        sample_rows = [dict(r) for r in cur.fetchall()]

        result[table] = {
            "row_count": row_count,
            "columns": [
                {"name": n, "type": t, "null_count": null_counts.get(n, 0)}
                for n, t in zip(col_names, col_types)
            ],
            "sample_rows": sample_rows,
        }

    conn.close()
    return {"tables": result}


# ---------------------------------------------------------------------------
# Ask / session / health
# ---------------------------------------------------------------------------

@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    session_id = req.session_id or str(uuid.uuid4())
    history = SESSIONS.get(session_id, [])

    initial_state = {
        "user_question": req.question,
        "chat_history": history,
        "retry_count": 0,
        "max_retries": MAX_RETRIES,
        "db_path": req.db_path,
    }

    final_state = compiled_graph.invoke(initial_state)

    if final_state.get("needs_clarification"):
        return AskResponse(
            session_id=session_id,
            needs_clarification=True,
            clarification_question=final_state.get("clarification_question"),
        )

    result = final_state.get("sql_result") or {}

    if final_state.get("business_summary"):
        history.append({"question": req.question, "answer": final_state["business_summary"]})
        SESSIONS[session_id] = history

    return AskResponse(
        session_id=session_id,
        needs_clarification=False,
        generated_sql=final_state.get("generated_sql"),
        columns=result.get("columns"),
        rows=result.get("rows"),
        row_count=result.get("row_count"),
        business_summary=final_state.get("business_summary"),
        chart_spec=final_state.get("chart_spec"),
        followup_questions=final_state.get("followup_questions", []),
        retry_count=final_state.get("retry_count", 0),
        error=final_state.get("error"),
    )


@app.post("/session/reset")
def reset_session(session_id: str):
    SESSIONS.pop(session_id, None)
    return {"status": "reset", "session_id": session_id}


@app.get("/health")
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# SQLite reserved keywords that commonly appear as column names in CSV exports
_SQLITE_KEYWORDS = {
    "index", "order", "group", "select", "table", "where", "from", "by",
    "as", "on", "in", "is", "not", "and", "or", "null", "true", "false",
    "case", "when", "then", "else", "end", "join", "left", "right", "inner",
    "outer", "full", "cross", "natural", "union", "all", "distinct", "limit",
    "offset", "having", "exists", "between", "like", "glob", "create",
    "drop", "insert", "update", "delete", "alter", "primary", "key",
    "unique", "check", "default", "references", "foreign", "constraint",
    "transaction", "commit", "rollback", "view", "trigger", "with", "recursive",
}


def _sanitise_name(name: str) -> str:
    """Convert a sheet/file name into a safe SQLite table name."""
    name = re.sub(r"[^\w]", "_", name.strip())
    if name and name[0].isdigit():
        name = "t_" + name
    return name.lower() or "data"


def _unique_table_name(base: str, db_path: str) -> str:
    """Ensure the table name doesn't collide with existing tables in the DB."""
    existing = set(_list_tables(db_path))
    name, counter = base, 1
    while name in existing:
        name = f"{base}_{counter}"
        counter += 1
    return name


def _sanitise_columns(columns: list) -> list:
    """Rename columns that are SQLite reserved keywords and replace special chars."""
    sanitised, seen = [], set()
    for col in columns:
        clean = re.sub(r"[^\w]", "_", str(col).strip()).strip("_")
        if not clean or clean[0].isdigit():
            clean = "col_" + clean
        if clean.lower() in _SQLITE_KEYWORDS:
            clean = clean + "_col"
        original, counter = clean, 1
        while clean.lower() in seen:
            clean = f"{original}_{counter}"
            counter += 1
        seen.add(clean.lower())
        sanitised.append(clean)
    return sanitised


def _list_tables(db_path: str) -> list[str]:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    tables = [row[0] for row in cur.fetchall()]
    conn.close()
    return tables


def _merge_sqlite(contents: bytes, target_db_path: str) -> None:
    """Copy all tables from an uploaded SQLite blob into the target session DB."""
    tmp_path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4().hex}_tmp.db")
    try:
        with open(tmp_path, "wb") as f:
            f.write(contents)
        src = sqlite3.connect(tmp_path)
        dst = sqlite3.connect(target_db_path)
        for line in src.iterdump():
            if line.startswith("INSERT") or line.startswith("CREATE TABLE"):
                try:
                    dst.execute(line)
                except sqlite3.Error:
                    pass
        dst.commit()
        src.close()
        dst.close()
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
