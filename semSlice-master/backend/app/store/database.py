import os
import sqlite3
from contextlib import contextmanager
from typing import Iterator


BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "semslice.db")


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS user_account (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_session (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    token TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'active',
    expired_at TEXT,
    created_at TEXT NOT NULL,
    last_access_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES user_account(id)
);

CREATE TABLE IF NOT EXISTS task_submission (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES user_account(id)
);

CREATE TABLE IF NOT EXISTS task_item (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id INTEGER NOT NULL,
    biz_user_code TEXT NOT NULL,
    requirement_type TEXT NOT NULL,
    domain_type TEXT NOT NULL,
    payload_symbols INTEGER NOT NULL,
    distance_m REAL NOT NULL,
    base_similarity REAL NOT NULL,
    task_pkl TEXT,
    task_vocab TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(submission_id) REFERENCES task_submission(id)
);

CREATE TABLE IF NOT EXISTS network_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cpu_capacity REAL NOT NULL,
    compute_energy_threshold REAL NOT NULL,
    total_bandwidth REAL NOT NULL,
    total_power REAL NOT NULL,
    channel_scenario TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 0,
    created_by_user_id INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY(created_by_user_id) REFERENCES user_account(id)
);

CREATE TABLE IF NOT EXISTS slice_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slice_count INTEGER NOT NULL,
    slice_names_json TEXT NOT NULL,
    codec_count INTEGER NOT NULL,
    codec_modality TEXT NOT NULL,
    knowledge_bases_json TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 0,
    created_by_user_id INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY(created_by_user_id) REFERENCES user_account(id)
);

CREATE TABLE IF NOT EXISTS workflow_run (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id INTEGER NOT NULL,
    network_config_id INTEGER NOT NULL,
    slice_config_id INTEGER NOT NULL,
    allocation_algorithm TEXT NOT NULL,
    adaptation_method TEXT NOT NULL,
    run_status TEXT NOT NULL,
    avg_fidelity REAL,
    avg_delay_ms REAL,
    avg_energy REAL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    FOREIGN KEY(submission_id) REFERENCES task_submission(id),
    FOREIGN KEY(network_config_id) REFERENCES network_config(id),
    FOREIGN KEY(slice_config_id) REFERENCES slice_config(id)
);

CREATE TABLE IF NOT EXISTS adaptation_result (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    task_item_id INTEGER NOT NULL,
    matched_slice_id TEXT NOT NULL,
    matched_slice_name TEXT NOT NULL,
    codec_id TEXT NOT NULL,
    kb_id TEXT NOT NULL,
    similarity_score REAL NOT NULL,
    FOREIGN KEY(run_id) REFERENCES workflow_run(id),
    FOREIGN KEY(task_item_id) REFERENCES task_item(id)
);

CREATE TABLE IF NOT EXISTS allocation_result (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    task_item_id INTEGER NOT NULL,
    slice_id TEXT NOT NULL,
    bandwidth REAL NOT NULL,
    power REAL NOT NULL,
    compute REAL NOT NULL,
    energy_cost REAL NOT NULL,
    FOREIGN KEY(run_id) REFERENCES workflow_run(id),
    FOREIGN KEY(task_item_id) REFERENCES task_item(id)
);

CREATE TABLE IF NOT EXISTS performance_result (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    task_item_id INTEGER NOT NULL,
    slice_id TEXT NOT NULL,
    fidelity REAL NOT NULL,
    delay_ms REAL NOT NULL,
    snr_db REAL NOT NULL,
    similarity_score REAL NOT NULL,
    knowledge_factor REAL NOT NULL,
    FOREIGN KEY(run_id) REFERENCES workflow_run(id),
    FOREIGN KEY(task_item_id) REFERENCES task_item(id)
);

CREATE TABLE IF NOT EXISTS strategy_compare_summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id INTEGER NOT NULL,
    strategy TEXT NOT NULL,
    avg_delay_ms REAL NOT NULL,
    avg_ss REAL NOT NULL,
    avg_s_se REAL NOT NULL,
    task_count INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(submission_id) REFERENCES task_submission(id)
);

CREATE INDEX IF NOT EXISTS idx_user_account_username ON user_account(username);
CREATE INDEX IF NOT EXISTS idx_auth_session_token ON auth_session(token);
CREATE INDEX IF NOT EXISTS idx_task_submission_user_id ON task_submission(user_id);
CREATE INDEX IF NOT EXISTS idx_task_item_submission_id ON task_item(submission_id);
CREATE INDEX IF NOT EXISTS idx_workflow_run_submission_id ON workflow_run(submission_id);
CREATE INDEX IF NOT EXISTS idx_workflow_run_strategy ON workflow_run(allocation_algorithm);
CREATE INDEX IF NOT EXISTS idx_adaptation_result_run_id ON adaptation_result(run_id);
CREATE INDEX IF NOT EXISTS idx_allocation_result_run_id ON allocation_result(run_id);
CREATE INDEX IF NOT EXISTS idx_performance_result_run_id ON performance_result(run_id);
CREATE INDEX IF NOT EXISTS idx_strategy_compare_submission_id ON strategy_compare_summary(submission_id);
"""


def _ensure_data_dir() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)


def get_connection() -> sqlite3.Connection:
    _ensure_data_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def connection_scope() -> Iterator[sqlite3.Connection]:
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with connection_scope() as conn:
        conn.executescript(SCHEMA_SQL)
