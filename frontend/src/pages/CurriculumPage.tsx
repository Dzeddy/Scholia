import React, { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  ArrowUpRight,
  BookOpen,
  Check,
  Eye,
  PencilLine,
  Plus,
  Save,
} from 'lucide-react';
import { api } from '../lib/api';
import { MarkdownMath } from '../components/MarkdownMath';
import type {
  CurriculumDetail,
  CurriculumItem,
  CurriculumItemKind,
  CurriculumPhase,
  RunningLog,
  WorkspaceSummary,
} from '../types/scholia';

type TrackTab = 'core' | 'alongside' | 'optional' | 'logs';

const KIND_LABEL: Record<CurriculumItemKind, string> = {
  reading: 'Reading',
  do_task: 'Do',
  at_work: 'At Work',
  milestone: 'Milestone',
  cuj_practice: 'CUJ',
};

interface CurriculumPageProps {
  workspace: WorkspaceSummary | null;
}

export const CurriculumPage: React.FC<CurriculumPageProps> = ({ workspace }) => {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const [curricula, setCurricula] = useState<CurriculumDetail[]>([]);
  const [activeCurriculum, setActiveCurriculum] = useState<CurriculumDetail | null>(null);
  const [logs, setLogs] = useState<RunningLog[]>([]);
  const [selectedLogId, setSelectedLogId] = useState<string | null>(null);
  const [logDraft, setLogDraft] = useState('');
  const [logPreview, setLogPreview] = useState(false);
  const [savingLog, setSavingLog] = useState(false);
  const [logSavedMsg, setLogSavedMsg] = useState<string | null>(null);
  const [newLogTitle, setNewLogTitle] = useState('');
  const [showNewLog, setShowNewLog] = useState(false);

  const [track, setTrack] = useState<TrackTab>(
    ((searchParams.get('track') as TrackTab) || 'core')
  );
  const [loading, setLoading] = useState(true);
  const [launchingPhaseId, setLaunchingPhaseId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const wsSlug = workspace?.slug;
      const [curRes, logRes] = await Promise.all([
        api.listCurricula(wsSlug),
        api.listRunningLogs(wsSlug),
      ]);
      setCurricula(curRes.curricula);
      setActiveCurriculum(curRes.curricula[0] || null);
      setLogs(logRes.logs);
      if (logRes.logs.length > 0) {
        const chosen = logRes.logs.find((l) => l.id === selectedLogId) || logRes.logs[0];
        setSelectedLogId(chosen.id);
        setLogDraft(chosen.content || '');
      } else {
        setSelectedLogId(null);
        setLogDraft('');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load curriculum.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadData();
  }, [workspace?.slug]);

  const selectTrack = (next: TrackTab) => {
    setTrack(next);
    setSearchParams(next === 'core' ? {} : { track: next });
  };

  const toggleItemStatus = async (item: CurriculumItem) => {
    const nextStatus = item.status === 'done' ? 'todo' : 'done';
    try {
      await api.updateCurriculumItem(item.id, { status: nextStatus });
      if (activeCurriculum) {
        const fresh = await api.getCurriculum(activeCurriculum.id);
        setActiveCurriculum(fresh);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update item status.');
    }
  };

  const handleLaunchPhaseExitExam = async (phase: CurriculumPhase) => {
    setLaunchingPhaseId(phase.id);
    setError(null);
    try {
      const sess = await api.launchPhaseExitExam(phase.id);
      const targetChapter = sess.chapter_id || phase.linked_chapter_ids[0];
      if (targetChapter) {
        navigate(`/study/${targetChapter}?session=${sess.id}`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to launch phase exit exam.');
    } finally {
      setLaunchingPhaseId(null);
    }
  };

  const selectLog = async (logId: string) => {
    setSelectedLogId(logId);
    setLogSavedMsg(null);
    const local = logs.find((l) => l.id === logId);
    if (local && typeof local.content === 'string') {
      setLogDraft(local.content);
    }
    try {
      const full = await api.getRunningLog(logId);
      setLogDraft(full.content || '');
    } catch {
      // Keep local draft
    }
  };

  const handleSaveLog = async () => {
    if (!selectedLogId || savingLog) return;
    setSavingLog(true);
    setLogSavedMsg(null);
    try {
      const updated = await api.updateRunningLog(selectedLogId, logDraft);
      setLogs((prev) => prev.map((l) => (l.id === updated.id ? { ...l, ...updated } : l)));
      setLogSavedMsg(`Saved to ${updated.file_relpath}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save log.');
    } finally {
      setSavingLog(false);
    }
  };

  const handleCreateLog = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!workspace || !newLogTitle.trim()) return;
    try {
      const created = await api.createRunningLog({
        workspace_id: workspace.id,
        title: newLogTitle.trim(),
        curriculum_id: activeCurriculum?.id,
      });
      setLogs((prev) => [...prev, created]);
      setSelectedLogId(created.id);
      setLogDraft(created.content || '');
      setNewLogTitle('');
      setShowNewLog(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to create log.');
    }
  };

  const visiblePhases = (activeCurriculum?.phases || []).filter((p) => p.track === track);
  const selectedLog = logs.find((l) => l.id === selectedLogId) || null;
  const overallPct =
    activeCurriculum && activeCurriculum.total_items > 0
      ? Math.round((activeCurriculum.done_items / activeCurriculum.total_items) * 100)
      : 0;

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-[1160px] mx-auto px-6 sm:px-8 pt-10 pb-20">
        {/* Confident Anthropic-Style Editorial Header (Zero Kicker Clutter) */}
        <header className="flex flex-col md:flex-row md:items-end justify-between gap-6 pb-8">
          <div className="min-w-0 flex-1">
            <h1 className="text-[32px] sm:text-[38px] font-medium tracking-[-0.03em] leading-[1.12] text-[var(--ink-primary)] m-0">
              {activeCurriculum?.title || `${workspace?.name || 'Study'} Curriculum`}
            </h1>
            {activeCurriculum?.subtitle && (
              <p className="text-[15px] text-[var(--ink-secondary)] mt-2.5 mb-0">
                {activeCurriculum.subtitle}
              </p>
            )}
          </div>

          {activeCurriculum && (
            <div className="min-w-[200px] md:pb-1">
              <div className="flex items-baseline justify-between gap-4 mb-2">
                <span className="meta-label">Progress</span>
                <span className="text-[14px] font-medium tabular-nums text-[var(--ink-primary)]">
                  {activeCurriculum.done_items}{' '}
                  <span className="text-[var(--ink-muted)] font-normal">
                    / {activeCurriculum.total_items}
                  </span>
                </span>
              </div>
              <div className="h-[2px] w-full bg-[var(--border-hairline)] rounded-full overflow-hidden">
                <div
                  className="h-full bg-[var(--accent)] transition-all duration-300"
                  style={{ width: `${Math.max(overallPct, activeCurriculum.done_items > 0 ? 3 : 0)}%` }}
                />
              </div>
            </div>
          )}
        </header>

        {error && (
          <div className="mb-6 px-4 py-3 rounded-xl bg-[var(--status-danger-soft)] text-[var(--status-danger)] text-[13px]">
            {error}
          </div>
        )}

        {loading ? (
          <div className="py-20 text-center text-[13.5px] text-[var(--ink-muted)]">
            Loading curriculum...
          </div>
        ) : !activeCurriculum ? (
          <div className="gallery-sheet p-10 max-w-2xl">
            <h2 className="text-[22px] font-semibold tracking-[-0.02em] m-0 mb-2">
              No curriculum in {workspace?.name || 'this workspace'}
            </h2>
            <p className="text-[14.5px] text-[var(--ink-secondary)] mb-6 leading-relaxed">
              Switch to the Career workspace to open your 11-month ML Performance Engineering roadmap, or ingest books in the Library to start studying.
            </p>
            <button
              type="button"
              onClick={() => navigate('/')}
              className="btn-primary"
            >
              <BookOpen className="w-4 h-4" strokeWidth={1.7} />
              <span>Open Library</span>
            </button>
          </div>
        ) : (
          <div className="space-y-8">
            {/* Quiet Single-Band Horizontal Weekly Cadence Strip (Zero Boxed Grid) */}
            {activeCurriculum.weekly_rhythm.length > 0 && (
              <section className="py-4 border-y border-[var(--border-hairline)] flex flex-col gap-2.5">
                <div className="flex flex-wrap items-center gap-x-7 gap-y-2">
                  <span className="meta-label shrink-0">Weekly Cadence</span>
                  {activeCurriculum.weekly_rhythm.map((slot, idx) => (
                    <div
                      key={idx}
                      className="inline-flex items-baseline gap-2 text-[13px]"
                      title={slot.focus}
                    >
                      <span className="font-medium text-[var(--ink-primary)]">{slot.slot}</span>
                      <span className="text-[var(--ink-muted)] tabular-nums">{slot.length}</span>
                    </div>
                  ))}
                </div>
                {activeCurriculum.guardrails[0] && (
                  <p className="text-[12.5px] text-[var(--ink-muted)] m-0">
                    {activeCurriculum.guardrails[0]}
                  </p>
                )}
              </section>
            )}

            {/* Borderless Editorial Track Switcher */}
            <div className="flex flex-wrap items-center justify-between gap-4 border-b border-[var(--border-hairline)]">
              <div className="flex flex-wrap items-center gap-6">
                {(
                  [
                    {
                      id: 'core',
                      label: 'Core Phases',
                      count: activeCurriculum.phases.filter((p) => p.track === 'core').length,
                    },
                    {
                      id: 'alongside',
                      label: 'Alongside',
                      count: activeCurriculum.phases.filter((p) => p.track === 'alongside').length,
                    },
                    {
                      id: 'optional',
                      label: 'Optional',
                      count: activeCurriculum.phases.filter((p) => p.track === 'optional').length,
                    },
                    {
                      id: 'logs',
                      label: 'Logs',
                      count: logs.length,
                    },
                  ] as const
                ).map((t) => {
                  const active = track === t.id;
                  return (
                    <button
                      key={t.id}
                      type="button"
                      onClick={() => selectTrack(t.id)}
                      className={`relative pb-3.5 text-[14px] font-medium tracking-[-0.01em] transition-colors cursor-pointer inline-flex items-baseline gap-1.5 ${
                        active
                          ? 'text-[var(--ink-primary)]'
                          : 'text-[var(--ink-muted)] hover:text-[var(--ink-secondary)]'
                      }`}
                    >
                      <span>{t.label}</span>
                      <span className="text-[12px] tabular-nums opacity-70">{t.count}</span>
                      {active && (
                        <span className="absolute left-0 right-0 -bottom-[1px] h-[2px] bg-[var(--ink-primary)] rounded-full" />
                      )}
                    </button>
                  );
                })}
              </div>

              {curricula.length > 1 && (
                <select
                  value={activeCurriculum.id}
                  onChange={(e) => {
                    const found = curricula.find((c) => c.id === e.target.value);
                    if (found) setActiveCurriculum(found);
                  }}
                  className="mb-2.5 px-3 py-1.5 rounded-full bg-[var(--bg-subtle)] text-[12.5px] font-medium text-[var(--ink-primary)] focus:outline-none cursor-pointer"
                >
                  {curricula.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.title}
                    </option>
                  ))}
                </select>
              )}
            </div>

            {/* Track Body: Gallery Phase Sheets OR Running Logs */}
            {track !== 'logs' ? (
              <div className="space-y-8">
                {visiblePhases.map((phase) => (
                  <article key={phase.id} className="gallery-sheet p-7 sm:p-9">
                    {/* Phase Header */}
                    <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4 pb-6">
                      <div className="max-w-2xl">
                        <div className="flex flex-wrap items-center gap-2.5 text-[12.5px] text-[var(--ink-muted)] mb-1.5">
                          <span className="font-mono-tech font-medium text-[var(--ink-secondary)]">
                            {phase.track === 'core'
                              ? String(phase.phase_number).padStart(2, '0')
                              : phase.track === 'alongside'
                                ? 'Work-Hours'
                                : 'Optional'}
                          </span>
                          {phase.date_range && (
                            <>
                              <span>·</span>
                              <span>{phase.date_range}</span>
                            </>
                          )}
                          <span>·</span>
                          <span className="tabular-nums">
                            {phase.done_count} / {phase.total_count}
                          </span>
                        </div>
                        <h2 className="text-[24px] font-semibold tracking-[-0.025em] leading-snug text-[var(--ink-primary)] m-0">
                          {phase.title}
                        </h2>
                        {phase.goal && (
                          <p className="text-[14.5px] text-[var(--ink-secondary)] mt-2 mb-0 leading-relaxed">
                            {phase.goal}
                          </p>
                        )}
                      </div>

                      {phase.exit_criterion && (
                        <button
                          type="button"
                          disabled={launchingPhaseId === phase.id}
                          onClick={() => void handleLaunchPhaseExitExam(phase)}
                          className="btn-primary shrink-0 self-start"
                        >
                          <span>
                            {launchingPhaseId === phase.id ? 'Starting Exam...' : 'Run Exit Exam'}
                          </span>
                        </button>
                      )}
                    </div>

                    {/* Airy Hairline-Separated Syllabus Rows (Zero Badge Soup) */}
                    <div className="border-t border-[var(--border-hairline)] divide-y divide-[var(--border-hairline)]">
                      {phase.items.map((item) => {
                        const isDone = item.status === 'done';
                        const kindLabel = KIND_LABEL[item.kind] || 'Reading';
                        const inlineMeta = item.week_label
                          ? `${item.week_label} · ${kindLabel}`
                          : kindLabel;

                        return (
                          <div
                            key={item.id}
                            className={`py-4 flex flex-col sm:flex-row sm:items-start gap-3 sm:gap-5 transition-opacity ${
                              isDone ? 'opacity-55' : ''
                            }`}
                          >
                            {/* Left: Circular Check + Quiet Rhythm-Style Metadata */}
                            <div className="flex items-center gap-3.5 sm:w-[144px] shrink-0 sm:pt-0.5">
                              <button
                                type="button"
                                onClick={() => void toggleItemStatus(item)}
                                className={`w-[18px] h-[18px] rounded-full border flex items-center justify-center shrink-0 cursor-pointer transition-colors ${
                                  isDone
                                    ? 'bg-[var(--status-forest)] border-[var(--status-forest)] text-white'
                                    : 'border-[var(--border-strong)] bg-transparent hover:border-[var(--ink-primary)]'
                                }`}
                                aria-label={isDone ? 'Mark incomplete' : 'Mark complete'}
                              >
                                {isDone && <Check className="w-3 h-3" strokeWidth={2.5} />}
                              </button>

                              <span className="text-[12px] text-[var(--ink-muted)] tabular-nums truncate">
                                {inlineMeta}
                              </span>
                            </div>

                            {/* Center: Crisp Title, Quiet Description, Surgical Vermilion Links */}
                            <div className="min-w-0 flex-1">
                              <div
                                className={`text-[15px] font-medium tracking-[-0.01em] leading-snug ${
                                  isDone
                                    ? 'line-through text-[var(--ink-muted)]'
                                    : 'text-[var(--ink-primary)]'
                                }`}
                              >
                                {item.title}
                              </div>

                              {item.description && (
                                <p className="text-[13.5px] text-[var(--ink-secondary)] mt-1 mb-0 leading-relaxed">
                                  {item.description}
                                </p>
                              )}

                              {(item.linked_chapters.length > 0 || item.external_url) && (
                                <div className="mt-2.5 flex flex-wrap items-center gap-x-5 gap-y-1.5">
                                  {item.linked_chapters.slice(0, 6).map((ch) => (
                                    <button
                                      key={ch.id}
                                      type="button"
                                      onClick={() => navigate(`/study/${ch.id}?pane=pdf`)}
                                      className="inline-flex items-center gap-1 text-[13px] font-medium text-[var(--accent)] hover:text-[var(--accent-hover)] hover:underline underline-offset-4 cursor-pointer bg-transparent border-0 p-0 text-left"
                                      title={`Open ${ch.book_title} — ${ch.title}`}
                                    >
                                      <span className="max-w-[280px] truncate">{ch.title}</span>
                                      <ArrowUpRight className="w-3.5 h-3.5 shrink-0" strokeWidth={1.8} />
                                    </button>
                                  ))}
                                  {item.linked_chapters.length > 6 && (
                                    <span className="text-[12px] text-[var(--ink-muted)]">
                                      +{item.linked_chapters.length - 6} more in Library
                                    </span>
                                  )}
                                  {item.external_url && (
                                    <a
                                      href={item.external_url}
                                      target="_blank"
                                      rel="noreferrer"
                                      className="inline-flex items-center gap-1 text-[13px] font-medium text-[var(--accent)] hover:text-[var(--accent-hover)] hover:underline underline-offset-4 no-underline"
                                    >
                                      <span>Resource</span>
                                      <ArrowUpRight className="w-3.5 h-3.5 shrink-0" strokeWidth={1.8} />
                                    </a>
                                  )}
                                </div>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>

                    {/* Quiet Editorial Footer: At Work & Exit Criterion */}
                    {(phase.at_work_prompt || phase.exit_criterion) && (
                      <div className="mt-2 pt-6 border-t border-[var(--border-hairline)] grid grid-cols-1 lg:grid-cols-2 gap-8">
                        {phase.at_work_prompt && (
                          <div>
                            <div className="meta-label mb-1.5">At Work</div>
                            <p className="text-[13.5px] text-[var(--ink-secondary)] m-0 leading-relaxed">
                              {phase.at_work_prompt}
                            </p>
                          </div>
                        )}

                        {phase.exit_criterion && (
                          <div>
                            <div className="flex items-center gap-2.5 mb-1.5">
                              <span className="meta-label">Exit Criterion</span>
                              <span className="inline-flex items-center gap-1.5 text-[11.5px] text-[var(--ink-muted)]">
                                <span
                                  className="w-1.5 h-1.5 rounded-full"
                                  style={{
                                    backgroundColor: phase.exit_passed
                                      ? 'var(--status-forest)'
                                      : 'var(--status-muted)',
                                  }}
                                />
                                <span>{phase.exit_passed ? 'Passed' : 'Pending'}</span>
                              </span>
                            </div>
                            <p className="text-[13.5px] text-[var(--ink-primary)] m-0 leading-relaxed">
                              {phase.exit_criterion}
                            </p>
                          </div>
                        )}
                      </div>
                    )}
                  </article>
                ))}
              </div>
            ) : (
              /* Running Logs Notebook Editor */
              <div className="flex flex-col lg:flex-row gap-8 items-start">
                <aside className="w-full lg:w-[300px] shrink-0 space-y-1">
                  <div className="flex items-center justify-between px-3 pb-2">
                    <span className="meta-label">Running Logs</span>
                    <button
                      type="button"
                      onClick={() => setShowNewLog((v) => !v)}
                      className="inline-flex items-center gap-1 text-[12.5px] font-medium text-[var(--accent)] hover:underline underline-offset-4 cursor-pointer"
                    >
                      <Plus className="w-3.5 h-3.5" strokeWidth={1.8} />
                      <span>New</span>
                    </button>
                  </div>

                  {showNewLog && (
                    <form onSubmit={handleCreateLog} className="gallery-sheet p-4 mb-3 space-y-2.5">
                      <input
                        type="text"
                        value={newLogTitle}
                        onChange={(e) => setNewLogTitle(e.target.value)}
                        placeholder="Log title (e.g. XProf Traces)"
                        className="w-full px-3 py-2 rounded-xl bg-[var(--bg-subtle)] text-[13px] text-[var(--ink-primary)] placeholder:text-[var(--ink-muted)] focus:outline-none"
                        required
                      />
                      <div className="flex justify-end gap-2">
                        <button
                          type="button"
                          onClick={() => setShowNewLog(false)}
                          className="px-3 py-1.5 rounded-full text-[12px] text-[var(--ink-secondary)] cursor-pointer"
                        >
                          Cancel
                        </button>
                        <button type="submit" className="btn-primary !py-1.5 !px-3.5 !text-[12px]">
                          Create
                        </button>
                      </div>
                    </form>
                  )}

                  {logs.map((lg) => {
                    const active = selectedLogId === lg.id;
                    return (
                      <button
                        key={lg.id}
                        type="button"
                        onClick={() => void selectLog(lg.id)}
                        className={`w-full text-left px-3.5 py-3 rounded-xl cursor-pointer transition-colors ${
                          active
                            ? 'bg-[var(--bg-subtle)] text-[var(--ink-primary)]'
                            : 'hover:bg-[var(--bg-subtle)]/60 text-[var(--ink-primary)]'
                        }`}
                      >
                        <div className="text-[14px] font-medium tracking-[-0.01em]">{lg.title}</div>
                        {lg.description && (
                          <p className="text-[12.5px] text-[var(--ink-secondary)] mt-0.5 mb-0 truncate">
                            {lg.description}
                          </p>
                        )}
                      </button>
                    );
                  })}
                </aside>

                <section className="flex-1 min-w-0 w-full">
                  {selectedLog ? (
                    <div className="gallery-sheet overflow-hidden">
                      <div className="px-7 py-5 border-b border-[var(--border-hairline)] flex flex-wrap items-center justify-between gap-4">
                        <div>
                          <h3 className="text-[20px] font-semibold tracking-[-0.02em] m-0">
                            {selectedLog.title}
                          </h3>
                          <div className="font-mono-tech text-[11.5px] text-[var(--ink-muted)] mt-0.5">
                            {selectedLog.file_relpath}
                          </div>
                        </div>

                        <div className="flex items-center gap-2">
                          <button
                            type="button"
                            onClick={() => setLogPreview((p) => !p)}
                            className="btn-secondary !py-1.5 !px-3.5 !text-[12.5px]"
                          >
                            {logPreview ? (
                              <>
                                <PencilLine className="w-3.5 h-3.5" strokeWidth={1.6} />
                                <span>Edit</span>
                              </>
                            ) : (
                              <>
                                <Eye className="w-3.5 h-3.5" strokeWidth={1.6} />
                                <span>Preview</span>
                              </>
                            )}
                          </button>

                          <button
                            type="button"
                            disabled={savingLog}
                            onClick={() => void handleSaveLog()}
                            className="btn-primary !py-1.5 !px-4 !text-[12.5px]"
                          >
                            <Save className="w-3.5 h-3.5" strokeWidth={1.7} />
                            <span>{savingLog ? 'Saving...' : 'Save'}</span>
                          </button>
                        </div>
                      </div>

                      {logSavedMsg && (
                        <div className="px-7 py-2.5 border-b border-[var(--border-hairline)] bg-[var(--status-forest-soft)] text-[var(--status-forest)] text-[12.5px]">
                          {logSavedMsg}
                        </div>
                      )}

                      {logPreview ? (
                        <div className="px-8 py-7 min-h-[420px] max-h-[620px] overflow-y-auto">
                          <MarkdownMath content={logDraft} variant="notes" />
                        </div>
                      ) : (
                        <textarea
                          value={logDraft}
                          onChange={(e) => setLogDraft(e.target.value)}
                          rows={18}
                          className="w-full px-7 py-6 bg-transparent font-mono-tech text-[13px] leading-relaxed text-[var(--ink-primary)] focus:outline-none resize-y border-0"
                        />
                      )}
                    </div>
                  ) : (
                    <div className="gallery-sheet p-12 text-center text-[13.5px] text-[var(--ink-muted)]">
                      Select a running log to view or edit its Markdown file.
                    </div>
                  )}
                </section>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
