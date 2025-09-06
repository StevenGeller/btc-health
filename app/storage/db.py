"""Database connection and helper functions for Bitcoin Health Scorecard."""

import os
import sqlite3
import json
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone
import logging
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# Database configuration
DB_PATH = os.getenv('DB_PATH', 'data/btc_health.db')


class JSONEncoder(json.JSONEncoder):
    """Custom JSON encoder for database storage."""
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def dict_factory(cursor, row):
    """Convert SQLite rows to dictionaries."""
    fields = [column[0] for column in cursor.description]
    return {key: value for key, value in zip(fields, row)}


@contextmanager
def get_db():
    """Context manager for database connections."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = dict_factory
    
    # Enable JSON support
    conn.execute("PRAGMA foreign_keys = ON")
    
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Database error: {e}")
        raise
    finally:
        conn.close()


def init_db():
    """Initialize database with schema."""
    schema_path = Path(__file__).parent / 'schema.sql'
    
    with open(schema_path, 'r') as f:
        schema = f.read()
    
    with get_db() as conn:
        conn.executescript(schema)
        logger.info("Database initialized successfully")


def execute_query(query: str, params: Optional[Tuple] = None) -> List[Dict]:
    """Execute a SELECT query and return results."""
    with get_db() as conn:
        cursor = conn.cursor()
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
        return cursor.fetchall()


def execute_insert(query: str, params: Tuple) -> int:
    """Execute an INSERT query and return last row id."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.lastrowid


def execute_many(query: str, params_list: List[Tuple]) -> int:
    """Execute multiple INSERT queries."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.executemany(query, params_list)
        return cursor.rowcount


def upsert_metric(metric_id: str, value: float, ts: Optional[int] = None, unit: Optional[str] = None):
    """Insert or update a metric value."""
    if ts is None:
        ts = int(datetime.now(timezone.utc).timestamp())
    
    query = """
        INSERT OR REPLACE INTO metrics (metric_id, ts, value, unit)
        VALUES (?, ?, ?, ?)
    """
    execute_insert(query, (metric_id, ts, value, unit))


def upsert_score(kind: str, id: str, score: float, ts: Optional[int] = None,
                 trend_7d: Optional[float] = None, trend_30d: Optional[float] = None):
    """Insert or update a score."""
    if ts is None:
        ts = int(datetime.now(timezone.utc).timestamp())
    
    query = """
        INSERT OR REPLACE INTO scores (kind, id, ts, score, trend_7d, trend_30d)
        VALUES (?, ?, ?, ?, ?, ?)
    """
    execute_insert(query, (kind, id, ts, score, trend_7d, trend_30d))


def get_latest_metric(metric_id: str) -> Optional[Dict]:
    """Get the most recent value for a metric."""
    query = """
        SELECT * FROM metrics 
        WHERE metric_id = ? 
        ORDER BY ts DESC 
        LIMIT 1
    """
    results = execute_query(query, (metric_id,))
    return results[0] if results else None


def get_metric_history(metric_id: str, days: int = 30) -> List[Dict]:
    """Get metric history for specified number of days."""
    cutoff = int(datetime.now(timezone.utc).timestamp()) - (days * 86400)
    query = """
        SELECT * FROM metrics 
        WHERE metric_id = ? AND ts >= ?
        ORDER BY ts ASC
    """
    return execute_query(query, (metric_id, cutoff))


def get_latest_scores(kind: Optional[str] = None) -> List[Dict]:
    """Get latest scores, optionally filtered by kind."""
    if kind:
        query = "SELECT * FROM latest_scores WHERE kind = ?"
        return execute_query(query, (kind,))
    else:
        query = "SELECT * FROM latest_scores"
        return execute_query(query)


def update_collection_status(collector: str, success: bool, error: Optional[str] = None):
    """Update the status of a data collector."""
    ts = int(datetime.now(timezone.utc).timestamp())
    
    if success:
        query = """
            INSERT OR REPLACE INTO collection_status 
            (collector, last_run, last_success, last_error, consecutive_failures)
            VALUES (?, ?, ?, NULL, 0)
        """
        execute_insert(query, (collector, ts, ts))
    else:
        # Increment failure count
        query = """
            INSERT INTO collection_status (collector, last_run, last_error, consecutive_failures)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(collector) DO UPDATE SET
                last_run = excluded.last_run,
                last_error = excluded.last_error,
                consecutive_failures = consecutive_failures + 1
        """
        execute_insert(query, (collector, ts, error))


def store_json_data(table: str, data: Dict, ts: Optional[int] = None):
    """Store JSON data in a raw table."""
    # Some tables use 'day' instead of 'ts' as primary key
    day_tables = ['raw_block_rewards', 'raw_utxo_count', 'raw_ln_stats', 'raw_segwit_stats']
    
    if table in day_tables and 'day' not in data:
        # These tables use 'day' as primary key, not 'ts'
        pass
    elif ts is None and table not in day_tables:
        ts = int(datetime.now(timezone.utc).timestamp())
    
    # Convert dict values to JSON strings where needed
    processed_data = {}
    for key, value in data.items():
        if isinstance(value, (dict, list)):
            processed_data[key] = json.dumps(value, cls=JSONEncoder)
        else:
            processed_data[key] = value
    
    # Build dynamic INSERT query
    columns = list(processed_data.keys())
    if table not in day_tables and 'ts' not in columns:
        columns.insert(0, 'ts')
        values = [ts] + list(processed_data.values())
    else:
        values = list(processed_data.values())
    
    placeholders = ','.join(['?' for _ in values])
    column_names = ','.join(columns)
    
    query = f"INSERT OR REPLACE INTO {table} ({column_names}) VALUES ({placeholders})"
    execute_insert(query, tuple(values))


def get_percentiles(metric_id: str, window_days: int = 365) -> Optional[Dict]:
    """Get the latest percentiles for a metric."""
    query = """
        SELECT * FROM percentiles 
        WHERE metric_id = ? AND window_days = ?
        ORDER BY ts DESC 
        LIMIT 1
    """
    results = execute_query(query, (metric_id, window_days))
    return results[0] if results else None


def store_percentiles(metric_id: str, window_days: int, percentiles: Dict, ts: Optional[int] = None):
    """Store computed percentiles."""
    if ts is None:
        ts = int(datetime.now(timezone.utc).timestamp())
    
    query = """
        INSERT OR REPLACE INTO percentiles 
        (metric_id, window_days, ts, p10, p25, p50, p75, p90, min_val, max_val)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    execute_insert(query, (
        metric_id, window_days, ts,
        percentiles.get('p10'), percentiles.get('p25'), percentiles.get('p50'),
        percentiles.get('p75'), percentiles.get('p90'),
        percentiles.get('min'), percentiles.get('max')
    ))


def update_meta_config(key: str, value: str):
    """Update metadata configuration."""
    ts = int(datetime.now(timezone.utc).timestamp())
    query = """
        INSERT OR REPLACE INTO meta_config (key, value, updated_at)
        VALUES (?, ?, ?)
    """
    execute_insert(query, (key, value, ts))


def get_meta_config(key: str) -> Optional[str]:
    """Get metadata configuration value."""
    query = "SELECT value FROM meta_config WHERE key = ?"
    results = execute_query(query, (key,))
    return results[0]['value'] if results else None


# Utility functions for specific data types

def get_recent_pool_shares(hours: int = 24) -> List[Dict]:
    """Get recent mining pool share data."""
    cutoff = int(datetime.now(timezone.utc).timestamp()) - (hours * 3600)
    query = """
        SELECT * FROM raw_pool_shares 
        WHERE ts >= ?
        ORDER BY ts DESC, share DESC
    """
    return execute_query(query, (cutoff,))


def get_recent_mempool_snapshots(hours: int = 1) -> List[Dict]:
    """Get recent mempool snapshots."""
    cutoff = int(datetime.now(timezone.utc).timestamp()) - (hours * 3600)
    query = """
        SELECT * FROM raw_mempool_snapshot 
        WHERE ts >= ?
        ORDER BY ts DESC
    """
    return execute_query(query, (cutoff,))


def get_stale_incidents(days: int = 30) -> List[Dict]:
    """Get recent stale block incidents."""
    cutoff = int(datetime.now(timezone.utc).timestamp()) - (days * 86400)
    query = """
        SELECT * FROM raw_stale_incidents 
        WHERE ts >= ?
        ORDER BY ts DESC
    """
    return execute_query(query, (cutoff,))
