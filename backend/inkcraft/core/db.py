"""SQLite persistence layer (WAL mode) for documents, layouts, jobs, checkpoints, profiles, and tasks."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any

from inkcraft.api.schemas import MachineProfile


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS machine_profiles (
    profile_id  TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    is_active   INTEGER NOT NULL DEFAULT 0,
    config_json TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    doc_id      TEXT PRIMARY KEY,
    filename    TEXT NOT NULL,
    file_type   TEXT NOT NULL,
    sha256      TEXT NOT NULL,
    page_count  INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL,
    meta_json   TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS layouts (
    layout_id    TEXT PRIMARY KEY,
    doc_id       TEXT NOT NULL,
    writer_id    TEXT NOT NULL,
    cache_key    TEXT NOT NULL,
    config_json  TEXT NOT NULL,
    page_count   INTEGER NOT NULL,
    summary_json TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_layouts_cache ON layouts(cache_key);
CREATE INDEX IF NOT EXISTS idx_layouts_doc ON layouts(doc_id);

CREATE TABLE IF NOT EXISTS jobs (
    job_id             TEXT PRIMARY KEY,
    layout_id          TEXT NOT NULL,
    profile_id         TEXT NOT NULL,
    state              TEXT NOT NULL,
    page_indices_json  TEXT NOT NULL,
    current_page_index INTEGER NOT NULL DEFAULT 0,
    last_stroke_index  INTEGER NOT NULL DEFAULT 0,
    last_line_acked    INTEGER NOT NULL DEFAULT 0,
    saved_wpos_json    TEXT,
    progress_json      TEXT,
    error_message      TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_checkpoints (
    checkpoint_id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id        TEXT NOT NULL,
    page_index    INTEGER NOT NULL,
    stroke_index  INTEGER NOT NULL,
    line_acked    INTEGER NOT NULL,
    wpos_json     TEXT,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_job_checkpoints_job ON job_checkpoints(job_id);

CREATE TABLE IF NOT EXISTS tasks (
    task_id     TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,
    state       TEXT NOT NULL,
    stage       TEXT NOT NULL,
    pct         REAL NOT NULL DEFAULT 0.0,
    page        INTEGER,
    page_count  INTEGER,
    message     TEXT NOT NULL DEFAULT '',
    result_json TEXT,
    error_text  TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""


class Database:
    """Thread-safe SQLite database wrapper for app.db."""

    def __init__(self, db_path: Path, default_profiles_path: Path | None = None) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA synchronous = NORMAL")
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.executescript(SCHEMA_SQL)
            self._conn.commit()
        if default_profiles_path is not None:
            self.seed_profiles(default_profiles_path)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------
    # Machine Profiles
    # ------------------------------------------------------------------

    def seed_profiles(self, profiles_path: Path) -> None:
        """Insert shipped profiles that are missing (never overwrites user edits)."""
        with self._lock:
            count = self._conn.execute("SELECT COUNT(*) FROM machine_profiles").fetchone()[0]
            profiles: list[MachineProfile] = []
            if profiles_path.is_file():
                raw = json.loads(profiles_path.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    for item in raw:
                        profiles.append(MachineProfile(**item))
            if not profiles:
                profiles.append(MachineProfile())

            now = _utc_now()
            for idx, prof in enumerate(profiles):
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO machine_profiles
                        (profile_id, name, is_active, config_json, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        prof.profile_id,
                        prof.name,
                        1 if (idx == 0 and count == 0) else 0,
                        prof.model_dump_json(),
                        now,
                    ),
                )
            self._conn.commit()

    def list_profiles(self) -> tuple[str | None, list[MachineProfile]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT profile_id, is_active, config_json FROM machine_profiles ORDER BY rowid ASC"
            ).fetchall()
            active_id: str | None = None
            result: list[MachineProfile] = []
            for row in rows:
                prof = MachineProfile.model_validate_json(row["config_json"])
                result.append(prof)
                if row["is_active"]:
                    active_id = row["profile_id"]
            if active_id is None and result:
                active_id = result[0].profile_id
            return active_id, result

    def get_profile(self, profile_id: str) -> MachineProfile | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT config_json FROM machine_profiles WHERE profile_id = ?",
                (profile_id,),
            ).fetchone()
            if row is None:
                return None
            return MachineProfile.model_validate_json(row["config_json"])

    def upsert_profile(self, profile: MachineProfile, *, set_active: bool = False) -> MachineProfile:
        now = _utc_now()
        with self._lock:
            if set_active:
                self._conn.execute("UPDATE machine_profiles SET is_active = 0")
            existing = self._conn.execute(
                "SELECT is_active FROM machine_profiles WHERE profile_id = ?",
                (profile.profile_id,),
            ).fetchone()
            is_active = 1 if set_active else (int(existing["is_active"]) if existing else 0)
            self._conn.execute(
                """
                INSERT INTO machine_profiles (profile_id, name, is_active, config_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(profile_id) DO UPDATE SET
                    name = excluded.name,
                    is_active = excluded.is_active,
                    config_json = excluded.config_json,
                    updated_at = excluded.updated_at
                """,
                (
                    profile.profile_id,
                    profile.name,
                    is_active,
                    profile.model_dump_json(),
                    now,
                ),
            )
            self._conn.commit()
        return profile

    def set_active_profile(self, profile_id: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE machine_profiles SET is_active = 0")
            self._conn.execute(
                "UPDATE machine_profiles SET is_active = 1, updated_at = ? WHERE profile_id = ?",
                (_utc_now(), profile_id),
            )
            self._conn.commit()

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------

    def upsert_document(
        self,
        *,
        doc_id: str,
        filename: str,
        file_type: str,
        sha256: str,
        page_count: int = 0,
        status: str = "parsing",
        meta: dict[str, Any] | None = None,
    ) -> None:
        now = _utc_now()
        meta_json = json.dumps(meta, ensure_ascii=False) if meta is not None else None
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO documents
                    (doc_id, filename, file_type, sha256, page_count, status, meta_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(doc_id) DO UPDATE SET
                    filename = excluded.filename,
                    file_type = excluded.file_type,
                    sha256 = excluded.sha256,
                    page_count = excluded.page_count,
                    status = excluded.status,
                    meta_json = COALESCE(excluded.meta_json, documents.meta_json),
                    updated_at = excluded.updated_at
                """,
                (doc_id, filename, file_type, sha256, page_count, status, meta_json, now, now),
            )
            self._conn.commit()

    def get_document(self, doc_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM documents WHERE doc_id = ?", (doc_id,)
            ).fetchone()
            if row is None:
                return None
            return self._row_to_doc(row)

    def list_documents(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM documents ORDER BY created_at DESC"
            ).fetchall()
            return [self._row_to_doc(r) for r in rows]

    def rename_document(self, doc_id: str, filename: str) -> bool:
        now = _utc_now()
        with self._lock:
            row = self._conn.execute(
                "SELECT meta_json FROM documents WHERE doc_id = ?", (doc_id,)
            ).fetchone()
            if row is None:
                return False
            meta = json.loads(row["meta_json"]) if row["meta_json"] else {}
            if isinstance(meta.get("source"), dict):
                meta["source"]["filename"] = filename
            self._conn.execute(
                "UPDATE documents SET filename = ?, meta_json = ?, updated_at = ? WHERE doc_id = ?",
                (filename, json.dumps(meta, ensure_ascii=False), now, doc_id),
            )
            self._conn.commit()
            return True

    def delete_document(self, doc_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
            self._conn.commit()
            return cur.rowcount > 0

    @staticmethod
    def _row_to_doc(row: sqlite3.Row) -> dict[str, Any]:
        meta = json.loads(row["meta_json"]) if row["meta_json"] else {}
        return {
            "doc_id": row["doc_id"],
            "filename": row["filename"],
            "file_type": row["file_type"],
            "sha256": row["sha256"],
            "page_count": row["page_count"],
            "status": row["status"],
            "meta": meta,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    # ------------------------------------------------------------------
    # Layouts
    # ------------------------------------------------------------------

    def save_layout(
        self,
        *,
        layout_id: str,
        doc_id: str,
        writer_id: str,
        cache_key: str,
        config_dict: dict[str, Any],
        page_count: int,
        summary_pages: list[dict[str, Any]],
    ) -> None:
        now = _utc_now()
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO layouts
                    (layout_id, doc_id, writer_id, cache_key, config_json, page_count, summary_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    layout_id,
                    doc_id,
                    writer_id,
                    cache_key,
                    json.dumps(config_dict, ensure_ascii=False),
                    page_count,
                    json.dumps(summary_pages, ensure_ascii=False),
                    now,
                ),
            )
            self._conn.commit()

    def get_layout(self, layout_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM layouts WHERE layout_id = ?", (layout_id,)
            ).fetchone()
            if row is None:
                return None
            return self._row_to_layout(row)

    def find_layout_by_cache_key(self, cache_key: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM layouts WHERE cache_key = ? ORDER BY created_at DESC LIMIT 1",
                (cache_key,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_layout(row)

    @staticmethod
    def _row_to_layout(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "layout_id": row["layout_id"],
            "doc_id": row["doc_id"],
            "writer_id": row["writer_id"],
            "cache_key": row["cache_key"],
            "config": json.loads(row["config_json"]),
            "page_count": row["page_count"],
            "pages": json.loads(row["summary_json"]),
            "created_at": row["created_at"],
        }

    # ------------------------------------------------------------------
    # Jobs & Checkpoints
    # ------------------------------------------------------------------

    def create_job(
        self,
        *,
        job_id: str,
        layout_id: str,
        profile_id: str,
        state: str,
        page_indices: list[int],
        current_page_index: int = 0,
    ) -> None:
        now = _utc_now()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO jobs
                    (job_id, layout_id, profile_id, state, page_indices_json,
                     current_page_index, last_stroke_index, last_line_acked,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, ?)
                """,
                (
                    job_id,
                    layout_id,
                    profile_id,
                    state,
                    json.dumps(page_indices),
                    current_page_index,
                    now,
                    now,
                ),
            )
            self._conn.commit()

    def update_job(
        self,
        job_id: str,
        *,
        state: str | None = None,
        current_page_index: int | None = None,
        last_stroke_index: int | None = None,
        last_line_acked: int | None = None,
        saved_wpos: dict[str, float] | None = None,
        progress: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> None:
        sets: list[str] = ["updated_at = ?"]
        params: list[Any] = [_utc_now()]
        if state is not None:
            sets.append("state = ?")
            params.append(state)
        if current_page_index is not None:
            sets.append("current_page_index = ?")
            params.append(current_page_index)
        if last_stroke_index is not None:
            sets.append("last_stroke_index = ?")
            params.append(last_stroke_index)
        if last_line_acked is not None:
            sets.append("last_line_acked = ?")
            params.append(last_line_acked)
        if saved_wpos is not None:
            sets.append("saved_wpos_json = ?")
            params.append(json.dumps(saved_wpos))
        if progress is not None:
            sets.append("progress_json = ?")
            params.append(json.dumps(progress))
        if error_message is not None:
            sets.append("error_message = ?")
            params.append(error_message)
        params.append(job_id)

        with self._lock:
            self._conn.execute(
                f"UPDATE jobs SET {', '.join(sets)} WHERE job_id = ?",
                params,
            )
            self._conn.commit()

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                return None
            return {
                "job_id": row["job_id"],
                "layout_id": row["layout_id"],
                "profile_id": row["profile_id"],
                "job_state": row["state"],
                "page_indices": json.loads(row["page_indices_json"]),
                "current_page_index": row["current_page_index"],
                "last_stroke_index": row["last_stroke_index"],
                "last_line_acked": row["last_line_acked"],
                "saved_wpos": json.loads(row["saved_wpos_json"]) if row["saved_wpos_json"] else None,
                "progress": json.loads(row["progress_json"]) if row["progress_json"] else None,
                "error_message": row["error_message"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }

    def save_checkpoint(
        self,
        *,
        job_id: str,
        page_index: int,
        stroke_index: int,
        line_acked: int,
        wpos: dict[str, float] | None = None,
    ) -> None:
        now = _utc_now()
        wpos_json = json.dumps(wpos) if wpos is not None else None
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO job_checkpoints
                    (job_id, page_index, stroke_index, line_acked, wpos_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (job_id, page_index, stroke_index, line_acked, wpos_json, now),
            )
            self._conn.execute(
                """
                UPDATE jobs SET
                    current_page_index = ?,
                    last_stroke_index = ?,
                    last_line_acked = ?,
                    saved_wpos_json = COALESCE(?, saved_wpos_json),
                    updated_at = ?
                WHERE job_id = ?
                """,
                (page_index, stroke_index, line_acked, wpos_json, now, job_id),
            )
            self._conn.commit()

    def get_latest_checkpoint(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT * FROM job_checkpoints
                WHERE job_id = ?
                ORDER BY checkpoint_id DESC LIMIT 1
                """,
                (job_id,),
            ).fetchone()
            if row is None:
                return None
            return {
                "checkpoint_id": row["checkpoint_id"],
                "job_id": row["job_id"],
                "page_index": row["page_index"],
                "stroke_index": row["stroke_index"],
                "line_acked": row["line_acked"],
                "wpos": json.loads(row["wpos_json"]) if row["wpos_json"] else None,
                "created_at": row["created_at"],
            }

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    def upsert_task(self, task: dict[str, Any]) -> None:
        now = _utc_now()
        result_json = (
            json.dumps(task["result"], ensure_ascii=False)
            if task.get("result") is not None
            else None
        )
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO tasks
                    (task_id, kind, state, stage, pct, page, page_count, message,
                     result_json, error_text, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    state = excluded.state,
                    stage = excluded.stage,
                    pct = excluded.pct,
                    page = excluded.page,
                    page_count = excluded.page_count,
                    message = excluded.message,
                    result_json = excluded.result_json,
                    error_text = excluded.error_text,
                    updated_at = excluded.updated_at
                """,
                (
                    task["task_id"],
                    task["kind"],
                    task["state"],
                    task["stage"],
                    float(task.get("pct", 0.0)),
                    task.get("page"),
                    task.get("page_count"),
                    task.get("message", ""),
                    result_json,
                    task.get("error"),
                    now,
                    now,
                ),
            )
            self._conn.commit()

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row is None:
                return None
            out: dict[str, Any] = {
                "task_id": row["task_id"],
                "kind": row["kind"],
                "state": row["state"],
                "stage": row["stage"],
                "pct": row["pct"],
                "message": row["message"],
            }
            if row["page"] is not None:
                out["page"] = row["page"]
            if row["page_count"] is not None:
                out["page_count"] = row["page_count"]
            if row["result_json"] is not None:
                out["result"] = json.loads(row["result_json"])
            if row["error_text"] is not None:
                out["error"] = row["error_text"]
            return out
