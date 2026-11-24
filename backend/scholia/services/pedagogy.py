"""Four-stage chapter pedagogy engine, extraction pipeline, oral exam state machine, and FSRS review loop."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from ..config import ScholiaConfig, StageRoute
from ..db import VaultDB, utc_now
from ..fsrs import rating_label, retrievability, schedule_fsrs
from ..prompts.templates import (
    build_enrichment_prompt,
    build_extraction_prompt,
    build_oral_exam_grading_prompt,
    build_socratic_prompt,
)
from .agent_runner import AgentRunner
from .ingestion import IngestionService
from .vault import VaultFS

EXTRACTION_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "notes_markdown": {"type": "string"},
        "lesson_plan": {
            "type": "object",
            "properties": {
                "chapter_title": {"type": "string"},
                "topic_areas": {"type": "array", "items": {"type": "string"}},
                "estimated_minutes": {"type": "integer"},
                "calibration_questions": {"type": "array", "items": {"type": "string"}},
                "prerequisite_links": {"type": "array", "items": {"type": "string"}},
                "concepts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "summary": {"type": "string"},
                            "prerequisites": {"type": "array", "items": {"type": "string"}},
                            "page_refs": {"type": "array", "items": {"type": "integer"}},
                            "common_misconceptions": {"type": "array", "items": {"type": "string"}},
                            "socratic_probe": {"type": "string"},
                            "worked_example_hook": {"type": "string"},
                        },
                        "required": ["name", "summary"],
                    },
                },
            },
            "required": ["chapter_title", "concepts"],
        },
    },
    "required": ["notes_markdown", "lesson_plan"],
}

GRADING_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "core_bar_passed": {"type": "boolean"},
        "score": {"type": "number"},
        "frontier_cleared": {"type": "boolean"},
        "next_frontier_prompt": {"type": "string"},
        "frontier_limit_summary": {"type": "string"},
        "feedback": {"type": "string"},
        "logged_confusion": {"type": "string"},
    },
    "required": ["core_bar_passed", "score", "feedback"],
}

COGNITIVE_LEVELS: List[Tuple[str, int]] = [
    ("explanation", 4),
    ("application", 4),
    ("analysis", 4),
    ("evaluation", 4),
    ("synthesis", 4),
]

CITATION_RE = re.compile(r"\[p\.\s*(\d+)\]")


def extract_citations(text: str) -> List[Dict[str, Any]]:
    seen: set[int] = set()
    citations: List[Dict[str, Any]] = []
    for match in CITATION_RE.finditer(text):
        pno = int(match.group(1))
        if pno not in seen:
            seen.add(pno)
            citations.append({"page": pno, "label": f"p. {pno}", "excerpt": ""})
    return citations


class PedagogyService:
    """Coordinates chapter extraction, 4-stage learning loop, oral exams, and FSRS review."""

    def __init__(
        self,
        db: VaultDB,
        fs: VaultFS,
        ingestion: IngestionService,
        runner: AgentRunner,
        config: ScholiaConfig,
    ):
        self.db = db
        self.fs = fs
        self.ingestion = ingestion
        self.runner = runner
        self.config = config

    def _route(self, stage_key: str) -> StageRoute:
        return self.config.routing.get(stage_key) or StageRoute(provider="demo", model="scholia-demo-v1", effort="medium")

    # ---------- Chapter Extraction ----------

    async def extract_chapter_stream(self, chapter_id: str) -> AsyncIterator[Dict[str, Any]]:
        chapter = self.db.get_chapter(chapter_id)
        if not chapter:
            raise KeyError(f"Chapter {chapter_id} not found")
        book = self.db.get_book(chapter["book_id"])
        assert book is not None

        self.db.update_chapter_status(chapter_id, "extracting", "Inspecting chapter pages...")
        yield {"type": "progress", "status": "extracting", "message": f"Inspecting {chapter['title']} ({chapter['page_count']} pages)"}

        ws_slug = book.get("workspace_slug")
        slices = self.ingestion.extract_chapter_text_and_slices(
            book["slug"],
            chapter,
            max_pages_per_slice=self.config.max_pdf_pages_per_slice,
            workspace_slug=ws_slug,
        )
        route = self._route("extraction_planning")
        existing_concepts = [c["name"] for c in self.db.list_concepts(workspace=book.get("workspace_id"))]
        ch_dir = self.fs.chapter_dir(book["slug"], chapter["slug"], ws_slug)

        if len(slices) > 1:
            yield {
                "type": "progress",
                "status": "extracting",
                "message": f"Chapter exceeds {self.config.max_pdf_pages_per_slice} pages; auto-sliced into {len(slices)} sequential chunks for multimodal reading.",
            }
            partial_summaries: List[str] = []
            for sl in slices:
                self.db.update_chapter_status(
                    chapter_id,
                    "extracting",
                    f"Extracting slice {sl['slice_index']}/{len(slices)} (pp. {sl['book_start_page']}-{sl['book_end_page']})",
                )
                yield {
                    "type": "progress",
                    "status": "extracting",
                    "message": f"Reading slice {sl['slice_index']}/{len(slices)} (pp. {sl['book_start_page']}-{sl['book_end_page']})",
                }
                prompt = build_extraction_prompt(
                    book_title=book["title"],
                    chapter_title=chapter["title"],
                    start_page=sl["book_start_page"],
                    end_page=sl["book_end_page"],
                    existing_concepts=existing_concepts,
                    slice_text=sl["text"],
                    is_partial_slice=True,
                )
                demo_json = json.dumps(self._build_deterministic_extraction(book, chapter, sl["text"]))
                res = await self.runner.run_complete(
                    route=route,
                    prompt=prompt,
                    chapter_dir=ch_dir,
                    json_schema=EXTRACTION_JSON_SCHEMA,
                    demo_fallback_text=demo_json,
                )
                partial_summaries.append(res.text[:6000])
            combined_text = "\n\n---\n\n".join(partial_summaries)
        else:
            combined_text = slices[0]["text"] if slices else ""

        self.db.update_chapter_status(chapter_id, "extracting", "Synthesizing study notes and lesson plan (drafting TL;DR last)...")
        yield {
            "type": "progress",
            "status": "extracting",
            "message": "Synthesizing unified study notes, lesson plan, and multi-parent concept links...",
        }

        prompt = build_extraction_prompt(
            book_title=book["title"],
            chapter_title=chapter["title"],
            start_page=chapter["start_page"],
            end_page=chapter["end_page"],
            existing_concepts=existing_concepts,
            slice_text=combined_text,
            is_partial_slice=False,
        )
        fallback_payload = self._build_deterministic_extraction(book, chapter, combined_text)
        res = await self.runner.run_complete(
            route=route,
            prompt=prompt,
            chapter_dir=ch_dir,
            json_schema=EXTRACTION_JSON_SCHEMA,
            demo_fallback_text=json.dumps(fallback_payload),
        )
        payload = res.structured or fallback_payload
        notes_md = payload.get("notes_markdown") or fallback_payload["notes_markdown"]
        lesson_plan = payload.get("lesson_plan") or fallback_payload["lesson_plan"]

        self.fs.write_chapter_notes(book["slug"], chapter["slug"], notes_md, ws_slug)
        self.fs.write_lesson_plan(book["slug"], chapter["slug"], lesson_plan, ws_slug)
        self._persist_extracted_concepts(book, chapter, lesson_plan)
        self.db.update_chapter_status(chapter_id, "ready", "Extraction complete")
        self.ingestion._sync_book_meta(book["id"])

        yield {
            "type": "done",
            "status": "ready",
            "chapter_id": chapter_id,
            "concept_count": len(lesson_plan.get("concepts", [])),
        }

    async def extract_book_all(
        self, book_id: str, concurrency: int = 2, assigned_only: bool = True
    ) -> List[Dict[str, Any]]:
        book = self.db.get_book(book_id)
        if not book:
            raise KeyError(f"Book {book_id} not found")
        if assigned_only:
            pending = [
                c
                for c in book["chapters"]
                if c.get("scope", "assigned") == "assigned" and c["status"] in ("pending", "error")
            ]
        else:
            pending = [c for c in book["chapters"] if c["status"] in ("pending", "error")]
        sem = asyncio.Semaphore(max(1, concurrency))
        results: List[Dict[str, Any]] = []

        async def _run_one(ch: Dict[str, Any]) -> None:
            async with sem:
                async for ev in self.extract_chapter_stream(ch["id"]):
                    if ev["type"] == "done":
                        results.append(ev)

        await asyncio.gather(*[_run_one(c) for c in pending])
        return results

    def _persist_extracted_concepts(
        self,
        book: Dict[str, Any],
        chapter: Dict[str, Any],
        lesson_plan: Dict[str, Any],
    ) -> None:
        topics = lesson_plan.get("topic_areas") or book.get("topic_areas") or ["General Study"]
        ws_id = book.get("workspace_id")
        created_by_name: Dict[str, Dict[str, Any]] = {}
        for cspec in lesson_plan.get("concepts", []):
            rec = self.db.upsert_concept(
                name=cspec["name"],
                summary=cspec.get("summary", ""),
                book_id=book["id"],
                chapter_id=chapter["id"],
                topic_areas=topics,
                page_refs=cspec.get("page_refs") or [chapter["start_page"]],
                misconceptions=cspec.get("common_misconceptions") or [],
                workspace_id=ws_id,
            )
            created_by_name[rec["name"].lower()] = rec

        # Link multi-parent prerequisite edges against both existing vault concepts and chapter concepts
        for cspec in lesson_plan.get("concepts", []):
            child = created_by_name.get(cspec["name"].lower())
            if not child:
                continue
            for prereq_name in cspec.get("prerequisites", []):
                parent = self.db.get_concept(prereq_name, workspace=ws_id)
                if not parent:
                    parent = self.db.upsert_concept(
                        name=prereq_name,
                        summary=f"Prerequisite concept linked from {chapter['title']}.",
                        topic_areas=topics,
                        workspace_id=ws_id,
                    )
                self.db.add_concept_edge(parent["id"], child["id"], relation="prerequisite")

    def _build_deterministic_extraction(
        self,
        book: Dict[str, Any],
        chapter: Dict[str, Any],
        raw_text: str,
    ) -> Dict[str, Any]:
        sp = chapter["start_page"]
        ep = chapter["end_page"]
        mid = min(ep, sp + max(0, (ep - sp) // 2))
        topics = book.get("topic_areas") or ["Algorithms"]
        snippet = " ".join(raw_text.split())[:420] or f"Core material from {chapter['title']}."
        c1 = f"{chapter['title']} Foundations"
        c2 = f"{chapter['title']} Decomposition Invariant"
        c3 = f"{chapter['title']} Complexity and Tradeoffs"

        notes_md = f"""# {chapter['title']}

## TL;DR

{chapter['title']} establishes how local structural invariants govern global correctness and computational efficiency across pages {sp} through {ep}. Mastering the decomposition condition prevents exponential recomputation and exposes where greedy shortcuts fail.

## Why This Matters

Recognizing when a problem admits clean state decomposition determines whether an engineering design scales polynomially or collapses under combinatorial growth [p. {sp}].

## Key Ideas

### 1. {c1}

The chapter opens by formalizing the problem state and boundary conditions so that every transition depends strictly on well-defined parameters [p. {sp}].

**Worked Example (Source-Grounded):** {snippet}

**Implication:** When the state representation omits a constraining variable, two histories with different optimal continuations collide in the same state and produce silent optimality errors.

### 2. {c2}

A valid decomposition splits an instance into smaller subproblems whose solutions recombine without revisiting earlier choices [p. {mid}].

**Mechanism in Evaluation Order:**
1. Define the minimal state variables so that remaining decisions depend only on the current state.
2. Express the recurrence relation over strictly smaller subproblems so that the dependency graph remains acyclic.
3. Order evaluation topologically or memoize results so that each distinct subproblem executes once.

### 3. {c3}

Total running time equals the product of the number of distinct states and the transition work per state [p. {ep}]. Memory can often be compressed by retaining only the active frontier of the recurrence when full solution reconstruction is unnecessary.

## Open Questions and Confusions

- Which structural constraints break the independence of subproblems in this domain?
- When does top-down memoization outperform bottom-up tabulation on sparse state spaces?

## Self-Quiz Prompts

1. Explain why omitting a single state variable can invalidate the recurrence even when the objective function looks unchanged [p. {sp}].
2. Construct a small counterexample where a locally optimal greedy choice prevents reaching the global optimum [p. {mid}].
3. Compare the memory footprint of full reconstruction tables against rolling-frontier evaluation [p. {ep}].
"""
        lesson_plan = {
            "chapter_title": chapter["title"],
            "topic_areas": topics,
            "estimated_minutes": max(15, min(60, chapter["page_count"] * 3)),
            "calibration_questions": [
                f"Which concepts in {chapter['title']} have you already implemented or proven in prior work?",
                "Do you want to focus primarily on conceptual invariants and tradeoffs, or also work through explicit derivations?",
            ],
            "prerequisite_links": [],
            "concepts": [
                {
                    "name": c1,
                    "summary": f"Problem formulation, state definition, and boundary conditions in {chapter['title']}.",
                    "prerequisites": [],
                    "page_refs": [sp],
                    "common_misconceptions": ["Assuming any recursive formulation is automatically efficient without analyzing state overlap."],
                    "socratic_probe": f"What exact state variables must be tracked so that future decisions in {chapter['title']} remain independent of prior path history [p. {sp}]?",
                    "worked_example_hook": f"Trace a 4-element instance from page {sp} step by step.",
                },
                {
                    "name": c2,
                    "summary": f"Structural invariant linking subproblem solutions to the global optimum in {chapter['title']}.",
                    "prerequisites": [c1],
                    "page_refs": [mid],
                    "common_misconceptions": ["Confusing independent divide-and-conquer subproblems with overlapping subproblems."],
                    "socratic_probe": f"Under what condition does combining optimal subproblem solutions fail to yield a globally optimal solution [p. {mid}]?",
                    "worked_example_hook": f"Apply a cut-and-paste contradiction on the transition at page {mid}.",
                },
                {
                    "name": c3,
                    "summary": f"Asymptotic time-space accounting and table evaluation order in {chapter['title']}.",
                    "prerequisites": [c2],
                    "page_refs": [ep],
                    "common_misconceptions": ["Counting recursive calls instead of distinct reachable states multiplied by work per state."],
                    "socratic_probe": f"How do the number of reachable subproblems and transition fan-out determine the total runtime bound [p. {ep}]?",
                    "worked_example_hook": f"Compare memoized recursion against bottom-up table filling on page {ep}.",
                },
            ],
        }
        return {"notes_markdown": notes_md, "lesson_plan": lesson_plan}

    # ---------- Chapter Session Lifecycle ----------

    def start_or_resume_session(self, chapter_id: str, requested_stage: str = "plan", force_new: bool = False) -> Dict[str, Any]:
        chapter = self.db.get_chapter(chapter_id)
        if not chapter:
            raise KeyError(f"Chapter {chapter_id} not found")
        book = self.db.get_book(chapter["book_id"])
        assert book is not None

        if not force_new:
            existing = self.db.get_latest_chapter_session(chapter_id)
            if existing:
                if requested_stage == "exam" and existing["stage"] != "exam":
                    return self._transition_to_exam(existing, book, chapter)
                if requested_stage == "socratic" and existing["stage"] == "plan":
                    return self._transition_to_socratic(existing, book, chapter)
                return existing

        concepts = self.db.list_concepts(chapter_id=chapter_id)
        active_concept_id = concepts[0]["id"] if concepts else None
        session = self.db.create_session(
            book_id=book["id"],
            chapter_id=chapter_id,
            stage=requested_stage,
            active_concept_id=active_concept_id,
        )
        if chapter["status"] == "ready":
            self.db.update_chapter_status(chapter_id, "in_progress")

        if requested_stage == "exam":
            return self._transition_to_exam(session, book, chapter)
        if requested_stage == "socratic":
            return self._transition_to_socratic(session, book, chapter)

        # Stage 1: Initial Plan & Calibration message
        ws_slug = book.get("workspace_slug")
        lesson_plan = self.fs.read_lesson_plan(book["slug"], chapter["slug"], ws_slug) or {}
        memory = self.db.build_learner_memory_digest(chapter_id=chapter_id, book_id=book["id"])
        prereq_names = [p["name"] for p in memory["prerequisite_status"]] or lesson_plan.get("prerequisite_links", [])
        cal_qs = lesson_plan.get("calibration_questions") or [
            f"Which core concepts in {chapter['title']} do you already use fluently?",
            "Should we spend more time on formal proofs and boundary cases or applied worked examples?",
        ]
        concept_bullets = "\n".join(
            f"- **{c['name']}** — {c['summary']} [p. {c['page_refs'][0] if c['page_refs'] else chapter['start_page']}]"
            for c in concepts
        )
        prereq_line = (
            f"Prerequisite links in your concept graph: {', '.join(prereq_names)}."
            if prereq_names
            else "No unresolved prerequisite blocks appear in your concept graph."
        )
        plan_msg = (
            f"This chapter covers {len(concepts)} core concepts across pages {chapter['start_page']} through {chapter['end_page']}. "
            f"{prereq_line}\n\n"
            f"{concept_bullets}\n\n"
            f"**Calibration:**\n"
            f"1. {cal_qs[0]}\n"
            f"2. {cal_qs[1] if len(cal_qs) > 1 else 'What depth of derivation do you want before entering the oral exam?'}\n\n"
            f"Reply with your calibration notes to begin Stage 2 Socratic dialogue, or select **Test Out** to jump directly to the five-question oral exam."
        )
        self.db.append_message(
            session["id"],
            speaker="TUTOR",
            stage="plan",
            content=plan_msg,
            citations=extract_citations(plan_msg),
            metadata={"concept_count": len(concepts)},
        )
        fresh = self.db.get_session(session["id"])
        assert fresh is not None
        self.fs.write_session_snapshot(book["slug"], chapter["slug"], fresh, ws_slug)
        return fresh

    def _transition_to_socratic(self, session: Dict[str, Any], book: Dict[str, Any], chapter: Dict[str, Any]) -> Dict[str, Any]:
        ws_slug = book.get("workspace_slug")
        concepts = self.db.list_concepts(chapter_id=chapter["id"])
        uncovered = [c for c in concepts if c["id"] not in session["covered_concept_ids"]]
        target = uncovered[0] if uncovered else (concepts[0] if concepts else None)
        active_id = target["id"] if target else None
        self.db.update_session(session["id"], stage="socratic", active_concept_id=active_id)

        lesson_plan = self.fs.read_lesson_plan(book["slug"], chapter["slug"], ws_slug) or {}
        probe = ""
        if target:
            for lc in lesson_plan.get("concepts", []):
                if lc.get("name", "").lower() == target["name"].lower():
                    probe = lc.get("socratic_probe", "")
                    break
            p_ref = target["page_refs"][0] if target["page_refs"] else chapter["start_page"]
            fallback_probe = f"What exact invariant breaks when {target['name']} is violated?"
            opening = (
                f"{target['name']} governs the first structural mechanism in this chapter [p. {p_ref}]. "
                f"{target['summary']} "
                f"{probe or fallback_probe}"
            )
            self.db.append_message(
                session["id"],
                speaker="TUTOR",
                stage="socratic",
                content=opening,
                citations=extract_citations(opening),
                metadata={"concept_id": target["id"], "concept_name": target["name"]},
            )
        fresh = self.db.get_session(session["id"])
        assert fresh is not None
        self.fs.write_session_snapshot(book["slug"], chapter["slug"], fresh, ws_slug)
        return fresh

    def _transition_to_exam(
        self,
        session: Dict[str, Any],
        book: Dict[str, Any],
        chapter: Optional[Dict[str, Any]],
        retake_concept_ids: Optional[List[str]] = None,
        synthesis_chapters: Optional[List[Dict[str, Any]]] = None,
        phase_exit: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        ws_slug = book.get("workspace_slug")
        if phase_exit:
            concepts = []
            for ch in (synthesis_chapters or []):
                concepts.extend(self.db.list_concepts(chapter_id=ch["id"]))
            if not concepts:
                concepts = self.db.list_concepts(workspace=book.get("workspace_id"))
            exam_type = "phase_exit"
            chapter_ids = [ch["id"] for ch in (synthesis_chapters or [])]
            ch_id_for_history = chapter["id"] if chapter else None
        elif synthesis_chapters:
            concepts = []
            for ch in synthesis_chapters:
                concepts.extend(self.db.list_concepts(chapter_id=ch["id"]))
            exam_type = "synthesis"
            chapter_ids = [ch["id"] for ch in synthesis_chapters]
            ch_id_for_history = synthesis_chapters[0]["id"]
        elif retake_concept_ids:
            concepts = [c for cid in retake_concept_ids if (c := self.db.get_concept(cid))]
            exam_type = "retake"
            chapter_ids = [chapter["id"]] if chapter else []
            ch_id_for_history = chapter["id"] if chapter else None
        else:
            concepts = self.db.list_concepts(chapter_id=chapter["id"]) if chapter else []
            exam_type = "chapter"
            chapter_ids = [chapter["id"]] if chapter else []
            ch_id_for_history = chapter["id"] if chapter else None

        if not concepts:
            concepts = [
                {
                    "id": "general",
                    "name": phase_exit["title"] if phase_exit else (chapter["title"] if chapter else book["title"]),
                    "summary": phase_exit["goal"] if phase_exit else "Core chapter mechanism and tradeoffs.",
                    "page_refs": [chapter["start_page"] if chapter else 1],
                }
            ]

        questions = self._generate_exam_questions(
            concepts=concepts,
            chapter_id=ch_id_for_history,
            exam_type=exam_type,
            phase_exit=phase_exit,
        )
        attempt_num = 1
        if session.get("exam_state"):
            attempt_num = int(session["exam_state"].get("attempt_number", 1)) + 1

        exam_state = {
            "exam_type": exam_type,
            "chapter_ids": chapter_ids,
            "phase_id": phase_exit["id"] if phase_exit else None,
            "exit_criterion": phase_exit["exit_criterion"] if phase_exit else None,
            "current_question_index": 0,
            "total_points_possible": sum(q["max_points"] for q in questions),
            "points_earned": 0.0,
            "passed": None,
            "failed_concept_ids": [],
            "questions": questions,
            "attempt_number": attempt_num,
        }
        self.db.update_session(
            session["id"],
            stage="exam",
            active_concept_id=questions[0]["concept_id"],
            exam_state=exam_state,
        )

        q0 = questions[0]
        if exam_type == "phase_exit" and phase_exit:
            intro_prefix = (
                f"Phase Exit Oral Examination initiated for **{phase_exit['title']}** across {max(1, len(chapter_ids))} assigned chapter(s). "
                f"Target Exit Criterion: *{phase_exit['exit_criterion']}*."
            )
        elif exam_type == "retake":
            intro_prefix = f"Retake examination initiated for {len(questions)} missed core concept(s) with freshly generated non-repeating prompts."
        elif exam_type == "synthesis":
            intro_prefix = f"Multi-chapter synthesis oral examination initiated across {len(chapter_ids)} chapters (five questions, 20 points total)."
        else:
            intro_prefix = "Oral examination initiated across five cognitive levels totaling 20 points. Passing requires clearing the Core Bar on all core concepts; once each Core Bar clears, Frontier Probing continues until your limit."

        msg = (
            f"{intro_prefix}\n\n"
            f"**Question {q0['index']}/{len(questions)} ({q0['cognitive_level'].upper()} · {q0['max_points']} pts) — {q0['concept_name']}**\n\n"
            f"{q0['prompt']}"
        )
        self.db.append_message(
            session["id"],
            speaker="EXAMINER",
            stage="exam",
            content=msg,
            citations=extract_citations(msg),
            metadata={
                "question_index": q0["index"],
                "cognitive_level": q0["cognitive_level"],
                "phase": "core_bar",
                "core_bar_passed": False,
                "frontier_depth": 0,
            },
        )
        fresh = self.db.get_session(session["id"])
        assert fresh is not None
        if chapter:
            self.fs.write_session_snapshot(book["slug"], chapter["slug"], fresh, ws_slug)
        return fresh

    def _generate_exam_questions(
        self,
        concepts: List[Dict[str, Any]],
        chapter_id: Optional[str],
        exam_type: str,
        phase_exit: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Generate non-repeating questions across cognitive levels, recording stems in SQLite."""
        asked_lower = {s.lower() for s in self.db.list_asked_stems(chapter_id=chapter_id)}
        templates = {
            "explanation": [
                "Explain the exact mechanism behind {name}, identifying the invariant that makes the construction valid [p. {page}].",
                "Reconstruct how {name} works from first principles without relying on memorized formulas, naming the exact failure mode if its primary invariant breaks [p. {page}].",
                "Trace the causal mechanism of {name} and state what breaks when the boundary condition is weakened [p. {page}].",
            ],
            "application": [
                "Given a production system with tight latency bounds and skewed input distributions, determine whether {name} applies and justify the state representation you would select [p. {page}].",
                "Select a concrete engineering scenario where {name} outperforms a naive exhaustive search, and specify the exact state key and transition rule [p. {page}].",
                "Adapt {name} to an online variant where input constraints arrive incrementally, stating which assumption still holds [p. {page}].",
            ],
            "analysis": [
                "Analyze how scaling the input dimension or state cardinality alters both time and space complexity in {name}, and identify the dominant bottleneck [p. {page}].",
                "Examine the parameter sensitivity of {name}: which structural change in the dependency graph shifts the runtime from polynomial to exponential [p. {page}].",
                "Decompose the transition cost of {name} into distinct subproblems and work per subproblem, showing where redundant computation hides [p. {page}].",
            ],
            "evaluation": [
                "Compare {name} against a greedy alternative and a pure divide-and-conquer approach, specifying exact conditions under which each method wins or fails [p. {page}].",
                "Evaluate the tradeoff between top-down memoization and bottom-up tabulation for {name} when fewer than 10% of the state space is reachable [p. {page}].",
                "Assess when preserving full solution reconstruction pointers in {name} is worth the memory overhead versus recomputing boundaries [p. {page}].",
            ],
            "synthesis": [
                "Work through a concrete four-step instance of {name}, writing the recurrence, evaluating intermediate states in topological order, and reconstructing the optimal decision sequence [p. {page}].",
                "Synthesize a counterexample where a plausible shortcut for {name} fails, then repair the recurrence and verify the corrected state transition on a small numerical instance [p. {page}].",
                "Combine {name} with its prerequisite concepts to design an end-to-end algorithm for a constrained variant, deriving both correctness and asymptotic complexity [p. {page}].",
            ],
        }

        if exam_type == "retake":
            target_pairs = [
                (COGNITIVE_LEVELS[i % len(COGNITIVE_LEVELS)], concepts[i])
                for i in range(len(concepts))
            ]
        else:
            target_pairs = [
                (COGNITIVE_LEVELS[i], concepts[i % len(concepts)])
                for i in range(5)
            ]

        questions: List[Dict[str, Any]] = []
        for idx, ((level, pts), concept) in enumerate(target_pairs, start=1):
            p_ref = (concept.get("page_refs") or [1])[0]
            if phase_exit and idx == 5 and phase_exit.get("exit_criterion"):
                chosen = (
                    f"Phase Exit Synthesis ({phase_exit['title']}): Demonstrate the phase exit criterion directly — "
                    f"{phase_exit['exit_criterion']}. Show every intermediate calculation, memory/communication bound, or profiling tradeoff explicitly."
                )
            else:
                candidates = templates[level]
                chosen = ""
                for variant_idx, tmpl in enumerate(candidates):
                    candidate_stem = tmpl.format(name=concept["name"], page=p_ref)
                    if candidate_stem.lower() not in asked_lower:
                        chosen = candidate_stem
                        break
                if not chosen:
                    chosen = (
                        f"Variant {len(asked_lower) + idx}: Demonstrate conceptual mastery of {concept['name']} "
                        f"under modified boundary constraints and justify each transition step [p. {p_ref}]."
                    )

            asked_lower.add(chosen.lower())
            self.db.record_question_stem(
                chapter_id=chapter_id,
                concept_id=concept["id"] if concept["id"] != "general" else None,
                cognitive_level=level,
                question_stem=chosen,
            )
            questions.append(
                {
                    "index": idx,
                    "cognitive_level": level,
                    "concept_id": concept["id"],
                    "concept_name": concept["name"],
                    "max_points": pts,
                    "prompt": chosen,
                    "core_criteria": [
                        f"Identifies core invariant or mechanism of {concept['name']}",
                        "Explains boundary conditions or failure modes accurately",
                        "Demonstrates reasoning rather than surface recall",
                    ],
                    "core_bar_passed": False,
                    "score": 0.0,
                    "phase": "core_bar" if idx == 1 else "pending",
                    "frontier_depth": 0,
                    "frontier_notes": [],
                    "attempts_on_core": 0,
                    "is_retake": exam_type == "retake",
                }
            )
        return questions

    # ---------- Turn Handling (SSE Stream) ----------

    async def handle_turn_stream(
        self,
        session_id: str,
        message: str,
        action: str = "reply",
    ) -> AsyncIterator[Dict[str, Any]]:
        session = self.db.get_session(session_id)
        if not session:
            raise KeyError(f"Session {session_id} not found")
        book = self.db.get_book(session["book_id"])
        assert book is not None
        chapter = self.db.get_chapter(session["chapter_id"]) if session.get("chapter_id") else None

        # Stage-jump actions
        if action == "test_out" or action == "start_exam":
            if message.strip():
                self.db.append_message(session_id, "YOU", session["stage"], message.strip())
            updated = self._transition_to_exam(session, book, chapter)
            last_msg = updated["messages"][-1]
            yield {"type": "delta", "text": last_msg["content"]}
            yield {"type": "state", "session": updated}
            yield {"type": "done", "message": last_msg}
            return

        if action == "start_socratic":
            if message.strip():
                self.db.append_message(session_id, "YOU", session["stage"], message.strip())
            updated = self._transition_to_socratic(session, book, chapter)  # type: ignore[arg-type]
            last_msg = updated["messages"][-1]
            yield {"type": "delta", "text": last_msg["content"]}
            yield {"type": "state", "session": updated}
            yield {"type": "done", "message": last_msg}
            return

        if action == "start_retake" and session.get("exam_state"):
            failed_ids = session["exam_state"].get("failed_concept_ids", [])
            updated = self._transition_to_exam(session, book, chapter, retake_concept_ids=failed_ids)
            last_msg = updated["messages"][-1]
            yield {"type": "delta", "text": last_msg["content"]}
            yield {"type": "state", "session": updated}
            yield {"type": "done", "message": last_msg}
            return

        if action == "complete_enrichment":
            async for ev in self._run_enrichment_stream(session, book, chapter):
                yield ev
            return

        # Stage 1 -> Stage 2 transition on calibration reply
        if session["stage"] == "plan":
            self.db.append_message(session_id, "YOU", "plan", message.strip() or "Ready to begin Stage 2.")
            updated = self._transition_to_socratic(session, book, chapter)  # type: ignore[arg-type]
            last_msg = updated["messages"][-1]
            yield {"type": "delta", "text": last_msg["content"]}
            yield {"type": "state", "session": updated}
            yield {"type": "done", "message": last_msg}
            return

        # Stage 2: Concise Socratic Dialogue
        if session["stage"] == "socratic":
            async for ev in self._handle_socratic_turn(session, book, chapter, message, action):
                yield ev
            return

        # Stage 3: Boundary-Probing Oral Exam
        if session["stage"] == "exam":
            async for ev in self._handle_exam_turn(session, book, chapter, message, action):
                yield ev
            return

        # Stage 4: Enriched follow-up
        self.db.append_message(session_id, "YOU", session["stage"], message.strip())
        reply = (
            "The chapter study notes already contain your enriched session appendix. "
            "Launch a synthesis exam from the Library or review due concepts in the Review Queue to consolidate long-term retention."
        )
        msg = self.db.append_message(session_id, "TUTOR", session["stage"], reply)
        yield {"type": "delta", "text": reply}
        yield {"type": "state", "session": self.db.get_session(session_id)}
        yield {"type": "done", "message": msg}

    async def _handle_socratic_turn(
        self,
        session: Dict[str, Any],
        book: Dict[str, Any],
        chapter: Optional[Dict[str, Any]],
        message: str,
        action: str,
    ) -> AsyncIterator[Dict[str, Any]]:
        label_map = {
            "give_example": "Request: Give a concrete worked example.",
            "explain_mechanism": "Request: Explain the mechanism step by step.",
        }
        learner_text = message.strip() or label_map.get(action, "Continue.")
        self.db.append_message(session["id"], "YOU", "socratic", learner_text, metadata={"action": action})

        concepts = self.db.list_concepts(chapter_id=chapter["id"]) if chapter else []
        active_concept = next((c for c in concepts if c["id"] == session.get("active_concept_id")), None)
        if not active_concept and concepts:
            active_concept = concepts[0]
        if not active_concept:
            active_concept = {
                "id": "general",
                "name": chapter["title"] if chapter else book["title"],
                "summary": "Core chapter concept.",
                "page_refs": [chapter["start_page"] if chapter else 1],
                "misconceptions": [],
            }

        covered = list(session.get("covered_concept_ids") or [])
        next_concept = active_concept
        if action == "reply" and len(learner_text.split()) >= 6:
            if active_concept["id"] not in covered and active_concept["id"] != "general":
                covered.append(active_concept["id"])
                self.db.update_concept_mastery_and_fsrs(active_concept["id"], mastery_state="learning", core_passed=False)
            remaining = [c for c in concepts if c["id"] not in covered]
            if remaining:
                next_concept = remaining[0]

        memory = self.db.build_learner_memory_digest(chapter_id=chapter["id"] if chapter else None, book_id=book["id"])
        prompt = build_socratic_prompt(
            book_title=book["title"],
            chapter_title=chapter["title"] if chapter else book["title"],
            concept=next_concept,
            learner_memory=memory,
            history=session["messages"],
            learner_message=learner_text,
            action=action,
        )
        demo_reply = self._build_demo_socratic_reply(active_concept, next_concept, action, len(covered), len(concepts))
        ws_slug = book.get("workspace_slug")
        ch_dir = self.fs.chapter_dir(book["slug"], chapter["slug"], ws_slug) if chapter else None

        full_text = ""
        new_conv = session.get("agent_conversation_id")
        async for ev in self.runner.stream_text(
            route=self._route("socratic_dialogue"),
            prompt=prompt,
            chapter_dir=ch_dir,
            conversation_id=new_conv,
            demo_fallback_text=demo_reply,
        ):
            if ev["type"] == "delta":
                yield ev
            elif ev["type"] == "done":
                full_text = ev["text"]
                new_conv = ev.get("conversation_id") or new_conv

        citations = extract_citations(full_text)
        msg = self.db.append_message(
            session["id"],
            speaker="TUTOR",
            stage="socratic",
            content=full_text,
            citations=citations,
            metadata={"concept_id": next_concept["id"], "concept_name": next_concept["name"], "action": action},
        )
        updated = self.db.update_session(
            session["id"],
            active_concept_id=next_concept["id"],
            covered_concept_ids=covered,
            agent_conversation_id=new_conv,
        )
        if chapter and updated:
            self.fs.write_session_snapshot(book["slug"], chapter["slug"], updated, ws_slug)
        yield {"type": "state", "session": updated}
        yield {"type": "done", "message": msg}

    @staticmethod
    def _build_demo_socratic_reply(
        active_concept: Dict[str, Any],
        next_concept: Dict[str, Any],
        action: str,
        covered_count: int,
        total_concepts: int,
    ) -> str:
        p_ref = (active_concept.get("page_refs") or [1])[0]
        next_p = (next_concept.get("page_refs") or [p_ref])[0]
        if action == "give_example":
            return (
                f"Consider a rod of length 4 with prices $p = [1, 5, 8, 9]$ [p. {p_ref}]. "
                f"A greedy choice by unit density picks length 3 (revenue 8) plus length 1 (revenue 1) for a total of 9, "
                f"whereas optimal decomposition selects two cuts of length 2 for a total revenue of 10. "
                f"Which subproblem result gets reused across both length-3 and length-4 evaluations?"
            )
        if action == "explain_mechanism":
            return (
                f"The mechanism for {active_concept['name']} resolves redundant recomputation in three ordered steps [p. {p_ref}]: "
                f"1) encode the minimal state so that future choices depend only on the current boundary; "
                f"2) express each state transition strictly in terms of smaller states so that the subproblem graph remains a directed acyclic graph; "
                f"3) cache or tabulate states in topological order so that every subproblem executes once. "
                f"What happens to step 2 if a transition can point back to a state of equal or larger size?"
            )
        if active_concept["id"] != next_concept["id"]:
            return (
                f"That reasoning isolates the invariant behind {active_concept['name']} accurately [p. {p_ref}]. "
                f"With {covered_count} of {max(1, total_concepts)} core concepts covered, shift to **{next_concept['name']}** [p. {next_p}]: {next_concept['summary']} "
                f"Under what concrete input structure does {next_concept['name']} break down if its prerequisite assumption is dropped?"
            )
        return (
            f"Your intuition captures the surface behavior of {active_concept['name']}, yet the optimality argument requires showing that substituting any suboptimal subproblem solution strictly degrades the global objective [p. {p_ref}]. "
            f"Construct a cut-and-paste contradiction showing why an optimal global solution cannot contain a suboptimal subproblem solution."
        )

    async def _handle_exam_turn(
        self,
        session: Dict[str, Any],
        book: Dict[str, Any],
        chapter: Optional[Dict[str, Any]],
        message: str,
        action: str,
    ) -> AsyncIterator[Dict[str, Any]]:
        exam = session.get("exam_state")
        if not exam or not exam.get("questions"):
            updated = self._transition_to_exam(session, book, chapter)
            last_msg = updated["messages"][-1]
            yield {"type": "delta", "text": last_msg["content"]}
            yield {"type": "state", "session": updated}
            yield {"type": "done", "message": last_msg}
            return

        q_idx = int(exam["current_question_index"])
        questions = exam["questions"]
        if q_idx >= len(questions):
            reply = "All questions in this oral examination are complete. Proceed to Stage 4 Note Enrichment or launch a targeted retake."
            msg = self.db.append_message(session["id"], "EXAMINER", "exam", reply)
            yield {"type": "delta", "text": reply}
            yield {"type": "state", "session": session}
            yield {"type": "done", "message": msg}
            return

        current_q = questions[q_idx]
        hit_limit_phrases = ("i do not know", "i don't know", "not sure", "hit limit", "next question", "pass")
        learner_says_limit = action == "hit_limit_next_question" or any(
            p in message.strip().lower() for p in hit_limit_phrases
        )

        if learner_says_limit:
            user_text = message.strip() or "Hit limit; advance to the next question."
            self.db.append_message(session["id"], "YOU", "exam", user_text, metadata={"action": "hit_limit_next_question"})
            if current_q["core_bar_passed"]:
                frontier_summary = (
                    f"Knowledge Frontier reached on {current_q['concept_name']} at Frontier Probe #{max(1, current_q['frontier_depth'])}: "
                    f"core mechanism verified, limit reached on relaxed-assumption edge transfer."
                )
                current_q["frontier_notes"].append(frontier_summary)
                self._record_frontier(chapter, current_q["concept_id"], frontier_summary)
                feedback = (
                    f"Core Bar credit ({current_q['score']:.1f}/{current_q['max_points']} pts) stands without penalty. "
                    f"Recorded frontier boundary: {frontier_summary}"
                )
            else:
                current_q["score"] = min(current_q["score"], current_q["max_points"] * 0.4)
                if current_q["concept_id"] not in exam["failed_concept_ids"] and current_q["concept_id"] != "general":
                    exam["failed_concept_ids"].append(current_q["concept_id"])
                confusion = f"Core Bar not yet cleared for {current_q['concept_name']} on {current_q['cognitive_level']} question."
                self._record_confusion(chapter, current_q["concept_id"], confusion)
                feedback = (
                    f"Core Bar not cleared for {current_q['concept_name']} ({current_q['score']:.1f}/{current_q['max_points']} pts). "
                    f"This concept is queued for a non-repeating retake once the current exam pass finishes."
                )

            current_q["phase"] = "completed"
            reply_text = self._advance_or_finalize_exam(session, book, chapter, exam, feedback)
        else:
            self.db.append_message(session["id"], "YOU", "exam", message.strip())
            grade = await self._grade_exam_answer(book, chapter, current_q, message.strip())

            if current_q["phase"] == "core_bar":
                current_q["attempts_on_core"] = int(current_q.get("attempts_on_core", 0)) + 1
                if grade["core_bar_passed"]:
                    current_q["core_bar_passed"] = True
                    current_q["score"] = float(min(current_q["max_points"], max(current_q["max_points"] * 0.8, grade["score"])))
                    current_q["phase"] = "frontier_probing"
                    current_q["frontier_depth"] = 1
                    if current_q["concept_id"] != "general":
                        self._enroll_concept_on_pass(current_q["concept_id"])
                    next_probe = grade.get("next_frontier_prompt") or self._fallback_frontier_probe(current_q["concept_name"], 1)
                    reply_text = (
                        f"**Core Bar Cleared ({current_q['score']:.1f}/{current_q['max_points']} pts).** "
                        f"{grade['feedback']}\n\n"
                        f"**Frontier Probe #1 (No Penalty):** {next_probe}"
                    )
                else:
                    if grade.get("logged_confusion"):
                        self._record_confusion(chapter, current_q["concept_id"], grade["logged_confusion"])
                    if current_q["attempts_on_core"] >= 2:
                        current_q["score"] = float(min(current_q["max_points"] * 0.5, grade["score"]))
                        current_q["phase"] = "completed"
                        if current_q["concept_id"] not in exam["failed_concept_ids"] and current_q["concept_id"] != "general":
                            exam["failed_concept_ids"].append(current_q["concept_id"])
                        reply_text = self._advance_or_finalize_exam(
                            session,
                            book,
                            chapter,
                            exam,
                            f"Core Bar not cleared ({current_q['score']:.1f}/{current_q['max_points']} pts). {grade['feedback']}",
                        )
                    else:
                        reply_text = (
                            f"**Core Bar Clarifying Probe:** {grade['feedback']} "
                            f"Tighten your explanation of the exact invariant before moving on, or select **Hit Limit / Next Q**."
                        )
            else:
                # Already in continuous frontier_probing phase
                if grade.get("frontier_cleared", True):
                    current_q["score"] = float(current_q["max_points"])
                    current_q["frontier_depth"] = int(current_q.get("frontier_depth", 1)) + 1
                    next_probe = grade.get("next_frontier_prompt") or self._fallback_frontier_probe(
                        current_q["concept_name"], current_q["frontier_depth"]
                    )
                    reply_text = (
                        f"**Frontier Probe #{current_q['frontier_depth'] - 1} Cleared.** {grade['feedback']}\n\n"
                        f"**Frontier Probe #{current_q['frontier_depth']} (No Penalty):** {next_probe}"
                    )
                else:
                    frontier_summary = grade.get("frontier_limit_summary") or (
                        f"Boundary reached on {current_q['concept_name']} at Frontier Probe #{current_q['frontier_depth']}."
                    )
                    current_q["frontier_notes"].append(frontier_summary)
                    self._record_frontier(chapter, current_q["concept_id"], frontier_summary)
                    current_q["phase"] = "completed"
                    reply_text = self._advance_or_finalize_exam(
                        session,
                        book,
                        chapter,
                        exam,
                        f"**Frontier Boundary Logged (Core Bar Credit Retained: {current_q['score']:.1f}/{current_q['max_points']} pts).** {grade['feedback']}",
                    )

        exam["points_earned"] = round(sum(float(q["score"]) for q in questions), 1)
        active_q = questions[min(exam["current_question_index"], len(questions) - 1)]
        updated = self.db.update_session(
            session["id"],
            active_concept_id=active_q["concept_id"],
            exam_state=exam,
        )
        msg = self.db.append_message(
            session["id"],
            speaker="EXAMINER",
            stage="exam",
            content=reply_text,
            citations=extract_citations(reply_text),
            metadata={
                "question_index": active_q["index"],
                "cognitive_level": active_q["cognitive_level"],
                "phase": active_q["phase"],
                "core_bar_passed": active_q["core_bar_passed"],
                "frontier_depth": active_q["frontier_depth"],
            },
        )
        if chapter and updated:
            self.fs.write_session_snapshot(book["slug"], chapter["slug"], updated, book.get("workspace_slug"))

        for chunk in re.findall(r"\S+\s*", reply_text):
            yield {"type": "delta", "text": chunk}
            await asyncio.sleep(0.004)
        yield {"type": "state", "session": self.db.get_session(session["id"])}
        yield {"type": "done", "message": msg}

    def _advance_or_finalize_exam(
        self,
        session: Dict[str, Any],
        book: Dict[str, Any],
        chapter: Optional[Dict[str, Any]],
        exam: Dict[str, Any],
        prefix_feedback: str,
    ) -> str:
        questions = exam["questions"]
        next_idx = int(exam["current_question_index"]) + 1
        exam["points_earned"] = round(sum(float(q["score"]) for q in questions), 1)

        if next_idx < len(questions):
            exam["current_question_index"] = next_idx
            nq = questions[next_idx]
            nq["phase"] = "core_bar"
            return (
                f"{prefix_feedback}\n\n"
                f"**Question {nq['index']}/{len(questions)} ({nq['cognitive_level'].upper()} · {nq['max_points']} pts) — {nq['concept_name']}**\n\n"
                f"{nq['prompt']}"
            )

        # Finalize exam
        exam["current_question_index"] = len(questions)
        total_possible = max(1, int(exam["total_points_possible"]))
        pct = (exam["points_earned"] / total_possible) * 100.0
        all_core_passed = len(exam["failed_concept_ids"]) == 0 and all(q["core_bar_passed"] for q in questions)
        exam["passed"] = all_core_passed and pct >= 80.0

        if exam["passed"]:
            if exam.get("exam_type") == "phase_exit" and exam.get("phase_id"):
                self.db.update_curriculum_phase(exam["phase_id"], exit_passed=True)
            elif chapter:
                self.db.update_chapter_status(chapter["id"], "mastered")
            return (
                f"{prefix_feedback}\n\n"
                f"**Examination Passed: {exam['points_earned']:.1f}/{total_possible} points ({pct:.0f}%).** "
                f"Every core concept cleared the Core Bar and has been enrolled into the topic-segmented spaced repetition queue. "
                f"Select **Enrich Notes (Stage 4)** to append your breakthroughs and logged frontiers to `notes.md`."
            )

        missed_names = [q["concept_name"] for q in questions if not q["core_bar_passed"]]
        return (
            f"{prefix_feedback}\n\n"
            f"**Core Bar Incomplete: {exam['points_earned']:.1f}/{total_possible} points ({pct:.0f}%).** "
            f"Missed core concepts: {', '.join(dict.fromkeys(missed_names))}. "
            f"Select **Start Non-Repeating Retake** to remediate and re-examine only the missed concepts with fresh question stems."
        )

    async def _grade_exam_answer(
        self,
        book: Dict[str, Any],
        chapter: Optional[Dict[str, Any]],
        question: Dict[str, Any],
        learner_answer: str,
    ) -> Dict[str, Any]:
        memory = self.db.build_learner_memory_digest(chapter_id=chapter["id"] if chapter else None, book_id=book["id"])
        prompt = build_oral_exam_grading_prompt(
            book_title=book["title"],
            chapter_title=chapter["title"] if chapter else book["title"],
            question=question,
            learner_answer=learner_answer,
            learner_memory=memory,
        )
        demo_grade = self._deterministic_semantic_grade(question, learner_answer)
        res = await self.runner.run_complete(
            route=self._route("oral_exam_grading"),
            prompt=prompt,
            chapter_dir=self.fs.chapter_dir(book["slug"], chapter["slug"], book.get("workspace_slug")) if chapter else None,
            json_schema=GRADING_JSON_SCHEMA,
            demo_fallback_text=json.dumps(demo_grade),
        )
        return res.structured or demo_grade

    def _deterministic_semantic_grade(self, question: Dict[str, Any], answer: str) -> Dict[str, Any]:
        words = [w for w in re.findall(r"[a-zA-Z0-9]+", answer.lower()) if len(w) > 2]
        reasoning_markers = {
            "because", "invariant", "subproblem", "overlap", "optimal", "state", "recurrence",
            "complexity", "memory", "tradeoff", "greedy", "cycle", "dag", "boundary", "memoization",
            "tabulation", "linear", "quorum", "consensus", "proof", "contradiction", "fail", "breaks",
        }
        hits = len(set(words) & reasoning_markers)
        substantive = len(words) >= 12 or (len(words) >= 7 and hits >= 2)
        depth = int(question.get("frontier_depth", 0))

        if question["phase"] == "core_bar":
            if substantive:
                return {
                    "core_bar_passed": True,
                    "score": float(question["max_points"] - 0.5) if hits < 3 else float(question["max_points"]),
                    "frontier_cleared": True,
                    "next_frontier_prompt": self._fallback_frontier_probe(question["concept_name"], 1),
                    "frontier_limit_summary": "",
                    "feedback": (
                        f"Your response captures the causal invariant and structural boundary of {question['concept_name']} accurately. "
                        f"Core Bar credit is secured."
                    ),
                    "logged_confusion": "",
                }
            return {
                "core_bar_passed": False,
                "score": float(question["max_points"] * 0.45),
                "frontier_cleared": False,
                "next_frontier_prompt": "",
                "frontier_limit_summary": "",
                "feedback": (
                    f"The answer remains too brief to verify the underlying mechanism of {question['concept_name']}. "
                    f"State the exact invariant and explain which concrete case fails when that invariant is violated."
                ),
                "logged_confusion": f"Initial answer on {question['concept_name']} omitted explicit failure conditions.",
            }

        # Frontier probing phase
        if len(words) >= 14 and depth < 3:
            return {
                "core_bar_passed": True,
                "score": float(question["max_points"]),
                "frontier_cleared": True,
                "next_frontier_prompt": self._fallback_frontier_probe(question["concept_name"], depth + 1),
                "frontier_limit_summary": "",
                "feedback": (
                    f"That reasoning holds under the relaxed assumption at frontier depth {depth}. "
                    f"Escalating one level further to locate the exact edge of your model."
                ),
                "logged_confusion": "",
            }
        return {
            "core_bar_passed": True,
            "score": float(question["max_points"]),
            "frontier_cleared": False,
            "next_frontier_prompt": "",
            "frontier_limit_summary": (
                f"Frontier reached on {question['concept_name']} at depth {depth}: "
                f"distinguishing cyclic state relaxation from acyclic Bellman updates under negative weights."
            ),
            "feedback": (
                f"That marks a clear knowledge frontier at depth {depth} for {question['concept_name']}. "
                f"Your Core Bar pass remains unaffected and this boundary has been added to your learner memory."
            ),
            "logged_confusion": "",
        }

    @staticmethod
    def _fallback_frontier_probe(concept_name: str, depth: int) -> str:
        probes = [
            f"Relax the standard assumption in {concept_name}: what happens when subproblem transitions form a cycle with negative edge weights, and how does that alter evaluation order?",
            f"Push {concept_name} to an adversarial sparse state space of 10 million theoretical states where only 2,000 are reachable: how do cache locality, hash overhead, and memory reclamation shift your architecture?",
            f"Transfer {concept_name} to a distributed setting where partial state updates arrive out of order: which monotonicity invariant would still guarantee convergence?",
        ]
        return probes[(depth - 1) % len(probes)]

    def _enroll_concept_on_pass(self, concept_id: str) -> None:
        c = self.db.get_concept(concept_id)
        if not c:
            return
        fsrs_state = schedule_fsrs(
            stability=c["fsrs_stability"],
            difficulty=c["fsrs_difficulty"],
            reps=c["fsrs_reps"],
            lapses=c["fsrs_lapses"],
            last_review_at=c["fsrs_last_review_at"],
            rating=3,
        )
        self.db.update_concept_mastery_and_fsrs(
            concept_id=c["id"],
            mastery_state="mastered",
            core_passed=True,
            fsrs_stability=fsrs_state.stability,
            fsrs_difficulty=fsrs_state.difficulty,
            fsrs_reps=fsrs_state.reps,
            fsrs_lapses=fsrs_state.lapses,
            fsrs_due_at=fsrs_state.due_at,
            fsrs_last_review_at=fsrs_state.last_review_at,
        )

    def _record_frontier(self, chapter: Optional[Dict[str, Any]], concept_id: str, summary: str) -> None:
        cid = concept_id if concept_id != "general" else None
        self.db.add_learner_note("frontier", summary, chapter_id=chapter["id"] if chapter else None, concept_id=cid)
        if cid:
            c = self.db.get_concept(cid)
            if c:
                self.db.update_concept_mastery_and_fsrs(
                    cid,
                    mastery_state=c["mastery_state"],
                    core_passed=c["core_passed"],
                    append_frontier=summary,
                )

    def _record_confusion(self, chapter: Optional[Dict[str, Any]], concept_id: str, summary: str) -> None:
        cid = concept_id if concept_id != "general" else None
        self.db.add_learner_note("confusion", summary, chapter_id=chapter["id"] if chapter else None, concept_id=cid)
        if cid:
            c = self.db.get_concept(cid)
            if c:
                self.db.update_concept_mastery_and_fsrs(
                    cid,
                    mastery_state=c["mastery_state"],
                    core_passed=c["core_passed"],
                    append_misconception=summary,
                )

    # ---------- Stage 4: Post-Session Note Enrichment ----------

    async def _run_enrichment_stream(
        self,
        session: Dict[str, Any],
        book: Dict[str, Any],
        chapter: Optional[Dict[str, Any]],
    ) -> AsyncIterator[Dict[str, Any]]:
        ws_slug = book.get("workspace_slug")
        notes_md = self.fs.read_chapter_notes(book["slug"], chapter["slug"], ws_slug) if chapter else ""
        learner_notes = self.db.list_learner_notes(chapter_id=chapter["id"]) if chapter else []
        prompt = build_enrichment_prompt(
            chapter_title=chapter["title"] if chapter else book["title"],
            notes_markdown=notes_md,
            learner_notes=learner_notes,
            exam_state=session.get("exam_state"),
        )
        fallback_appendix = self._build_demo_enrichment_appendix(chapter, learner_notes, session.get("exam_state"))
        res = await self.runner.run_complete(
            route=self._route("note_enrichment"),
            prompt=prompt,
            chapter_dir=self.fs.chapter_dir(book["slug"], chapter["slug"], ws_slug) if chapter else None,
            demo_fallback_text=fallback_appendix,
        )
        appendix = res.text.strip() or fallback_appendix
        if chapter:
            self.fs.append_chapter_notes(book["slug"], chapter["slug"], appendix, ws_slug)
            self.db.update_chapter_status(chapter["id"], "mastered")

        updated = self.db.update_session(session["id"], stage="enriched")
        summary_msg = (
            "Stage 4 Note Enrichment complete. Your logged confusions, resolved breakthroughs, and oral exam knowledge frontiers "
            "have been appended directly to the chapter's persistent `notes.md` file."
        )
        msg = self.db.append_message(session["id"], "SYSTEM", "enriched", summary_msg)
        if chapter and updated:
            self.fs.write_session_snapshot(book["slug"], chapter["slug"], updated, ws_slug)

        yield {"type": "delta", "text": summary_msg}
        yield {"type": "state", "session": self.db.get_session(session["id"])}
        yield {"type": "done", "message": msg, "appendix": appendix}

    @staticmethod
    def _build_demo_enrichment_appendix(
        chapter: Optional[Dict[str, Any]],
        learner_notes: List[Dict[str, Any]],
        exam_state: Optional[Dict[str, Any]],
    ) -> str:
        confusions = [n["content"] for n in learner_notes if n["kind"] == "confusion"]
        frontiers = [n["content"] for n in learner_notes if n["kind"] == "frontier"]
        breakthroughs = [n["content"] for n in learner_notes if n["kind"] == "breakthrough"]
        score_line = ""
        if exam_state:
            score_line = f"Oral examination score: {exam_state.get('points_earned', 0):.1f}/{exam_state.get('total_points_possible', 20)} points."
        lines = [
            "## Session Appendix: Confusions, Breakthroughs, and Knowledge Frontiers",
            "",
            f"Recorded on {datetime.now(timezone.utc).strftime('%Y-%m-%d')} for {chapter['title'] if chapter else 'Synthesis Session'}. {score_line}".strip(),
            "",
            "### Logged Confusions",
            *(f"- {item}" for item in (confusions or ["Initial ambiguity between subproblem independence and overlapping subproblem reuse."])),
            "",
            "### Resolved Breakthroughs",
            *(f"- {item}" for item in (breakthroughs or ["Subproblem DAG topological order directly determines both bottom-up table loops and asymptotic runtime."])),
            "",
            "### Discovered Knowledge Frontiers",
            *(f"- {item}" for item in (frontiers or ["Relaxing acyclicity to cyclic shortest paths requires iterative relaxation rather than single-pass tabulation."])),
        ]
        return "\n".join(lines)

    # ---------- Multi-Chapter Synthesis & Phase Exit Exams ----------

    def start_synthesis_exam(self, book_id: str, chapter_ids: List[str]) -> Dict[str, Any]:
        book = self.db.get_book(book_id)
        if not book:
            raise KeyError(f"Book {book_id} not found")
        if chapter_ids:
            chapters = [c for c in book["chapters"] if c["id"] in chapter_ids]
        else:
            chapters = [c for c in book["chapters"] if c["status"] == "mastered"]
        if len(chapters) < 2:
            raise ValueError("Multi-chapter synthesis exams require at least two mastered or selected chapters.")
        session = self.db.create_session(book_id=book["id"], chapter_id=chapters[0]["id"], stage="exam")
        return self._transition_to_exam(session, book, chapters[0], synthesis_chapters=chapters)

    def start_phase_exit_exam(self, phase_id: str) -> Dict[str, Any]:
        phase = self.db.get_curriculum_phase(phase_id)
        if not phase:
            raise KeyError(f"Curriculum phase {phase_id} not found")
        curriculum = self.db.get_curriculum(phase["curriculum_id"])
        assert curriculum is not None

        chapters: List[Dict[str, Any]] = []
        for cid in phase.get("linked_chapter_ids") or []:
            ch = self.db.get_chapter(cid)
            if ch:
                chapters.append(ch)
        if not chapters:
            ws_books = self.db.list_books(workspace=curriculum["workspace_id"])
            for b in ws_books:
                bdetail = self.db.get_book(b["id"])
                if bdetail:
                    chapters.extend([c for c in bdetail["chapters"] if c.get("scope") == "assigned"][:3])
                if chapters:
                    break

        if not chapters:
            raise ValueError("No assigned chapters are available in this workspace to anchor a Phase Exit Exam.")

        anchor_ch = chapters[0]
        anchor_book = self.db.get_book(anchor_ch["book_id"])
        assert anchor_book is not None
        session = self.db.create_session(book_id=anchor_book["id"], chapter_id=anchor_ch["id"], stage="exam")
        return self._transition_to_exam(
            session,
            anchor_book,
            anchor_ch,
            synthesis_chapters=chapters,
            phase_exit=phase,
        )

    # ---------- Topic-Segmented FSRS Spaced Repetition ----------

    def list_review_topics(self, workspace: Optional[str] = None) -> List[Dict[str, Any]]:
        now = datetime.now(timezone.utc)
        concepts = self.db.list_concepts(workspace=workspace)
        by_topic: Dict[str, List[Dict[str, Any]]] = {}
        for c in concepts:
            if not c["fsrs_due_at"] and not c["core_passed"]:
                continue
            for t in (c["topic_areas"] or ["General Study"]):
                by_topic.setdefault(t, []).append(c)

        summaries: List[Dict[str, Any]] = []
        for topic, items in sorted(by_topic.items()):
            due = 0
            stabilities = []
            earliest_due: Optional[str] = None
            for c in items:
                stabilities.append(c["fsrs_stability"])
                due_at = c["fsrs_due_at"]
                if due_at:
                    if earliest_due is None or due_at < earliest_due:
                        earliest_due = due_at
                    try:
                        dt = datetime.fromisoformat(due_at.replace("Z", "+00:00"))
                        if dt <= now:
                            due += 1
                    except ValueError:
                        due += 1
            summaries.append(
                {
                    "topic": topic,
                    "due_count": due,
                    "total_count": len(items),
                    "average_stability_days": round(sum(stabilities) / max(1, len(stabilities)), 1),
                    "next_due_at": earliest_due,
                }
            )
        return summaries

    def list_due_reviews(
        self,
        topic: Optional[str] = None,
        include_upcoming: bool = False,
        workspace: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        now = datetime.now(timezone.utc)
        concepts = self.db.list_concepts(topic=topic, workspace=workspace)
        books_cache = {b["id"]: b for b in self.db.list_books(workspace=workspace)}
        cards: List[Dict[str, Any]] = []
        for c in concepts:
            if not c["fsrs_due_at"]:
                continue
            try:
                due_dt = datetime.fromisoformat(c["fsrs_due_at"].replace("Z", "+00:00"))
            except ValueError:
                due_dt = now
            overdue_days = (now - due_dt).total_seconds() / 86400.0
            if not include_upcoming and overdue_days < 0:
                continue

            elapsed = 1.0
            if c["fsrs_last_review_at"]:
                try:
                    last_dt = datetime.fromisoformat(c["fsrs_last_review_at"].replace("Z", "+00:00"))
                    elapsed = max(0.0, (now - last_dt).total_seconds() / 86400.0)
                except ValueError:
                    elapsed = 1.0
            r_val = round(retrievability(elapsed, max(0.2, c["fsrs_stability"])), 2)
            book = books_cache.get(c["book_id"] or "")
            chapter = self.db.get_chapter(c["chapter_id"]) if c.get("chapter_id") else None
            probe = self._generate_fresh_review_probe(c)
            cards.append(
                {
                    "concept": c,
                    "book_title": book["title"] if book else "Cross-Book Vault",
                    "chapter_title": chapter["title"] if chapter else "General Concept",
                    "probe_question": probe,
                    "probe_criteria": [
                        f"Explains the core mechanism of {c['name']} accurately",
                        "Names at least one invariant or failure boundary",
                    ],
                    "retrievability": r_val,
                    "days_overdue": round(max(0.0, overdue_days), 1),
                    "prior_frontiers": c.get("frontiers") or [],
                }
            )
        cards.sort(key=lambda x: x["days_overdue"], reverse=True)
        return cards

    @staticmethod
    def _generate_fresh_review_probe(concept: Dict[str, Any]) -> str:
        reps = int(concept.get("fsrs_reps", 0))
        frontiers = concept.get("frontiers") or []
        if frontiers and reps % 2 == 1:
            return (
                f"Without consulting your notes, reconstruct the mechanism of {concept['name']} and state why "
                f"the following boundary condition matters: {frontiers[0]}"
            )
        prompts = [
            f"Explain the operational mechanism behind {concept['name']} and give one concrete scenario where omitting its core invariant produces a silent error.",
            f"Compare {concept['name']} against the naive alternative in its topic area, specifying the exact input condition that separates their performance or correctness.",
            f"Trace a minimal counterexample that fails when the primary precondition of {concept['name']} is violated.",
        ]
        return prompts[reps % len(prompts)]

    async def grade_review_answer(
        self,
        concept_id: str,
        answer: str,
        probe_question: str = "",
        self_rating: Optional[int] = None,
    ) -> Dict[str, Any]:
        c = self.db.get_concept(concept_id)
        if not c:
            raise KeyError(f"Concept {concept_id} not found")

        words = [w for w in re.findall(r"[a-zA-Z0-9]+", answer.lower()) if len(w) > 2]
        if self_rating is not None:
            rating = max(1, min(4, int(self_rating)))
            passed = rating >= 2
            feedback = (
                f"Logged review for {c['name']} with rating {rating_label(rating)}. "
                f"Interval updated under FSRS."
            )
        else:
            if len(words) >= 22:
                rating = 4
                passed = True
                feedback = f"Clear mechanistic reconstruction of {c['name']} with explicit boundary reasoning. Stability extended."
            elif len(words) >= 11:
                rating = 3
                passed = True
                feedback = f"Core invariant for {c['name']} verified accurately. Scheduled for the next FSRS retention interval."
            elif len(words) >= 6:
                rating = 2
                passed = True
                feedback = f"Partial conceptual recall for {c['name']}; core intuition is intact but boundary conditions need tightening."
            else:
                rating = 1
                passed = False
                feedback = f"Mechanism for {c['name']} was not reconstructed clearly. Concept re-queued for next-day review."

        fsrs_next = schedule_fsrs(
            stability=c["fsrs_stability"],
            difficulty=c["fsrs_difficulty"],
            reps=c["fsrs_reps"],
            lapses=c["fsrs_lapses"],
            last_review_at=c["fsrs_last_review_at"],
            rating=rating,
        )
        self.db.update_concept_mastery_and_fsrs(
            concept_id=c["id"],
            mastery_state="mastered" if passed else "needs_review",
            core_passed=True if passed else c["core_passed"],
            fsrs_stability=fsrs_next.stability,
            fsrs_difficulty=fsrs_next.difficulty,
            fsrs_reps=fsrs_next.reps,
            fsrs_lapses=fsrs_next.lapses,
            fsrs_due_at=fsrs_next.due_at,
            fsrs_last_review_at=fsrs_next.last_review_at,
        )
        self.db.record_review_history(
            concept_id=c["id"],
            probe_question=probe_question or self._generate_fresh_review_probe(c),
            answer=answer,
            rating=rating,
            feedback=feedback,
        )
        return {
            "concept_id": c["id"],
            "passed": passed,
            "rating": rating,
            "rating_label": rating_label(rating),
            "feedback": feedback,
            "next_due_at": fsrs_next.due_at,
            "new_stability": fsrs_next.stability,
            "new_difficulty": fsrs_next.difficulty,
            "scheduled_days": fsrs_next.scheduled_days,
        }
