"""Конфигурация RAG системы ПТЭ/ИДП"""

import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent
DOCX_PATH = PROJECT_ROOT / "data" / "для RAG птэ вариант 2.docx"

load_dotenv(PROJECT_ROOT / ".env")

MINMAX_URL = os.getenv("MINMAX_URL", "http://172.22.100.48:8000/v1/chat/completions")
MINMAX_MODEL = os.getenv("MINMAX_MODEL", "minimax-m2.7")

CHUNK_SIZE = 2000
CHUNK_OVERLAP = 300

API_TIMEOUT = 60
TEMPERATURE = 0.1
MAX_TOKENS = 100