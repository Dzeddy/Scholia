"""Pydantic domain models for Scholia REST API and vault artifacts (v2)."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

from .config import BinaryOverrides, EffortLevel, ProviderName, StageRoute

ChapterStatus = Literal["pending", "extracting", "ready", "in_progress", "mastered", "error"]
ChapterScope = Literal["assigned", "optional", "skipped"]
SessionStage = Literal["plan", "socratic", "exam", "enriched"]
MasteryState = Literal["unseen", "learning", "core_passed", "mastered", "needs_review"]
CognitiveLevel = Literal["explanation", "application", "analysis", "evaluation", "synthesis"]
CurriculumTrack = Literal["core", "alongside", "optional"]
CurriculumItemKind = Literal["reading", "do_task", "at_work", "milestone", "cuj_practice"]
CurriculumItemStatus = Literal["todo", "in_progress", "done", "skipped"]


class WorkspaceSummary(BaseModel):
    id: str
    slug: str
    name: str
    description: str = ""
    book_count: int = 0
    curriculum_count: int = 0
    concept_count: int = 0
    created_at: str
    updated_at: str


class CreateWorkspaceRequest(BaseModel):
    name: str
    description: str = ""
    slug: Optional[str] = None


class UpdateWorkspaceRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class Citation(BaseModel):
    page: int
    label: str = ""
    excerpt: str = ""


class ChapterBoundaryInput(BaseModel):
    id: Optional[str] = None
    title: str
    start_page: int = 1
    end_page: int = 1
    order_index: Optional[int] = None
    scope: Optional[ChapterScope] = None


class UpdateBoundariesRequest(BaseModel):
    topic_areas: Optional[List[str]] = None
    chapters: List[ChapterBoundaryInput]


class UpdateChapterScopeRequest(BaseModel):
    scope: ChapterScope


class BulkChapterScopeRequest(BaseModel):
    scopes: Dict[str, ChapterScope]


class ImportUrlRequest(BaseModel):
    url: str
    workspace_id: Optional[str] = None
    title: str = ""
    authors: str = ""
    topic_areas: List[str] = Field(default_factory=list)


class ImportLocalRequest(BaseModel):
    path: str
    workspace_id: Optional[str] = None
    title: str = ""
    authors: str = ""
    topic_areas: List[str] = Field(default_factory=list)
    toc_level: Optional[int] = None
    single_unit: bool = False
    detect_printed_toc: bool = False
    assigned_filter: Optional[List[str]] = None


class TocEntry(BaseModel):
    level: int
    title: str
    start_page: int
    end_page: int


class BookSummary(BaseModel):
    id: str
    workspace_id: Optional[str] = None
    workspace_slug: Optional[str] = None
    slug: str
    title: str
    authors: str
    source_format: str
    source_url: str = ""
    page_count: int
    topic_areas: List[str] = Field(default_factory=list)
    chapter_count: int = 0
    mastered_chapters: int = 0
    ready_chapters: int = 0
    assigned_chapters: int = 0
    assigned_mastered_chapters: int = 0
    assigned_ready_chapters: int = 0
    optional_chapters: int = 0
    skipped_chapters: int = 0
    created_at: str


class ChapterSummary(BaseModel):
    id: str
    book_id: str
    slug: str
    order_index: int
    title: str
    start_page: int
    end_page: int
    page_count: int
    status: ChapterStatus
    scope: ChapterScope = "assigned"
    extraction_progress: str = ""
    concept_count: int = 0
    mastered_concepts: int = 0
    has_pdf: bool = False
    updated_at: str


class BookDetail(BookSummary):
    chapters: List[ChapterSummary] = Field(default_factory=list)
    can_launch_synthesis: bool = False


class ConceptRecord(BaseModel):
    id: str
    workspace_id: Optional[str] = None
    slug: str
    name: str
    summary: str = ""
    book_id: Optional[str] = None
    chapter_id: Optional[str] = None
    topic_areas: List[str] = Field(default_factory=list)
    mastery_state: MasteryState = "unseen"
    core_passed: bool = False
    page_refs: List[int] = Field(default_factory=list)
    misconceptions: List[str] = Field(default_factory=list)
    frontiers: List[str] = Field(default_factory=list)
    parent_ids: List[str] = Field(default_factory=list)
    child_ids: List[str] = Field(default_factory=list)
    fsrs_stability: float = 0.0
    fsrs_difficulty: float = 5.0
    fsrs_reps: int = 0
    fsrs_lapses: int = 0
    fsrs_due_at: Optional[str] = None
    fsrs_last_review_at: Optional[str] = None


class LessonPlanConcept(BaseModel):
    name: str
    summary: str
    prerequisites: List[str] = Field(default_factory=list)
    page_refs: List[int] = Field(default_factory=list)
    common_misconceptions: List[str] = Field(default_factory=list)
    socratic_probe: str = ""
    worked_example_hook: str = ""


class LessonPlan(BaseModel):
    chapter_title: str
    topic_areas: List[str] = Field(default_factory=list)
    estimated_minutes: int = 25
    calibration_questions: List[str] = Field(default_factory=list)
    prerequisite_links: List[str] = Field(default_factory=list)
    concepts: List[LessonPlanConcept] = Field(default_factory=list)
    core_exam_blueprint: List[Dict[str, Any]] = Field(default_factory=list)


class LearnerNoteRecord(BaseModel):
    id: str
    chapter_id: Optional[str] = None
    concept_id: Optional[str] = None
    kind: Literal["confusion", "breakthrough", "frontier", "analogy"]
    content: str
    resolved: bool = False
    created_at: str


class ExamQuestionState(BaseModel):
    index: int
    cognitive_level: CognitiveLevel
    concept_id: str
    concept_name: str
    max_points: int = 4
    prompt: str
    core_criteria: List[str] = Field(default_factory=list)
    core_bar_passed: bool = False
    score: float = 0.0
    phase: Literal["pending", "core_bar", "frontier_probing", "completed"] = "pending"
    frontier_depth: int = 0
    frontier_notes: List[str] = Field(default_factory=list)
    attempts_on_core: int = 0
    is_retake: bool = False


class OralExamState(BaseModel):
    exam_type: Literal["chapter", "retake", "synthesis", "phase_exit"] = "chapter"
    chapter_ids: List[str] = Field(default_factory=list)
    phase_id: Optional[str] = None
    exit_criterion: Optional[str] = None
    current_question_index: int = 0
    total_points_possible: int = 20
    points_earned: float = 0.0
    passed: Optional[bool] = None
    failed_concept_ids: List[str] = Field(default_factory=list)
    questions: List[ExamQuestionState] = Field(default_factory=list)
    attempt_number: int = 1


class SessionMessage(BaseModel):
    id: str
    session_id: str
    speaker: Literal["TUTOR", "EXAMINER", "YOU", "SYSTEM"]
    stage: SessionStage
    content: str
    citations: List[Citation] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: str


class SessionDetail(BaseModel):
    id: str
    book_id: str
    chapter_id: Optional[str] = None
    stage: SessionStage
    active_concept_id: Optional[str] = None
    covered_concept_ids: List[str] = Field(default_factory=list)
    exam_state: Optional[OralExamState] = None
    agent_conversation_id: Optional[str] = None
    messages: List[SessionMessage] = Field(default_factory=list)
    created_at: str
    updated_at: str


class ChapterDetail(ChapterSummary):
    book_title: str
    topic_areas: List[str] = Field(default_factory=list)
    notes_markdown: str = ""
    lesson_plan: Optional[LessonPlan] = None
    concepts: List[ConceptRecord] = Field(default_factory=list)
    learner_notes: List[LearnerNoteRecord] = Field(default_factory=list)
    active_session: Optional[SessionDetail] = None
    sessions: List[Dict[str, Any]] = Field(default_factory=list)


class StartSessionRequest(BaseModel):
    stage: SessionStage = "plan"
    force_new: bool = False


class SessionTurnRequest(BaseModel):
    message: str = ""
    action: Literal[
        "reply",
        "give_example",
        "explain_mechanism",
        "test_out",
        "start_socratic",
        "start_exam",
        "hit_limit_next_question",
        "start_retake",
        "complete_enrichment",
    ] = "reply"


class SynthesisExamRequest(BaseModel):
    chapter_ids: List[str] = Field(default_factory=list)


class ReviewTopicSummary(BaseModel):
    topic: str
    due_count: int
    total_count: int
    average_stability_days: float
    next_due_at: Optional[str] = None


class ReviewCard(BaseModel):
    concept: ConceptRecord
    book_title: str
    chapter_title: str
    probe_question: str
    probe_criteria: List[str] = Field(default_factory=list)
    retrievability: float = 0.0
    days_overdue: float = 0.0
    prior_frontiers: List[str] = Field(default_factory=list)


class ReviewAnswerRequest(BaseModel):
    answer: str
    probe_question: str = ""
    self_rating: Optional[int] = Field(default=None, ge=1, le=4)


class ReviewAnswerResponse(BaseModel):
    concept_id: str
    passed: bool
    rating: int
    rating_label: str
    feedback: str
    next_due_at: str
    new_stability: float
    new_difficulty: float
    scheduled_days: int


class GraphEdgeRequest(BaseModel):
    parent_id: str
    child_id: str
    relation: str = "prerequisite"


class MergeConceptsRequest(BaseModel):
    source_id: str
    target_id: str


class UpdateCurriculumItemRequest(BaseModel):
    status: Optional[CurriculumItemStatus] = None
    title: Optional[str] = None
    description: Optional[str] = None
    linked_chapter_ids: Optional[List[str]] = None


class UpdateCurriculumPhaseRequest(BaseModel):
    exit_passed: Optional[bool] = None
    title: Optional[str] = None
    goal: Optional[str] = None
    exit_criterion: Optional[str] = None


class CreateRunningLogRequest(BaseModel):
    workspace_id: str
    title: str
    description: str = ""
    curriculum_id: Optional[str] = None
    initial_content: str = ""


class UpdateRunningLogRequest(BaseModel):
    content: str


class AgentCLIStatus(BaseModel):
    provider: ProviderName
    display_name: str
    available: bool
    binary_path: Optional[str] = None
    version: Optional[str] = None
    setup_hint: str = ""
    recommended_models: List[str] = Field(default_factory=list)
    supported_efforts: List[EffortLevel] = Field(default_factory=lambda: ["low", "medium", "high"])


class SettingsResponse(BaseModel):
    vault_dir: str
    routing: Dict[str, StageRoute]
    binary_overrides: BinaryOverrides
    max_pdf_pages_per_slice: int
    socratic_max_sentences: int
    voice_rules_enabled: bool
    voice_rules_preview: str
    study_notes_contract_preview: str


class SettingsUpdateRequest(BaseModel):
    vault_dir: Optional[str] = None
    routing: Optional[Dict[str, StageRoute]] = None
    binary_overrides: Optional[BinaryOverrides] = None
    max_pdf_pages_per_slice: Optional[int] = None
    socratic_max_sentences: Optional[int] = None
    voice_rules_enabled: Optional[bool] = None
