"""SQLite index and relational persistence layer for the Scholia vault (v2 workspace & curriculum aware)."""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .config import ensure_vault_dirs


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(text: str, max_len: int = 48) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    if not cleaned:
        cleaned = "item"
    return cleaned[:max_len].rstrip("-")


def new_id(prefix: str = "") -> str:
    token = uuid.uuid4().hex[:12]
    return f"{prefix}_{token}" if prefix else token


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS books (
    id TEXT PRIMARY KEY,
    workspace_id TEXT REFERENCES workspaces(id) ON DELETE CASCADE,
    slug TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    authors TEXT NOT NULL DEFAULT 'Unknown',
    source_format TEXT NOT NULL,
    source_filename TEXT NOT NULL,
    source_url TEXT NOT NULL DEFAULT '',
    page_count INTEGER NOT NULL DEFAULT 1,
    topic_areas_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chapters (
    id TEXT PRIMARY KEY,
    book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    slug TEXT NOT NULL,
    order_index INTEGER NOT NULL,
    title TEXT NOT NULL,
    start_page INTEGER NOT NULL DEFAULT 1,
    end_page INTEGER NOT NULL DEFAULT 1,
    page_count INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'pending',
    scope TEXT NOT NULL DEFAULT 'assigned',
    extraction_progress TEXT NOT NULL DEFAULT '',
    has_pdf INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chapters_book ON chapters(book_id, order_index);

CREATE TABLE IF NOT EXISTS concepts (
    id TEXT PRIMARY KEY,
    workspace_id TEXT REFERENCES workspaces(id) ON DELETE CASCADE,
    slug TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    book_id TEXT REFERENCES books(id) ON DELETE SET NULL,
    chapter_id TEXT REFERENCES chapters(id) ON DELETE SET NULL,
    topic_areas_json TEXT NOT NULL DEFAULT '[]',
    mastery_state TEXT NOT NULL DEFAULT 'unseen',
    core_passed INTEGER NOT NULL DEFAULT 0,
    page_refs_json TEXT NOT NULL DEFAULT '[]',
    misconceptions_json TEXT NOT NULL DEFAULT '[]',
    frontiers_json TEXT NOT NULL DEFAULT '[]',
    fsrs_stability REAL NOT NULL DEFAULT 0.0,
    fsrs_difficulty REAL NOT NULL DEFAULT 5.0,
    fsrs_reps INTEGER NOT NULL DEFAULT 0,
    fsrs_lapses INTEGER NOT NULL DEFAULT 0,
    fsrs_due_at TEXT,
    fsrs_last_review_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_concepts_chapter ON concepts(chapter_id);

CREATE TABLE IF NOT EXISTS concept_edges (
    parent_id TEXT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
    child_id TEXT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
    relation TEXT NOT NULL DEFAULT 'prerequisite',
    created_at TEXT NOT NULL,
    PRIMARY KEY (parent_id, child_id)
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    chapter_id TEXT REFERENCES chapters(id) ON DELETE CASCADE,
    stage TEXT NOT NULL DEFAULT 'plan',
    active_concept_id TEXT,
    covered_concept_ids_json TEXT NOT NULL DEFAULT '[]',
    exam_state_json TEXT,
    agent_conversation_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_chapter ON sessions(chapter_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    speaker TEXT NOT NULL,
    stage TEXT NOT NULL,
    content TEXT NOT NULL,
    citations_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at ASC);

CREATE TABLE IF NOT EXISTS question_history (
    id TEXT PRIMARY KEY,
    chapter_id TEXT,
    concept_id TEXT,
    cognitive_level TEXT NOT NULL,
    question_stem TEXT NOT NULL,
    asked_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_qhist_concept ON question_history(concept_id);

CREATE TABLE IF NOT EXISTS learner_notes (
    id TEXT PRIMARY KEY,
    chapter_id TEXT REFERENCES chapters(id) ON DELETE CASCADE,
    concept_id TEXT REFERENCES concepts(id) ON DELETE SET NULL,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    resolved INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS review_history (
    id TEXT PRIMARY KEY,
    concept_id TEXT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
    probe_question TEXT NOT NULL,
    answer TEXT NOT NULL,
    rating INTEGER NOT NULL,
    feedback TEXT NOT NULL,
    reviewed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS curricula (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    slug TEXT NOT NULL,
    title TEXT NOT NULL,
    subtitle TEXT NOT NULL DEFAULT '',
    goal TEXT NOT NULL DEFAULT '',
    weekly_rhythm_json TEXT NOT NULL DEFAULT '[]',
    guardrails_json TEXT NOT NULL DEFAULT '[]',
    source_markdown TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_curricula_ws ON curricula(workspace_id);

CREATE TABLE IF NOT EXISTS curriculum_phases (
    id TEXT PRIMARY KEY,
    curriculum_id TEXT NOT NULL REFERENCES curricula(id) ON DELETE CASCADE,
    track TEXT NOT NULL DEFAULT 'core',
    phase_number INTEGER NOT NULL DEFAULT 1,
    title TEXT NOT NULL,
    date_range TEXT NOT NULL DEFAULT '',
    goal TEXT NOT NULL DEFAULT '',
    exit_criterion TEXT NOT NULL DEFAULT '',
    exit_passed INTEGER NOT NULL DEFAULT 0,
    at_work_prompt TEXT NOT NULL DEFAULT '',
    order_index INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_phases_curriculum ON curriculum_phases(curriculum_id, order_index);

CREATE TABLE IF NOT EXISTS curriculum_items (
    id TEXT PRIMARY KEY,
    phase_id TEXT NOT NULL REFERENCES curriculum_phases(id) ON DELETE CASCADE,
    week_label TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'reading',
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    external_url TEXT NOT NULL DEFAULT '',
    linked_book_id TEXT REFERENCES books(id) ON DELETE SET NULL,
    linked_chapter_ids_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'todo',
    order_index INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_items_phase ON curriculum_items(phase_id, order_index);

CREATE TABLE IF NOT EXISTS running_logs (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    curriculum_id TEXT REFERENCES curricula(id) ON DELETE SET NULL,
    slug TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    file_relpath TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_logs_ws ON running_logs(workspace_id);
"""


class VaultDB:
    """Thread-safe SQLite repository anchored at `<vault_dir>/scholia.sqlite`."""

    def __init__(self, vault_dir: Path):
        self.vault_dir = ensure_vault_dirs(vault_dir)
        self.db_path = self.vault_dir / "scholia.sqlite"
        self.init_schema()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA_SQL)
            self._auto_migrate(conn)

    def _auto_migrate(self, conn: sqlite3.Connection) -> None:
        """Safely upgrade older v1 SQLite databases in-place."""
        book_cols = {r["name"] for r in conn.execute("PRAGMA table_info(books)").fetchall()}
        if "workspace_id" not in book_cols:
            conn.execute("ALTER TABLE books ADD COLUMN workspace_id TEXT REFERENCES workspaces(id) ON DELETE CASCADE")
        if "source_url" not in book_cols:
            conn.execute("ALTER TABLE books ADD COLUMN source_url TEXT NOT NULL DEFAULT ''")

        ch_cols = {r["name"] for r in conn.execute("PRAGMA table_info(chapters)").fetchall()}
        if "scope" not in ch_cols:
            conn.execute("ALTER TABLE chapters ADD COLUMN scope TEXT NOT NULL DEFAULT 'assigned'")

        con_cols = {r["name"] for r in conn.execute("PRAGMA table_info(concepts)").fetchall()}
        if "workspace_id" not in con_cols:
            conn.execute("ALTER TABLE concepts ADD COLUMN workspace_id TEXT REFERENCES workspaces(id) ON DELETE CASCADE")

        # Ensure at least one workspace exists if books/concepts exist or DB is brand new
        ws_count = conn.execute("SELECT COUNT(*) AS c FROM workspaces").fetchone()["c"]
        if ws_count == 0:
            now = utc_now()
            conn.execute(
                """
                INSERT INTO workspaces (id, slug, name, description, created_at, updated_at)
                VALUES ('ws_general', 'general', 'General', 'Default study umbrella', ?, ?)
                """,
                (now, now),
            )

        default_ws = conn.execute("SELECT id FROM workspaces ORDER BY created_at ASC LIMIT 1").fetchone()["id"]
        conn.execute("UPDATE books SET workspace_id = ? WHERE workspace_id IS NULL", (default_ws,))
        conn.execute(
            """
            UPDATE concepts
            SET workspace_id = COALESCE(
                (SELECT b.workspace_id FROM books b WHERE b.id = concepts.book_id),
                ?
            )
            WHERE workspace_id IS NULL
            """,
            (default_ws,),
        )

        # Create workspace indexes after columns exist
        conn.execute("CREATE INDEX IF NOT EXISTS idx_books_ws ON books(workspace_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_concepts_ws ON concepts(workspace_id)")

    # ---------- Workspaces ----------

    def create_workspace(
        self,
        name: str,
        description: str = "",
        slug: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = utc_now()
        wid = workspace_id or new_id("ws")
        base_slug = slugify(slug or name, 40)
        with self.connect() as conn:
            candidate = base_slug
            suffix = 2
            while conn.execute("SELECT 1 FROM workspaces WHERE slug = ?", (candidate,)).fetchone():
                candidate = f"{base_slug}-{suffix}"
                suffix += 1
            conn.execute(
                """
                INSERT INTO workspaces (id, slug, name, description, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (wid, candidate, name.strip(), description.strip(), now, now),
            )
        return self.get_workspace(wid)  # type: ignore[return-value]

    def list_workspaces(self) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM workspaces ORDER BY created_at ASC").fetchall()
            out: List[Dict[str, Any]] = []
            for r in rows:
                item = dict(r)
                item["book_count"] = int(
                    conn.execute("SELECT COUNT(*) FROM books WHERE workspace_id = ?", (r["id"],)).fetchone()[0]
                )
                item["curriculum_count"] = int(
                    conn.execute("SELECT COUNT(*) FROM curricula WHERE workspace_id = ?", (r["id"],)).fetchone()[0]
                )
                item["concept_count"] = int(
                    conn.execute("SELECT COUNT(*) FROM concepts WHERE workspace_id = ?", (r["id"],)).fetchone()[0]
                )
                out.append(item)
            return out

    def get_workspace(self, workspace_ref: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM workspaces WHERE id = ? OR lower(slug) = lower(?) OR lower(name) = lower(?)",
                (workspace_ref, workspace_ref, workspace_ref),
            ).fetchone()
            if not row:
                return None
            item = dict(row)
            item["book_count"] = int(
                conn.execute("SELECT COUNT(*) FROM books WHERE workspace_id = ?", (row["id"],)).fetchone()[0]
            )
            item["curriculum_count"] = int(
                conn.execute("SELECT COUNT(*) FROM curricula WHERE workspace_id = ?", (row["id"],)).fetchone()[0]
            )
            item["concept_count"] = int(
                conn.execute("SELECT COUNT(*) FROM concepts WHERE workspace_id = ?", (row["id"],)).fetchone()[0]
            )
            return item

    def update_workspace(
        self,
        workspace_ref: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        ws = self.get_workspace(workspace_ref)
        if not ws:
            return None
        with self.connect() as conn:
            conn.execute(
                "UPDATE workspaces SET name = ?, description = ?, updated_at = ? WHERE id = ?",
                (
                    name.strip() if name is not None else ws["name"],
                    description.strip() if description is not None else ws["description"],
                    utc_now(),
                    ws["id"],
                ),
            )
        return self.get_workspace(ws["id"])

    def delete_workspace(self, workspace_ref: str) -> bool:
        ws = self.get_workspace(workspace_ref)
        if not ws:
            return False
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM workspaces WHERE id = ?", (ws["id"],))
            return cur.rowcount > 0

    def get_default_workspace(self) -> Dict[str, Any]:
        wss = self.list_workspaces()
        # Prefer a non-empty workspace (e.g., Career) if General is empty, else first
        if len(wss) > 1:
            for w in wss:
                if w["slug"] != "general" and (w["book_count"] > 0 or w["curriculum_count"] > 0):
                    return w
        return wss[0]

    def resolve_workspace_id(self, workspace: Optional[str]) -> Optional[str]:
        if not workspace or workspace.strip().lower() in ("", "all", "*"):
            return None
        ws = self.get_workspace(workspace.strip())
        return ws["id"] if ws else "__missing_workspace__"

    def _default_write_workspace_id(self, conn: sqlite3.Connection) -> str:
        row = conn.execute("SELECT id FROM workspaces ORDER BY created_at ASC LIMIT 1").fetchone()
        if row:
            return row["id"]
        now = utc_now()
        conn.execute(
            "INSERT INTO workspaces (id, slug, name, description, created_at, updated_at) VALUES ('ws_general', 'general', 'General', 'Default study umbrella', ?, ?)",
            (now, now),
        )
        return "ws_general"

    # ---------- Books ----------

    def create_book(
        self,
        title: str,
        authors: str,
        source_format: str,
        source_filename: str,
        page_count: int,
        topic_areas: List[str],
        book_id: Optional[str] = None,
        slug: Optional[str] = None,
        workspace_id: Optional[str] = None,
        source_url: str = "",
    ) -> Dict[str, Any]:
        now = utc_now()
        bid = book_id or new_id("book")
        base_slug = slug or slugify(title)
        resolved_ws = self.resolve_workspace_id(workspace_id) if workspace_id else None
        if resolved_ws == "__missing_workspace__":
            resolved_ws = None
        with self.connect() as conn:
            ws_id = resolved_ws or self._default_write_workspace_id(conn)
            candidate = base_slug
            suffix = 2
            while conn.execute("SELECT 1 FROM books WHERE slug = ?", (candidate,)).fetchone():
                candidate = f"{base_slug}-{suffix}"
                suffix += 1
            conn.execute(
                """
                INSERT INTO books (
                    id, workspace_id, slug, title, authors, source_format, source_filename,
                    source_url, page_count, topic_areas_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bid,
                    ws_id,
                    candidate,
                    title,
                    authors,
                    source_format,
                    source_filename,
                    source_url,
                    page_count,
                    json.dumps(topic_areas),
                    now,
                    now,
                ),
            )
        return self.get_book(bid)  # type: ignore[return-value]

    def list_books(self, workspace: Optional[str] = None) -> List[Dict[str, Any]]:
        ws_id = self.resolve_workspace_id(workspace)
        if ws_id == "__missing_workspace__":
            return []
        with self.connect() as conn:
            if ws_id:
                rows = conn.execute(
                    """
                    SELECT b.*, w.slug AS workspace_slug
                    FROM books b
                    LEFT JOIN workspaces w ON w.id = b.workspace_id
                    WHERE b.workspace_id = ?
                    ORDER BY b.created_at ASC
                    """,
                    (ws_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT b.*, w.slug AS workspace_slug
                    FROM books b
                    LEFT JOIN workspaces w ON w.id = b.workspace_id
                    ORDER BY b.created_at ASC
                    """
                ).fetchall()
            out: List[Dict[str, Any]] = []
            for row in rows:
                item = self._row_to_book(row)
                ch_stats = conn.execute(
                    """
                    SELECT COUNT(*) AS total,
                           SUM(CASE WHEN status = 'mastered' THEN 1 ELSE 0 END) AS mastered,
                           SUM(CASE WHEN status IN ('ready', 'in_progress', 'mastered') THEN 1 ELSE 0 END) AS ready,
                           SUM(CASE WHEN scope = 'assigned' THEN 1 ELSE 0 END) AS assigned_total,
                           SUM(CASE WHEN scope = 'assigned' AND status = 'mastered' THEN 1 ELSE 0 END) AS assigned_mastered,
                           SUM(CASE WHEN scope = 'assigned' AND status IN ('ready', 'in_progress', 'mastered') THEN 1 ELSE 0 END) AS assigned_ready,
                           SUM(CASE WHEN scope = 'optional' THEN 1 ELSE 0 END) AS optional_total,
                           SUM(CASE WHEN scope = 'skipped' THEN 1 ELSE 0 END) AS skipped_total
                    FROM chapters WHERE book_id = ?
                    """,
                    (item["id"],),
                ).fetchone()
                item["chapter_count"] = int(ch_stats["total"] or 0)
                item["mastered_chapters"] = int(ch_stats["mastered"] or 0)
                item["ready_chapters"] = int(ch_stats["ready"] or 0)
                item["assigned_chapters"] = int(ch_stats["assigned_total"] or 0)
                item["assigned_mastered_chapters"] = int(ch_stats["assigned_mastered"] or 0)
                item["assigned_ready_chapters"] = int(ch_stats["assigned_ready"] or 0)
                item["optional_chapters"] = int(ch_stats["optional_total"] or 0)
                item["skipped_chapters"] = int(ch_stats["skipped_total"] or 0)
                out.append(item)
            return out

    def get_book(self, book_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT b.*, w.slug AS workspace_slug
                FROM books b
                LEFT JOIN workspaces w ON w.id = b.workspace_id
                WHERE b.id = ? OR b.slug = ?
                """,
                (book_id, book_id),
            ).fetchone()
            if not row:
                return None
            item = self._row_to_book(row)
            chapters = self.list_chapters(item["id"])
            item["chapters"] = chapters
            item["chapter_count"] = len(chapters)
            item["mastered_chapters"] = sum(1 for c in chapters if c["status"] == "mastered")
            item["ready_chapters"] = sum(1 for c in chapters if c["status"] in ("ready", "in_progress", "mastered"))
            item["assigned_chapters"] = sum(1 for c in chapters if c["scope"] == "assigned")
            item["assigned_mastered_chapters"] = sum(
                1 for c in chapters if c["scope"] == "assigned" and c["status"] == "mastered"
            )
            item["assigned_ready_chapters"] = sum(
                1 for c in chapters if c["scope"] == "assigned" and c["status"] in ("ready", "in_progress", "mastered")
            )
            item["optional_chapters"] = sum(1 for c in chapters if c["scope"] == "optional")
            item["skipped_chapters"] = sum(1 for c in chapters if c["scope"] == "skipped")
            item["can_launch_synthesis"] = item["mastered_chapters"] >= 2
            return item

    def update_book_topics(self, book_id: str, topic_areas: List[str]) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE books SET topic_areas_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(topic_areas), utc_now(), book_id),
            )

    def delete_book(self, book_id: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
            return cur.rowcount > 0

    @staticmethod
    def _row_to_book(row: sqlite3.Row) -> Dict[str, Any]:
        keys = row.keys()
        return {
            "id": row["id"],
            "workspace_id": row["workspace_id"] if "workspace_id" in keys else None,
            "workspace_slug": row["workspace_slug"] if "workspace_slug" in keys else None,
            "slug": row["slug"],
            "title": row["title"],
            "authors": row["authors"],
            "source_format": row["source_format"],
            "source_filename": row["source_filename"],
            "source_url": row["source_url"] if "source_url" in keys else "",
            "page_count": row["page_count"],
            "topic_areas": json.loads(row["topic_areas_json"] or "[]"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    # ---------- Chapters ----------

    def create_chapter(
        self,
        book_id: str,
        order_index: int,
        title: str,
        start_page: int,
        end_page: int,
        has_pdf: bool = False,
        status: str = "pending",
        scope: str = "assigned",
        chapter_id: Optional[str] = None,
        slug: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = utc_now()
        cid = chapter_id or new_id("ch")
        ch_slug = slug or f"ch-{order_index:02d}-{slugify(title, 36)}"
        norm_scope = scope if scope in ("assigned", "optional", "skipped") else "assigned"
        page_count = max(1, end_page - start_page + 1)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO chapters (
                    id, book_id, slug, order_index, title, start_page, end_page,
                    page_count, status, scope, extraction_progress, has_pdf, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?)
                """,
                (
                    cid,
                    book_id,
                    ch_slug,
                    order_index,
                    title,
                    start_page,
                    end_page,
                    page_count,
                    status,
                    norm_scope,
                    1 if has_pdf else 0,
                    now,
                    now,
                ),
            )
        return self.get_chapter(cid)  # type: ignore[return-value]

    def list_chapters(self, book_id: str, scope: Optional[str] = None) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            if scope:
                rows = conn.execute(
                    "SELECT * FROM chapters WHERE book_id = ? AND scope = ? ORDER BY order_index ASC",
                    (book_id, scope),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM chapters WHERE book_id = ? ORDER BY order_index ASC",
                    (book_id,),
                ).fetchall()
            out: List[Dict[str, Any]] = []
            for row in rows:
                ch = self._row_to_chapter(row)
                cstats = conn.execute(
                    """
                    SELECT COUNT(*) AS total,
                           SUM(CASE WHEN core_passed = 1 OR mastery_state IN ('core_passed', 'mastered') THEN 1 ELSE 0 END) AS mastered
                    FROM concepts WHERE chapter_id = ?
                    """,
                    (ch["id"],),
                ).fetchone()
                ch["concept_count"] = int(cstats["total"] or 0)
                ch["mastered_concepts"] = int(cstats["mastered"] or 0)
                out.append(ch)
            return out

    def get_chapter(self, chapter_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM chapters WHERE id = ?", (chapter_id,)).fetchone()
            if not row:
                return None
            ch = self._row_to_chapter(row)
            cstats = conn.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN core_passed = 1 OR mastery_state IN ('core_passed', 'mastered') THEN 1 ELSE 0 END) AS mastered
                FROM concepts WHERE chapter_id = ?
                """,
                (ch["id"],),
            ).fetchone()
            ch["concept_count"] = int(cstats["total"] or 0)
            ch["mastered_concepts"] = int(cstats["mastered"] or 0)
            return ch

    def update_chapter_status(
        self,
        chapter_id: str,
        status: str,
        extraction_progress: Optional[str] = None,
    ) -> None:
        with self.connect() as conn:
            if extraction_progress is not None:
                conn.execute(
                    "UPDATE chapters SET status = ?, extraction_progress = ?, updated_at = ? WHERE id = ?",
                    (status, extraction_progress, utc_now(), chapter_id),
                )
            else:
                conn.execute(
                    "UPDATE chapters SET status = ?, updated_at = ? WHERE id = ?",
                    (status, utc_now(), chapter_id),
                )

    def update_chapter_scope(self, chapter_id: str, scope: str) -> Optional[Dict[str, Any]]:
        if scope not in ("assigned", "optional", "skipped"):
            raise ValueError(f"Invalid chapter scope: {scope}")
        with self.connect() as conn:
            cur = conn.execute(
                "UPDATE chapters SET scope = ?, updated_at = ? WHERE id = ?",
                (scope, utc_now(), chapter_id),
            )
            if cur.rowcount == 0:
                return None
        return self.get_chapter(chapter_id)

    def bulk_update_chapter_scopes(self, book_id: str, scopes: Dict[str, str]) -> List[Dict[str, Any]]:
        now = utc_now()
        with self.connect() as conn:
            for ch_id, scope in scopes.items():
                if scope not in ("assigned", "optional", "skipped"):
                    continue
                conn.execute(
                    "UPDATE chapters SET scope = ?, updated_at = ? WHERE id = ? AND book_id = ?",
                    (scope, now, ch_id, book_id),
                )
        return self.list_chapters(book_id)

    def replace_book_chapters(self, book_id: str, chapter_specs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Update/insert/delete chapters according to edited boundaries while preserving existing chapter IDs."""
        now = utc_now()
        with self.connect() as conn:
            existing_rows = conn.execute("SELECT * FROM chapters WHERE book_id = ?", (book_id,)).fetchall()
            existing_by_id = {r["id"]: dict(r) for r in existing_rows}
            keep_ids: set[str] = set()

            for idx, spec in enumerate(chapter_specs, start=1):
                cid = spec.get("id")
                title = spec["title"].strip() or f"Chapter {idx}"
                start_p = int(spec["start_page"])
                end_p = max(start_p, int(spec["end_page"]))
                page_count = max(1, end_p - start_p + 1)
                ch_slug = f"ch-{idx:02d}-{slugify(title, 36)}"
                has_pdf = 1 if spec.get("has_pdf") else 0
                raw_scope = spec.get("scope")
                if raw_scope not in ("assigned", "optional", "skipped"):
                    raw_scope = existing_by_id[cid]["scope"] if (cid and cid in existing_by_id) else "assigned"

                if cid and cid in existing_by_id:
                    keep_ids.add(cid)
                    conn.execute(
                        """
                        UPDATE chapters
                        SET slug = ?, order_index = ?, title = ?, start_page = ?, end_page = ?,
                            page_count = ?, scope = ?, has_pdf = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (ch_slug, idx, title, start_p, end_p, page_count, raw_scope, has_pdf, now, cid),
                    )
                else:
                    new_cid = cid or new_id("ch")
                    keep_ids.add(new_cid)
                    conn.execute(
                        """
                        INSERT INTO chapters (
                            id, book_id, slug, order_index, title, start_page, end_page,
                            page_count, status, scope, extraction_progress, has_pdf, created_at, updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, '', ?, ?, ?)
                        """,
                        (new_cid, book_id, ch_slug, idx, title, start_p, end_p, page_count, raw_scope, has_pdf, now, now),
                    )

            for old_id in existing_by_id:
                if old_id not in keep_ids:
                    conn.execute("DELETE FROM chapters WHERE id = ?", (old_id,))

        return self.list_chapters(book_id)

    @staticmethod
    def _row_to_chapter(row: sqlite3.Row) -> Dict[str, Any]:
        keys = row.keys()
        return {
            "id": row["id"],
            "book_id": row["book_id"],
            "slug": row["slug"],
            "order_index": row["order_index"],
            "title": row["title"],
            "start_page": row["start_page"],
            "end_page": row["end_page"],
            "page_count": row["page_count"],
            "status": row["status"],
            "scope": row["scope"] if "scope" in keys and row["scope"] else "assigned",
            "extraction_progress": row["extraction_progress"] or "",
            "has_pdf": bool(row["has_pdf"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    # ---------- Concepts & Multi-Parent DAG ----------

    def upsert_concept(
        self,
        name: str,
        summary: str = "",
        book_id: Optional[str] = None,
        chapter_id: Optional[str] = None,
        topic_areas: Optional[List[str]] = None,
        page_refs: Optional[List[int]] = None,
        misconceptions: Optional[List[str]] = None,
        frontiers: Optional[List[str]] = None,
        mastery_state: Optional[str] = None,
        core_passed: Optional[bool] = None,
        concept_id: Optional[str] = None,
        slug: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = utc_now()
        c_slug = slug or slugify(name)
        resolved_ws = self.resolve_workspace_id(workspace_id) if workspace_id else None
        if resolved_ws == "__missing_workspace__":
            resolved_ws = None

        with self.connect() as conn:
            ws_id = resolved_ws
            if not ws_id and book_id:
                brow = conn.execute("SELECT workspace_id FROM books WHERE id = ?", (book_id,)).fetchone()
                if brow:
                    ws_id = brow["workspace_id"]
            if not ws_id:
                ws_id = self._default_write_workspace_id(conn)

            existing = None
            if concept_id:
                existing = conn.execute("SELECT * FROM concepts WHERE id = ?", (concept_id,)).fetchone()
            if not existing:
                existing = conn.execute(
                    "SELECT * FROM concepts WHERE workspace_id = ? AND (slug = ? OR lower(name) = lower(?))",
                    (ws_id, c_slug, name),
                ).fetchone()

            if existing:
                cid = existing["id"]
                merged_topics = sorted(
                    set(json.loads(existing["topic_areas_json"] or "[]")) | set(topic_areas or [])
                )
                merged_pages = sorted(
                    set(json.loads(existing["page_refs_json"] or "[]")) | set(page_refs or [])
                )
                merged_misc = list(
                    dict.fromkeys(json.loads(existing["misconceptions_json"] or "[]") + (misconceptions or []))
                )
                merged_frontiers = list(
                    dict.fromkeys(json.loads(existing["frontiers_json"] or "[]") + (frontiers or []))
                )
                conn.execute(
                    """
                    UPDATE concepts
                    SET summary = COALESCE(NULLIF(?, ''), summary),
                        book_id = COALESCE(?, book_id),
                        chapter_id = COALESCE(?, chapter_id),
                        topic_areas_json = ?,
                        page_refs_json = ?,
                        misconceptions_json = ?,
                        frontiers_json = ?,
                        mastery_state = COALESCE(?, mastery_state),
                        core_passed = COALESCE(?, core_passed),
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        summary,
                        book_id,
                        chapter_id,
                        json.dumps(merged_topics),
                        json.dumps(merged_pages),
                        json.dumps(merged_misc),
                        json.dumps(merged_frontiers),
                        mastery_state,
                        (1 if core_passed else 0) if core_passed is not None else None,
                        now,
                        cid,
                    ),
                )
            else:
                cid = concept_id or new_id("con")
                candidate = c_slug
                suffix = 2
                while conn.execute("SELECT 1 FROM concepts WHERE slug = ?", (candidate,)).fetchone():
                    candidate = f"{c_slug}-{suffix}"
                    suffix += 1
                conn.execute(
                    """
                    INSERT INTO concepts (
                        id, workspace_id, slug, name, summary, book_id, chapter_id, topic_areas_json,
                        mastery_state, core_passed, page_refs_json, misconceptions_json,
                        frontiers_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cid,
                        ws_id,
                        candidate,
                        name,
                        summary,
                        book_id,
                        chapter_id,
                        json.dumps(topic_areas or []),
                        mastery_state or "unseen",
                        1 if core_passed else 0,
                        json.dumps(page_refs or []),
                        json.dumps(misconceptions or []),
                        json.dumps(frontiers or []),
                        now,
                        now,
                    ),
                )
        return self.get_concept(cid)  # type: ignore[return-value]

    def get_concept(self, concept_id: str, workspace: Optional[str] = None) -> Optional[Dict[str, Any]]:
        ws_id = self.resolve_workspace_id(workspace)
        with self.connect() as conn:
            if ws_id and ws_id != "__missing_workspace__":
                row = conn.execute(
                    "SELECT * FROM concepts WHERE workspace_id = ? AND (id = ? OR slug = ? OR lower(name) = lower(?))",
                    (ws_id, concept_id, concept_id, concept_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM concepts WHERE id = ? OR slug = ? OR lower(name) = lower(?)",
                    (concept_id, concept_id, concept_id),
                ).fetchone()
            if not row:
                return None
            return self._hydrate_concept(conn, row)

    def list_concepts(
        self,
        chapter_id: Optional[str] = None,
        book_id: Optional[str] = None,
        topic: Optional[str] = None,
        workspace: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        ws_id = self.resolve_workspace_id(workspace)
        if ws_id == "__missing_workspace__":
            return []
        with self.connect() as conn:
            if chapter_id:
                rows = conn.execute(
                    "SELECT * FROM concepts WHERE chapter_id = ? ORDER BY created_at ASC",
                    (chapter_id,),
                ).fetchall()
            elif book_id:
                rows = conn.execute(
                    "SELECT * FROM concepts WHERE book_id = ? ORDER BY created_at ASC",
                    (book_id,),
                ).fetchall()
            elif ws_id:
                rows = conn.execute(
                    "SELECT * FROM concepts WHERE workspace_id = ? ORDER BY created_at ASC",
                    (ws_id,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM concepts ORDER BY created_at ASC").fetchall()
            concepts = [self._hydrate_concept(conn, r) for r in rows]
            if topic:
                t_lower = topic.strip().lower()
                concepts = [c for c in concepts if any(t.lower() == t_lower for t in c["topic_areas"])]
            return concepts

    def _hydrate_concept(self, conn: sqlite3.Connection, row: sqlite3.Row) -> Dict[str, Any]:
        cid = row["id"]
        parents = [
            r["parent_id"]
            for r in conn.execute("SELECT parent_id FROM concept_edges WHERE child_id = ?", (cid,)).fetchall()
        ]
        children = [
            r["child_id"]
            for r in conn.execute("SELECT child_id FROM concept_edges WHERE parent_id = ?", (cid,)).fetchall()
        ]
        keys = row.keys()
        return {
            "id": cid,
            "workspace_id": row["workspace_id"] if "workspace_id" in keys else None,
            "slug": row["slug"],
            "name": row["name"],
            "summary": row["summary"],
            "book_id": row["book_id"],
            "chapter_id": row["chapter_id"],
            "topic_areas": json.loads(row["topic_areas_json"] or "[]"),
            "mastery_state": row["mastery_state"],
            "core_passed": bool(row["core_passed"]),
            "page_refs": json.loads(row["page_refs_json"] or "[]"),
            "misconceptions": json.loads(row["misconceptions_json"] or "[]"),
            "frontiers": json.loads(row["frontiers_json"] or "[]"),
            "parent_ids": parents,
            "child_ids": children,
            "fsrs_stability": float(row["fsrs_stability"] or 0.0),
            "fsrs_difficulty": float(row["fsrs_difficulty"] or 5.0),
            "fsrs_reps": int(row["fsrs_reps"] or 0),
            "fsrs_lapses": int(row["fsrs_lapses"] or 0),
            "fsrs_due_at": row["fsrs_due_at"],
            "fsrs_last_review_at": row["fsrs_last_review_at"],
        }

    def add_concept_edge(self, parent_id: str, child_id: str, relation: str = "prerequisite") -> Tuple[bool, str]:
        """Add directed prerequisite edge `parent_id -> child_id`, rejecting cycles."""
        if parent_id == child_id:
            return False, "A concept cannot be its own prerequisite."
        with self.connect() as conn:
            if not conn.execute("SELECT 1 FROM concepts WHERE id = ?", (parent_id,)).fetchone():
                return False, f"Parent concept {parent_id} not found."
            if not conn.execute("SELECT 1 FROM concepts WHERE id = ?", (child_id,)).fetchone():
                return False, f"Child concept {child_id} not found."
            visited: set[str] = set()
            stack = [child_id]
            while stack:
                curr = stack.pop()
                if curr == parent_id:
                    return False, "Adding this prerequisite edge would create a cycle in the concept DAG."
                if curr in visited:
                    continue
                visited.add(curr)
                next_rows = conn.execute(
                    "SELECT child_id FROM concept_edges WHERE parent_id = ?",
                    (curr,),
                ).fetchall()
                stack.extend(r["child_id"] for r in next_rows)

            conn.execute(
                """
                INSERT OR IGNORE INTO concept_edges (parent_id, child_id, relation, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (parent_id, child_id, relation, utc_now()),
            )
            return True, "Edge added."

    def delete_concept_edge(self, parent_id: str, child_id: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute(
                "DELETE FROM concept_edges WHERE parent_id = ? AND child_id = ?",
                (parent_id, child_id),
            )
            return cur.rowcount > 0

    def list_edges(self) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT parent_id, child_id, relation FROM concept_edges").fetchall()
            return [dict(r) for r in rows]

    def merge_concepts(self, source_id: str, target_id: str) -> Optional[Dict[str, Any]]:
        if source_id == target_id:
            return self.get_concept(target_id)
        src = self.get_concept(source_id)
        tgt = self.get_concept(target_id)
        if not src or not tgt:
            return None

        merged_topics = sorted(set(tgt["topic_areas"]) | set(src["topic_areas"]))
        merged_pages = sorted(set(tgt["page_refs"]) | set(src["page_refs"]))
        merged_misc = list(dict.fromkeys(tgt["misconceptions"] + src["misconceptions"]))
        merged_frontiers = list(dict.fromkeys(tgt["frontiers"] + src["frontiers"]))

        with self.connect() as conn:
            conn.execute(
                """
                UPDATE concepts
                SET topic_areas_json = ?, page_refs_json = ?, misconceptions_json = ?, frontiers_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    json.dumps(merged_topics),
                    json.dumps(merged_pages),
                    json.dumps(merged_misc),
                    json.dumps(merged_frontiers),
                    utc_now(),
                    target_id,
                ),
            )
            for p_id in src["parent_ids"]:
                if p_id != target_id:
                    conn.execute(
                        "INSERT OR IGNORE INTO concept_edges (parent_id, child_id, relation, created_at) VALUES (?, ?, 'prerequisite', ?)",
                        (p_id, target_id, utc_now()),
                    )
            for c_id in src["child_ids"]:
                if c_id != target_id:
                    conn.execute(
                        "INSERT OR IGNORE INTO concept_edges (parent_id, child_id, relation, created_at) VALUES (?, ?, 'prerequisite', ?)",
                        (target_id, c_id, utc_now()),
                    )
            conn.execute("UPDATE learner_notes SET concept_id = ? WHERE concept_id = ?", (target_id, source_id))
            conn.execute("UPDATE question_history SET concept_id = ? WHERE concept_id = ?", (target_id, source_id))
            conn.execute("DELETE FROM concepts WHERE id = ?", (source_id,))
        return self.get_concept(target_id)

    def update_concept_mastery_and_fsrs(
        self,
        concept_id: str,
        mastery_state: str,
        core_passed: bool,
        fsrs_stability: Optional[float] = None,
        fsrs_difficulty: Optional[float] = None,
        fsrs_reps: Optional[int] = None,
        fsrs_lapses: Optional[int] = None,
        fsrs_due_at: Optional[str] = None,
        fsrs_last_review_at: Optional[str] = None,
        append_frontier: Optional[str] = None,
        append_misconception: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        current = self.get_concept(concept_id)
        if not current:
            return None
        frontiers = list(current["frontiers"])
        if append_frontier and append_frontier not in frontiers:
            frontiers.append(append_frontier)
        misconceptions = list(current["misconceptions"])
        if append_misconception and append_misconception not in misconceptions:
            misconceptions.append(append_misconception)

        with self.connect() as conn:
            conn.execute(
                """
                UPDATE concepts
                SET mastery_state = ?,
                    core_passed = ?,
                    frontiers_json = ?,
                    misconceptions_json = ?,
                    fsrs_stability = COALESCE(?, fsrs_stability),
                    fsrs_difficulty = COALESCE(?, fsrs_difficulty),
                    fsrs_reps = COALESCE(?, fsrs_reps),
                    fsrs_lapses = COALESCE(?, fsrs_lapses),
                    fsrs_due_at = COALESCE(?, fsrs_due_at),
                    fsrs_last_review_at = COALESCE(?, fsrs_last_review_at),
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    mastery_state,
                    1 if core_passed else 0,
                    json.dumps(frontiers),
                    json.dumps(misconceptions),
                    fsrs_stability,
                    fsrs_difficulty,
                    fsrs_reps,
                    fsrs_lapses,
                    fsrs_due_at,
                    fsrs_last_review_at,
                    utc_now(),
                    current["id"],
                ),
            )
        return self.get_concept(current["id"])

    # ---------- Sessions & Messages ----------

    def create_session(
        self,
        book_id: str,
        chapter_id: Optional[str],
        stage: str = "plan",
        active_concept_id: Optional[str] = None,
        exam_state: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = utc_now()
        sid = session_id or new_id("sess")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (id, book_id, chapter_id, stage, active_concept_id, covered_concept_ids_json, exam_state_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, '[]', ?, ?, ?)
                """,
                (
                    sid,
                    book_id,
                    chapter_id,
                    stage,
                    active_concept_id,
                    json.dumps(exam_state) if exam_state else None,
                    now,
                    now,
                ),
            )
        return self.get_session(sid)  # type: ignore[return-value]

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if not row:
                return None
            msgs = conn.execute(
                "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at ASC, rowid ASC",
                (session_id,),
            ).fetchall()
            return self._row_to_session(row, msgs)

    def get_latest_chapter_session(self, chapter_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE chapter_id = ? ORDER BY updated_at DESC LIMIT 1",
                (chapter_id,),
            ).fetchone()
            if not row:
                return None
            msgs = conn.execute(
                "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at ASC, rowid ASC",
                (row["id"],),
            ).fetchall()
            return self._row_to_session(row, msgs)

    def list_chapter_sessions(self, chapter_id: str) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id, stage, created_at, updated_at FROM sessions WHERE chapter_id = ? ORDER BY updated_at DESC",
                (chapter_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def update_session(
        self,
        session_id: str,
        stage: Optional[str] = None,
        active_concept_id: Optional[str] = None,
        covered_concept_ids: Optional[List[str]] = None,
        exam_state: Optional[Dict[str, Any]] = None,
        clear_exam_state: bool = False,
        agent_conversation_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if not row:
                return None
            new_stage = stage or row["stage"]
            new_active = active_concept_id if active_concept_id is not None else row["active_concept_id"]
            new_covered = (
                json.dumps(covered_concept_ids)
                if covered_concept_ids is not None
                else row["covered_concept_ids_json"]
            )
            if clear_exam_state:
                new_exam = None
            elif exam_state is not None:
                new_exam = json.dumps(exam_state)
            else:
                new_exam = row["exam_state_json"]
            new_conv = agent_conversation_id or row["agent_conversation_id"]
            conn.execute(
                """
                UPDATE sessions
                SET stage = ?, active_concept_id = ?, covered_concept_ids_json = ?,
                    exam_state_json = ?, agent_conversation_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_stage, new_active, new_covered, new_exam, new_conv, utc_now(), session_id),
            )
        return self.get_session(session_id)

    def append_message(
        self,
        session_id: str,
        speaker: str,
        stage: str,
        content: str,
        citations: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        now = utc_now()
        mid = new_id("msg")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO messages (id, session_id, speaker, stage, content, citations_json, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mid,
                    session_id,
                    speaker,
                    stage,
                    content,
                    json.dumps(citations or []),
                    json.dumps(metadata or {}),
                    now,
                ),
            )
            conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
        return {
            "id": mid,
            "session_id": session_id,
            "speaker": speaker,
            "stage": stage,
            "content": content,
            "citations": citations or [],
            "metadata": metadata or {},
            "created_at": now,
        }

    @staticmethod
    def _row_to_session(row: sqlite3.Row, msgs: Iterable[sqlite3.Row]) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "book_id": row["book_id"],
            "chapter_id": row["chapter_id"],
            "stage": row["stage"],
            "active_concept_id": row["active_concept_id"],
            "covered_concept_ids": json.loads(row["covered_concept_ids_json"] or "[]"),
            "exam_state": json.loads(row["exam_state_json"]) if row["exam_state_json"] else None,
            "agent_conversation_id": row["agent_conversation_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "messages": [
                {
                    "id": m["id"],
                    "session_id": m["session_id"],
                    "speaker": m["speaker"],
                    "stage": m["stage"],
                    "content": m["content"],
                    "citations": json.loads(m["citations_json"] or "[]"),
                    "metadata": json.loads(m["metadata_json"] or "{}"),
                    "created_at": m["created_at"],
                }
                for m in msgs
            ],
        }

    # ---------- Question History ----------

    def record_question_stem(
        self,
        chapter_id: Optional[str],
        concept_id: Optional[str],
        cognitive_level: str,
        question_stem: str,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO question_history (id, chapter_id, concept_id, cognitive_level, question_stem, asked_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (new_id("q"), chapter_id, concept_id, cognitive_level, question_stem.strip(), utc_now()),
            )

    def list_asked_stems(
        self,
        chapter_id: Optional[str] = None,
        concept_id: Optional[str] = None,
    ) -> List[str]:
        with self.connect() as conn:
            if concept_id:
                rows = conn.execute(
                    "SELECT question_stem FROM question_history WHERE concept_id = ? ORDER BY asked_at DESC",
                    (concept_id,),
                ).fetchall()
            elif chapter_id:
                rows = conn.execute(
                    "SELECT question_stem FROM question_history WHERE chapter_id = ? ORDER BY asked_at DESC",
                    (chapter_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT question_stem FROM question_history ORDER BY asked_at DESC LIMIT 100"
                ).fetchall()
            return [r["question_stem"] for r in rows]

    # ---------- Learner Notes ----------

    def add_learner_note(
        self,
        kind: str,
        content: str,
        chapter_id: Optional[str] = None,
        concept_id: Optional[str] = None,
        resolved: bool = False,
    ) -> Dict[str, Any]:
        nid = new_id("ln")
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO learner_notes (id, chapter_id, concept_id, kind, content, resolved, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (nid, chapter_id, concept_id, kind, content.strip(), 1 if resolved else 0, now),
            )
        return {
            "id": nid,
            "chapter_id": chapter_id,
            "concept_id": concept_id,
            "kind": kind,
            "content": content.strip(),
            "resolved": resolved,
            "created_at": now,
        }

    def list_learner_notes(
        self,
        chapter_id: Optional[str] = None,
        concept_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            if chapter_id:
                rows = conn.execute(
                    "SELECT * FROM learner_notes WHERE chapter_id = ? ORDER BY created_at DESC",
                    (chapter_id,),
                ).fetchall()
            elif concept_ids:
                placeholders = ",".join("?" for _ in concept_ids)
                rows = conn.execute(
                    f"SELECT * FROM learner_notes WHERE concept_id IN ({placeholders}) ORDER BY created_at DESC",
                    tuple(concept_ids),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM learner_notes ORDER BY created_at DESC LIMIT 60").fetchall()
            return [
                {
                    "id": r["id"],
                    "chapter_id": r["chapter_id"],
                    "concept_id": r["concept_id"],
                    "kind": r["kind"],
                    "content": r["content"],
                    "resolved": bool(r["resolved"]),
                    "created_at": r["created_at"],
                }
                for r in rows
            ]

    def record_review_history(
        self,
        concept_id: str,
        probe_question: str,
        answer: str,
        rating: int,
        feedback: str,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO review_history (id, concept_id, probe_question, answer, rating, feedback, reviewed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (new_id("rev"), concept_id, probe_question, answer, rating, feedback, utc_now()),
            )

    def build_learner_memory_digest(
        self,
        chapter_id: Optional[str] = None,
        book_id: Optional[str] = None,
        workspace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build compact cross-chapter memory digest scoped to workspace & assigned chapters."""
        ws = workspace
        if not ws and book_id:
            b = self.get_book(book_id)
            if b:
                ws = b.get("workspace_id")
        all_concepts = self.list_concepts(workspace=ws)
        target_concepts = self.list_concepts(chapter_id=chapter_id) if chapter_id else []
        prereq_ids: set[str] = set()
        for c in target_concepts:
            prereq_ids.update(c["parent_ids"])

        # Exclude concepts belonging to skipped chapters
        skipped_ch_ids: set[str] = set()
        with self.connect() as conn:
            for r in conn.execute("SELECT id FROM chapters WHERE scope = 'skipped'").fetchall():
                skipped_ch_ids.add(r["id"])
        active_concepts = [c for c in all_concepts if not c.get("chapter_id") or c["chapter_id"] not in skipped_ch_ids]

        mastered = [
            {"id": c["id"], "name": c["name"], "topics": c["topic_areas"], "stability_days": c["fsrs_stability"]}
            for c in active_concepts
            if c["core_passed"] or c["mastery_state"] in ("core_passed", "mastered")
        ]
        prereq_status = [
            {
                "id": c["id"],
                "name": c["name"],
                "mastery_state": c["mastery_state"],
                "frontiers": c["frontiers"],
                "misconceptions": c["misconceptions"],
            }
            for c in active_concepts
            if c["id"] in prereq_ids
        ]
        concept_ids_in_ws = [c["id"] for c in active_concepts]
        notes = self.list_learner_notes(concept_ids=concept_ids_in_ws) if (ws and concept_ids_in_ws) else self.list_learner_notes()
        confusions = [n["content"] for n in notes if n["kind"] == "confusion" and not n["resolved"]][:12]
        frontiers = [n["content"] for n in notes if n["kind"] == "frontier"][:12]
        breakthroughs = [n["content"] for n in notes if n["kind"] == "breakthrough"][:8]
        return {
            "mastered_concepts": mastered[:25],
            "prerequisite_status": prereq_status,
            "unresolved_confusions": confusions,
            "recorded_frontiers": frontiers,
            "recent_breakthroughs": breakthroughs,
        }

    # ---------- Curricula, Phases & Items ----------

    def create_curriculum(
        self,
        workspace_id: str,
        title: str,
        subtitle: str = "",
        goal: str = "",
        weekly_rhythm: Optional[List[Dict[str, str]]] = None,
        guardrails: Optional[List[str]] = None,
        source_markdown: str = "",
        slug: Optional[str] = None,
        curriculum_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = utc_now()
        cid = curriculum_id or new_id("cur")
        ws_id = self.resolve_workspace_id(workspace_id) or workspace_id
        c_slug = slugify(slug or title, 48)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO curricula (
                    id, workspace_id, slug, title, subtitle, goal,
                    weekly_rhythm_json, guardrails_json, source_markdown, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cid,
                    ws_id,
                    c_slug,
                    title.strip(),
                    subtitle.strip(),
                    goal.strip(),
                    json.dumps(weekly_rhythm or []),
                    json.dumps(guardrails or []),
                    source_markdown,
                    now,
                    now,
                ),
            )
        return self.get_curriculum(cid)  # type: ignore[return-value]

    def list_curricula(self, workspace: Optional[str] = None) -> List[Dict[str, Any]]:
        ws_id = self.resolve_workspace_id(workspace)
        if ws_id == "__missing_workspace__":
            return []
        with self.connect() as conn:
            if ws_id:
                rows = conn.execute(
                    "SELECT * FROM curricula WHERE workspace_id = ? ORDER BY created_at DESC",
                    (ws_id,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM curricula ORDER BY created_at DESC").fetchall()
            return [self._hydrate_curriculum(conn, r) for r in rows]

    def get_curriculum(self, curriculum_ref: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM curricula WHERE id = ? OR slug = ?",
                (curriculum_ref, curriculum_ref),
            ).fetchone()
            if not row:
                return None
            return self._hydrate_curriculum(conn, row)

    def delete_curriculum(self, curriculum_id: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM curricula WHERE id = ?", (curriculum_id,))
            return cur.rowcount > 0

    def create_curriculum_phase(
        self,
        curriculum_id: str,
        track: str,
        phase_number: int,
        title: str,
        date_range: str = "",
        goal: str = "",
        exit_criterion: str = "",
        at_work_prompt: str = "",
        order_index: Optional[int] = None,
        phase_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = utc_now()
        pid = phase_id or new_id("ph")
        norm_track = track if track in ("core", "alongside", "optional") else "core"
        with self.connect() as conn:
            if order_index is None:
                mx = conn.execute(
                    "SELECT COALESCE(MAX(order_index), 0) FROM curriculum_phases WHERE curriculum_id = ?",
                    (curriculum_id,),
                ).fetchone()[0]
                order_index = int(mx) + 1
            conn.execute(
                """
                INSERT INTO curriculum_phases (
                    id, curriculum_id, track, phase_number, title, date_range, goal,
                    exit_criterion, exit_passed, at_work_prompt, order_index, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
                """,
                (
                    pid,
                    curriculum_id,
                    norm_track,
                    phase_number,
                    title.strip(),
                    date_range.strip(),
                    goal.strip(),
                    exit_criterion.strip(),
                    at_work_prompt.strip(),
                    order_index,
                    now,
                    now,
                ),
            )
        return self.get_curriculum_phase(pid)  # type: ignore[return-value]

    def get_curriculum_phase(self, phase_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM curriculum_phases WHERE id = ?", (phase_id,)).fetchone()
            if not row:
                return None
            return self._hydrate_phase(conn, row)

    def update_curriculum_phase(
        self,
        phase_id: str,
        exit_passed: Optional[bool] = None,
        title: Optional[str] = None,
        goal: Optional[str] = None,
        exit_criterion: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        ph = self.get_curriculum_phase(phase_id)
        if not ph:
            return None
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE curriculum_phases
                SET exit_passed = ?, title = ?, goal = ?, exit_criterion = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    (1 if exit_passed else 0) if exit_passed is not None else (1 if ph["exit_passed"] else 0),
                    title.strip() if title is not None else ph["title"],
                    goal.strip() if goal is not None else ph["goal"],
                    exit_criterion.strip() if exit_criterion is not None else ph["exit_criterion"],
                    utc_now(),
                    phase_id,
                ),
            )
        return self.get_curriculum_phase(phase_id)

    def create_curriculum_item(
        self,
        phase_id: str,
        title: str,
        kind: str = "reading",
        week_label: str = "",
        description: str = "",
        external_url: str = "",
        linked_book_id: Optional[str] = None,
        linked_chapter_ids: Optional[List[str]] = None,
        status: str = "todo",
        order_index: Optional[int] = None,
        item_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = utc_now()
        iid = item_id or new_id("ci")
        norm_kind = kind if kind in ("reading", "do_task", "at_work", "milestone", "cuj_practice") else "reading"
        norm_status = status if status in ("todo", "in_progress", "done", "skipped") else "todo"
        with self.connect() as conn:
            if order_index is None:
                mx = conn.execute(
                    "SELECT COALESCE(MAX(order_index), 0) FROM curriculum_items WHERE phase_id = ?",
                    (phase_id,),
                ).fetchone()[0]
                order_index = int(mx) + 1
            conn.execute(
                """
                INSERT INTO curriculum_items (
                    id, phase_id, week_label, kind, title, description, external_url,
                    linked_book_id, linked_chapter_ids_json, status, order_index, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    iid,
                    phase_id,
                    week_label.strip(),
                    norm_kind,
                    title.strip(),
                    description.strip(),
                    external_url.strip(),
                    linked_book_id,
                    json.dumps(linked_chapter_ids or []),
                    norm_status,
                    order_index,
                    now,
                    now,
                ),
            )
            row = conn.execute("SELECT * FROM curriculum_items WHERE id = ?", (iid,)).fetchone()
            return self._hydrate_item(conn, row)

    def update_curriculum_item(
        self,
        item_id: str,
        status: Optional[str] = None,
        title: Optional[str] = None,
        description: Optional[str] = None,
        linked_chapter_ids: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM curriculum_items WHERE id = ?", (item_id,)).fetchone()
            if not row:
                return None
            new_status = status if status in ("todo", "in_progress", "done", "skipped") else row["status"]
            new_title = title.strip() if title is not None else row["title"]
            new_desc = description.strip() if description is not None else row["description"]
            new_chs = (
                json.dumps(linked_chapter_ids)
                if linked_chapter_ids is not None
                else row["linked_chapter_ids_json"]
            )
            conn.execute(
                """
                UPDATE curriculum_items
                SET status = ?, title = ?, description = ?, linked_chapter_ids_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_status, new_title, new_desc, new_chs, utc_now(), item_id),
            )
            updated = conn.execute("SELECT * FROM curriculum_items WHERE id = ?", (item_id,)).fetchone()
            return self._hydrate_item(conn, updated)

    def _hydrate_curriculum(self, conn: sqlite3.Connection, row: sqlite3.Row) -> Dict[str, Any]:
        phase_rows = conn.execute(
            "SELECT * FROM curriculum_phases WHERE curriculum_id = ? ORDER BY order_index ASC",
            (row["id"],),
        ).fetchall()
        phases = [self._hydrate_phase(conn, p) for p in phase_rows]
        all_items = [it for p in phases for it in p["items"]]
        done_items = sum(1 for it in all_items if it["status"] == "done")
        return {
            "id": row["id"],
            "workspace_id": row["workspace_id"],
            "slug": row["slug"],
            "title": row["title"],
            "subtitle": row["subtitle"],
            "goal": row["goal"],
            "weekly_rhythm": json.loads(row["weekly_rhythm_json"] or "[]"),
            "guardrails": json.loads(row["guardrails_json"] or "[]"),
            "phases": phases,
            "total_items": len(all_items),
            "done_items": done_items,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _hydrate_phase(self, conn: sqlite3.Connection, row: sqlite3.Row) -> Dict[str, Any]:
        item_rows = conn.execute(
            "SELECT * FROM curriculum_items WHERE phase_id = ? ORDER BY order_index ASC",
            (row["id"],),
        ).fetchall()
        items = [self._hydrate_item(conn, it) for it in item_rows]
        linked_chapter_ids: List[str] = []
        for it in items:
            for ch_id in it["linked_chapter_ids"]:
                if ch_id not in linked_chapter_ids:
                    linked_chapter_ids.append(ch_id)
        return {
            "id": row["id"],
            "curriculum_id": row["curriculum_id"],
            "track": row["track"],
            "phase_number": row["phase_number"],
            "title": row["title"],
            "date_range": row["date_range"],
            "goal": row["goal"],
            "exit_criterion": row["exit_criterion"],
            "exit_passed": bool(row["exit_passed"]),
            "at_work_prompt": row["at_work_prompt"],
            "order_index": row["order_index"],
            "items": items,
            "linked_chapter_ids": linked_chapter_ids,
            "done_count": sum(1 for it in items if it["status"] == "done"),
            "total_count": len(items),
        }

    def _hydrate_item(self, conn: sqlite3.Connection, row: sqlite3.Row) -> Dict[str, Any]:
        ch_ids: List[str] = json.loads(row["linked_chapter_ids_json"] or "[]")
        linked_chapters: List[Dict[str, Any]] = []
        if ch_ids:
            placeholders = ",".join("?" for _ in ch_ids)
            ch_rows = conn.execute(
                f"""
                SELECT c.id, c.book_id, c.title, c.start_page, c.end_page, c.status, c.scope, b.title AS book_title
                FROM chapters c
                JOIN books b ON b.id = c.book_id
                WHERE c.id IN ({placeholders})
                ORDER BY c.order_index ASC
                """,
                tuple(ch_ids),
            ).fetchall()
            by_id = {r["id"]: dict(r) for r in ch_rows}
            for cid in ch_ids:
                if cid in by_id:
                    linked_chapters.append(by_id[cid])
        book_title = None
        if row["linked_book_id"]:
            brow = conn.execute("SELECT title FROM books WHERE id = ?", (row["linked_book_id"],)).fetchone()
            if brow:
                book_title = brow["title"]
        return {
            "id": row["id"],
            "phase_id": row["phase_id"],
            "week_label": row["week_label"],
            "kind": row["kind"],
            "title": row["title"],
            "description": row["description"],
            "external_url": row["external_url"],
            "linked_book_id": row["linked_book_id"],
            "linked_book_title": book_title,
            "linked_chapter_ids": ch_ids,
            "linked_chapters": linked_chapters,
            "status": row["status"],
            "order_index": row["order_index"],
        }

    # ---------- Running Logs ----------

    def create_running_log(
        self,
        workspace_id: str,
        title: str,
        description: str = "",
        curriculum_id: Optional[str] = None,
        slug: Optional[str] = None,
        file_relpath: Optional[str] = None,
        log_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = utc_now()
        lid = log_id or new_id("log")
        ws = self.get_workspace(workspace_id)
        assert ws is not None
        l_slug = slugify(slug or title, 48)
        rel = file_relpath or f"workspaces/{ws['slug']}/logs/{l_slug}.md"
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT id FROM running_logs WHERE workspace_id = ? AND slug = ?",
                (ws["id"], l_slug),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE running_logs SET title = ?, description = ?, curriculum_id = COALESCE(?, curriculum_id), updated_at = ? WHERE id = ?",
                    (title.strip(), description.strip(), curriculum_id, now, existing["id"]),
                )
                lid = existing["id"]
            else:
                conn.execute(
                    """
                    INSERT INTO running_logs (id, workspace_id, curriculum_id, slug, title, description, file_relpath, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (lid, ws["id"], curriculum_id, l_slug, title.strip(), description.strip(), rel, now, now),
                )
        return self.get_running_log(lid)  # type: ignore[return-value]

    def list_running_logs(
        self,
        workspace: Optional[str] = None,
        curriculum_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        ws_id = self.resolve_workspace_id(workspace)
        if ws_id == "__missing_workspace__":
            return []
        with self.connect() as conn:
            if curriculum_id:
                rows = conn.execute(
                    """
                    SELECT rl.*, w.slug AS workspace_slug
                    FROM running_logs rl
                    JOIN workspaces w ON w.id = rl.workspace_id
                    WHERE rl.curriculum_id = ?
                    ORDER BY rl.created_at ASC
                    """,
                    (curriculum_id,),
                ).fetchall()
            elif ws_id:
                rows = conn.execute(
                    """
                    SELECT rl.*, w.slug AS workspace_slug
                    FROM running_logs rl
                    JOIN workspaces w ON w.id = rl.workspace_id
                    WHERE rl.workspace_id = ?
                    ORDER BY rl.created_at ASC
                    """,
                    (ws_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT rl.*, w.slug AS workspace_slug
                    FROM running_logs rl
                    JOIN workspaces w ON w.id = rl.workspace_id
                    ORDER BY rl.created_at ASC
                    """
                ).fetchall()
            return [dict(r) for r in rows]

    def get_running_log(self, log_ref: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT rl.*, w.slug AS workspace_slug
                FROM running_logs rl
                JOIN workspaces w ON w.id = rl.workspace_id
                WHERE rl.id = ? OR rl.slug = ?
                """,
                (log_ref, log_ref),
            ).fetchone()
            return dict(row) if row else None

    def touch_running_log(self, log_id: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE running_logs SET updated_at = ? WHERE id = ?", (utc_now(), log_id))
