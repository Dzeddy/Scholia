import type {
  AgentCLIStatus,
  BookDetail,
  BookSummary,
  ChapterDetail,
  ChapterScope,
  ChapterSummary,
  CurriculumDetail,
  CurriculumItem,
  CurriculumItemStatus,
  CurriculumPhase,
  GraphResponse,
  PrintedTocResponse,
  ReviewAnswerResponse,
  ReviewCard,
  ReviewTopicSummary,
  RunningLog,
  SessionDetail,
  SessionStage,
  SettingsResponse,
  StageRoute,
  TocTreeResponse,
  WorkspaceSummary,
} from '../types/scholia';

const BASE = '/api';

async function jsonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

function withParams(path: string, params: Record<string, string | boolean | undefined | null>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') {
      sp.set(k, String(v));
    }
  }
  const q = sp.toString();
  return q ? `${path}?${q}` : path;
}

export const api = {
  getAgentsStatus: () =>
    jsonFetch<{ agents: AgentCLIStatus[]; routing: Record<string, StageRoute> }>('/agents/status'),

  getSettings: () => jsonFetch<SettingsResponse>('/settings'),

  updateSettings: (payload: Partial<SettingsResponse>) =>
    jsonFetch<SettingsResponse>('/settings', {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),

  // Workspaces
  listWorkspaces: () =>
    jsonFetch<{ workspaces: WorkspaceSummary[]; default_workspace: WorkspaceSummary }>('/workspaces'),

  createWorkspace: (payload: { name: string; description?: string; slug?: string }) =>
    jsonFetch<WorkspaceSummary>('/workspaces', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  updateWorkspace: (workspaceRef: string, payload: { name?: string; description?: string }) =>
    jsonFetch<WorkspaceSummary>(`/workspaces/${encodeURIComponent(workspaceRef)}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),

  // Books & Ingestion
  listBooks: (workspace?: string) =>
    jsonFetch<{ books: BookSummary[]; due_reviews_count: number }>(withParams('/books', { workspace })),

  getBook: (bookId: string) => jsonFetch<BookDetail>(`/books/${bookId}`),

  uploadBook: async (
    file: File,
    title: string,
    authors: string,
    topicAreas: string,
    workspaceId?: string
  ): Promise<BookDetail> => {
    const fd = new FormData();
    fd.append('file', file);
    if (title.trim()) fd.append('title', title.trim());
    if (authors.trim()) fd.append('authors', authors.trim());
    if (topicAreas.trim()) fd.append('topic_areas', topicAreas.trim());
    if (workspaceId) fd.append('workspace_id', workspaceId);
    const res = await fetch(`${BASE}/books/upload`, { method: 'POST', body: fd });
    if (!res.ok) {
      throw new Error(await res.text());
    }
    return res.json() as Promise<BookDetail>;
  },

  importUrl: (payload: {
    url: string;
    workspace_id?: string;
    title?: string;
    authors?: string;
    topic_areas?: string[];
  }) =>
    jsonFetch<BookDetail>('/books/import-url', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  importLocal: (payload: {
    path: string;
    workspace_id?: string;
    title?: string;
    authors?: string;
    topic_areas?: string[];
    toc_level?: number;
    single_unit?: boolean;
    detect_printed_toc?: boolean;
  }) =>
    jsonFetch<BookDetail>('/books/import-local', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  getTocTree: (bookId: string) => jsonFetch<TocTreeResponse>(`/books/${bookId}/toc-tree`),

  detectPrintedToc: (bookId: string, apply = false) =>
    jsonFetch<PrintedTocResponse>(withParams(`/books/${bookId}/detect-printed-toc`, { apply }), {
      method: 'POST',
    }),

  updateBoundaries: (
    bookId: string,
    payload: {
      topic_areas?: string[];
      chapters: { id?: string; title: string; start_page: number; end_page: number; scope?: ChapterScope }[];
    }
  ) =>
    jsonFetch<BookDetail>(`/books/${bookId}/chapters/boundaries`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),

  updateChapterScope: (chapterId: string, scope: ChapterScope) =>
    jsonFetch<ChapterSummary>(`/chapters/${chapterId}/scope`, {
      method: 'PUT',
      body: JSON.stringify({ scope }),
    }),

  bulkUpdateChapterScopes: (bookId: string, scopes: Record<string, ChapterScope>) =>
    jsonFetch<BookDetail>(`/books/${bookId}/chapters/scopes`, {
      method: 'PUT',
      body: JSON.stringify({ scopes }),
    }),

  deleteBook: (bookId: string) => jsonFetch<{ deleted: boolean }>(`/books/${bookId}`, { method: 'DELETE' }),

  extractAllChapters: (bookId: string, assignedOnly = true) =>
    jsonFetch<{ queued: boolean; queued_chapter_ids: string[]; assigned_only: boolean }>(
      withParams(`/books/${bookId}/extract-all`, { assigned_only: assignedOnly }),
      { method: 'POST' }
    ),

  launchSynthesisExam: (bookId: string, chapterIds: string[]) =>
    jsonFetch<SessionDetail>(`/books/${bookId}/synthesis-exam`, {
      method: 'POST',
      body: JSON.stringify({ chapter_ids: chapterIds }),
    }),

  // Chapters & Source Markdown
  getChapter: (chapterId: string) => jsonFetch<ChapterDetail>(`/chapters/${chapterId}`),

  getChapterSourceMarkdown: (chapterId: string) =>
    jsonFetch<{ chapter_id: string; book_id: string; title: string; has_pdf: boolean; source_markdown: string }>(
      `/chapters/${chapterId}/source-markdown`
    ),

  startSession: (chapterId: string, stage: SessionStage = 'plan', forceNew = false) =>
    jsonFetch<SessionDetail>(`/chapters/${chapterId}/sessions`, {
      method: 'POST',
      body: JSON.stringify({ stage, force_new: forceNew }),
    }),

  getSession: (sessionId: string) => jsonFetch<SessionDetail>(`/sessions/${sessionId}`),

  streamExtractChapter: async (
    chapterId: string,
    onEvent: (ev: Record<string, unknown>) => void
  ): Promise<void> => {
    const res = await fetch(`${BASE}/chapters/${chapterId}/extract`, { method: 'POST' });
    if (!res.ok || !res.body) throw new Error('Extraction stream failed');
    await consumeSSE(res.body, onEvent);
  },

  streamSessionTurn: async (
    sessionId: string,
    payload: { message: string; action: string },
    onEvent: (ev: Record<string, unknown>) => void
  ): Promise<void> => {
    const res = await fetch(`${BASE}/sessions/${sessionId}/turn`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok || !res.body) throw new Error('Session turn stream failed');
    await consumeSSE(res.body, onEvent);
  },

  // Curricula & Running Logs
  listCurricula: (workspace?: string) =>
    jsonFetch<{ curricula: CurriculumDetail[] }>(withParams('/curricula', { workspace })),

  getCurriculum: (curriculumRef: string) => jsonFetch<CurriculumDetail>(`/curricula/${curriculumRef}`),

  updateCurriculumItem: (
    itemId: string,
    payload: { status?: CurriculumItemStatus; title?: string; description?: string }
  ) =>
    jsonFetch<CurriculumItem>(`/curriculum-items/${itemId}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),

  updateCurriculumPhase: (phaseId: string, payload: { exit_passed?: boolean }) =>
    jsonFetch<CurriculumPhase>(`/curriculum-phases/${phaseId}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),

  launchPhaseExitExam: (phaseId: string) =>
    jsonFetch<SessionDetail>(`/curriculum-phases/${phaseId}/exit-exam`, {
      method: 'POST',
    }),

  listRunningLogs: (workspace?: string, curriculumId?: string) =>
    jsonFetch<{ logs: RunningLog[] }>(withParams('/logs', { workspace, curriculum_id: curriculumId })),

  createRunningLog: (payload: {
    workspace_id: string;
    title: string;
    description?: string;
    curriculum_id?: string;
    initial_content?: string;
  }) =>
    jsonFetch<RunningLog>('/logs', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  getRunningLog: (logRef: string) => jsonFetch<RunningLog>(`/logs/${encodeURIComponent(logRef)}`),

  updateRunningLog: (logRef: string, content: string) =>
    jsonFetch<RunningLog>(`/logs/${encodeURIComponent(logRef)}`, {
      method: 'PUT',
      body: JSON.stringify({ content }),
    }),

  // Review Queue
  getReviewTopics: (workspace?: string) =>
    jsonFetch<{ topics: ReviewTopicSummary[]; total_unique_due: number }>(
      withParams('/review/topics', { workspace })
    ),

  getDueReviews: (topic?: string, includeUpcoming = false, workspace?: string) =>
    jsonFetch<{ topic: string; cards: ReviewCard[] }>(
      withParams('/review/due', {
        topic,
        include_upcoming: includeUpcoming ? 'true' : undefined,
        workspace,
      })
    ),

  answerReview: (conceptId: string, payload: { answer: string; probe_question?: string; self_rating?: number }) =>
    jsonFetch<ReviewAnswerResponse>(`/review/${conceptId}/answer`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  // Topic Graph
  getGraph: (topic?: string, workspace?: string) =>
    jsonFetch<GraphResponse>(withParams('/graph', { topic, workspace })),

  addGraphEdge: (parentId: string, childId: string) =>
    jsonFetch<{ ok: boolean; message: string }>('/graph/edges', {
      method: 'POST',
      body: JSON.stringify({ parent_id: parentId, child_id: childId, relation: 'prerequisite' }),
    }),

  deleteGraphEdge: (parentId: string, childId: string) =>
    jsonFetch<{ deleted: boolean }>(
      `/graph/edges?parent_id=${encodeURIComponent(parentId)}&child_id=${encodeURIComponent(childId)}`,
      { method: 'DELETE' }
    ),

  mergeConcepts: (sourceId: string, targetId: string) =>
    jsonFetch<{ merged: unknown }>('/graph/concepts/merge', {
      method: 'POST',
      body: JSON.stringify({ source_id: sourceId, target_id: targetId }),
    }),
};

async function consumeSSE(
  stream: ReadableStream<Uint8Array>,
  onEvent: (ev: Record<string, unknown>) => void
): Promise<void> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split('\n\n');
    buffer = parts.pop() || '';
    for (const part of parts) {
      const line = part
        .split('\n')
        .find((l) => l.startsWith('data: '));
      if (!line) continue;
      try {
        onEvent(JSON.parse(line.slice(6)) as Record<string, unknown>);
      } catch {
        // Ignore malformed partial frame
      }
    }
  }
}
