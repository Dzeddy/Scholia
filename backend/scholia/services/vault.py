"""Obsidian-friendly local vault filesystem layout manager (v2 workspace-aware)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from ..config import ensure_vault_dirs


class VaultFS:
    """Manages human-readable Markdown, JSON, assets, logs, and sliced sources in the vault."""

    def __init__(self, vault_dir: Path):
        self.vault_dir = ensure_vault_dirs(vault_dir)

    def workspace_dir(self, workspace_slug: str) -> Path:
        path = self.vault_dir / "workspaces" / workspace_slug
        path.mkdir(parents=True, exist_ok=True)
        (path / "books").mkdir(parents=True, exist_ok=True)
        (path / "curricula").mkdir(parents=True, exist_ok=True)
        (path / "logs").mkdir(parents=True, exist_ok=True)
        return path

    def book_dir(self, book_slug: str, workspace_slug: Optional[str] = None) -> Path:
        legacy = self.vault_dir / "books" / book_slug
        if workspace_slug:
            preferred = self.workspace_dir(workspace_slug) / "books" / book_slug
            if not preferred.exists() and legacy.exists():
                path = legacy
            else:
                path = preferred
        else:
            if legacy.exists():
                path = legacy
            else:
                # Search workspaces for an existing book folder so single-arg v1 callers keep working
                found: Optional[Path] = None
                ws_root = self.vault_dir / "workspaces"
                if ws_root.exists():
                    for candidate in ws_root.glob(f"*/books/{book_slug}"):
                        if candidate.is_dir():
                            found = candidate
                            break
                path = found if found else legacy
        path.mkdir(parents=True, exist_ok=True)
        (path / "chapters").mkdir(parents=True, exist_ok=True)
        return path

    def book_assets_dir(self, book_slug: str, workspace_slug: Optional[str] = None) -> Path:
        path = self.book_dir(book_slug, workspace_slug) / "assets"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def chapter_dir(self, book_slug: str, chapter_slug: str, workspace_slug: Optional[str] = None) -> Path:
        path = self.book_dir(book_slug, workspace_slug) / "chapters" / chapter_slug
        path.mkdir(parents=True, exist_ok=True)
        (path / "pages").mkdir(parents=True, exist_ok=True)
        (path / "sessions").mkdir(parents=True, exist_ok=True)
        return path

    def write_book_meta(self, book_slug: str, meta: Dict[str, Any], workspace_slug: Optional[str] = None) -> Path:
        path = self.book_dir(book_slug, workspace_slug) / "meta.json"
        path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        return path

    def read_book_meta(self, book_slug: str, workspace_slug: Optional[str] = None) -> Optional[Dict[str, Any]]:
        path = self.book_dir(book_slug, workspace_slug) / "meta.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def write_chapter_notes(
        self, book_slug: str, chapter_slug: str, markdown: str, workspace_slug: Optional[str] = None
    ) -> Path:
        path = self.chapter_dir(book_slug, chapter_slug, workspace_slug) / "notes.md"
        path.write_text(markdown, encoding="utf-8")
        return path

    def read_chapter_notes(
        self, book_slug: str, chapter_slug: str, workspace_slug: Optional[str] = None
    ) -> str:
        path = self.chapter_dir(book_slug, chapter_slug, workspace_slug) / "notes.md"
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def append_chapter_notes(
        self, book_slug: str, chapter_slug: str, appendix_markdown: str, workspace_slug: Optional[str] = None
    ) -> Path:
        path = self.chapter_dir(book_slug, chapter_slug, workspace_slug) / "notes.md"
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        combined = (existing.rstrip() + "\n\n" + appendix_markdown.lstrip()).strip() + "\n"
        path.write_text(combined, encoding="utf-8")
        return path

    def write_lesson_plan(
        self, book_slug: str, chapter_slug: str, plan: Dict[str, Any], workspace_slug: Optional[str] = None
    ) -> Path:
        path = self.chapter_dir(book_slug, chapter_slug, workspace_slug) / "lesson_plan.json"
        path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        return path

    def read_lesson_plan(
        self, book_slug: str, chapter_slug: str, workspace_slug: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        path = self.chapter_dir(book_slug, chapter_slug, workspace_slug) / "lesson_plan.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def write_session_snapshot(
        self, book_slug: str, chapter_slug: str, session: Dict[str, Any], workspace_slug: Optional[str] = None
    ) -> Path:
        path = self.chapter_dir(book_slug, chapter_slug, workspace_slug) / "sessions" / f"{session['id']}.json"
        path.write_text(json.dumps(session, indent=2) + "\n", encoding="utf-8")
        return path

    def chapter_source_pdf(
        self, book_slug: str, chapter_slug: str, workspace_slug: Optional[str] = None
    ) -> Path:
        return self.chapter_dir(book_slug, chapter_slug, workspace_slug) / "source.pdf"

    def chapter_source_md(
        self, book_slug: str, chapter_slug: str, workspace_slug: Optional[str] = None
    ) -> Path:
        return self.chapter_dir(book_slug, chapter_slug, workspace_slug) / "source.md"

    def read_chapter_source_md(
        self, book_slug: str, chapter_slug: str, workspace_slug: Optional[str] = None
    ) -> str:
        path = self.chapter_source_md(book_slug, chapter_slug, workspace_slug)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def book_source_path(
        self, book_slug: str, source_format: str, workspace_slug: Optional[str] = None
    ) -> Path:
        return self.book_dir(book_slug, workspace_slug) / f"source.{source_format}"

    def delete_book_files(self, book_slug: str, workspace_slug: Optional[str] = None) -> None:
        if workspace_slug:
            ws_path = self.vault_dir / "workspaces" / workspace_slug / "books" / book_slug
            if ws_path.exists():
                shutil.rmtree(ws_path, ignore_errors=True)
        legacy = self.vault_dir / "books" / book_slug
        if legacy.exists():
            shutil.rmtree(legacy, ignore_errors=True)

    # ---------- Curricula & Running Logs ----------

    def write_curriculum_markdown(self, workspace_slug: str, curriculum_slug: str, markdown: str) -> Path:
        path = self.workspace_dir(workspace_slug) / "curricula" / f"{curriculum_slug}.md"
        path.write_text(markdown, encoding="utf-8")
        return path

    def running_log_path(self, workspace_slug: str, log_slug: str) -> Path:
        return self.workspace_dir(workspace_slug) / "logs" / f"{log_slug}.md"

    def read_running_log(self, workspace_slug: str, log_slug: str, file_relpath: Optional[str] = None) -> str:
        if file_relpath:
            p = (self.vault_dir / file_relpath).resolve()
            if p.exists():
                return p.read_text(encoding="utf-8")
        p = self.running_log_path(workspace_slug, log_slug)
        if not p.exists():
            return ""
        return p.read_text(encoding="utf-8")

    def write_running_log(
        self, workspace_slug: str, log_slug: str, content: str, file_relpath: Optional[str] = None
    ) -> Path:
        if file_relpath:
            p = (self.vault_dir / file_relpath).resolve()
            p.parent.mkdir(parents=True, exist_ok=True)
        else:
            p = self.running_log_path(workspace_slug, log_slug)
        p.write_text(content, encoding="utf-8")
        return p
