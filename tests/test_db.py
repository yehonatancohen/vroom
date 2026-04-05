import pytest
import sqlite3
from datetime import datetime

import db
from config import DEFAULT_CONFIG


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    """Point db module at a fresh temp database for each test."""
    path = str(tmp_path / "test.db")
    monkeypatch.setattr(db, "DB_PATH", path)
    # Also patch the import inside db.get_conn
    import config
    monkeypatch.setattr(config, "DB_PATH", path)
    db.init_db()
    yield


def test_init_db_creates_tables(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "seen_listings" in tables
    assert "user_config" in tables


def test_mark_seen_and_is_seen():
    db.mark_seen(["id1", "id2"])
    assert db.is_seen("id1") is True
    assert db.is_seen("id2") is True
    assert db.is_seen("id3") is False


def test_mark_seen_idempotent():
    db.mark_seen(["id1"])
    db.mark_seen(["id1"])  # should not raise
    assert db.is_seen("id1") is True


def test_filter_new():
    db.mark_seen(["seen1", "seen2"])
    result = db.filter_new(["seen1", "new1", "seen2", "new2"])
    assert set(result) == {"new1", "new2"}


def test_filter_new_empty():
    assert db.filter_new([]) == []


def test_get_config_defaults():
    cfg = db.get_config()
    for key, val in DEFAULT_CONFIG.items():
        assert cfg[key] == val


def test_set_and_get_config_key():
    db.set_config_key("price_max", 99000)
    cfg = db.get_config()
    assert cfg["price_max"] == 99000


def test_set_config_key_list():
    db.set_config_key("brands", ["טויוטה", "הונדה"])
    cfg = db.get_config()
    assert cfg["brands"] == ["טויוטה", "הונדה"]


def test_reset_config():
    db.set_config_key("price_max", 1)
    db.reset_config()
    cfg = db.get_config()
    assert cfg["price_max"] == DEFAULT_CONFIG["price_max"]


def test_last_scan_time_default_none():
    assert db.get_last_scan_time() is None


def test_set_and_get_last_scan_time():
    dt = datetime(2025, 11, 17, 20, 34, 59)
    db.set_last_scan_time(dt)
    assert db.get_last_scan_time() == dt
