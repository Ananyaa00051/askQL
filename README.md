# askQL

Ask your business a question in plain English. Get SQL, a chart, a plain-English
explanation, and suggested follow-up questions — with a self-correcting agent
underneath and a read-only safety layer so it can never touch your data.

This is a working, simplified build of the full askQL spec, tuned to
run on one laptop with a single LangGraph workflow instead of a distributed
system. Everything in the "Simplified vs. spec" section below is a deliberate
cut to keep the code readable — the architecture is built so you can add each
piece back incrementally.

## Architecture

```
User question
     │
     ▼
detect_intent  ──(ambiguous)──► ask for clarification, stop
     │ (clear)
     ▼
generate_sql
     │
     ▼
validate (read-only safety check)
     │
     ▼
execute
     │
     ├── success ──► interpret_results ──► generate_chart ──► generate_followups ──► done
     │
     └── fail ──► repair_sql ──► (retry, up to MAX_RETRIES) ──► validate
                        │
                        └── (retries exhausted) ──► give_up ──► done
```

This mirrors the LangGraph node graph in the original spec 1:1 — intent
detection, schema retrieval, SQL generation, validation, execution, the
success/failure branches, error diagnosis + repair, interpretation,
visualization, and follow-up generation are all separate nodes so you can
inspect or swap any one of them independently.

## Project layout

```text
askQL/
  app/
    config.py       # env vars
    database.py      # SQLite connector + schema introspection + query executor
    security.py      # read-only SQL safety validator
    state.py         # LangGraph state schema (TypedDict)
    prompts.py        # every prompt template used by the agent
    llm.py            # thin Anthropic API wrapper (text / JSON / SQL helpers)
    nodes.py           # the 9 LangGraph node functions
    graph.py            # wires the nodes into the StateGraph above
  main.py              # FastAPI backend (`/ask`, `/upload`, `/schema` endpoints)
  streamlit_app.py     # chat UI with charts, multi-file uploads, SQL inspector, follow-ups
  seed_db.py           # creates a demo SQLite DB (customers/sales/invoices/campaigns)
  requirements.txt
  .env.example
```

## Setup

```bash
cd querypilot-ai
python -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -r requirements.txt

cp .env.example .env
# edit .env and paste your ANTHROPIC_API_KEY (from console.anthropic.com)

python seed_db.py          # creates data/querypilot.db with sample data
```

Run the backend and frontend in two terminals:

```bash
# terminal 1
uvicorn main:app --reload --port 8000

# terminal 2
streamlit run streamlit_app.py
```

Open the Streamlit URL it prints (usually http://localhost:8501) and try:

- "What was our revenue in Q2?"
- "Which customers churned?"
- "Top campaigns by ROAS"
- "How many invoices are unpaid?"
- Then a follow-up like "only Europe" — the agent uses conversational memory
  to know that's a filter on the previous question.

## How each spec feature is implemented

| Spec feature | Where it lives |
|---|---|
| NL → SQL | `nodes.generate_sql` + `prompts.SQL_GENERATION_PROMPT` |
| Semantic SQL Retrieval | Finance, campaign, and variance queries are dynamically prompted to fetch full conceptual context (`prompts.SQL_GENERATION_PROMPT`). |
| Automatic SQL repair | `nodes.repair_sql` + `retry_router` (loops back to `validate`, capped by `MAX_RETRIES`) |
| Schema understanding | `database.get_full_schema` — supports multi-file uploads natively. |
| Strict Grounding Validation | `nodes.interpret_results` dynamically validates if the SQL output contained enough columns. If missing data, it routes back to `repair_sql` via `interpretation_router`. |
| Business interpretation | `nodes.interpret_results` |
| Auto visualization | `nodes.generate_chart` picks line/bar/pie/table; rendered with Plotly in Streamlit |
| Follow-up questions | `nodes.generate_followups`, rendered as clickable buttons |
| Query memory | `main.py`'s `SESSIONS` dict, passed into the prompt as `chat_history` |
| Custom Data Uploads | Dynamic DataFrame loading (`streamlit_app.py`), appending to a unified SQLite `_session.db` (`main.py`) across `.csv` and `.xlsx` files. |
| Explanation mode | The Streamlit "Generated SQL & execution details" expander shows SQL, row count, and repair attempts on every answer |
| SQL safety layer | `security.validate_sql` — hard-blocks anything that isn't a single `SELECT`/`WITH` statement |
| Ambiguity detection | `nodes.detect_intent` returns `needs_clarification`, which short-circuits the graph straight to a clarifying question |
| Business metrics library | `prompts.DEFAULT_METRICS` — a plain string today; see below for making it editable |

## Simplified vs. the original spec (and how to extend)

The original spec describes an enterprise-grade product. To keep this a
runnable, readable codebase, a few things were simplified on purpose:

1. **Schema retrieval is "load everything," not vector search.** With 4 demo
   tables this is instant. For a real enterprise DB with hundreds of tables,
   replace `database.get_full_schema()` with an embeddings-based retriever:
   embed each table's name + column list once (Chroma or FAISS, as the spec
   suggests), then at query time embed the question and pull the top-k most
   similar tables into the prompt instead of the whole schema.

2. **Memory is an in-memory Python dict, not Redis.** Fine for one backend
   process. If you deploy with multiple workers or need memory to survive a
   restart, swap `SESSIONS` in `main.py` for a Redis-backed session store —
   the interface (`get`/`set` on a `session_id` key) stays the same.

3. **Business Metrics Library is a static string.** `prompts.DEFAULT_METRICS`
   is what teaches the agent that "revenue" means `SUM(sales_amount)`. To make
   it editable by finance without touching code, put these definitions in a
   small `metrics` table in the same database and load them dynamically in
   `nodes.generate_sql` instead of importing the constant.

4. **One database, SQLite.** `database.py` is the only file that knows about
   SQLite. Swapping to Postgres/MySQL/Snowflake means changing
   `get_connection()`, `get_full_schema()`, and `run_query()` there — nothing
   else in the app touches the DB directly.

5. **No auth, audit log, or role-based access control.** This is a Phase 4
   ("Enterprise") item in the original roadmap. Adding FastAPI middleware for
   an API key or JWT check on `/ask`, plus a log line per query (question,
   generated SQL, user, timestamp) is a natural next step before this goes
   near real company data.

6. **Single LLM for every step.** Every node calls the same `MODEL_NAME`. If
   you want to cut cost, point `INTENT_PROMPT`/`FOLLOWUP_PROMPT` calls (which
   don't need much reasoning) at `claude-haiku-4-5-20251001`, and keep
   `claude-sonnet-5` for SQL generation and repair where accuracy matters
   most. That's a one-line change per call site in `nodes.py`.

## A note on the safety layer

`security.validate_sql` is a hard Python-level gate, not a prompt
instruction — it runs after the LLM generates SQL and before anything touches
the database. It rejects anything that isn't a single `SELECT`/`WITH`
statement and blocks `DROP/DELETE/UPDATE/ALTER/TRUNCATE/INSERT/CREATE` and a
few other keywords outright, plus stacked statements (`SELECT ...; DROP
...`). Treat this as a floor, not a ceiling — for production use, also run
the DB user itself with read-only grants as a second layer of defense.
