import os
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
MODEL_NAME = os.getenv("MODEL_NAME", "claude-sonnet-5")
DB_PATH = os.getenv("DB_PATH", "data/querypilot.db")
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "2"))
MAX_ROWS_RETURNED = int(os.getenv("MAX_ROWS_RETURNED", "200"))

if not GROQ_API_KEY:
    print("[warning] GROQ_API_KEY is not set. Copy .env.example to .env and add your key.")
