"""All settings come from environment variables (or a .env file next to this one)."""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).with_name(".env"))
except ImportError:
    pass

BASE = Path(__file__).parent

DATA_DIR = Path(os.getenv("DATA_DIR", BASE / "data"))          # folder with the CSV files
DB_PATH = Path(os.getenv("DB_PATH", BASE / "exchange.duckdb"))  # built by loader.py
LOG_PATH = Path(os.getenv("LOG_PATH", BASE / "logs" / "qa.jsonl"))

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")

# LLM: "anthropic" (Claude) or "openai" (any OpenAI-compatible API: OpenAI, OpenRouter, DeepSeek, Gemini...)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic").lower()
LLM_MODEL = os.getenv("LLM_MODEL", "claude-sonnet-5-5" if LLM_PROVIDER == "anthropic" else "gpt-4.1")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL") or None
LLM_FALLBACK_MODEL = os.getenv("LLM_FALLBACK_MODEL", "")  # used when the main model hits its rate limit

MAX_STEPS = int(os.getenv("MAX_STEPS", "12"))           # max tool calls per question
TIME_BUDGET = float(os.getenv("TIME_BUDGET", "60"))      # seconds of tool work before forcing an answer
HARD_TIMEOUT = float(os.getenv("HARD_TIMEOUT", "82"))    # the committee allows 90 s per answer
SQL_TIMEOUT = float(os.getenv("SQL_TIMEOUT", "15"))
MAX_ROWS = int(os.getenv("MAX_ROWS", "60"))              # rows of an SQL result shown to the model
HISTORY_TURNS = int(os.getenv("HISTORY_TURNS", "2"))     # previous Q/A pairs kept for follow-ups
