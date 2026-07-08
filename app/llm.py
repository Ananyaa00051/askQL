import json
import re
import groq
from app.config import GROQ_API_KEY, MODEL_NAME

_client = groq.Groq(api_key=GROQ_API_KEY)


def ask(prompt: str, max_tokens: int = 1000) -> str:
    """Single-turn call to Groq. Returns the raw text response."""
    response = _client.chat.completions.create(
        model=MODEL_NAME,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content.strip()


def ask_json(prompt: str, max_tokens: int = 1000) -> dict | list:
    """Calls the model and parses the response as JSON, stripping any
    accidental markdown fences the model adds despite instructions."""
    raw = ask(prompt, max_tokens=max_tokens)
    cleaned = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    return json.loads(cleaned)


def ask_sql(prompt: str, max_tokens: int = 500) -> str:
    """Calls the model expecting raw SQL back, strips fences/labels."""
    raw = ask(prompt, max_tokens=max_tokens)
    cleaned = re.sub(r"^```(sql)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    return cleaned.rstrip(";").strip()
