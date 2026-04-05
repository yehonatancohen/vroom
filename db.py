import sqlite3
import json
from datetime import datetime
from typing import Optional
from config import DB_PATH, DEFAULT_CONFIG


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS seen_listings (
                listing_id TEXT PRIMARY KEY,
                seen_at    TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_config (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)


def mark_seen(listing_ids: list[str]):
    if not listing_ids:
        return
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO seen_listings (listing_id, seen_at) VALUES (?, ?)",
            [(lid, now) for lid in listing_ids],
        )


def is_seen(listing_id: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM seen_listings WHERE listing_id = ?", (listing_id,)
        ).fetchone()
    return row is not None


def filter_new(listing_ids: list[str]) -> list[str]:
    if not listing_ids:
        return []
    placeholders = ",".join("?" * len(listing_ids))
    with get_conn() as conn:
        seen = {
            row[0]
            for row in conn.execute(
                f"SELECT listing_id FROM seen_listings WHERE listing_id IN ({placeholders})",
                listing_ids,
            )
        }
    return [lid for lid in listing_ids if lid not in seen]


def get_config() -> dict:
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM user_config").fetchall()
    cfg = dict(DEFAULT_CONFIG)
    for row in rows:
        try:
            cfg[row["key"]] = json.loads(row["value"])
        except (json.JSONDecodeError, KeyError):
            pass
    return cfg


def set_config_key(key: str, value):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO user_config (key, value) VALUES (?, ?)",
            (key, json.dumps(value)),
        )


def reset_config():
    with get_conn() as conn:
        conn.execute("DELETE FROM user_config")


def get_last_scan_time() -> Optional[datetime]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM user_config WHERE key = 'last_scan_time'"
        ).fetchone()
    if row:
        try:
            return datetime.fromisoformat(row["value"])
        except ValueError:
            pass
    return None


def set_last_scan_time(dt: datetime):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO user_config (key, value) VALUES ('last_scan_time', ?)",
            (dt.isoformat(),),
        )
