import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id      TEXT PRIMARY KEY,
                    topic       TEXT NOT NULL,
                    series_name TEXT,
                    episode_no  INTEGER,
                    title       TEXT,
                    status      TEXT DEFAULT 'running',
                    created_at  TEXT,
                    completed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS scene_steps (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id     TEXT NOT NULL,
                    scene_no   INTEGER NOT NULL,
                    step       TEXT NOT NULL,
                    status     TEXT DEFAULT 'done',
                    path       TEXT,
                    error      TEXT,
                    updated_at TEXT,
                    UNIQUE(job_id, scene_no, step)
                );

                CREATE INDEX IF NOT EXISTS idx_jobs_topic ON jobs(topic);
                CREATE INDEX IF NOT EXISTS idx_scene_steps_job ON scene_steps(job_id, scene_no);
            """)

    def get_or_create_job(self, topic: str, series_name: str = "", episode_no: int = 0) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT job_id, status FROM jobs WHERE topic = ? ORDER BY created_at DESC LIMIT 1",
                (topic,),
            ).fetchone()

            if row and row["status"] not in ("completed", "failed"):
                return row["job_id"]

            job_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO jobs (job_id, topic, series_name, episode_no, status, created_at) VALUES (?,?,?,?,'running',?)",
                (job_id, topic, series_name, episode_no, datetime.now().isoformat()),
            )
            return job_id

    def is_job_completed(self, topic: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status FROM jobs WHERE topic = ? ORDER BY created_at DESC LIMIT 1",
                (topic,),
            ).fetchone()
            return row is not None and row["status"] == "completed"

    def set_job_title(self, job_id: str, title: str):
        with self._connect() as conn:
            conn.execute("UPDATE jobs SET title=? WHERE job_id=?", (title, job_id))

    def mark_job_completed(self, job_id: str):
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status='completed', completed_at=? WHERE job_id=?",
                (datetime.now().isoformat(), job_id),
            )

    def mark_job_failed(self, job_id: str, error: str):
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status='failed', completed_at=? WHERE job_id=?",
                (datetime.now().isoformat(), job_id),
            )

    def mark_step_done(self, job_id: str, scene_no: int, step: str, path: str = ""):
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO scene_steps (job_id, scene_no, step, status, path, updated_at)
                   VALUES (?,?,?,'done',?,?)""",
                (job_id, scene_no, step, path, datetime.now().isoformat()),
            )

    def is_step_done(self, job_id: str, scene_no: int, step: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status FROM scene_steps WHERE job_id=? AND scene_no=? AND step=?",
                (job_id, scene_no, step),
            ).fetchone()
            return row is not None and row["status"] == "done"

    def get_step_path(self, job_id: str, scene_no: int, step: str) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT path FROM scene_steps WHERE job_id=? AND scene_no=? AND step=?",
                (job_id, scene_no, step),
            ).fetchone()
            return row["path"] if row else None

    def get_done_scene_count(self, job_id: str) -> int:
        # 'done_v3' = current pipeline; older keys kept for pre-upgrade jobs
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(DISTINCT scene_no) FROM scene_steps WHERE job_id=? AND step IN ('done','done_v2','done_v3') AND status='done'",
                (job_id,),
            ).fetchone()
            return row[0] if row else 0

    def list_jobs(self) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT job_id, topic, title, status, created_at, completed_at FROM jobs ORDER BY created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]
