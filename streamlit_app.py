import streamlit as st
import requests
import plotly.express as px
import pandas as pd

BACKEND_URL = "http://localhost:8001"

st.set_page_config(page_title="askQL", page_icon="📊", layout="wide")
st.title("📊 askQL")
st.caption("Ask your business a question in plain English.")

# ── Session state init ──────────────────────────────────────────────────────
if "session_id" not in st.session_state:
    st.session_state.session_id = None
if "messages" not in st.session_state:
    st.session_state.messages = []
if "db_path" not in st.session_state:
    st.session_state.db_path = None
if "db_tables" not in st.session_state:
    st.session_state.db_tables = []          # flat list of all table names
if "file_table_map" not in st.session_state:
    st.session_state.file_table_map = {}     # {filename: [table1, table2, ...]}
if "last_uploaded_name" not in st.session_state:
    st.session_state.last_uploaded_name = None
if "upload_error" not in st.session_state:
    st.session_state.upload_error = None


# ── Helpers ─────────────────────────────────────────────────────────────────
def render_chart(chart_spec, columns, rows):
    if not rows:
        st.info("No rows returned.")
        return
    df = pd.DataFrame(rows)
    chart_type = (chart_spec or {}).get("chart_type", "table")
    x = (chart_spec or {}).get("x")
    y = (chart_spec or {}).get("y")
    try:
        if chart_type == "line" and x in df.columns and y in df.columns:
            st.plotly_chart(px.line(df, x=x, y=y, markers=True), use_container_width=True)
        elif chart_type == "bar" and x in df.columns and y in df.columns:
            st.plotly_chart(px.bar(df, x=x, y=y), use_container_width=True)
        elif chart_type == "pie" and x in df.columns and y in df.columns:
            st.plotly_chart(px.pie(df, names=x, values=y), use_container_width=True)
        else:
            st.dataframe(df, use_container_width=True)
    except Exception:
        st.dataframe(df, use_container_width=True)


def ask_backend(question: str):
    payload = {
        "question": question,
        "session_id": st.session_state.session_id,
        "db_path": st.session_state.db_path,
    }
    resp = requests.post(f"{BACKEND_URL}/ask", json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()


def do_upload(file, existing_db_path=None):
    """POST file to /upload. Appends to existing_db_path if provided."""
    file_bytes = file.read()
    data = {}
    if existing_db_path:
        data["existing_db_path"] = existing_db_path
    resp = requests.post(
        f"{BACKEND_URL}/upload",
        files={"file": (file.name, file_bytes, "application/octet-stream")},
        data=data,
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def do_remove_table(table_name: str):
    """DELETE a single table from the session DB."""
    resp = requests.delete(
        f"{BACKEND_URL}/tables/{table_name}",
        params={"db_path": st.session_state.db_path},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def reset_all():
    if st.session_state.session_id:
        try:
            requests.post(
                f"{BACKEND_URL}/session/reset",
                params={"session_id": st.session_state.session_id},
            )
        except Exception:
            pass
    st.session_state.db_path = None
    st.session_state.db_tables = []
    st.session_state.file_table_map = {}
    st.session_state.session_id = None
    st.session_state.messages = []
    st.session_state.last_uploaded_name = None
    st.session_state.upload_error = None


# ── Sidebar ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("🗄️ Data Source")

    # ── Active table list ────────────────────────────────────────────────────
    if st.session_state.db_tables:
        st.markdown(f"**{len(st.session_state.db_tables)} table(s) loaded:**")

        for table in st.session_state.db_tables:
            col_name, col_btn = st.columns([4, 1])
            col_name.markdown(f"📋 `{table}`")
            if col_btn.button("✕", key=f"remove_{table}", help=f"Remove {table}"):
                try:
                    result = do_remove_table(table)
                    st.session_state.db_tables = result["tables"]
                    # Remove from file_table_map; drop file entry if now empty
                    for fname, tbls in list(st.session_state.file_table_map.items()):
                        if table in tbls:
                            tbls.remove(table)
                            if not tbls:
                                del st.session_state.file_table_map[fname]
                            break
                    if not st.session_state.db_tables:
                        st.session_state.db_path = None
                        st.session_state.session_id = None
                        st.session_state.messages = []
                    st.rerun()
                except Exception as e:
                    st.error(f"Could not remove table: {e}")

        st.divider()

        if st.button("🗑️ Clear all tables", use_container_width=True, type="secondary"):
            reset_all()
            st.rerun()

    else:
        st.info("📊 Using **Demo database**\n(customers, sales, invoices, campaigns)")

    st.divider()

    # ── Upload widget ────────────────────────────────────────────────────────
    if st.session_state.db_tables:
        upload_label = "➕ Add another file (appends tables)"
    else:
        upload_label = "📤 Upload Your Own Data"

    st.markdown(f"#### {upload_label}")
    st.caption("Supported: `.csv` · `.xlsx` · `.xls` · `.db` · `.sqlite`")

    if st.session_state.db_tables:
        st.caption("New tables will be **added** to your current session — existing tables are kept.")

    if st.session_state.upload_error:
        st.error(st.session_state.upload_error)

    uploaded = st.file_uploader(
        label="Choose a file",
        type=["csv", "xlsx", "xls", "db", "sqlite"],
        label_visibility="collapsed",
    )

    if uploaded is not None and uploaded.name != st.session_state.last_uploaded_name:
        st.session_state.upload_error = None
        with st.spinner(f"Uploading **{uploaded.name}**…"):
            try:
                # Append to existing session DB if one already exists
                result = do_upload(uploaded, existing_db_path=st.session_state.db_path)

                st.session_state.db_path = result["db_path"]
                st.session_state.db_tables = result["tables"]
                st.session_state.last_uploaded_name = uploaded.name

                # Record which tables came from this file
                new = result.get("new_tables", [])
                if new:
                    existing = st.session_state.file_table_map.get(uploaded.name, [])
                    st.session_state.file_table_map[uploaded.name] = existing + new

                # Reset conversation so context aligns with updated schema
                st.session_state.session_id = None
                st.session_state.messages = []

                st.success(
                    f"Added **{', '.join(new) if new else uploaded.name}**. "
                    f"Session now has **{len(result['tables'])}** table(s)."
                )
            except requests.exceptions.HTTPError as e:
                try:
                    detail = e.response.json().get("detail", str(e))
                except Exception:
                    detail = str(e)
                st.session_state.upload_error = f"Upload failed: {detail}"
                st.error(st.session_state.upload_error)
            except requests.exceptions.ConnectionError:
                st.session_state.upload_error = (
                    f"Cannot connect to backend at {BACKEND_URL}. "
                    "Is `uvicorn main:app --port 8001` running?"
                )
                st.error(st.session_state.upload_error)
            except Exception as e:
                st.session_state.upload_error = f"Unexpected error: {e}"
                st.error(st.session_state.upload_error)

    st.divider()

    # ── About + examples ─────────────────────────────────────────────────────
    st.header("ℹ️ About")
    st.markdown(
        "askQL turns plain-English questions into safe, "
        "read-only SQL, explains results, draws charts, and suggests follow-ups."
    )

    if not st.session_state.db_tables:
        st.markdown("**Try asking (demo data):**")
        for example in [
            "What was our revenue in Q2?",
            "Which customers churned?",
            "Top campaigns by ROAS",
            "How many invoices are unpaid?",
        ]:
            st.markdown(f"- {example}")
    else:
        st.markdown("**Tips for your data:**")
        st.markdown(
            "- Reference any table shown above in your question\n"
            "- Ask cross-table questions: *'JOIN customers and orders'*\n"
            "- *'Show first 10 rows of [table]'* to explore\n"
            "- Follow up with *'only [filter]'* to narrow results"
        )

    if st.button("🔄 Reset conversation", use_container_width=True):
        if st.session_state.session_id:
            try:
                requests.post(
                    f"{BACKEND_URL}/session/reset",
                    params={"session_id": st.session_state.session_id},
                )
            except Exception:
                pass
        st.session_state.session_id = None
        st.session_state.messages = []
        st.rerun()


# ── Data Summary Panel (tabbed, one tab per uploaded file) ──────────────────
if st.session_state.db_tables and st.session_state.file_table_map:

    @st.cache_data(ttl=10, show_spinner=False)
    def fetch_schema(db_path: str) -> dict:
        try:
            r = requests.get(f"{BACKEND_URL}/schema", params={"db_path": db_path}, timeout=10)
            r.raise_for_status()
            return r.json().get("tables", {})
        except Exception:
            return {}

    schema_data = fetch_schema(st.session_state.db_path)

    def render_table_summary(tname: str, schema_data: dict):
        """Render column cards + sample rows for a single table."""
        tinfo = schema_data.get(tname)
        if not tinfo:
            st.warning(f"No schema info for `{tname}` yet. Try re-uploading.")
            return

        row_count = tinfo.get("row_count", 0)
        cols      = tinfo.get("columns", [])
        sample    = tinfo.get("sample_rows", [])

        # Table header
        h1, h2 = st.columns([5, 1])
        h1.markdown(f"#### 🗂️ `{tname}`")
        h2.markdown(
            f"<div style='text-align:right;margin-top:10px;'>"
            f"<span style='background:#1f77b4;color:white;padding:3px 10px;"
            f"border-radius:12px;font-size:12px;'>{row_count:,} rows</span></div>",
            unsafe_allow_html=True,
        )

        # Column cards (3 per row)
        col_groups = [cols[i:i+3] for i in range(0, len(cols), 3)]
        for group in col_groups:
            gcols = st.columns(len(group))
            for gcol, cinfo in zip(gcols, group):
                cname    = cinfo["name"]
                ctype    = (cinfo.get("type") or "TEXT").upper()
                nulls    = cinfo.get("null_count", 0)
                pct_null = (nulls / row_count * 100) if row_count else 0
                colour   = {
                    "INTEGER": "#e67e22", "REAL": "#e67e22", "NUMERIC": "#e67e22",
                    "TEXT": "#27ae60", "BLOB": "#8e44ad",
                }.get(ctype, "#7f8c8d")
                null_html = (
                    f"<br><span style='color:#e74c3c;font-size:10px;'>⚠ {pct_null:.0f}% null</span>"
                    if pct_null > 0 else ""
                )
                gcol.markdown(
                    f"<div style='background:#1e1e2e;border-radius:8px;padding:8px 10px;"
                    f"margin-bottom:6px;border-left:3px solid {colour};'>"
                    f"<b style='font-size:13px;'>{cname}</b><br>"
                    f"<span style='color:{colour};font-size:11px;'>{ctype}</span>"
                    f"{null_html}</div>",
                    unsafe_allow_html=True,
                )

        # Sample rows
        if sample:
            st.caption("Sample rows:")
            st.dataframe(pd.DataFrame(sample), use_container_width=True, hide_index=True)

    st.markdown("### 📊 Data Summary")

    file_names = list(st.session_state.file_table_map.keys())
    tabs = st.tabs([f"📁 {fname}" for fname in file_names])

    for tab, fname in zip(tabs, file_names):
        with tab:
            tables_in_file = st.session_state.file_table_map[fname]
            if len(tables_in_file) == 1:
                # Single table — render directly
                render_table_summary(tables_in_file[0], schema_data)
            else:
                # Multiple tables (e.g. multi-sheet Excel) — nested tabs
                inner_tabs = st.tabs([f"🗂️ {t}" for t in tables_in_file])
                for itab, tname in zip(inner_tabs, tables_in_file):
                    with itab:
                        render_table_summary(tname, schema_data)

    st.divider()

# ── Chat history ─────────────────────────────────────────────────────────────
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        extra = msg.get("extra")
        if extra:
            with st.expander("Generated SQL & execution details"):
                st.code(extra.get("generated_sql", ""), language="sql")
                st.caption(
                    f"Rows returned: {extra.get('row_count', 0)} | "
                    f"Repair attempts: {extra.get('retry_count', 0)}"
                )
            if extra.get("rows"):
                render_chart(extra.get("chart_spec"), extra.get("columns"), extra.get("rows"))
            if extra.get("followup_questions"):
                st.markdown("**You might also ask:**")
                for i, fq in enumerate(extra["followup_questions"]):
                    st.button(fq, key=f"followup_{msg['content'][:10]}_{i}")


# ── Chat input ───────────────────────────────────────────────────────────────
if st.session_state.db_tables:
    tables_str = ", ".join(st.session_state.db_tables)
    placeholder = f"Ask about: {tables_str}…"
else:
    placeholder = "e.g. What was our revenue in Q2?"

question = st.chat_input(placeholder)

if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            try:
                data = ask_backend(question)
            except requests.exceptions.ConnectionError:
                st.error(
                    f"Cannot reach the backend at {BACKEND_URL}. "
                    "Make sure `uvicorn main:app --port 8001` is running."
                )
                st.stop()
            except requests.exceptions.RequestException as e:
                st.error(f"Backend error: {e}")
                st.stop()

        st.session_state.session_id = data.get("session_id")

        if data.get("needs_clarification"):
            answer = data.get("clarification_question") or "Could you clarify?"
            st.markdown(f"🤔 {answer}")
            st.session_state.messages.append({"role": "assistant", "content": f"🤔 {answer}"})
        elif data.get("error"):
            st.markdown(f"⚠️ {data['error']}")
            st.session_state.messages.append({"role": "assistant", "content": f"⚠️ {data['error']}"})
        else:
            summary = data.get("business_summary", "")
            st.markdown(summary)
            with st.expander("Generated SQL & execution details"):
                st.code(data.get("generated_sql", ""), language="sql")
                st.caption(
                    f"Rows returned: {data.get('row_count', 0)} | "
                    f"Repair attempts: {data.get('retry_count', 0)}"
                )
            if data.get("rows"):
                render_chart(data.get("chart_spec"), data.get("columns"), data.get("rows"))
            if data.get("followup_questions"):
                st.markdown("**You might also ask:**")
                for fq in data["followup_questions"]:
                    st.button(fq)

            st.session_state.messages.append({
                "role": "assistant",
                "content": summary,
                "extra": data,
            })
