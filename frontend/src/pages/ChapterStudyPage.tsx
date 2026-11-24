import React, { useEffect, useRef, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import {
  ArrowLeft,
  FastForward,
  Lightbulb,
  RefreshCw,
  RotateCcw,
  Sparkles,
  Wrench,
} from 'lucide-react';
import { api } from '../lib/api';
import { MarkdownMath } from '../components/MarkdownMath';
import { PdfViewer } from '../components/PdfViewer';
import { StudyComposer } from '../components/StudyComposer';
import type { ChapterDetail, SessionDetail, SessionStage } from '../types/scholia';

type LeftTab = 'notes' | 'pdf' | 'concepts';

const STAGES: { key: SessionStage; label: string }[] = [
  { key: 'plan', label: 'Plan' },
  { key: 'socratic', label: 'Socratic' },
  { key: 'exam', label: 'Oral Exam' },
  { key: 'enriched', label: 'Enriched' },
];

function parsePaneParam(raw: string | null): LeftTab | null {
  if (!raw) return null;
  if (raw === 'source' || raw === 'pdf') return 'pdf';
  if (raw === 'notes' || raw === 'concepts') return raw;
  return null;
}

export const ChapterStudyPage: React.FC = () => {
  const { chapterId } = useParams<{ chapterId: string }>();
  const [searchParams] = useSearchParams();

  const [chapter, setChapter] = useState<ChapterDetail | null>(null);
  const [sourceMarkdown, setSourceMarkdown] = useState<string>('');
  const [sourceLoading, setSourceLoading] = useState<boolean>(false);
  const [session, setSession] = useState<SessionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [extractingMsg, setExtractingMsg] = useState<string | null>(null);

  const [leftTab, setLeftTab] = useState<LeftTab>(
    parsePaneParam(searchParams.get('pane')) || 'notes'
  );
  const [targetBookPage, setTargetBookPage] = useState<number | null>(() => {
    const p = searchParams.get('page');
    return p ? Number(p) : null;
  });

  const [leftPercent, setLeftPercent] = useState<number>(50);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const draggingRef = useRef<boolean>(false);

  const [draft, setDraft] = useState(() => searchParams.get('draft') || '');
  const [streaming, setStreaming] = useState(false);
  const [streamBuffer, setStreamBuffer] = useState('');
  const transcriptEndRef = useRef<HTMLDivElement | null>(null);

  const loadChapterAndSession = async () => {
    if (!chapterId) return;
    setLoading(true);
    try {
      const ch = await api.getChapter(chapterId);
      setChapter(ch);

      const explicitPane = parsePaneParam(searchParams.get('pane'));
      if (explicitPane) {
        setLeftTab(explicitPane);
      } else if (!ch.has_pdf && !ch.notes_markdown) {
        setLeftTab('pdf');
      }

      if (!ch.has_pdf) {
        setSourceLoading(true);
        api
          .getChapterSourceMarkdown(chapterId)
          .then((res) => setSourceMarkdown(res.source_markdown || ''))
          .catch(() => setSourceMarkdown(''))
          .finally(() => setSourceLoading(false));
      } else {
        setSourceMarkdown('');
      }

      const requestedSessionId = searchParams.get('session');
      const requestedMode = searchParams.get('mode');

      if (requestedSessionId) {
        const s = await api.getSession(requestedSessionId);
        setSession(s);
      } else if (requestedMode === 'exam') {
        const examMeta = ch.sessions.find((s) => s.stage === 'exam');
        if (examMeta) {
          setSession(await api.getSession(examMeta.id));
        } else {
          setSession(await api.startSession(chapterId, 'exam', false));
        }
      } else if (ch.active_session) {
        setSession(ch.active_session);
      } else if (ch.status !== 'pending') {
        const started = await api.startSession(chapterId, 'plan', false);
        setSession(started);
      } else {
        setSession(null);
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadChapterAndSession();
  }, [chapterId]);

  useEffect(() => {
    const pane = parsePaneParam(searchParams.get('pane'));
    if (pane) setLeftTab(pane);
    const p = searchParams.get('page');
    if (p) setTargetBookPage(Number(p));
  }, [searchParams]);

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!draggingRef.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const pct = ((e.clientX - rect.left) / rect.width) * 100;
      setLeftPercent(Math.min(68, Math.max(30, pct)));
    };
    const onUp = () => {
      draggingRef.current = false;
      document.body.style.cursor = '';
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, []);

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [session?.messages.length, streamBuffer]);

  const handleCitePage = (bookPage: number) => {
    setTargetBookPage(bookPage);
    setLeftTab('pdf');
  };

  const handleExtractChapter = async () => {
    if (!chapterId) return;
    setExtractingMsg('Starting chapter extraction...');
    setLeftTab('notes');
    try {
      await api.streamExtractChapter(chapterId, (ev) => {
        if (ev.type === 'progress' && typeof ev.message === 'string') {
          setExtractingMsg(ev.message);
        }
      });
      setExtractingMsg(null);
      await loadChapterAndSession();
    } catch (err) {
      setExtractingMsg(err instanceof Error ? err.message : 'Extraction failed.');
    }
  };

  const switchSessionById = async (sid: string) => {
    const loaded = await api.getSession(sid);
    setSession(loaded);
  };

  const ensureSession = async (stage: SessionStage = 'plan'): Promise<SessionDetail | null> => {
    if (session) return session;
    if (!chapterId) return null;
    const created = await api.startSession(chapterId, stage, false);
    setSession(created);
    return created;
  };

  const sendTurn = async (action: string, messageOverride?: string) => {
    if (streaming) return;
    const msgText = messageOverride !== undefined ? messageOverride : draft;
    if (action === 'reply' && !msgText.trim()) return;

    const activeSess = await ensureSession(action === 'test_out' ? 'exam' : 'plan');
    if (!activeSess) return;

    setStreaming(true);
    setStreamBuffer('');
    if (action === 'reply') setDraft('');

    try {
      await api.streamSessionTurn(
        activeSess.id,
        { message: msgText, action },
        (ev) => {
          if (ev.type === 'delta' && typeof ev.text === 'string') {
            setStreamBuffer((prev) => prev + ev.text);
          } else if (ev.type === 'state' && ev.session) {
            setSession(ev.session as SessionDetail);
            setStreamBuffer('');
          }
        }
      );
      if (chapterId) {
        const refreshed = await api.getChapter(chapterId);
        setChapter(refreshed);
      }
    } finally {
      setStreaming(false);
      setStreamBuffer('');
    }
  };

  const handleStageSelect = async (stage: SessionStage) => {
    if (!chapter || !chapterId) return;
    const existingForStage = chapter.sessions.find((s) => s.stage === stage);
    if (existingForStage) {
      await switchSessionById(existingForStage.id);
      return;
    }
    if (!session) {
      const created = await api.startSession(chapterId, stage, false);
      setSession(created);
      return;
    }
    if (stage === 'exam') {
      await sendTurn('test_out', '');
    } else if (stage === 'socratic') {
      await sendTurn('start_socratic', '');
    } else if (stage === 'enriched') {
      await sendTurn('complete_enrichment', '');
    }
  };

  if (loading || !chapter) {
    return (
      <div className="flex-1 flex items-center justify-center text-[13.5px] text-[var(--ink-muted)]">
        Loading study studio...
      </div>
    );
  }

  const activeStage: SessionStage = session?.stage || 'plan';
  const exam = session?.exam_state || null;
  const activeQ =
    exam && exam.questions.length > 0
      ? exam.questions[Math.min(exam.current_question_index, exam.questions.length - 1)]
      : null;

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
      {/* Compact Airy Breadcrumb Subheader */}
      <div className="h-11 shrink-0 px-6 lg:px-8 border-b border-[var(--border-hairline)] bg-[var(--bg-canvas)] flex items-center justify-between gap-4">
        <div className="flex items-center gap-2.5 min-w-0 text-[13px]">
          <Link
            to="/"
            className="inline-flex items-center gap-1.5 text-[var(--ink-secondary)] hover:text-[var(--ink-primary)] no-underline shrink-0 transition-colors"
          >
            <ArrowLeft className="w-3.5 h-3.5" strokeWidth={1.7} />
            <span>Library</span>
          </Link>
          <span className="text-[var(--ink-muted)]/50">/</span>
          <span className="text-[var(--ink-secondary)] truncate hidden md:inline">
            {chapter.book_title}
          </span>
          <span className="text-[var(--ink-muted)]/50 hidden md:inline">/</span>
          <span className="font-medium text-[var(--ink-primary)] truncate">
            {chapter.title}
          </span>
          <span className="text-[12px] text-[var(--ink-muted)] tabular-nums shrink-0 hidden sm:inline">
            · {chapter.has_pdf ? `pp. ${chapter.start_page}–${chapter.end_page}` : `Section ${chapter.order_index}`}
          </span>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {chapter.sessions.length > 1 && (
            <div className="inline-flex items-center gap-0.5 p-0.5 rounded-full bg-[var(--bg-subtle)]">
              {chapter.sessions.map((s) => {
                const isCurr = session?.id === s.id;
                const lbl =
                  s.stage === 'exam' ? 'Oral Exam' : s.stage === 'socratic' ? 'Socratic' : s.stage;
                return (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => void switchSessionById(s.id)}
                    className={`px-2.5 py-0.5 rounded-full text-[11.5px] font-medium capitalize transition-colors cursor-pointer ${
                      isCurr
                        ? 'bg-[var(--cta-bg)] text-[var(--cta-ink)]'
                        : 'text-[var(--ink-secondary)] hover:text-[var(--ink-primary)]'
                    }`}
                  >
                    {lbl}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Frameless Resizable Two-Pane Studio */}
      <div ref={containerRef} className="flex-1 flex min-h-0 overflow-hidden">
        {/* LEFT PANE: Pure Elevated Reading Sheet (Notes / Source / Concepts) */}
        <section
          className="flex flex-col min-h-0 bg-[var(--bg-sheet)] border-r border-[var(--border-hairline)]"
          style={{ width: `${leftPercent}%` }}
        >
          {/* Whisper-Light Pill Tab Bar */}
          <div className="h-12 shrink-0 px-6 border-b border-[var(--border-hairline)] flex items-center justify-between gap-3">
            <div className="inline-flex items-center gap-0.5 p-0.5 rounded-full bg-[var(--bg-subtle)]">
              {(
                [
                  { id: 'notes', label: 'Notes' },
                  { id: 'pdf', label: chapter.has_pdf ? 'PDF' : 'Source' },
                  {
                    id: 'concepts',
                    label: `Concepts ${chapter.mastered_concepts}/${chapter.concept_count}`,
                  },
                ] as const
              ).map((tab) => {
                const active = leftTab === tab.id;
                return (
                  <button
                    key={tab.id}
                    type="button"
                    onClick={() => setLeftTab(tab.id)}
                    className={`px-3.5 py-1 rounded-full text-[12.5px] font-medium transition-all cursor-pointer tabular-nums ${
                      active
                        ? 'bg-[var(--bg-sheet)] text-[var(--ink-primary)] shadow-xs'
                        : 'text-[var(--ink-secondary)] hover:text-[var(--ink-primary)]'
                    }`}
                  >
                    {tab.label}
                  </button>
                );
              })}
            </div>

            {chapter.status === 'pending' && (
              <button
                type="button"
                onClick={handleExtractChapter}
                className="btn-primary !py-1.5 !px-3.5 !text-[12px]"
              >
                <Sparkles className="w-3.5 h-3.5" strokeWidth={1.7} />
                <span>Extract Notes</span>
              </button>
            )}
          </div>

          {/* Reading Body */}
          <div className="flex-1 min-h-0 overflow-hidden">
            {leftTab === 'notes' && (
              <div className="h-full overflow-y-auto px-10 py-8">
                {extractingMsg ? (
                  <div className="py-16 text-[13.5px] text-[var(--accent)] flex items-center gap-2.5">
                    <RefreshCw className="w-4 h-4 animate-spin" />
                    <span>{extractingMsg}</span>
                  </div>
                ) : chapter.notes_markdown ? (
                  <MarkdownMath
                    content={chapter.notes_markdown}
                    variant="notes"
                    onCitePage={handleCitePage}
                  />
                ) : (
                  <div className="py-12 max-w-md">
                    <h3 className="text-[22px] font-semibold tracking-[-0.02em] m-0 mb-2">
                      Study notes not yet extracted
                    </h3>
                    <p className="text-[14.5px] text-[var(--ink-secondary)] leading-relaxed mb-6">
                      Extract this chapter to synthesize structured study notes in your Voice contract and map prerequisites into the Concept Graph.
                    </p>
                    <div className="flex items-center gap-2.5">
                      <button
                        type="button"
                        onClick={handleExtractChapter}
                        className="btn-primary"
                      >
                        Extract Notes
                      </button>
                      {!chapter.has_pdf && (
                        <button
                          type="button"
                          onClick={() => setLeftTab('pdf')}
                          className="btn-secondary"
                        >
                          Read Source
                        </button>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}

            {leftTab === 'pdf' &&
              (chapter.has_pdf ? (
                <PdfViewer
                  chapterId={chapter.id}
                  startBookPage={chapter.start_page}
                  targetBookPage={targetBookPage}
                  hasPdf={chapter.has_pdf}
                />
              ) : (
                <div className="h-full overflow-y-auto px-10 py-8">
                  {sourceLoading ? (
                    <div className="py-16 text-[13.5px] text-[var(--ink-muted)]">
                      Loading source text and figures...
                    </div>
                  ) : sourceMarkdown ? (
                    <MarkdownMath
                      content={sourceMarkdown}
                      variant="notes"
                      onCitePage={handleCitePage}
                    />
                  ) : (
                    <div className="py-16 text-[13.5px] text-[var(--ink-muted)]">
                      No Markdown source available for this chapter.
                    </div>
                  )}
                </div>
              ))}

            {leftTab === 'concepts' && (
              <div className="h-full overflow-y-auto px-10 py-8 space-y-8">
                <div>
                  <div className="meta-label mb-3">Concepts</div>
                  {chapter.concepts.length > 0 ? (
                    <div className="divide-y divide-[var(--border-hairline)]">
                      {chapter.concepts.map((c) => {
                        const passed = c.core_passed || c.mastery_state === 'mastered';
                        return (
                          <div key={c.id} className="py-4">
                            <div className="flex items-start gap-3">
                              <span
                                className="w-2 h-2 rounded-full mt-2 shrink-0"
                                style={{
                                  backgroundColor: passed
                                    ? 'var(--status-forest)'
                                    : 'var(--status-muted)',
                                }}
                              />
                              <div className="min-w-0 flex-1">
                                <div className="flex flex-wrap items-baseline justify-between gap-2">
                                  <span className="text-[15px] font-medium text-[var(--ink-primary)]">
                                    {c.name}
                                  </span>
                                  <span className="text-[12px] text-[var(--ink-muted)] capitalize">
                                    {c.mastery_state.replace('_', ' ')}
                                    {c.fsrs_stability > 0 && ` · S=${c.fsrs_stability.toFixed(1)}d`}
                                  </span>
                                </div>
                                <p className="text-[13.5px] text-[var(--ink-secondary)] mt-1 mb-0 leading-relaxed">
                                  {c.summary}
                                </p>
                                {c.page_refs.length > 0 && (
                                  <div className="mt-2 flex flex-wrap items-center gap-1">
                                    {c.page_refs.map((p) => (
                                      <button
                                        key={p}
                                        type="button"
                                        onClick={() => handleCitePage(p)}
                                        className="citation-btn"
                                      >
                                        p. {p}
                                      </button>
                                    ))}
                                  </div>
                                )}
                                {c.frontiers.length > 0 && (
                                  <div className="mt-2 text-[12.5px] text-[var(--accent)]">
                                    <span className="meta-label !text-[var(--accent)] mr-2">
                                      Frontier
                                    </span>
                                    {c.frontiers[0]}
                                  </div>
                                )}
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <p className="text-[13.5px] text-[var(--ink-muted)] m-0">
                      Extract this chapter to populate its concept checklist and link prerequisites into the Concept Graph.
                    </p>
                  )}
                </div>

                {chapter.learner_notes.length > 0 && (
                  <div className="pt-4 border-t border-[var(--border-hairline)]">
                    <div className="meta-label mb-3">Session Memory</div>
                    <div className="divide-y divide-[var(--border-hairline)]">
                      {chapter.learner_notes.map((n) => {
                        const dotColor =
                          n.kind === 'frontier'
                            ? 'var(--accent)'
                            : n.kind === 'breakthrough'
                              ? 'var(--status-forest)'
                              : 'var(--status-danger)';
                        return (
                          <div key={n.id} className="py-3 flex items-start gap-3 text-[13.5px]">
                            <span
                              className="w-1.5 h-1.5 rounded-full mt-2 shrink-0"
                              style={{ backgroundColor: dotColor }}
                            />
                            <div>
                              <span className="meta-label mr-2">{n.kind}</span>
                              <span className="text-[var(--ink-primary)]">{n.content}</span>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </section>

        {/* Subtle Draggable Split Handle */}
        <div
          role="separator"
          aria-orientation="vertical"
          onMouseDown={() => {
            draggingRef.current = true;
            document.body.style.cursor = 'col-resize';
          }}
          className="w-1.5 -ml-[1px] shrink-0 bg-transparent hover:bg-[var(--accent)]/25 cursor-col-resize transition-colors z-10"
          title="Drag to resize study panes"
        />

        {/* RIGHT PANE: Calm Seminar & Oral Examination Studio */}
        <section className="flex-1 flex flex-col min-w-0 min-h-0 bg-[var(--bg-canvas)]">
          {/* Stage Pill Header Bar */}
          <div className="h-12 shrink-0 px-6 border-b border-[var(--border-hairline)] flex items-center justify-between gap-3">
            <div className="inline-flex items-center gap-0.5 p-0.5 rounded-full bg-[var(--bg-subtle)] overflow-x-auto">
              {STAGES.map((st) => {
                const isCurrent = activeStage === st.key;
                return (
                  <button
                    key={st.key}
                    type="button"
                    onClick={() => void handleStageSelect(st.key)}
                    className={`px-3.5 py-1 rounded-full text-[12.5px] font-medium whitespace-nowrap transition-all cursor-pointer ${
                      isCurrent
                        ? 'bg-[var(--cta-bg)] text-[var(--cta-ink)]'
                        : 'text-[var(--ink-secondary)] hover:text-[var(--ink-primary)]'
                    }`}
                  >
                    {st.label}
                  </button>
                );
              })}
            </div>

            {activeStage !== 'exam' &&
              activeStage !== 'enriched' &&
              session &&
              session.messages.length > 0 && (
              <button
                type="button"
                onClick={() => void sendTurn('test_out', '')}
                className="btn-secondary !py-1.5 !px-3.5 !text-[12px] shrink-0"
                title="Skip Socratic dialogue and enter the 5-question Oral Exam"
              >
                Test Out
              </button>
            )}
          </div>

          {/* Live Oral Exam Status Bar (Minimal, Zero Badge Soup) */}
          {activeStage === 'exam' && exam && activeQ && (
            <div className="shrink-0 px-6 py-3 border-b border-[var(--border-hairline)] bg-[var(--bg-sheet)]/60 flex flex-wrap items-center justify-between gap-3 text-[12.5px]">
              <div className="flex flex-wrap items-center gap-3">
                <span className="font-medium text-[var(--ink-primary)] tabular-nums">
                  {exam.exam_type === 'phase_exit' ? 'Phase Exit · ' : ''}
                  Q{activeQ.index} of {exam.questions.length}
                </span>
                <span className="text-[var(--ink-muted)] capitalize">
                  {activeQ.cognitive_level}
                </span>
                <span className="inline-flex items-center gap-1.5 text-[var(--ink-secondary)]">
                  <span
                    className="w-1.5 h-1.5 rounded-full"
                    style={{
                      backgroundColor: activeQ.core_bar_passed
                        ? 'var(--status-forest)'
                        : 'var(--accent)',
                    }}
                  />
                  <span>
                    {activeQ.core_bar_passed ? 'Core Bar Cleared' : 'Core Bar Active'}
                  </span>
                </span>
                {activeQ.phase === 'frontier_probing' && (
                  <span className="inline-flex items-center gap-1.5 text-[var(--accent)] font-medium">
                    <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent)]" />
                    <span>Frontier #{activeQ.frontier_depth} · No penalty</span>
                  </span>
                )}
              </div>

              <div className="flex items-center gap-3 tabular-nums">
                <span className="text-[var(--ink-secondary)]">
                  <strong className="text-[var(--ink-primary)]">
                    {exam.points_earned.toFixed(1)}
                  </strong>
                  /{exam.total_points_possible} pts
                </span>
                <div className="flex items-center gap-1">
                  {exam.questions.map((q) => {
                    const bg = q.core_bar_passed
                      ? 'var(--status-forest)'
                      : q.phase === 'completed'
                        ? 'var(--status-danger)'
                        : q.index === activeQ.index
                          ? 'var(--accent)'
                          : 'var(--border-strong)';
                    return (
                      <span
                        key={q.index}
                        className="w-4 h-[3px] rounded-full"
                        style={{ backgroundColor: bg }}
                        title={`Q${q.index}: ${q.concept_name} (${q.cognitive_level})`}
                      />
                    );
                  })}
                </div>
              </div>
            </div>
          )}

          {/* Editorial Seminar Transcript */}
          <div className="flex-1 overflow-y-auto px-7 py-7 space-y-7">
            {(!session || session.messages.length === 0) && (
              <div className="gallery-sheet p-7 max-w-lg">
                <h3 className="text-[20px] font-semibold tracking-[-0.02em] m-0 mb-2">
                  {chapter.title}
                </h3>
                <p className="text-[14px] text-[var(--ink-secondary)] leading-relaxed m-0 mb-5">
                  Read the {chapter.has_pdf ? 'Source PDF' : 'Source Text'} on the left, extract structured notes, or start a Socratic or Oral Exam session below with LaTeX and code blocks.
                </p>
                <div className="flex flex-wrap items-center gap-2.5">
                  <button
                    type="button"
                    onClick={() => void handleStageSelect('plan')}
                    className="btn-primary !py-2 !px-4 !text-[13px]"
                  >
                    Start Plan
                  </button>
                  <button
                    type="button"
                    onClick={() => void sendTurn('test_out', '')}
                    className="btn-secondary !py-2 !px-4 !text-[13px]"
                  >
                    Test Out
                  </button>
                </div>
              </div>
            )}

            {session?.messages.map((msg) => {
              const isUser = msg.speaker === 'YOU';
              const isExaminer = msg.speaker === 'EXAMINER';
              const isFrontier = msg.metadata?.phase === 'frontier_probing';

              const dotColor = isExaminer
                ? isFrontier
                  ? 'var(--accent)'
                  : 'var(--status-forest)'
                : isUser
                  ? 'var(--status-muted)'
                  : 'var(--ink-primary)';

              const speakerLabel = isUser
                ? 'You'
                : isExaminer
                  ? 'Examiner'
                  : 'Tutor';

              return (
                <article key={msg.id} className="max-w-2xl">
                  <div className="flex items-center gap-2 mb-1.5">
                    <span
                      className="w-1.5 h-1.5 rounded-full shrink-0"
                      style={{ backgroundColor: dotColor }}
                    />
                    <span className="text-[12px] font-semibold tracking-[-0.01em] text-[var(--ink-primary)]">
                      {speakerLabel}
                    </span>
                    {typeof msg.metadata?.concept_name === 'string' && (
                      <span className="text-[12px] text-[var(--ink-muted)]">
                        · {msg.metadata.concept_name}
                      </span>
                    )}
                    {isFrontier && (
                      <span className="text-[11.5px] font-medium text-[var(--accent)]">
                        · Frontier #{String(msg.metadata.frontier_depth || 1)}
                      </span>
                    )}
                  </div>

                  <div className="pl-3.5">
                    <MarkdownMath
                      content={msg.content}
                      variant="dialogue"
                      onCitePage={handleCitePage}
                    />
                  </div>
                </article>
              );
            })}

            {streaming && streamBuffer && (
              <article className="max-w-2xl">
                <div className="flex items-center gap-2 mb-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent)] animate-pulse" />
                  <span className="text-[12px] font-semibold text-[var(--ink-primary)]">
                    {activeStage === 'exam' ? 'Examiner' : 'Tutor'}
                  </span>
                  <span className="text-[12px] text-[var(--ink-muted)]">· Thinking</span>
                </div>
                <div className="pl-3.5">
                  <MarkdownMath
                    content={streamBuffer}
                    variant="dialogue"
                    onCitePage={handleCitePage}
                  />
                </div>
              </article>
            )}

            <div ref={transcriptEndRef} />
          </div>

          {/* Floating Bottom Composer Dock */}
          <div className="shrink-0 px-6 pb-5 pt-2">
            {(activeStage === 'socratic' ||
              (activeStage === 'exam' && exam)) && (
              <div className="flex flex-wrap items-center gap-2 mb-2.5">
                {activeStage === 'socratic' && (
                  <>
                    <button
                      type="button"
                      disabled={streaming}
                      onClick={() => void sendTurn('give_example', '')}
                      className="btn-secondary !py-1 !px-3 !text-[12px]"
                    >
                      <Lightbulb className="w-3.5 h-3.5" strokeWidth={1.6} />
                      <span>Give Example</span>
                    </button>
                    <button
                      type="button"
                      disabled={streaming}
                      onClick={() => void sendTurn('explain_mechanism', '')}
                      className="btn-secondary !py-1 !px-3 !text-[12px]"
                    >
                      <Wrench className="w-3.5 h-3.5" strokeWidth={1.6} />
                      <span>Explain Mechanism</span>
                    </button>
                  </>
                )}

                {activeStage === 'exam' && exam && exam.passed === null && (
                  <button
                    type="button"
                    disabled={streaming}
                    onClick={() =>
                      void sendTurn(
                        'hit_limit_next_question',
                        'I have reached my limit on this probe; advance to the next question.'
                      )
                    }
                    className="btn-secondary !py-1 !px-3 !text-[12px] !text-[var(--accent)]"
                  >
                    <FastForward className="w-3.5 h-3.5" strokeWidth={1.7} />
                    <span>Hit Limit · Next Question</span>
                  </button>
                )}

                {activeStage === 'exam' && exam && exam.passed === false && (
                  <button
                    type="button"
                    disabled={streaming}
                    onClick={() => void sendTurn('start_retake', '')}
                    className="btn-primary !py-1.5 !px-3.5 !text-[12px]"
                  >
                    <RotateCcw className="w-3.5 h-3.5" strokeWidth={1.7} />
                    <span>Start Non-Repeating Retake</span>
                  </button>
                )}

                {activeStage === 'exam' && exam && exam.passed === true && (
                  <button
                    type="button"
                    disabled={streaming}
                    onClick={() => void sendTurn('complete_enrichment', '')}
                    className="btn-primary !py-1.5 !px-3.5 !text-[12px]"
                  >
                    <Sparkles className="w-3.5 h-3.5" strokeWidth={1.7} />
                    <span>Enrich Study Notes</span>
                  </button>
                )}
              </div>
            )}

            <StudyComposer
              value={draft}
              onChange={setDraft}
              onSubmit={() => void sendTurn('reply')}
              disabled={streaming}
              rows={2}
              defaultPreview={searchParams.get('preview') === '1'}
              placeholder={
                activeStage === 'exam'
                  ? 'Articulate the mechanism, equation, kernel trace, or boundary condition...'
                  : activeStage === 'socratic'
                    ? 'Reason through the question concisely...'
                    : 'Share your familiarity or ask a question to begin...'
              }
            />
          </div>
        </section>
      </div>
    </div>
  );
};
