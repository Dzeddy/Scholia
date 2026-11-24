export type ProviderName = 'agy' | 'claude' | 'codex' | 'demo';
export type EffortLevel = 'low' | 'medium' | 'high' | 'max';
export type ChapterStatus = 'pending' | 'extracting' | 'ready' | 'in_progress' | 'mastered' | 'error';
export type ChapterScope = 'assigned' | 'optional' | 'skipped';
export type SessionStage = 'plan' | 'socratic' | 'exam' | 'enriched';
export type MasteryState = 'unseen' | 'learning' | 'core_passed' | 'mastered' | 'needs_review';
export type CurriculumTrack = 'core' | 'alongside' | 'optional';
export type CurriculumItemKind = 'reading' | 'do_task' | 'at_work' | 'milestone' | 'cuj_practice';
export type CurriculumItemStatus = 'todo' | 'in_progress' | 'done' | 'skipped';

export interface WorkspaceSummary {
  id: string;
  slug: string;
  name: string;
  description: string;
  book_count: number;
  curriculum_count: number;
  concept_count: number;
  created_at: string;
  updated_at: string;
}

export interface StageRoute {
  provider: ProviderName;
  model: string;
  effort: EffortLevel;
}

export interface AgentCLIStatus {
  provider: ProviderName;
  display_name: string;
  available: boolean;
  binary_path: string | null;
  version: string | null;
  setup_hint: string;
  recommended_models: string[];
  supported_efforts: EffortLevel[];
}

export interface BookSummary {
  id: string;
  workspace_id?: string | null;
  workspace_slug?: string | null;
  slug: string;
  title: string;
  authors: string;
  source_format: string;
  source_url?: string;
  page_count: number;
  topic_areas: string[];
  chapter_count: number;
  mastered_chapters: number;
  ready_chapters: number;
  assigned_chapters: number;
  assigned_mastered_chapters: number;
  assigned_ready_chapters: number;
  optional_chapters: number;
  skipped_chapters: number;
  created_at: string;
}

export interface ChapterSummary {
  id: string;
  book_id: string;
  slug: string;
  order_index: number;
  title: string;
  start_page: number;
  end_page: number;
  page_count: number;
  status: ChapterStatus;
  scope: ChapterScope;
  extraction_progress: string;
  concept_count: number;
  mastered_concepts: number;
  has_pdf: boolean;
  updated_at: string;
}

export interface BookDetail extends BookSummary {
  chapters: ChapterSummary[];
  can_launch_synthesis: boolean;
}

export interface TocEntry {
  index: number;
  level: number;
  title: string;
  start_page: number;
  end_page: number;
}

export interface TocTreeResponse {
  book_id: string;
  page_count: number;
  levels: number[];
  entries: TocEntry[];
}

export interface PrintedTocResponse {
  book_id: string;
  offset: number;
  toc_pages: number[];
  chapters: { title: string; start_page: number; end_page: number; scope?: ChapterScope }[];
  applied: boolean;
  book?: BookDetail | null;
}

export interface ConceptRecord {
  id: string;
  workspace_id?: string | null;
  slug: string;
  name: string;
  summary: string;
  book_id: string | null;
  chapter_id: string | null;
  book_title?: string;
  topic_areas: string[];
  mastery_state: MasteryState;
  core_passed: boolean;
  page_refs: number[];
  misconceptions: string[];
  frontiers: string[];
  parent_ids: string[];
  child_ids: string[];
  fsrs_stability: number;
  fsrs_difficulty: number;
  fsrs_reps: number;
  fsrs_lapses: number;
  fsrs_due_at: string | null;
  fsrs_last_review_at: string | null;
}

export interface LearnerNoteRecord {
  id: string;
  chapter_id: string | null;
  concept_id: string | null;
  kind: 'confusion' | 'breakthrough' | 'frontier' | 'analogy';
  content: string;
  resolved: boolean;
  created_at: string;
}

export interface ExamQuestionState {
  index: number;
  cognitive_level: 'explanation' | 'application' | 'analysis' | 'evaluation' | 'synthesis';
  concept_id: string;
  concept_name: string;
  max_points: number;
  prompt: string;
  core_criteria: string[];
  core_bar_passed: boolean;
  score: number;
  phase: 'pending' | 'core_bar' | 'frontier_probing' | 'completed';
  frontier_depth: number;
  frontier_notes: string[];
  attempts_on_core: number;
  is_retake: boolean;
}

export interface OralExamState {
  exam_type: 'chapter' | 'retake' | 'synthesis' | 'phase_exit';
  chapter_ids: string[];
  phase_id?: string | null;
  exit_criterion?: string | null;
  current_question_index: number;
  total_points_possible: number;
  points_earned: number;
  passed: boolean | null;
  failed_concept_ids: string[];
  questions: ExamQuestionState[];
  attempt_number: number;
}

export interface Citation {
  page: number;
  label: string;
  excerpt?: string;
}

export interface SessionMessage {
  id: string;
  session_id: string;
  speaker: 'TUTOR' | 'EXAMINER' | 'YOU' | 'SYSTEM';
  stage: SessionStage;
  content: string;
  citations: Citation[];
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface SessionDetail {
  id: string;
  book_id: string;
  chapter_id: string | null;
  stage: SessionStage;
  active_concept_id: string | null;
  covered_concept_ids: string[];
  exam_state: OralExamState | null;
  agent_conversation_id: string | null;
  messages: SessionMessage[];
  created_at: string;
  updated_at: string;
}

export interface ChapterDetail extends ChapterSummary {
  book_title: string;
  workspace_id?: string | null;
  workspace_slug?: string | null;
  topic_areas: string[];
  notes_markdown: string;
  lesson_plan: Record<string, unknown> | null;
  concepts: ConceptRecord[];
  learner_notes: LearnerNoteRecord[];
  active_session: SessionDetail | null;
  sessions: { id: string; stage: SessionStage; created_at: string; updated_at: string }[];
}

export interface LinkedChapterRef {
  id: string;
  book_id: string;
  book_title: string;
  title: string;
  start_page: number;
  end_page: number;
  status: ChapterStatus;
  scope: ChapterScope;
}

export interface CurriculumItem {
  id: string;
  phase_id: string;
  week_label: string;
  kind: CurriculumItemKind;
  title: string;
  description: string;
  external_url: string;
  linked_book_id: string | null;
  linked_book_title?: string | null;
  linked_chapter_ids: string[];
  linked_chapters: LinkedChapterRef[];
  status: CurriculumItemStatus;
  order_index: number;
}

export interface CurriculumPhase {
  id: string;
  curriculum_id: string;
  track: CurriculumTrack;
  phase_number: number;
  title: string;
  date_range: string;
  goal: string;
  exit_criterion: string;
  exit_passed: boolean;
  at_work_prompt: string;
  order_index: number;
  items: CurriculumItem[];
  linked_chapter_ids: string[];
  done_count: number;
  total_count: number;
}

export interface CurriculumDetail {
  id: string;
  workspace_id: string;
  slug: string;
  title: string;
  subtitle: string;
  goal: string;
  weekly_rhythm: { slot: string; length: string; focus: string }[];
  guardrails: string[];
  phases: CurriculumPhase[];
  total_items: number;
  done_items: number;
  created_at: string;
  updated_at: string;
}

export interface RunningLog {
  id: string;
  workspace_id: string;
  workspace_slug?: string;
  curriculum_id: string | null;
  slug: string;
  title: string;
  description: string;
  file_relpath: string;
  content?: string;
  line_count?: number;
  created_at: string;
  updated_at: string;
}

export interface ReviewTopicSummary {
  topic: string;
  due_count: number;
  total_count: number;
  average_stability_days: number;
  next_due_at: string | null;
}

export interface ReviewCard {
  concept: ConceptRecord;
  book_title: string;
  chapter_title: string;
  probe_question: string;
  probe_criteria: string[];
  retrievability: number;
  days_overdue: number;
  prior_frontiers: string[];
}

export interface ReviewAnswerResponse {
  concept_id: string;
  passed: boolean;
  rating: number;
  rating_label: string;
  feedback: string;
  next_due_at: string;
  new_stability: number;
  new_difficulty: number;
  scheduled_days: number;
}

export interface GraphResponse {
  topics: string[];
  nodes: ConceptRecord[];
  edges: { parent_id: string; child_id: string; relation: string }[];
}

export interface SettingsResponse {
  vault_dir: string;
  routing: Record<string, StageRoute>;
  binary_overrides: { agy: string | null; claude: string | null; codex: string | null };
  max_pdf_pages_per_slice: number;
  socratic_max_sentences: number;
  voice_rules_enabled: boolean;
  voice_rules_preview: string;
  study_notes_contract_preview: string;
}
