"""FastAPI HTTP and SSE backend for Scholia (v2 workspaces, curricula, rich ingestion & assets)."""

from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from .config import get_vault_dir, load_config, save_config
from .db import VaultDB
from .models import (
    BulkChapterScopeRequest,
    CreateRunningLogRequest,
    CreateWorkspaceRequest,
    GraphEdgeRequest,
    ImportLocalRequest,
    ImportUrlRequest,
    MergeConceptsRequest,
    ReviewAnswerRequest,
    SessionTurnRequest,
    SettingsResponse,
    SettingsUpdateRequest,
    StartSessionRequest,
    SynthesisExamRequest,
    UpdateBoundariesRequest,
    UpdateChapterScopeRequest,
    UpdateCurriculumItemRequest,
    UpdateCurriculumPhaseRequest,
    UpdateRunningLogRequest,
    UpdateWorkspaceRequest,
)
from .prompts.templates import load_study_notes_contract, load_voice_rules_contract
from .services.agent_runner import AgentRunner
from .services.ingestion import IngestionService
from .services.pedagogy import PedagogyService
from .services.vault import VaultFS


class AppContainer:
    """Holds live vault-backed services and reloads cleanly if vault path changes."""

    def __init__(self, vault_dir: Optional[Path] = None):
        self.vault_dir = (vault_dir or get_vault_dir()).resolve()
        self.reload(self.vault_dir)

    def reload(self, vault_dir: Path) -> None:
        self.vault_dir = vault_dir.resolve()
        self.config = load_config(self.vault_dir)
        self.db = VaultDB(self.vault_dir)
        self.fs = VaultFS(self.vault_dir)
        self.ingestion = IngestionService(self.db, self.fs)
        self.runner = AgentRunner(self.config.binary_overrides)
        self.pedagogy = PedagogyService(self.db, self.fs, self.ingestion, self.runner, self.config)


def create_app(vault_dir: Optional[Path] = None) -> FastAPI:
    app = FastAPI(title="Scholia Studio API", version="0.2.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    container = AppContainer(vault_dir)
    app.state.container = container

    def sse_event(payload: Dict[str, Any]) -> str:
        return f"data: {json.dumps(payload)}\n\n"

    # ---------- Health & Settings ----------

    @app.get("/api/health")
    def health() -> Dict[str, Any]:
        return {
            "status": "ok",
            "version": "2.0",
            "vault_dir": str(container.vault_dir),
            "workspaces": len(container.db.list_workspaces()),
            "books": len(container.db.list_books()),
        }

    @app.get("/api/agents/status")
    def agents_status() -> Dict[str, Any]:
        agents = [a.model_dump() for a in container.runner.detect_agents()]
        return {
            "agents": agents,
            "routing": {k: v.model_dump() for k, v in container.config.routing.items()},
        }

    @app.get("/api/settings", response_model=SettingsResponse)
    def get_settings() -> SettingsResponse:
        cfg = container.config
        return SettingsResponse(
            vault_dir=str(container.vault_dir),
            routing=cfg.routing,
            binary_overrides=cfg.binary_overrides,
            max_pdf_pages_per_slice=cfg.max_pdf_pages_per_slice,
            socratic_max_sentences=cfg.socratic_max_sentences,
            voice_rules_enabled=cfg.voice_rules_enabled,
            voice_rules_preview=load_voice_rules_contract(),
            study_notes_contract_preview=load_study_notes_contract(),
        )

    @app.put("/api/settings", response_model=SettingsResponse)
    def update_settings(body: SettingsUpdateRequest) -> SettingsResponse:
        cfg = container.config
        if body.routing is not None:
            cfg.routing.update(body.routing)
        if body.binary_overrides is not None:
            cfg.binary_overrides = body.binary_overrides
        if body.max_pdf_pages_per_slice is not None:
            cfg.max_pdf_pages_per_slice = max(5, min(30, body.max_pdf_pages_per_slice))
        if body.socratic_max_sentences is not None:
            cfg.socratic_max_sentences = max(2, min(6, body.socratic_max_sentences))
        if body.voice_rules_enabled is not None:
            cfg.voice_rules_enabled = body.voice_rules_enabled

        target_vault = Path(body.vault_dir).expanduser().resolve() if body.vault_dir else container.vault_dir
        save_config(cfg, target_vault)
        container.reload(target_vault)
        return get_settings()

    # ---------- Big-Umbrella Workspaces ----------

    @app.get("/api/workspaces")
    def list_workspaces() -> Dict[str, Any]:
        wss = container.db.list_workspaces()
        default_ws = container.db.get_default_workspace()
        return {"workspaces": wss, "default_workspace": default_ws}

    @app.post("/api/workspaces")
    def create_workspace(body: CreateWorkspaceRequest) -> Dict[str, Any]:
        if not body.name.strip():
            raise HTTPException(status_code=400, detail="Workspace name is required.")
        ws = container.db.create_workspace(name=body.name, description=body.description, slug=body.slug)
        container.fs.workspace_dir(ws["slug"])
        return ws

    @app.put("/api/workspaces/{workspace_ref}")
    def update_workspace(workspace_ref: str, body: UpdateWorkspaceRequest) -> Dict[str, Any]:
        ws = container.db.update_workspace(workspace_ref, name=body.name, description=body.description)
        if not ws:
            raise HTTPException(status_code=404, detail="Workspace not found.")
        return ws

    @app.delete("/api/workspaces/{workspace_ref}")
    def delete_workspace(workspace_ref: str) -> Dict[str, Any]:
        wss = container.db.list_workspaces()
        if len(wss) <= 1:
            raise HTTPException(status_code=400, detail="Cannot delete the last remaining workspace.")
        ok = container.db.delete_workspace(workspace_ref)
        if not ok:
            raise HTTPException(status_code=404, detail="Workspace not found.")
        return {"deleted": True}

    # ---------- Books, Ingestion & Boundaries ----------

    @app.post("/api/books/upload")
    async def upload_book(
        file: UploadFile = File(...),
        title: str = Form(default=""),
        authors: str = Form(default=""),
        topic_areas: str = Form(default=""),
        workspace_id: str = Form(default=""),
    ) -> Dict[str, Any]:
        raw = await file.read()
        if not raw:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")
        topics = [t.strip() for t in topic_areas.split(",") if t.strip()] if topic_areas else []
        try:
            book = container.ingestion.ingest_upload(
                filename=file.filename or "document.pdf",
                content=raw,
                title_override=title,
                authors_override=authors,
                topic_areas=topics or None,
                workspace_id=workspace_id or None,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return book

    @app.post("/api/books/import-url")
    def import_url(body: ImportUrlRequest) -> Dict[str, Any]:
        try:
            return container.ingestion.ingest_url(
                url=body.url,
                workspace_id=body.workspace_id,
                title_override=body.title,
                authors_override=body.authors,
                topic_areas=body.topic_areas or None,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/books/import-local")
    def import_local(body: ImportLocalRequest) -> Dict[str, Any]:
        try:
            return container.ingestion.ingest_local(
                local_path=body.path,
                workspace_id=body.workspace_id,
                title_override=body.title,
                authors_override=body.authors,
                topic_areas=body.topic_areas or None,
                toc_level=body.toc_level,
                single_unit=body.single_unit,
                detect_printed_toc=body.detect_printed_toc,
                assigned_filter=body.assigned_filter,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/books")
    def list_books(workspace: Optional[str] = Query(default=None)) -> Dict[str, Any]:
        books = container.db.list_books(workspace=workspace)
        due_total = len(container.pedagogy.list_due_reviews(workspace=workspace))
        return {"books": books, "due_reviews_count": due_total}

    @app.get("/api/books/{book_id}")
    def get_book(book_id: str) -> Dict[str, Any]:
        book = container.db.get_book(book_id)
        if not book:
            raise HTTPException(status_code=404, detail="Book not found.")
        return book

    @app.get("/api/books/{book_id}/toc-tree")
    def get_book_toc_tree(book_id: str) -> Dict[str, Any]:
        try:
            return container.ingestion.get_pdf_toc_tree(book_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/books/{book_id}/detect-printed-toc")
    def detect_printed_toc(book_id: str, apply: bool = Query(default=False)) -> Dict[str, Any]:
        try:
            return container.ingestion.detect_printed_toc_for_book(book_id, apply=apply)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/books/{book_id}/assets/{asset_path:path}")
    def get_book_asset(book_id: str, asset_path: str) -> FileResponse:
        book = container.db.get_book(book_id)
        if not book:
            raise HTTPException(status_code=404, detail="Book not found.")
        assets_root = container.fs.book_assets_dir(book["slug"], book.get("workspace_slug")).resolve()
        candidate = (assets_root / asset_path).resolve()
        if not str(candidate).startswith(str(assets_root)) or not candidate.is_file():
            raise HTTPException(status_code=404, detail="Asset not found.")
        mime, _ = mimetypes.guess_type(str(candidate))
        return FileResponse(str(candidate), media_type=mime or "application/octet-stream")

    @app.put("/api/books/{book_id}/chapters/boundaries")
    def update_boundaries(book_id: str, body: UpdateBoundariesRequest) -> Dict[str, Any]:
        if not body.chapters:
            raise HTTPException(status_code=400, detail="At least one chapter boundary is required.")
        try:
            return container.ingestion.update_boundaries(
                book_id=book_id,
                chapters_input=[c.model_dump() for c in body.chapters],
                topic_areas=body.topic_areas,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.put("/api/books/{book_id}/chapters/scopes")
    def bulk_update_scopes(book_id: str, body: BulkChapterScopeRequest) -> Dict[str, Any]:
        book = container.db.get_book(book_id)
        if not book:
            raise HTTPException(status_code=404, detail="Book not found.")
        container.db.bulk_update_chapter_scopes(book["id"], body.scopes)
        container.ingestion._sync_book_meta(book["id"])
        return container.db.get_book(book["id"])  # type: ignore[return-value]

    @app.put("/api/chapters/{chapter_id}/scope")
    def update_chapter_scope(chapter_id: str, body: UpdateChapterScopeRequest) -> Dict[str, Any]:
        updated = container.db.update_chapter_scope(chapter_id, body.scope)
        if not updated:
            raise HTTPException(status_code=404, detail="Chapter not found.")
        container.ingestion._sync_book_meta(updated["book_id"])
        return updated

    @app.delete("/api/books/{book_id}")
    def delete_book(book_id: str) -> Dict[str, Any]:
        book = container.db.get_book(book_id)
        if not book:
            raise HTTPException(status_code=404, detail="Book not found.")
        container.db.delete_book(book["id"])
        container.fs.delete_book_files(book["slug"], book.get("workspace_slug"))
        return {"deleted": True, "book_id": book["id"]}

    @app.post("/api/books/{book_id}/extract-all")
    async def extract_all_chapters(
        book_id: str,
        background_tasks: BackgroundTasks,
        assigned_only: bool = Query(default=True),
    ) -> Dict[str, Any]:
        book = container.db.get_book(book_id)
        if not book:
            raise HTTPException(status_code=404, detail="Book not found.")
        if assigned_only:
            pending = [
                c["id"]
                for c in book["chapters"]
                if c.get("scope", "assigned") == "assigned" and c["status"] in ("pending", "error")
            ]
        else:
            pending = [c["id"] for c in book["chapters"] if c["status"] in ("pending", "error")]
        background_tasks.add_task(container.pedagogy.extract_book_all, book["id"], 2, assigned_only)
        return {"queued": True, "book_id": book["id"], "queued_chapter_ids": pending, "assigned_only": assigned_only}

    @app.post("/api/books/{book_id}/synthesis-exam")
    def launch_synthesis_exam(book_id: str, body: SynthesisExamRequest) -> Dict[str, Any]:
        try:
            return container.pedagogy.start_synthesis_exam(book_id, body.chapter_ids)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # ---------- Chapters & Source Media ----------

    @app.post("/api/chapters/{chapter_id}/extract")
    async def extract_chapter(chapter_id: str) -> StreamingResponse:
        if not container.db.get_chapter(chapter_id):
            raise HTTPException(status_code=404, detail="Chapter not found.")

        async def event_gen():
            try:
                async for ev in container.pedagogy.extract_chapter_stream(chapter_id):
                    yield sse_event(ev)
            except Exception as exc:
                container.db.update_chapter_status(chapter_id, "error", str(exc)[:200])
                yield sse_event({"type": "error", "message": str(exc)})

        return StreamingResponse(event_gen(), media_type="text/event-stream")

    @app.get("/api/chapters/{chapter_id}")
    def get_chapter(chapter_id: str) -> Dict[str, Any]:
        chapter = container.db.get_chapter(chapter_id)
        if not chapter:
            raise HTTPException(status_code=404, detail="Chapter not found.")
        book = container.db.get_book(chapter["book_id"])
        assert book is not None
        ws_slug = book.get("workspace_slug")
        notes_md = container.fs.read_chapter_notes(book["slug"], chapter["slug"], ws_slug)
        lesson_plan = container.fs.read_lesson_plan(book["slug"], chapter["slug"], ws_slug)
        concepts = container.db.list_concepts(chapter_id=chapter_id)
        learner_notes = container.db.list_learner_notes(chapter_id=chapter_id)
        active_session = container.db.get_latest_chapter_session(chapter_id)
        sessions = container.db.list_chapter_sessions(chapter_id)
        return {
            **chapter,
            "book_title": book["title"],
            "workspace_id": book.get("workspace_id"),
            "workspace_slug": ws_slug,
            "topic_areas": book["topic_areas"],
            "notes_markdown": notes_md,
            "lesson_plan": lesson_plan,
            "concepts": concepts,
            "learner_notes": learner_notes,
            "active_session": active_session,
            "sessions": sessions,
        }

    @app.get("/api/chapters/{chapter_id}/source-markdown")
    def get_chapter_source_markdown(chapter_id: str) -> Dict[str, Any]:
        chapter = container.db.get_chapter(chapter_id)
        if not chapter:
            raise HTTPException(status_code=404, detail="Chapter not found.")
        book = container.db.get_book(chapter["book_id"])
        assert book is not None
        md = container.fs.read_chapter_source_md(book["slug"], chapter["slug"], book.get("workspace_slug"))
        return {
            "chapter_id": chapter["id"],
            "book_id": book["id"],
            "title": chapter["title"],
            "has_pdf": chapter["has_pdf"],
            "source_markdown": md,
        }

    @app.get("/api/chapters/{chapter_id}/pdf")
    def get_chapter_pdf(chapter_id: str) -> FileResponse:
        chapter = container.db.get_chapter(chapter_id)
        if not chapter:
            raise HTTPException(status_code=404, detail="Chapter not found.")
        book = container.db.get_book(chapter["book_id"])
        assert book is not None
        pdf_path = container.fs.chapter_source_pdf(book["slug"], chapter["slug"], book.get("workspace_slug"))
        if not pdf_path.exists():
            raise HTTPException(status_code=404, detail="Chapter PDF not available.")
        return FileResponse(str(pdf_path), media_type="application/pdf", filename=f"{chapter['slug']}.pdf")

    @app.get("/api/chapters/{chapter_id}/page/{num}.png")
    def get_chapter_page_png(chapter_id: str, num: int) -> FileResponse:
        chapter = container.db.get_chapter(chapter_id)
        if not chapter:
            raise HTTPException(status_code=404, detail="Chapter not found.")
        book = container.db.get_book(chapter["book_id"])
        assert book is not None
        try:
            png_path = container.ingestion.render_chapter_page_png(
                book["slug"], chapter["slug"], num, workspace_slug=book.get("workspace_slug")
            )
        except (FileNotFoundError, IndexError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(str(png_path), media_type="image/png")

    # ---------- Multi-Book Curricula & Running Logs ----------

    @app.get("/api/curricula")
    def list_curricula(workspace: Optional[str] = Query(default=None)) -> Dict[str, Any]:
        return {"curricula": container.db.list_curricula(workspace=workspace)}

    @app.get("/api/curricula/{curriculum_ref}")
    def get_curriculum(curriculum_ref: str) -> Dict[str, Any]:
        cur = container.db.get_curriculum(curriculum_ref)
        if not cur:
            raise HTTPException(status_code=404, detail="Curriculum not found.")
        return cur

    @app.put("/api/curriculum-items/{item_id}")
    def update_curriculum_item(item_id: str, body: UpdateCurriculumItemRequest) -> Dict[str, Any]:
        updated = container.db.update_curriculum_item(
            item_id=item_id,
            status=body.status,
            title=body.title,
            description=body.description,
            linked_chapter_ids=body.linked_chapter_ids,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Curriculum item not found.")
        return updated

    @app.put("/api/curriculum-phases/{phase_id}")
    def update_curriculum_phase(phase_id: str, body: UpdateCurriculumPhaseRequest) -> Dict[str, Any]:
        updated = container.db.update_curriculum_phase(
            phase_id=phase_id,
            exit_passed=body.exit_passed,
            title=body.title,
            goal=body.goal,
            exit_criterion=body.exit_criterion,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Curriculum phase not found.")
        return updated

    @app.post("/api/curriculum-phases/{phase_id}/exit-exam")
    def launch_phase_exit_exam(phase_id: str) -> Dict[str, Any]:
        try:
            return container.pedagogy.start_phase_exit_exam(phase_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/logs")
    def list_running_logs(
        workspace: Optional[str] = Query(default=None),
        curriculum_id: Optional[str] = Query(default=None),
    ) -> Dict[str, Any]:
        logs = container.db.list_running_logs(workspace=workspace, curriculum_id=curriculum_id)
        for lg in logs:
            content = container.fs.read_running_log(lg["workspace_slug"], lg["slug"], lg["file_relpath"])
            lg["content"] = content
            lg["line_count"] = len(content.splitlines()) if content else 0
        return {"logs": logs}

    @app.post("/api/logs")
    def create_running_log(body: CreateRunningLogRequest) -> Dict[str, Any]:
        ws = container.db.get_workspace(body.workspace_id)
        if not ws:
            raise HTTPException(status_code=404, detail="Workspace not found.")
        lg = container.db.create_running_log(
            workspace_id=ws["id"],
            title=body.title,
            description=body.description,
            curriculum_id=body.curriculum_id,
        )
        initial = body.initial_content or f"# {lg['title']}\n\n{lg['description']}\n"
        container.fs.write_running_log(ws["slug"], lg["slug"], initial, lg["file_relpath"])
        lg["content"] = initial
        return lg

    @app.get("/api/logs/{log_ref}")
    def get_running_log(log_ref: str) -> Dict[str, Any]:
        lg = container.db.get_running_log(log_ref)
        if not lg:
            raise HTTPException(status_code=404, detail="Running log not found.")
        lg["content"] = container.fs.read_running_log(lg["workspace_slug"], lg["slug"], lg["file_relpath"])
        return lg

    @app.put("/api/logs/{log_ref}")
    def update_running_log(log_ref: str, body: UpdateRunningLogRequest) -> Dict[str, Any]:
        lg = container.db.get_running_log(log_ref)
        if not lg:
            raise HTTPException(status_code=404, detail="Running log not found.")
        container.fs.write_running_log(lg["workspace_slug"], lg["slug"], body.content, lg["file_relpath"])
        container.db.touch_running_log(lg["id"])
        fresh = container.db.get_running_log(lg["id"])
        assert fresh is not None
        fresh["content"] = body.content
        return fresh

    # ---------- Sessions & Streaming Turns ----------

    @app.post("/api/chapters/{chapter_id}/sessions")
    def start_chapter_session(chapter_id: str, body: StartSessionRequest) -> Dict[str, Any]:
        try:
            return container.pedagogy.start_or_resume_session(
                chapter_id=chapter_id,
                requested_stage=body.stage,
                force_new=body.force_new,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str) -> Dict[str, Any]:
        session = container.db.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found.")
        return session

    @app.post("/api/sessions/{session_id}/turn")
    async def session_turn(session_id: str, body: SessionTurnRequest) -> StreamingResponse:
        if not container.db.get_session(session_id):
            raise HTTPException(status_code=404, detail="Session not found.")

        async def event_gen():
            try:
                async for ev in container.pedagogy.handle_turn_stream(
                    session_id=session_id,
                    message=body.message,
                    action=body.action,
                ):
                    yield sse_event(ev)
            except Exception as exc:
                yield sse_event({"type": "error", "message": str(exc)})

        return StreamingResponse(event_gen(), media_type="text/event-stream")

    # ---------- Topic-Segmented Spaced Repetition ----------

    @app.get("/api/review/topics")
    def review_topics(workspace: Optional[str] = Query(default=None)) -> Dict[str, Any]:
        return {
            "topics": container.pedagogy.list_review_topics(workspace=workspace),
            "total_unique_due": len(container.pedagogy.list_due_reviews(workspace=workspace)),
        }

    @app.get("/api/review/due")
    def review_due(
        topic: Optional[str] = Query(default=None),
        include_upcoming: bool = Query(default=False),
        workspace: Optional[str] = Query(default=None),
    ) -> Dict[str, Any]:
        cards = container.pedagogy.list_due_reviews(
            topic=topic, include_upcoming=include_upcoming, workspace=workspace
        )
        return {"topic": topic or "all", "cards": cards}

    @app.post("/api/review/{concept_id}/answer")
    async def review_answer(concept_id: str, body: ReviewAnswerRequest) -> Dict[str, Any]:
        try:
            return await container.pedagogy.grade_review_answer(
                concept_id=concept_id,
                answer=body.answer,
                probe_question=body.probe_question,
                self_rating=body.self_rating,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    # ---------- Multi-Parent Topic Graph (DAG) ----------

    @app.get("/api/graph")
    def get_graph(
        topic: Optional[str] = Query(default=None),
        workspace: Optional[str] = Query(default=None),
    ) -> Dict[str, Any]:
        nodes = container.db.list_concepts(topic=topic, workspace=workspace)
        node_ids = {n["id"] for n in nodes}
        edges = [e for e in container.db.list_edges() if e["parent_id"] in node_ids and e["child_id"] in node_ids]
        all_topics = sorted({t for n in container.db.list_concepts(workspace=workspace) for t in n["topic_areas"]})
        books_map = {b["id"]: b["title"] for b in container.db.list_books(workspace=workspace)}
        for n in nodes:
            n["book_title"] = books_map.get(n["book_id"] or "", "Cross-Book Foundation")
        return {
            "topics": all_topics,
            "nodes": nodes,
            "edges": edges,
        }

    @app.post("/api/graph/edges")
    def add_graph_edge(body: GraphEdgeRequest) -> Dict[str, Any]:
        ok, msg = container.db.add_concept_edge(body.parent_id, body.child_id, body.relation)
        if not ok:
            raise HTTPException(status_code=400, detail=msg)
        return {"ok": True, "message": msg}

    @app.delete("/api/graph/edges")
    def delete_graph_edge(
        parent_id: str = Query(...),
        child_id: str = Query(...),
    ) -> Dict[str, Any]:
        deleted = container.db.delete_concept_edge(parent_id, child_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Edge not found.")
        return {"deleted": True}

    @app.post("/api/graph/concepts/merge")
    def merge_graph_concepts(body: MergeConceptsRequest) -> Dict[str, Any]:
        merged = container.db.merge_concepts(body.source_id, body.target_id)
        if not merged:
            raise HTTPException(status_code=404, detail="Source or target concept not found.")
        return {"merged": merged}

    return app


app = create_app()
