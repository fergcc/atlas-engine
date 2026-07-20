"""
SQLite database initialization and helpers.

Tables:
  - series_cache: raw time series fetched from APIs
  - llm_cache: DeepSeek responses keyed by prompt hash
  - search_cache: SearchAPI results keyed by query hash
  - pipeline_runs: metadata about each batch execution
  - indicator_values: computed 34-indicator values per region
"""

from __future__ import annotations

import sqlite3
import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS series_cache (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    country TEXT NOT NULL,
    region_code TEXT NOT NULL,
    sector_id TEXT NOT NULL,
    frequency TEXT NOT NULL,
    observations_json TEXT NOT NULL,
    vintage_date TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS llm_cache (
    prompt_hash TEXT PRIMARY KEY,
    model TEXT NOT NULL,
    prompt TEXT NOT NULL,
    response_json TEXT NOT NULL,
    tokens_input INTEGER,
    tokens_output INTEGER,
    cost_estimate REAL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS search_cache (
    query_hash TEXT PRIMARY KEY,
    engine TEXT NOT NULL DEFAULT 'searchapi',
    query TEXT NOT NULL,
    results_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT,
    mode TEXT NOT NULL DEFAULT 'mock',
    status TEXT NOT NULL DEFAULT 'running',
    pairs_total INTEGER DEFAULT 0,
    pairs_real INTEGER DEFAULT 0,
    pairs_mock INTEGER DEFAULT 0,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS indicator_values (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    country TEXT NOT NULL,
    region_code TEXT NOT NULL,
    indicator_id TEXT NOT NULL,
    sector_id TEXT,
    value REAL,
    unit TEXT,
    year INTEGER,
    source TEXT,
    computed_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(country, region_code, indicator_id, sector_id, year)
);

CREATE INDEX IF NOT EXISTS idx_series_cache_country
    ON series_cache(country);
CREATE INDEX IF NOT EXISTS idx_series_cache_sector
    ON series_cache(sector_id);
CREATE INDEX IF NOT EXISTS idx_llm_cache_model
    ON llm_cache(model);
CREATE INDEX IF NOT EXISTS idx_indicator_values_country
    ON indicator_values(country, indicator_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status
    ON pipeline_runs(status);
"""


def init_db(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def hash_prompt(prompt: str, model: str = "") -> str:
    return hashlib.sha256(f"{model}:{prompt}".encode()).hexdigest()


def hash_query(query: str, engine: str = "searchapi") -> str:
    return hashlib.sha256(f"{engine}:{query}".encode()).hexdigest()


def cache_llm_response(
    conn: sqlite3.Connection,
    prompt: str,
    response: dict[str, Any],
    model: str = "deepseek-chat",
    tokens_input: int | None = None,
    tokens_output: int | None = None,
) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO llm_cache
           (prompt_hash, model, prompt, response_json, tokens_input, tokens_output)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            hash_prompt(prompt, model),
            model,
            prompt,
            json.dumps(response, ensure_ascii=False),
            tokens_input,
            tokens_output,
        ),
    )
    conn.commit()


def get_llm_cache(
    conn: sqlite3.Connection, prompt: str, model: str = "deepseek-chat"
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT response_json FROM llm_cache WHERE prompt_hash = ?",
        (hash_prompt(prompt, model),),
    ).fetchone()
    if row:
        return json.loads(row[0])
    return None


def cache_search_response(
    conn: sqlite3.Connection,
    query: str,
    results: dict[str, Any],
    engine: str = "searchapi",
) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO search_cache
           (query_hash, engine, query, results_json)
           VALUES (?, ?, ?, ?)""",
        (hash_query(query, engine), engine, query, json.dumps(results, ensure_ascii=False)),
    )
    conn.commit()


def get_search_cache(
    conn: sqlite3.Connection, query: str, engine: str = "searchapi"
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT results_json FROM search_cache WHERE query_hash = ?",
        (hash_query(query, engine),),
    ).fetchone()
    if row:
        return json.loads(row[0])
    return None
