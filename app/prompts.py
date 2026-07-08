INTENT_PROMPT = """You are the intent-detection step of a business intelligence assistant.
Given the user's question and the database schema, decide:

1. Is the question answerable as a read-only SQL query against this schema?
2. Is it too ambiguous to safely turn into SQL (e.g. "show revenue" with no
   dimension, time range, or metric definition specified)?

Schema:
{schema}

Conversation so far (most recent last, may be empty):
{history}

Question: "{question}"

Respond ONLY with JSON, no preamble, no markdown fences:
{{
  "intent": "short label like 'revenue_trend' or 'churn_analysis'",
  "needs_clarification": true or false,
  "clarification_question": "a single clarifying question if needs_clarification is true, else null"
}}
"""

SQL_GENERATION_PROMPT = """You are a senior data analyst writing SQLite queries.

Schema (only these tables/columns exist -- never invent columns):
{schema}

Business metric definitions (use these exact formulas when the question
mentions these terms):
{metrics}

Conversation history for context (e.g. "only Europe" refers to a filter on
the previous question):
{history}

Question: "{question}"

Rules:
- Write exactly one SQLite SELECT statement. No explanations, no markdown fences.
- Never use DROP/DELETE/UPDATE/ALTER/INSERT/CREATE.
- Use explicit column names, not SELECT *.
- If the question implies a time series, include the relevant date/month column.
- CRITICAL — Text / category filters: ALWAYS use case-insensitive matching.
  Use: LOWER(column) LIKE LOWER('%user_value%')
  NEVER use: column = "exact value" for string columns.
  Example: user says "plastics industry" → WHERE LOWER(Industry) LIKE '%plastics%'
- CRITICAL — Numeric comparisons: use >, <, >=, <=, = directly on numeric columns.
  Example: "1000+ employees" → WHERE Number_of_employees >= 1000
- For counting questions ("how many"), use COUNT(*) and return a single number.
- Column names in the DB use underscores for spaces (e.g. "Number of employees" → Number_of_employees).
- CRITICAL — Semantic column selection: Automatically retrieve all relevant contextual columns. 
  - Invoice/Balance questions MUST retrieve invoice amounts, amounts paid, outstanding balances (computed if needed), payment status, and dates.
  - Variance questions MUST retrieve budget and actual spend.
  - Campaign questions MUST retrieve impressions, clicks, spend, and budget.
- Output ONLY the raw SQL.
"""

SQL_REPAIR_PROMPT = """The following SQLite query failed or was insufficient.

Schema:
{schema}

Original question: "{question}"

Failed SQL:
{sql}

Database error / Feedback:
{error}

Diagnose what's wrong (e.g. column/table name mismatch, syntax issue, or missing required columns) and output a corrected SQLite SELECT statement only.
No explanations, no markdown fences, just the corrected SQL.
"""

INTERPRETATION_PROMPT = """You are a business analyst explaining query results to a
non-technical executive.

Question: "{question}"
SQL used: {sql}
Result (columns and up to 20 rows as JSON): {result_preview}

Rules:
1. ONLY use data present in the SQL result.
2. NEVER invent numbers.
3. NEVER assume missing values (e.g. if invoice_amount is not returned, do not discuss invoice value).
4. If the SQL result lacks necessary information to answer the question, explicitly state that it cannot be determined.

Respond ONLY with JSON matching this structure:
{{
  "is_sufficient": true | false,
  "missing_columns_needed": ["column1", "column2"] /* if is_sufficient is false, else [] */,
  "business_summary": "Write a short (2-4 sentence) plain-English business summary. Call out the key number, trend, or standout segment. If the result set is empty or insufficient, state plainly that the information cannot be determined from the retrieved columns and why."
}}
"""

CHART_SPEC_PROMPT = """Given this query result, decide the best chart type to
visualize it for a business dashboard.

Columns: {columns}
Sample rows (up to 5): {sample_rows}

Respond ONLY with JSON:
{{
  "chart_type": "line" | "bar" | "pie" | "table",
  "x": "column name to use for x-axis / categories (or null)",
  "y": "column name to use for y-axis / values (or null)",
  "reason": "one short sentence"
}}

Guidance: time series (has a date/month column) -> line. Category comparison
-> bar. Share-of-total with few categories (<=6) -> pie. Anything else, or
result has only 1 row, or more than 2 relevant columns -> table.
"""

FOLLOWUP_PROMPT = """Question: "{question}"
Business summary just given to the user: "{summary}"

Suggest exactly 3 short, specific follow-up questions a business user might
naturally ask next (e.g. drill into a segment, compare periods, find the
cause). Respond ONLY with a JSON list of 3 strings, no preamble.
"""

DEFAULT_METRICS = """- Revenue = SUM(sales_amount) from the sales table
- Churn rate = COUNT(customers WHERE churned = 1) / COUNT(all customers)
- Overdue invoices = invoices WHERE paid = 0 AND due_date < today
- ROAS (return on ad spend) = revenue_attributed / spend from campaigns
"""
