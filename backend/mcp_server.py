"""Companion FastMCP server exposing the Scholia vault to Antigravity, Claude Code, and Codex (v2 workspace-aware)."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:
    from mcp.server.fastmcp import FastMCP  # type: ignore[no-redef]

from scholia.config import get_vault_dir, load_config
from scholia.db import VaultDB
from scholia.fsrs import schedule_fsrs
from scholia.services.agent_runner import AgentRunner
from scholia.services.ingestion import IngestionService
from scholia.services.pedagogy import PedagogyService
from scholia.services.vault import VaultFS


class ScholiaMCPToolkit:
    """Testable core handlers backed by a vault directory."""

    def __init__(self, vault_dir: Optional[Path] = None):
        self.vault_dir = (vault_dir or get_vault_dir()).resolve()
        self.config = load_config(self.vault_dir)
        self.db = VaultDB(self.vault_dir)
        self.fs = VaultFS(self.vault_dir)
        self.ingestion = IngestionService(self.db, self.fs)
        self.runner = AgentRunner(self.config.binary_overrides)
        self.pedagogy = PedagogyService(self.db, self.fs, self.ingestion, self.runner, self.config)

    def list_workspaces(self) -> List[Dict[str, Any]]:
        """List all big-umbrella workspaces (e.g. Career, General) with book and curriculum counts."""
        return self.db.list_workspaces()

    def list_books(self, workspace: Optional[str] = None) -> List[Dict[str, Any]]:
        """List books in the local Scholia vault, optionally scoped to a workspace slug or ID."""
        return self.db.list_books(workspace=workspace)

    def get_chapter_notes(self, chapter_id: str) -> Dict[str, Any]:
        """Return persistent Markdown study notes and metadata for a chapter."""
        chapter = self.db.get_chapter(chapter_id)
        if not chapter:
            return {"error": f"Chapter '{chapter_id}' not found."}
        book = self.db.get_book(chapter["book_id"])
        assert book is not None
        notes = self.fs.read_chapter_notes(book["slug"], chapter["slug"], book.get("workspace_slug"))
        return {
            "book_id": book["id"],
            "book_title": book["title"],
            "workspace_slug": book.get("workspace_slug"),
            "chapter_id": chapter["id"],
            "chapter_title": chapter["title"],
            "scope": chapter.get("scope", "assigned"),
            "pages": f"{chapter['start_page']}-{chapter['end_page']}",
            "status": chapter["status"],
            "notes_markdown": notes,
        }

    def get_lesson_plan(self, chapter_id: str) -> Dict[str, Any]:
        """Return structured lesson plan JSON (ordered concepts, prerequisites, misconceptions, probes)."""
        chapter = self.db.get_chapter(chapter_id)
        if not chapter:
            return {"error": f"Chapter '{chapter_id}' not found."}
        book = self.db.get_book(chapter["book_id"])
        assert book is not None
        plan = self.fs.read_lesson_plan(book["slug"], chapter["slug"], book.get("workspace_slug"))
        return {
            "chapter_id": chapter["id"],
            "chapter_title": chapter["title"],
            "lesson_plan": plan or {},
        }

    def get_learner_memory(
        self,
        chapter_id: Optional[str] = None,
        book_id: Optional[str] = None,
        workspace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return compact cross-chapter learner memory digest (mastered concepts, confusions, frontiers)."""
        return self.db.build_learner_memory_digest(chapter_id=chapter_id, book_id=book_id, workspace=workspace)

    def log_confusion_or_frontier(
        self,
        kind: str,
        content: str,
        chapter_id: Optional[str] = None,
        concept_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Log a learner confusion, breakthrough, analogy, or knowledge frontier into SQLite and concept state."""
        norm_kind = kind if kind in ("confusion", "breakthrough", "frontier", "analogy") else "confusion"
        note = self.db.add_learner_note(norm_kind, content, chapter_id=chapter_id, concept_id=concept_id)
        if concept_id:
            concept = self.db.get_concept(concept_id)
            if concept:
                self.db.update_concept_mastery_and_fsrs(
                    concept["id"],
                    mastery_state=concept["mastery_state"],
                    core_passed=concept["core_passed"],
                    append_frontier=content if norm_kind == "frontier" else None,
                    append_misconception=content if norm_kind == "confusion" else None,
                )
        return note

    def record_concept_mastery(
        self,
        concept_id: str,
        mastery_state: str = "mastered",
        core_passed: bool = True,
        rating: int = 3,
    ) -> Dict[str, Any]:
        """Update concept mastery state and enroll or advance its FSRS spaced repetition schedule."""
        concept = self.db.get_concept(concept_id)
        if not concept:
            return {"error": f"Concept '{concept_id}' not found."}
        fsrs_state = schedule_fsrs(
            stability=concept["fsrs_stability"],
            difficulty=concept["fsrs_difficulty"],
            reps=concept["fsrs_reps"],
            lapses=concept["fsrs_lapses"],
            last_review_at=concept["fsrs_last_review_at"],
            rating=rating,
        )
        updated = self.db.update_concept_mastery_and_fsrs(
            concept_id=concept["id"],
            mastery_state=mastery_state,
            core_passed=core_passed,
            fsrs_stability=fsrs_state.stability,
            fsrs_difficulty=fsrs_state.difficulty,
            fsrs_reps=fsrs_state.reps,
            fsrs_lapses=fsrs_state.lapses,
            fsrs_due_at=fsrs_state.due_at,
            fsrs_last_review_at=fsrs_state.last_review_at,
        )
        return updated or {"error": "Update failed"}

    def get_due_reviews(self, topic: Optional[str] = None, workspace: Optional[str] = None) -> Dict[str, Any]:
        """Return topic-segmented due spaced repetition review cards and fresh understanding probes."""
        return {
            "topics": self.pedagogy.list_review_topics(workspace=workspace),
            "due_cards": self.pedagogy.list_due_reviews(topic=topic, workspace=workspace),
        }

    def query_topic_graph(self, topic: Optional[str] = None, workspace: Optional[str] = None) -> Dict[str, Any]:
        """Return multi-parent concept DAG nodes and directed prerequisite edges, optionally filtered by workspace/topic."""
        nodes = self.db.list_concepts(topic=topic, workspace=workspace)
        node_ids = {n["id"] for n in nodes}
        edges = [e for e in self.db.list_edges() if e["parent_id"] in node_ids and e["child_id"] in node_ids]
        return {
            "workspace": workspace or "all",
            "topic": topic or "all",
            "node_count": len(nodes),
            "edge_count": len(edges),
            "nodes": nodes,
            "edges": edges,
        }

    def get_curriculum(self, workspace: Optional[str] = None) -> Dict[str, Any]:
        """Return active curricula (phases, tracks, weekly items, exit criteria) for a workspace."""
        curricula = self.db.list_curricula(workspace=workspace)
        logs = self.db.list_running_logs(workspace=workspace)
        return {"curricula": curricula, "running_logs": logs}

    def get_running_log(self, log_slug_or_id: str) -> Dict[str, Any]:
        """Read a persistent workspace running log Markdown notebook."""
        lg = self.db.get_running_log(log_slug_or_id)
        if not lg:
            return {"error": f"Running log '{log_slug_or_id}' not found."}
        lg["content"] = self.fs.read_running_log(lg["workspace_slug"], lg["slug"], lg["file_relpath"])
        return lg

    def append_running_log(self, log_slug_or_id: str, entry_markdown: str) -> Dict[str, Any]:
        """Append a dated entry to a workspace running log Markdown file."""
        lg = self.db.get_running_log(log_slug_or_id)
        if not lg:
            return {"error": f"Running log '{log_slug_or_id}' not found."}
        existing = self.fs.read_running_log(lg["workspace_slug"], lg["slug"], lg["file_relpath"])
        updated_content = (existing.rstrip() + "\n\n" + entry_markdown.strip()).strip() + "\n"
        self.fs.write_running_log(lg["workspace_slug"], lg["slug"], updated_content, lg["file_relpath"])
        self.db.touch_running_log(lg["id"])
        return {"id": lg["id"], "slug": lg["slug"], "updated": True, "length": len(updated_content)}


def create_mcp_server(vault_dir: Optional[Path] = None) -> FastMCP:
    toolkit = ScholiaMCPToolkit(vault_dir)
    mcp = FastMCP("scholia")

    mcp.tool()(toolkit.list_workspaces)
    mcp.tool()(toolkit.list_books)
    mcp.tool()(toolkit.get_chapter_notes)
    mcp.tool()(toolkit.get_lesson_plan)
    mcp.tool()(toolkit.get_learner_memory)
    mcp.tool()(toolkit.log_confusion_or_frontier)
    mcp.tool()(toolkit.record_concept_mastery)
    mcp.tool()(toolkit.get_due_reviews)
    mcp.tool()(toolkit.query_topic_graph)
    mcp.tool()(toolkit.get_curriculum)
    mcp.tool()(toolkit.get_running_log)
    mcp.tool()(toolkit.append_running_log)
    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Scholia companion FastMCP server.")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--vault", type=str, default=None, help="Override vault directory path.")
    args = parser.parse_args()

    vault_path = Path(args.vault).expanduser().resolve() if args.vault else None
    server = create_mcp_server(vault_path)
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
