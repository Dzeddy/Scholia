"""Prompt templates embedding the Study Notes and Adapted Voice contracts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

PROMPTS_DIR = Path(__file__).parent


def load_study_notes_contract() -> str:
    return (PROMPTS_DIR / "study_notes.md").read_text(encoding="utf-8")


def load_voice_rules_contract() -> str:
    return (PROMPTS_DIR / "voice_rules.md").read_text(encoding="utf-8")


def build_extraction_prompt(
    book_title: str,
    chapter_title: str,
    start_page: int,
    end_page: int,
    existing_concepts: List[str],
    slice_text: str,
    is_partial_slice: bool = False,
) -> str:
    notes_contract = load_study_notes_contract()
    voice_contract = load_voice_rules_contract()
    scope_note = (
        f"This is a partial slice covering pages {start_page} through {end_page} of '{chapter_title}'."
        if is_partial_slice
        else f"This is the complete chapter '{chapter_title}' covering pages {start_page} through {end_page} of '{book_title}'."
    )
    return f"""You are Scholia's chapter extraction and curriculum planning engine.

{notes_contract}

{voice_contract}

Task:
{scope_note}
Existing concepts already in the learner's vault (link prerequisite edges to these exact names where applicable):
{json.dumps(existing_concepts[:40])}

Produce a JSON object matching the provided schema containing:
1. `notes_markdown`: Comprehensive explanatory study notes in clean Markdown with LaTeX math ($...$ / $$...$$), clickable `[p. N]` page citations, concrete worked examples, argument structure, open questions, and self-quiz prompts. Draft the top-level TL;DR last once all concepts are worked out.
2. `lesson_plan`: Ordered core concepts, prerequisite links (supporting multiple parents), page references, common misconceptions, targeted Socratic probes, two brief Stage 1 calibration questions, and a five-question oral exam blueprint across Explanation, Application, Analysis, Evaluation, and Synthesis.

Source excerpt:
{slice_text[:18000]}
"""


def build_socratic_prompt(
    book_title: str,
    chapter_title: str,
    concept: Dict[str, Any],
    learner_memory: Dict[str, Any],
    history: List[Dict[str, Any]],
    learner_message: str,
    action: str,
) -> str:
    voice_contract = load_voice_rules_contract()
    if action == "give_example":
        mode_instruction = (
            "The learner requested a concrete worked example. Provide one crisp, domain-grounded worked example "
            "with exact values or a concrete scenario, citing page numbers as [p. N], followed by one brief comprehension check question."
        )
    elif action == "explain_mechanism":
        mode_instruction = (
            "The learner requested an explicit mechanism explanation. Present the mechanism in order: problem, "
            "numbered steps in evaluation order with a 'so that' rationale for each step, and result, citing [p. N], "
            "then end with one focused question checking the critical invariant."
        )
    else:
        mode_instruction = (
            "Respond in strict concise Socratic format: two to four crisp sentences evaluating the learner's reasoning "
            "and advancing the concept, followed by a single targeted reasoning question. Include at least one [p. N] citation when referencing the chapter."
        )

    recent_turns = "\n".join(f"{m['speaker']}: {m['content']}" for m in history[-8:])
    return f"""You are Scholia's Socratic seminar tutor for '{book_title}', chapter '{chapter_title}'.

{voice_contract}

Active concept: {concept['name']}
Summary: {concept['summary']}
Page references: {concept.get('page_refs', [])}
Known misconceptions: {concept.get('misconceptions', [])}

Cross-chapter learner memory digest:
{json.dumps(learner_memory)}

Recent transcript:
{recent_turns}

Learner input ({action}):
{learner_message}

Instruction:
{mode_instruction}
"""


def build_oral_exam_grading_prompt(
    book_title: str,
    chapter_title: str,
    question: Dict[str, Any],
    learner_answer: str,
    learner_memory: Dict[str, Any],
) -> str:
    voice_contract = load_voice_rules_contract()
    return f"""You are Scholia's oral examiner for '{book_title}', chapter '{chapter_title}'.

{voice_contract}

Grading philosophy:
Evaluate conceptual understanding, invariants, mechanisms, boundary conditions, and tradeoffs rather than verbatim phrasing. Accept valid alternative framing or analogies.

Question {question['index']}/5 ({question['cognitive_level'].upper()}, max {question['max_points']} points):
Concept: {question['concept_name']}
Phase: {question['phase']} (Frontier depth: {question['frontier_depth']})
Prompt: {question['prompt']}
Core Bar criteria: {json.dumps(question.get('core_criteria', []))}

Cross-chapter learner memory:
{json.dumps(learner_memory)}

Learner response:
{learner_answer}

Return structured JSON with:
- `core_bar_passed`: boolean (true if the learner satisfies the Core Bar criteria)
- `score`: number between 0 and {question['max_points']}
- `frontier_cleared`: boolean (when already in frontier_probing, whether this frontier probe was answered solidly)
- `next_frontier_prompt`: string (if core_bar_passed and learner has not hit limit, escalate with a harder edge case, relaxed assumption, or cross-domain transfer)
- `frontier_limit_summary`: string (concise description of the breakdown boundary if the learner hit a limit)
- `feedback`: concise, formal feedback (2 to 4 sentences) adhering strictly to the Voice contract
- `logged_confusion`: optional string if a substantive misconception surfaced
"""


def build_enrichment_prompt(
    chapter_title: str,
    notes_markdown: str,
    learner_notes: List[Dict[str, Any]],
    exam_state: Dict[str, Any] | None,
) -> str:
    voice_contract = load_voice_rules_contract()
    return f"""You are Scholia's Stage 4 post-session note enrichment engine for '{chapter_title}'.

{voice_contract}

Synthesize a concise Markdown appendix titled `## Session Appendix: Confusions, Breakthroughs, and Knowledge Frontiers`
based on the learner's recorded confusions, resolved breakthroughs, personal analogies, and oral exam frontier boundaries.
Do not repeat the main study notes. Keep prose direct, formal, and useful for six-month review.

Recorded learner notes:
{json.dumps(learner_notes, indent=2)}

Exam summary:
{json.dumps(exam_state or {}, indent=2)[:4000]}
"""
