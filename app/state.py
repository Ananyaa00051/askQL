from typing import TypedDict, Optional, Any


class SQLAgentState(TypedDict, total=False):
    # input
    user_question: str
    chat_history: list[dict]        # [{\"question\": ..., \"answer\": ...}, ...] for memory
    db_path: Optional[str]          # override DB path (set when user uploads their own data)

    # planning
    intent: str
    needs_clarification: bool
    clarification_question: Optional[str]
    db_schema: str

    # sql lifecycle
    generated_sql: str
    is_valid: bool
    validation_error: Optional[str]
    sql_result: Optional[dict]
    execution_error: Optional[str]

    # retry loop
    retry_count: int
    max_retries: int

    # output
    business_summary: Optional[str]
    chart_spec: Optional[dict]
    followup_questions: list[str]

    # misc
    error: Optional[str]
