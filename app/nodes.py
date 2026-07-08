import sqlite3
from app.state import SQLAgentState
from app.database import get_full_schema, schema_to_prompt_string, run_query
from app.security import validate_sql
from app.llm import ask, ask_json, ask_sql
from app import prompts


def _history_to_text(history: list[dict]) -> str:
    if not history:
        return "(none yet)"
    lines = []
    for turn in history[-5:]:
        lines.append(f"Q: {turn['question']}\nA: {turn['answer']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------
# 1. Intent detection + ambiguity check + schema retrieval
# ---------------------------------------------------------------------
def detect_intent(state: SQLAgentState) -> SQLAgentState:
    db_path = state.get("db_path")
    schema = get_full_schema(db_path)
    schema_str = schema_to_prompt_string(schema)
    history_str = _history_to_text(state.get("chat_history", []))

    prompt = prompts.INTENT_PROMPT.format(
        schema=schema_str, history=history_str, question=state["user_question"]
    )
    try:
        result = ask_json(prompt)
    except Exception:
        result = {"intent": "general_query", "needs_clarification": False, "clarification_question": None}

    return {
        **state,
        "db_schema": schema_str,
        "intent": result.get("intent", "general_query"),
        "needs_clarification": bool(result.get("needs_clarification", False)),
        "clarification_question": result.get("clarification_question"),
    }


# ---------------------------------------------------------------------
# 2. SQL generation
# ---------------------------------------------------------------------
def generate_sql(state: SQLAgentState) -> SQLAgentState:
    prompt = prompts.SQL_GENERATION_PROMPT.format(
        schema=state["db_schema"],
        metrics=prompts.DEFAULT_METRICS,
        history=_history_to_text(state.get("chat_history", [])),
        question=state["user_question"],
    )
    sql = ask_sql(prompt)
    return {**state, "generated_sql": sql, "retry_count": state.get("retry_count", 0)}


# ---------------------------------------------------------------------
# 3. Validation (safety layer)
# ---------------------------------------------------------------------
def validate(state: SQLAgentState) -> SQLAgentState:
    is_valid, reason = validate_sql(state["generated_sql"])
    return {**state, "is_valid": is_valid, "validation_error": reason if not is_valid else None}


# ---------------------------------------------------------------------
# 4. Execution
# ---------------------------------------------------------------------
def execute(state: SQLAgentState) -> SQLAgentState:
    db_path = state.get("db_path")
    try:
        result = run_query(state["generated_sql"], db_path)
        return {**state, "sql_result": result, "execution_error": None}
    except sqlite3.Error as e:
        return {**state, "sql_result": None, "execution_error": str(e)}


def execution_router(state: SQLAgentState) -> str:
    if not state.get("is_valid", False):
        return "fail"
    if state.get("execution_error"):
        return "fail"
    return "success"


# ---------------------------------------------------------------------
# 5a. Error diagnosis + repair (failure branch)
# ---------------------------------------------------------------------
def repair_sql(state: SQLAgentState) -> SQLAgentState:
    error_message = state.get("execution_error") or state.get("validation_error") or "Unknown error"
    prompt = prompts.SQL_REPAIR_PROMPT.format(
        schema=state["db_schema"],
        question=state["user_question"],
        sql=state["generated_sql"],
        error=error_message,
    )
    repaired_sql = ask_sql(prompt)
    return {
        **state,
        "generated_sql": repaired_sql,
        "retry_count": state.get("retry_count", 0) + 1,
    }


def retry_router(state: SQLAgentState) -> str:
    max_retries = state.get("max_retries", 2)
    if state.get("retry_count", 0) >= max_retries:
        return "give_up"
    return "retry"


def give_up(state: SQLAgentState) -> SQLAgentState:
    err = state.get("execution_error") or state.get("validation_error") or "unknown error"
    return {
        **state,
        "error": f"Couldn't produce a working query after {state.get('retry_count', 0)} repair attempt(s). Last error: {err}",
        "business_summary": (
            "I wasn't able to reliably answer that question against the current schema. "
            f"Last database error: {err}. Try rephrasing with a specific metric, table, or "
            "time range, or check the Business Metrics Library for the right definition."
        ),
        "chart_spec": {"chart_type": "table", "x": None, "y": None, "reason": "no result"},
        "followup_questions": [],
    }


def interpret_results(state: SQLAgentState) -> SQLAgentState:
    result = state["sql_result"]
    preview = {"columns": result["columns"], "rows": result["rows"][:20]}
    prompt = prompts.INTERPRETATION_PROMPT.format(
        question=state["user_question"],
        sql=state["generated_sql"],
        result_preview=preview,
    )
    
    try:
        interpretation = ask_json(prompt)
    except Exception:
        interpretation = {
            "is_sufficient": True,
            "missing_columns_needed": [],
            "business_summary": "Failed to parse business summary."
        }
        
    is_sufficient = interpretation.get("is_sufficient", True)
    missing = interpretation.get("missing_columns_needed", [])
    summary = interpretation.get("business_summary", "")

    # Grounding check: if LLM says insufficient, force a repair loop if retries remain
    if not is_sufficient and missing and state.get("retry_count", 0) < state.get("max_retries", 2):
        return {
            **state,
            "business_summary": summary,
            "is_valid": False,
            "execution_error": f"The query did not return all necessary columns. Missing: {', '.join(missing)}. Please rewrite the query to SELECT these columns as well."
        }

    return {**state, "business_summary": summary}


def interpretation_router(state: SQLAgentState) -> str:
    # If interpret_results injected an execution_error due to missing columns, route back to repair
    if state.get("execution_error") and state.get("retry_count", 0) < state.get("max_retries", 2):
        return "repair"
    return "proceed"

# ---------------------------------------------------------------------
# 7. Auto visualization
# ---------------------------------------------------------------------
def generate_chart(state: SQLAgentState) -> SQLAgentState:
    result = state["sql_result"]
    if result["row_count"] == 0:
        return {**state, "chart_spec": {"chart_type": "table", "x": None, "y": None, "reason": "empty result"}}

    prompt = prompts.CHART_SPEC_PROMPT.format(
        columns=result["columns"],
        sample_rows=result["rows"][:5],
    )
    try:
        chart_spec = ask_json(prompt)
    except Exception:
        chart_spec = {"chart_type": "table", "x": None, "y": None, "reason": "fallback"}
    return {**state, "chart_spec": chart_spec}


# ---------------------------------------------------------------------
# 8. Follow-up question suggestions
# ---------------------------------------------------------------------
def generate_followups(state: SQLAgentState) -> SQLAgentState:
    prompt = prompts.FOLLOWUP_PROMPT.format(
        question=state["user_question"],
        summary=state.get("business_summary", ""),
    )
    try:
        followups = ask_json(prompt)
        if not isinstance(followups, list):
            followups = []
    except Exception:
        followups = []
    return {**state, "followup_questions": followups}
