"""
db_connection.py
----------------
Provides a single reusable function to get a PostgreSQL connection.
All other scripts import from here instead of duplicating connection logic.
"""

import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

# Load .env from project root, forcing latin-1 encoding for Windows compatibility
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(env_path, encoding="latin-1")


def get_connection():
    """Return an open psycopg2 connection using the parameters from .env."""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "fc_metz_mini_projet"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD"),
    )