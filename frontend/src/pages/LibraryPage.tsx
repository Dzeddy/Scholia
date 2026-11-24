import React, { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  ArrowRight,
  Check,
  ChevronRight,
  FileSearch,
  Globe,
  FolderOpen,
  Layers,
  Merge,
  Minimize2,
  Plus,
  Scissors,
  Sparkles,
  Trash2,
  Upload,
  X,
} from 'lucide-react';
import { api } from '../lib/api';
import type {
  BookDetail,
  BookSummary,
  ChapterScope,
  ChapterSummary,
  TocEntry,
  TocTreeResponse,
  WorkspaceSummary,
} from '../types/scholia';

interface BoundaryRow {
  id?: string;
  title: string;
  start_page: number;
  end_page: number;
  scope: ChapterScope;
}

const STATUS_DOT: Record<string, { label: string; color: string }> = {
  pending: { label: 'Pending', color: 'var(--status-muted)' },
  extracting: { label: 'Extracting', color: 'var(--accent)' },
  ready: { label: 'Ready', color: 'var(--ink-secondary)' },
  in_progress: { label: 'In Study', color: 'var(--accent)' },
  mastered: { label: 'Mastered', color: 'var(--status-forest)' },
  error: { label: 'Error', color: 'var(--status-danger)' },
};

const SCOPE_LABEL: Record<ChapterScope, { label: string; color: string }> = {
  assigned: { label: 'Assigned', color: 'var(--ink-primary)' },
  optional: { label: 'Optional', color: 'var(--ink-secondary)' },
  skipped: { label: 'Skipped', color: 'var(--ink-muted)' },
};

const SCOPE_CYCLE: ChapterScope[] = ['assigned', 'optional', 'skipped'];

interface LibraryPageProps {
  workspace: WorkspaceSummary | null;
  onRefreshGlobal?: () => void;
}

export const LibraryPage: React.FC<LibraryPageProps> = ({ workspace, onRefreshGlobal }) => {
  const navigate = useNavigate();
  const { bookId: routeBookId } = useParams<{ bookId?: string }>();

  const [books, setBooks] = useState<BookSummary[]>([]);
  const [selectedBook, setSelectedBook] = useState<BookDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [chapterFilter, setChapterFilter] = useState<'assigned' | 'all'>('assigned');

  // Ingest panel state
  const [showUpload, setShowUpload] = useState(false);
  const [ingestTab, setIngestTab] = useState<'upload' | 'url' | 'local'>('upload');
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadTitle, setUploadTitle] = useState('');
  const [uploadAuthors, setUploadAuthors] = useState('');
  const [uploadTopics, setUploadTopics] = useState('');
  const [importUrl, setImportUrl] = useState('');
  const [localPath, setLocalPath] = useState('');
  const [localSingleUnit, setLocalSingleUnit] = useState(false);
  const [localPrintedToc, setLocalPrintedToc] = useState(false);
  const [uploading, setUploading] = useState(false);

  // Multi-Level Boundary Editor state
  const [editingBoundaries, setEditingBoundaries] = useState(false);
  const [boundaryRows, setBoundaryRows] = useState<BoundaryRow[]>([]);
  const [tocTree, setTocTree] = useState<TocTreeResponse | null>(null);
  const [activeTocLevel, setActiveTocLevel] = useState<number | null>(null);
  const [detectingPrinted, setDetectingPrinted] = useState(false);
  const [boundaryNotice, setBoundaryNotice] = useState<string | null>(null);
  const [topicInput, setTopicInput] = useState('');
  const [savingBoundaries, setSavingBoundaries] = useState(false);
  const [splitTargetIdx, setSplitTargetIdx] = useState<number | null>(null);
  const [splitPage, setSplitPage] = useState<number>(1);
  const [queueNotice, setQueueNotice] = useState<string | null>(null);

  const loadBooks = async (selectId?: string) => {
    setLoading(true);
    try {
      const res = await api.listBooks(workspace?.slug);
      setBooks(res.books);
      const targetId = selectId || routeBookId || res.books[0]?.id;
      if (targetId) {
        const detail = await api.getBook(targetId);
        setSelectedBook(detail);
        setChapterFilter(
          detail.assigned_chapters > 0 && detail.assigned_chapters < detail.chapter_count
            ? 'assigned'
            : 'all'
        );
        if (routeBookId) {
          void openBoundaryEditor(detail);
        }
      } else {
        setSelectedBook(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load library.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadBooks();
  }, [routeBookId, workspace?.slug]);

  const selectBook = async (id: string) => {
    setEditingBoundaries(false);
    setQueueNotice(null);
    try {
      const detail = await api.getBook(id);
      setSelectedBook(detail);
      setChapterFilter(
        detail.assigned_chapters > 0 && detail.assigned_chapters < detail.chapter_count
          ? 'assigned'
          : 'all'
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load book.');
    }
  };

  const openBoundaryEditor = async (book: BookDetail) => {
    setBoundaryRows(
      book.chapters.map((c) => ({
        id: c.id,
        title: c.title,
        start_page: c.start_page,
        end_page: c.end_page,
        scope: c.scope || 'assigned',
      }))
    );
    setTopicInput(book.topic_areas.join(', '));
    setSplitTargetIdx(null);
    setActiveTocLevel(null);
    setBoundaryNotice(null);
    setEditingBoundaries(true);
    setTocTree(null);
    if (book.source_format === 'pdf') {
      try {
        const tree = await api.getTocTree(book.id);
        setTocTree(tree);
      } catch {
        setTocTree(null);
      }
    }
  };

  const applyTocLevel = (level: number) => {
    if (!tocTree || !selectedBook) return;
    const entries = tocTree.entries;
    const picked: TocEntry[] = [];
    for (let i = 0; i < entries.length; i++) {
      const e = entries[i];
      if (e.level > level) continue;
      if (e.level < level) {
        const next = entries[i + 1];
        if (next && next.level > e.level && next.level <= level) continue;
      }
      picked.push(e);
    }
    const useList = picked.length > 0 ? picked : entries.filter((e) => e.level === level);
    if (useList.length === 0) return;

    const rows: BoundaryRow[] = useList.map((e, idx) => {
      const nextStart = useList[idx + 1]?.start_page ?? selectedBook.page_count + 1;
      const endP = Math.min(selectedBook.page_count, Math.max(e.start_page, nextStart - 1));
      const existing = selectedBook.chapters.find(
        (c) => c.title.toLowerCase() === e.title.toLowerCase() && c.start_page === e.start_page
      );
      return {
        id: existing?.id,
        title: e.title,
        start_page: e.start_page,
        end_page: endP,
        scope: existing?.scope || 'assigned',
      };
    });
    setBoundaryRows(rows);
    setActiveTocLevel(level);
    setBoundaryNotice(`Loaded ${rows.length} entries from embedded PDF TOC at Level ${level}.`);
  };

  const findExpandableChildren = (row: BoundaryRow): TocEntry[] => {
    if (!tocTree) return [];
    const matchIdx = tocTree.entries.findIndex(
      (e) => e.start_page === row.start_page && e.title.toLowerCase() === row.title.toLowerCase()
    );
    if (matchIdx === -1) return [];
    const parentLevel = tocTree.entries[matchIdx].level;
    const children: TocEntry[] = [];
    for (let i = matchIdx + 1; i < tocTree.entries.length; i++) {
      const cand = tocTree.entries[i];
      if (cand.level <= parentLevel) break;
      if (cand.level === parentLevel + 1) {
        children.push(cand);
      }
    }
    return children;
  };

  const handleExpandRow = (idx: number) => {
    const row = boundaryRows[idx];
    const children = findExpandableChildren(row);
    if (children.length === 0) return;
    const expanded: BoundaryRow[] = children.map((c, i) => {
      const nextStart = children[i + 1]?.start_page ?? row.end_page + 1;
      const ep = Math.min(row.end_page, Math.max(c.start_page, nextStart - 1));
      return {
        title: c.title,
        start_page: c.start_page,
        end_page: ep,
        scope: row.scope,
      };
    });
    const next = [...boundaryRows];
    next.splice(idx, 1, ...expanded);
    setBoundaryRows(next);
    setBoundaryNotice(`Expanded "${row.title}" into ${expanded.length} L2 subsections.`);
  };

  const handleDetectPrintedToc = async () => {
    if (!selectedBook) return;
    setDetectingPrinted(true);
    setBoundaryNotice(null);
    setError(null);
    try {
      const res = await api.detectPrintedToc(selectedBook.id, false);
      setBoundaryRows(
        res.chapters.map((c) => ({
          title: c.title,
          start_page: c.start_page,
          end_page: c.end_page,
          scope: c.scope || 'assigned',
        }))
      );
      setBoundaryNotice(
        `Detected ${res.chapters.length} chapters from printed TOC (p. ${res.toc_pages.join(', ')}; offset ${res.offset >= 0 ? '+' : ''}${res.offset}).`
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Printed TOC detection failed.');
    } finally {
      setDetectingPrinted(false);
    }
  };

  const handleCollapseSingleUnit = () => {
    if (!selectedBook) return;
    setBoundaryRows([
      {
        title: selectedBook.title,
        start_page: 1,
        end_page: selectedBook.page_count,
        scope: 'assigned',
      },
    ]);
    setBoundaryNotice('Collapsed into a Single Study Unit (full paper mode).');
  };

  const handleIngestSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setUploading(true);
    setError(null);
    try {
      const topicsList = uploadTopics
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean);
      let created: BookDetail;
      if (ingestTab === 'upload') {
        if (!uploadFile) return;
        created = await api.uploadBook(
          uploadFile,
          uploadTitle,
          uploadAuthors,
          uploadTopics,
          workspace?.id
        );
      } else if (ingestTab === 'url') {
        if (!importUrl.trim()) return;
        created = await api.importUrl({
          url: importUrl.trim(),
          workspace_id: workspace?.id,
          title: uploadTitle.trim(),
          authors: uploadAuthors.trim(),
          topic_areas: topicsList,
        });
      } else {
        if (!localPath.trim()) return;
        created = await api.importLocal({
          path: localPath.trim(),
          workspace_id: workspace?.id,
          title: uploadTitle.trim(),
          authors: uploadAuthors.trim(),
          topic_areas: topicsList,
          single_unit: localSingleUnit,
          detect_printed_toc: localPrintedToc,
        });
      }
      setShowUpload(false);
      setUploadFile(null);
      setImportUrl('');
      setLocalPath('');
      setUploadTitle('');
      setUploadAuthors('');
      setUploadTopics('');
      await loadBooks(created.id);
      void openBoundaryEditor(created);
      onRefreshGlobal?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ingestion failed.');
    } finally {
      setUploading(false);
    }
  };

  const handleCycleChapterScope = async (ch: ChapterSummary) => {
    if (!selectedBook) return;
    const nextScope =
      SCOPE_CYCLE[(SCOPE_CYCLE.indexOf(ch.scope || 'assigned') + 1) % SCOPE_CYCLE.length];
    try {
      await api.updateChapterScope(ch.id, nextScope);
      const refreshed = await api.getBook(selectedBook.id);
      setSelectedBook(refreshed);
      const listRes = await api.listBooks(workspace?.slug);
      setBooks(listRes.books);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update chapter scope.');
    }
  };

  const handleMergeWithNext = (idx: number) => {
    if (idx >= boundaryRows.length - 1) return;
    const current = boundaryRows[idx];
    const next = boundaryRows[idx + 1];
    const updated = [...boundaryRows];
    updated.splice(idx, 2, {
      id: current.id,
      title: current.title,
      start_page: current.start_page,
      end_page: Math.max(current.end_page, next.end_page),
      scope: current.scope,
    });
    setBoundaryRows(updated);
  };

  const handleConfirmSplit = (idx: number) => {
    const row = boundaryRows[idx];
    if (!row) return;
    const sp = Math.max(row.start_page + 1, Math.min(row.end_page, splitPage));
    if (sp <= row.start_page || sp > row.end_page) return;
    const updated = [...boundaryRows];
    updated.splice(
      idx,
      1,
      { id: row.id, title: row.title, start_page: row.start_page, end_page: sp - 1, scope: row.scope },
      { title: `${row.title} (Part II)`, start_page: sp, end_page: row.end_page, scope: row.scope }
    );
    setBoundaryRows(updated);
    setSplitTargetIdx(null);
  };

  const handleDeleteRow = (idx: number) => {
    if (boundaryRows.length <= 1) return;
    setBoundaryRows(boundaryRows.filter((_, i) => i !== idx));
  };

  const handleSaveBoundaries = async () => {
    if (!selectedBook) return;
    setSavingBoundaries(true);
    setError(null);
    try {
      const topics = topicInput
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean);
      const updated = await api.updateBoundaries(selectedBook.id, {
        topic_areas: topics.length ? topics : selectedBook.topic_areas,
        chapters: boundaryRows,
      });
      setSelectedBook(updated);
      setEditingBoundaries(false);
      await loadBooks(updated.id);
      if (routeBookId) navigate('/');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save chapter boundaries.');
    } finally {
      setSavingBoundaries(false);
    }
  };

  const handleQueueAllAssigned = async () => {
    if (!selectedBook) return;
    try {
      const res = await api.extractAllChapters(selectedBook.id, true);
      setQueueNotice(
        res.queued_chapter_ids.length > 0
          ? `Queued ${res.queued_chapter_ids.length} assigned chapter(s) for background extraction.`
          : 'All assigned chapters in this volume are already extracted.'
      );
      setTimeout(() => void selectBook(selectedBook.id), 1400);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Queue extraction failed.');
    }
  };

  const handleLaunchSynthesis = async () => {
    if (!selectedBook) return;
    try {
      const masteredIds = selectedBook.chapters
        .filter((c) => c.status === 'mastered')
        .map((c) => c.id);
      const sess = await api.launchSynthesisExam(selectedBook.id, masteredIds);
      navigate(`/study/${selectedBook.chapters[0].id}?session=${sess.id}&pane=notes`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to launch synthesis exam.');
    }
  };

  const openChapter = (ch: ChapterSummary) => {
    const qs = !ch.has_pdf && ch.status === 'pending' ? '?pane=pdf' : '';
    navigate(`/study/${ch.id}${qs}`);
  };

  const visibleChapters = selectedBook
    ? chapterFilter === 'assigned'
      ? selectedBook.chapters.filter((c) => c.scope === 'assigned')
      : selectedBook.chapters
    : [];

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-[1220px] mx-auto px-6 sm:px-8 pt-10 pb-20">
        {/* Confident Page Header (Zero Kicker Clutter) */}
        <header className="flex flex-wrap items-end justify-between gap-4 pb-8">
          <div>
            <h1 className="text-[36px] sm:text-[40px] font-medium tracking-[-0.03em] leading-[1.1] text-[var(--ink-primary)] m-0">
              Library
            </h1>
            <p className="text-[15px] text-[var(--ink-secondary)] mt-2 mb-0">
              {books.length} {books.length === 1 ? 'volume' : 'volumes'} in{' '}
              {workspace?.name || 'your vault'}
            </p>
          </div>

          <button
            type="button"
            onClick={() => setShowUpload((v) => !v)}
            className="btn-primary"
          >
            <Upload className="w-3.5 h-3.5" strokeWidth={1.8} />
            <span>Ingest Source</span>
          </button>
        </header>

        {error && (
          <div className="mb-6 px-4 py-3 rounded-xl bg-[var(--status-danger-soft)] text-[var(--status-danger)] text-[13px] flex items-center justify-between">
            <span>{error}</span>
            <button type="button" onClick={() => setError(null)} className="cursor-pointer">
              <X className="w-4 h-4" />
            </button>
          </div>
        )}

        {/* Inline Multi-Source Ingest Sheet */}
        {showUpload && (
          <form onSubmit={handleIngestSubmit} className="mb-8 gallery-sheet p-7">
            <div className="flex flex-wrap items-center justify-between gap-3 mb-5">
              <div className="inline-flex items-center gap-1 p-1 rounded-full bg-[var(--bg-subtle)]">
                {(
                  [
                    { id: 'upload', label: 'Upload File', icon: Upload },
                    { id: 'url', label: 'Web URL', icon: Globe },
                    { id: 'local', label: 'Local Path', icon: FolderOpen },
                  ] as const
                ).map((t) => {
                  const Icon = t.icon;
                  const active = ingestTab === t.id;
                  return (
                    <button
                      key={t.id}
                      type="button"
                      onClick={() => setIngestTab(t.id)}
                      className={`inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-[12.5px] font-medium transition-colors cursor-pointer ${
                        active
                          ? 'bg-[var(--cta-bg)] text-[var(--cta-ink)]'
                          : 'text-[var(--ink-secondary)] hover:text-[var(--ink-primary)]'
                      }`}
                    >
                      <Icon className="w-3.5 h-3.5" strokeWidth={1.7} />
                      <span>{t.label}</span>
                    </button>
                  );
                })}
              </div>
              <button
                type="button"
                onClick={() => setShowUpload(false)}
                className="w-8 h-8 rounded-full inline-flex items-center justify-center text-[var(--ink-muted)] hover:text-[var(--ink-primary)] hover:bg-[var(--bg-subtle)] cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              {ingestTab === 'upload' && (
                <label className="md:col-span-2 flex flex-col gap-1.5">
                  <span className="meta-label">Source File (PDF / EPUB / ZIP / MD)</span>
                  <input
                    type="file"
                    accept=".pdf,.epub,.zip,.md,.markdown,.txt"
                    onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
                    className="px-3.5 py-2 rounded-xl bg-[var(--bg-subtle)] text-[var(--ink-primary)] text-[13px] file:mr-3 file:py-1 file:px-3 file:rounded-full file:border-0 file:bg-[var(--bg-sheet)] file:text-[12px] file:font-medium file:text-[var(--ink-primary)]"
                    required
                  />
                </label>
              )}

              {ingestTab === 'url' && (
                <label className="md:col-span-2 flex flex-col gap-1.5">
                  <span className="meta-label">Article or Docs URL</span>
                  <input
                    type="url"
                    value={importUrl}
                    onChange={(e) => setImportUrl(e.target.value)}
                    placeholder="https://horace.io/brrr_intro.html"
                    className="px-3.5 py-2.5 rounded-xl bg-[var(--bg-subtle)] text-[var(--ink-primary)] text-[13px] font-mono-tech focus:outline-none"
                    required
                  />
                </label>
              )}

              {ingestTab === 'local' && (
                <label className="md:col-span-2 flex flex-col gap-1.5">
                  <span className="meta-label">Local File Path</span>
                  <input
                    type="text"
                    value={localPath}
                    onChange={(e) => setLocalPath(e.target.value)}
                    placeholder="~/books/monograph.pdf"
                    className="px-3.5 py-2.5 rounded-xl bg-[var(--bg-subtle)] text-[var(--ink-primary)] text-[13px] font-mono-tech focus:outline-none"
                    required
                  />
                </label>
              )}

              <label className="flex flex-col gap-1.5">
                <span className="meta-label">Title (Optional)</span>
                <input
                  type="text"
                  value={uploadTitle}
                  onChange={(e) => setUploadTitle(e.target.value)}
                  placeholder="Auto-detected"
                  className="px-3.5 py-2.5 rounded-xl bg-[var(--bg-subtle)] text-[var(--ink-primary)] text-[13px] focus:outline-none"
                />
              </label>

              <label className="flex flex-col gap-1.5">
                <span className="meta-label">Topics</span>
                <input
                  type="text"
                  value={uploadTopics}
                  onChange={(e) => setUploadTopics(e.target.value)}
                  placeholder="ML Systems, GPU Kernels"
                  className="px-3.5 py-2.5 rounded-xl bg-[var(--bg-subtle)] text-[var(--ink-primary)] text-[13px] focus:outline-none"
                />
              </label>
            </div>

            <div className="mt-5 flex flex-wrap items-center justify-between gap-4">
              <div className="flex flex-wrap items-center gap-4">
                <input
                  type="text"
                  value={uploadAuthors}
                  onChange={(e) => setUploadAuthors(e.target.value)}
                  placeholder="Authors (optional)"
                  className="w-60 px-3.5 py-2 rounded-xl bg-[var(--bg-subtle)] text-[var(--ink-primary)] text-[13px] focus:outline-none"
                />
                {ingestTab === 'local' && (
                  <>
                    <label className="inline-flex items-center gap-2 text-[13px] text-[var(--ink-secondary)] cursor-pointer">
                      <input
                        type="checkbox"
                        checked={localSingleUnit}
                        onChange={(e) => setLocalSingleUnit(e.target.checked)}
                      />
                      <span>Single Study Unit</span>
                    </label>
                    <label className="inline-flex items-center gap-2 text-[13px] text-[var(--ink-secondary)] cursor-pointer">
                      <input
                        type="checkbox"
                        checked={localPrintedToc}
                        onChange={(e) => setLocalPrintedToc(e.target.checked)}
                      />
                      <span>Detect Printed TOC</span>
                    </label>
                  </>
                )}
              </div>

              <button type="submit" disabled={uploading} className="btn-primary">
                {uploading ? 'Ingesting...' : 'Ingest & Review Boundaries'}
              </button>
            </div>
          </form>
        )}

        {/* Open Editorial Two-Column Layout */}
        {loading ? (
          <div className="py-20 text-center text-[13.5px] text-[var(--ink-muted)]">
            Loading library...
          </div>
        ) : (
          <div className="flex flex-col lg:flex-row gap-10 items-start">
            {/* Left Rail: Calm Borderless Volume List (w-[340px]) */}
            <aside className="w-full lg:w-[340px] shrink-0 space-y-1">
              {books.map((book) => {
                const isSelected = selectedBook?.id === book.id;
                const denom =
                  book.assigned_chapters > 0 ? book.assigned_chapters : book.chapter_count;
                const num =
                  book.assigned_chapters > 0
                    ? book.assigned_mastered_chapters
                    : book.mastered_chapters;
                const progressPct = denom > 0 ? Math.round((num / denom) * 100) : 0;

                return (
                  <button
                    key={book.id}
                    type="button"
                    onClick={() => void selectBook(book.id)}
                    className={`w-full text-left px-4 py-3.5 rounded-xl transition-colors cursor-pointer ${
                      isSelected
                        ? 'bg-[var(--bg-subtle)]'
                        : 'bg-transparent hover:bg-[var(--bg-subtle)]/55'
                    }`}
                  >
                    <div className="text-[15px] font-medium tracking-[-0.015em] leading-snug text-[var(--ink-primary)]">
                      {book.title}
                    </div>
                    <div className="text-[12.5px] text-[var(--ink-secondary)] mt-0.5 truncate">
                      {book.authors}
                    </div>

                    <div className="mt-2.5 flex items-center justify-between text-[12px] text-[var(--ink-muted)] tabular-nums">
                      <span>
                        {book.assigned_chapters > 0
                          ? `${book.assigned_mastered_chapters}/${book.assigned_chapters} assigned`
                          : `${book.mastered_chapters}/${book.chapter_count} mastered`}
                      </span>
                      <span>
                        {book.chapter_count} ch · {book.page_count}p
                      </span>
                    </div>

                    <div className="mt-2 h-[2px] w-full bg-[var(--border-hairline)] rounded-full overflow-hidden">
                      <div
                        className="h-full transition-all duration-300"
                        style={{
                          width: `${progressPct}%`,
                          backgroundColor:
                            progressPct === 100 ? 'var(--status-forest)' : 'var(--accent)',
                        }}
                      />
                    </div>
                  </button>
                );
              })}

              {books.length === 0 && (
                <div className="px-4 py-10 text-center text-[13.5px] text-[var(--ink-muted)]">
                  No volumes in {workspace?.name || 'this workspace'} yet. Ingest a PDF, EPUB, ZIP bundle, or web URL to begin.
                </div>
              )}
            </aside>

            {/* Right Pane: Elevated Gallery Sheet (Selected Book OR Boundary Editor) */}
            <section className="flex-1 min-w-0 w-full">
              {selectedBook && !editingBoundaries && (
                <div className="gallery-sheet p-7 sm:p-9">
                  {/* Volume Header */}
                  <div className="flex flex-col xl:flex-row xl:items-start justify-between gap-5">
                    <div className="max-w-xl">
                      <h2 className="text-[26px] font-semibold tracking-[-0.025em] leading-tight text-[var(--ink-primary)] m-0">
                        {selectedBook.title}
                      </h2>
                      <p className="text-[14px] text-[var(--ink-secondary)] mt-1.5 mb-0">
                        {selectedBook.authors}
                      </p>
                      <div className="mt-2.5 flex flex-wrap items-center gap-2 text-[12.5px] text-[var(--ink-muted)] tabular-nums">
                        <span className="uppercase">{selectedBook.source_format}</span>
                        <span>·</span>
                        <span>{selectedBook.page_count} units</span>
                        <span>·</span>
                        <span>
                          {selectedBook.assigned_chapters} assigned of {selectedBook.chapter_count}
                        </span>
                      </div>
                    </div>

                    <div className="flex flex-wrap items-center gap-2 shrink-0">
                      <button
                        type="button"
                        onClick={() => void openBoundaryEditor(selectedBook)}
                        className="btn-secondary !py-2 !px-4 !text-[12.5px]"
                      >
                        <Scissors className="w-3.5 h-3.5" strokeWidth={1.6} />
                        <span>Edit Boundaries</span>
                      </button>

                      <button
                        type="button"
                        onClick={handleQueueAllAssigned}
                        className="btn-secondary !py-2 !px-4 !text-[12.5px]"
                      >
                        <Layers className="w-3.5 h-3.5" strokeWidth={1.6} />
                        <span>Queue Assigned</span>
                      </button>

                      {selectedBook.can_launch_synthesis && (
                        <button
                          type="button"
                          onClick={handleLaunchSynthesis}
                          className="btn-primary !py-2 !px-4 !text-[12.5px]"
                        >
                          <Sparkles className="w-3.5 h-3.5" strokeWidth={1.6} />
                          <span>Synthesis Exam</span>
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Minimal Segmented Filter */}
                  <div className="mt-7 pb-4 border-b border-[var(--border-hairline)] flex flex-wrap items-center justify-between gap-3">
                    <div className="inline-flex items-center gap-0.5 p-1 rounded-full bg-[var(--bg-subtle)]">
                      <button
                        type="button"
                        onClick={() => setChapterFilter('assigned')}
                        className={`px-3.5 py-1 rounded-full text-[12.5px] font-medium transition-colors cursor-pointer tabular-nums ${
                          chapterFilter === 'assigned'
                            ? 'bg-[var(--cta-bg)] text-[var(--cta-ink)]'
                            : 'text-[var(--ink-secondary)] hover:text-[var(--ink-primary)]'
                        }`}
                      >
                        Assigned {selectedBook.assigned_chapters}
                      </button>
                      <button
                        type="button"
                        onClick={() => setChapterFilter('all')}
                        className={`px-3.5 py-1 rounded-full text-[12.5px] font-medium transition-colors cursor-pointer tabular-nums ${
                          chapterFilter === 'all'
                            ? 'bg-[var(--cta-bg)] text-[var(--cta-ink)]'
                            : 'text-[var(--ink-secondary)] hover:text-[var(--ink-primary)]'
                        }`}
                      >
                        All {selectedBook.chapter_count}
                      </button>
                    </div>

                    <span className="text-[12px] text-[var(--ink-muted)]">
                      Click scope to cycle Assigned · Optional · Skipped
                    </span>
                  </div>

                  {queueNotice && (
                    <div className="mt-4 px-4 py-2.5 rounded-xl bg-[var(--accent-soft)] text-[var(--accent)] text-[12.5px]">
                      {queueNotice}
                    </div>
                  )}

                  {/* Airy Hairline-Separated Chapter Rows */}
                  <div className="divide-y divide-[var(--border-hairline)]">
                    {visibleChapters.map((ch) => {
                      const st = STATUS_DOT[ch.status] || STATUS_DOT.pending;
                      const sc = SCOPE_LABEL[ch.scope || 'assigned'] || SCOPE_LABEL.assigned;

                      return (
                        <div
                          key={ch.id}
                          className={`group py-4 flex flex-wrap items-center justify-between gap-4 transition-opacity ${
                            ch.scope === 'skipped' ? 'opacity-50 hover:opacity-100' : ''
                          }`}
                        >
                          <button
                            type="button"
                            onClick={() => openChapter(ch)}
                            className="min-w-0 flex-1 text-left bg-transparent border-0 p-0 cursor-pointer"
                          >
                            <div className="flex items-center gap-3">
                              <span className="font-mono-tech text-[12px] text-[var(--ink-muted)] w-6 shrink-0">
                                {String(ch.order_index).padStart(2, '0')}
                              </span>
                              <span
                                className="w-1.5 h-1.5 rounded-full shrink-0"
                                style={{ backgroundColor: st.color }}
                                title={st.label}
                              />
                              <span className="text-[15px] font-medium tracking-[-0.01em] text-[var(--ink-primary)] group-hover:text-[var(--accent)] transition-colors truncate">
                                {ch.title}
                              </span>
                            </div>

                            <div className="mt-1 pl-[42px] flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[12.5px] text-[var(--ink-muted)] tabular-nums">
                              <span>
                                {ch.has_pdf
                                  ? `pp. ${ch.start_page}–${ch.end_page} (${ch.page_count}p)`
                                  : `Section ${ch.order_index} · Markdown`}
                              </span>
                              <span>·</span>
                              <span>
                                {ch.mastered_concepts}/{ch.concept_count} concepts
                              </span>
                              {ch.status !== 'pending' && (
                                <>
                                  <span>·</span>
                                  <span>{st.label}</span>
                                </>
                              )}
                              {ch.extraction_progress && ch.status === 'extracting' && (
                                <span className="text-[var(--accent)]">
                                  {ch.extraction_progress}
                                </span>
                              )}
                            </div>
                          </button>

                          <div className="flex items-center gap-4 shrink-0">
                            <button
                              type="button"
                              onClick={() => void handleCycleChapterScope(ch)}
                              className="px-2.5 py-1 rounded-full text-[12px] font-medium hover:bg-[var(--bg-subtle)] transition-colors cursor-pointer bg-transparent border-0"
                              style={{ color: sc.color }}
                              title="Cycle scope: Assigned → Optional → Skipped"
                            >
                              {sc.label}
                            </button>

                            <button
                              type="button"
                              onClick={() => openChapter(ch)}
                              className="inline-flex items-center gap-1 text-[13px] font-medium text-[var(--ink-secondary)] group-hover:text-[var(--accent)] transition-colors cursor-pointer bg-transparent border-0 p-0"
                            >
                              <span>Open</span>
                              <ArrowRight
                                className="w-3.5 h-3.5 transition-transform group-hover:translate-x-0.5"
                                strokeWidth={1.8}
                              />
                            </button>
                          </div>
                        </div>
                      );
                    })}

                    {visibleChapters.length === 0 && (
                      <div className="py-12 text-center text-[13.5px] text-[var(--ink-muted)]">
                        No chapters match this filter. Switch to{' '}
                        <button
                          type="button"
                          onClick={() => setChapterFilter('all')}
                          className="text-[var(--accent)] font-medium hover:underline cursor-pointer bg-transparent border-0 p-0"
                        >
                          All {selectedBook.chapter_count}
                        </button>{' '}
                        to inspect or assign sections.
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Interactive Multi-Level Chapter Boundary Editor (Inside Same Gallery Sheet) */}
              {selectedBook && editingBoundaries && (
                <div className="gallery-sheet p-7 sm:p-9">
                  <div className="flex flex-wrap items-start justify-between gap-4 pb-6 border-b border-[var(--border-hairline)]">
                    <div className="max-w-lg">
                      <h2 className="text-[24px] font-semibold tracking-[-0.025em] m-0">
                        {selectedBook.title}
                      </h2>
                      <p className="text-[13.5px] text-[var(--ink-secondary)] mt-1 mb-0">
                        Adjust TOC depth, expand subsections, scan printed TOC, or scope chapters.
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => {
                          setEditingBoundaries(false);
                          if (routeBookId) navigate('/');
                        }}
                        className="btn-secondary !py-2 !px-4 !text-[12.5px]"
                      >
                        Cancel
                      </button>
                      <button
                        type="button"
                        disabled={savingBoundaries}
                        onClick={handleSaveBoundaries}
                        className="btn-primary !py-2 !px-4 !text-[12.5px]"
                      >
                        <Check className="w-3.5 h-3.5" strokeWidth={2} />
                        <span>{savingBoundaries ? 'Saving...' : 'Save Boundaries'}</span>
                      </button>
                    </div>
                  </div>

                  {/* Crisp Rounded-Full TOC Depth & Printed-TOC Controls */}
                  {selectedBook.source_format === 'pdf' && (
                    <div className="py-4 border-b border-[var(--border-hairline)] flex flex-wrap items-center justify-between gap-3">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="meta-label mr-2">Outline</span>
                        {tocTree && tocTree.levels.length > 0 ? (
                          tocTree.levels.slice(0, 3).map((lvl) => (
                            <button
                              key={lvl}
                              type="button"
                              onClick={() => applyTocLevel(lvl)}
                              className={`px-3 py-1 rounded-full text-[12px] font-medium transition-colors cursor-pointer ${
                                activeTocLevel === lvl
                                  ? 'bg-[var(--cta-bg)] text-[var(--cta-ink)]'
                                  : 'bg-[var(--bg-subtle)] text-[var(--ink-secondary)] hover:text-[var(--ink-primary)]'
                              }`}
                            >
                              L{lvl}
                            </button>
                          ))
                        ) : (
                          <span className="text-[12.5px] text-[var(--ink-muted)]">
                            No embedded bookmarks
                          </span>
                        )}
                      </div>

                      <div className="flex flex-wrap items-center gap-2">
                        <button
                          type="button"
                          disabled={detectingPrinted}
                          onClick={() => void handleDetectPrintedToc()}
                          className="btn-secondary !py-1.5 !px-3.5 !text-[12px]"
                        >
                          <FileSearch className="w-3.5 h-3.5" strokeWidth={1.7} />
                          <span>{detectingPrinted ? 'Scanning...' : 'Printed TOC'}</span>
                        </button>

                        <button
                          type="button"
                          onClick={handleCollapseSingleUnit}
                          className="btn-secondary !py-1.5 !px-3.5 !text-[12px]"
                        >
                          <Minimize2 className="w-3.5 h-3.5" strokeWidth={1.7} />
                          <span>Single Unit</span>
                        </button>
                      </div>
                    </div>
                  )}

                  {boundaryNotice && (
                    <div className="mt-4 px-4 py-2.5 rounded-xl bg-[var(--accent-soft)] text-[var(--accent)] text-[12.5px]">
                      {boundaryNotice}
                    </div>
                  )}

                  {/* Topics Row */}
                  <div className="py-4 border-b border-[var(--border-hairline)] flex flex-wrap items-center gap-4">
                    <span className="meta-label w-16 shrink-0">Topics</span>
                    <input
                      type="text"
                      value={topicInput}
                      onChange={(e) => setTopicInput(e.target.value)}
                      className="flex-1 min-w-[200px] px-3.5 py-2 rounded-xl bg-[var(--bg-subtle)] text-[13px] text-[var(--ink-primary)] focus:outline-none"
                      placeholder="GPU Kernels, Parallelism"
                    />
                    <span className="text-[12px] text-[var(--ink-muted)] tabular-nums">
                      {boundaryRows.filter((r) => r.scope === 'assigned').length} assigned ·{' '}
                      {boundaryRows.length} rows · {selectedBook.page_count}p
                    </span>
                  </div>

                  {/* Clean Borderless Row Inputs */}
                  <div className="divide-y divide-[var(--border-hairline)] max-h-[540px] overflow-y-auto">
                    {boundaryRows.map((row, idx) => {
                      const pageSpan = Math.max(1, row.end_page - row.start_page + 1);
                      const needsAutoSlice =
                        selectedBook.source_format === 'pdf' && pageSpan > 20;
                      const expandableKids = findExpandableChildren(row);

                      return (
                        <div key={`${row.id || 'new'}-${idx}`} className="py-2.5">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="font-mono-tech text-[11.5px] text-[var(--ink-muted)] w-6">
                              {String(idx + 1).padStart(2, '0')}
                            </span>

                            <input
                              type="text"
                              value={row.title}
                              onChange={(e) => {
                                const next = [...boundaryRows];
                                next[idx] = { ...row, title: e.target.value };
                                setBoundaryRows(next);
                              }}
                              className="flex-1 min-w-[180px] px-3 py-1.5 rounded-lg bg-[var(--bg-subtle)]/75 hover:bg-[var(--bg-subtle)] focus:bg-[var(--bg-subtle)] text-[13px] font-medium text-[var(--ink-primary)] focus:outline-none"
                            />

                            <select
                              value={row.scope}
                              onChange={(e) => {
                                const next = [...boundaryRows];
                                next[idx] = { ...row, scope: e.target.value as ChapterScope };
                                setBoundaryRows(next);
                              }}
                              className="px-2.5 py-1.5 rounded-lg bg-[var(--bg-subtle)] text-[12px] font-medium text-[var(--ink-primary)] focus:outline-none cursor-pointer"
                            >
                              <option value="assigned">Assigned</option>
                              <option value="optional">Optional</option>
                              <option value="skipped">Skipped</option>
                            </select>

                            <div className="flex items-center gap-1 font-mono-tech text-[12px]">
                              <span className="text-[var(--ink-muted)]">p.</span>
                              <input
                                type="number"
                                min={1}
                                max={selectedBook.page_count}
                                value={row.start_page}
                                onChange={(e) => {
                                  const val = Number(e.target.value) || 1;
                                  const next = [...boundaryRows];
                                  next[idx] = { ...row, start_page: val };
                                  setBoundaryRows(next);
                                }}
                                className="w-14 px-1.5 py-1.5 rounded-lg bg-[var(--bg-subtle)] text-center text-[12px] text-[var(--ink-primary)] focus:outline-none"
                              />
                              <span className="text-[var(--ink-muted)]">–</span>
                              <input
                                type="number"
                                min={row.start_page}
                                max={selectedBook.page_count}
                                value={row.end_page}
                                onChange={(e) => {
                                  const val = Number(e.target.value) || row.start_page;
                                  const next = [...boundaryRows];
                                  next[idx] = { ...row, end_page: val };
                                  setBoundaryRows(next);
                                }}
                                className="w-14 px-1.5 py-1.5 rounded-lg bg-[var(--bg-subtle)] text-center text-[12px] text-[var(--ink-primary)] focus:outline-none"
                              />
                            </div>

                            <span
                              className="font-mono-tech text-[11.5px] w-10 text-right"
                              style={{
                                color: needsAutoSlice ? 'var(--accent)' : 'var(--ink-muted)',
                              }}
                              title={
                                needsAutoSlice
                                  ? 'Will auto-slice into 15–20p chunks during extraction'
                                  : ''
                              }
                            >
                              {pageSpan}p
                            </span>

                            <div className="flex items-center gap-1">
                              {expandableKids.length > 0 && (
                                <button
                                  type="button"
                                  onClick={() => handleExpandRow(idx)}
                                  className="inline-flex items-center gap-0.5 px-2.5 py-1 rounded-full bg-[var(--accent-soft)] text-[var(--accent)] text-[11.5px] font-medium cursor-pointer"
                                  title={`Expand into ${expandableKids.length} L2 subsections`}
                                >
                                  <ChevronRight className="w-3 h-3" />
                                  <span>+{expandableKids.length} L2</span>
                                </button>
                              )}

                              <button
                                type="button"
                                disabled={pageSpan < 2}
                                onClick={() => {
                                  setSplitTargetIdx(splitTargetIdx === idx ? null : idx);
                                  setSplitPage(Math.floor((row.start_page + row.end_page + 1) / 2));
                                }}
                                className="w-7 h-7 rounded-full inline-flex items-center justify-center text-[var(--ink-secondary)] hover:bg-[var(--bg-subtle)] hover:text-[var(--ink-primary)] disabled:opacity-30 cursor-pointer"
                                title="Split chapter at page"
                              >
                                <Scissors className="w-3.5 h-3.5" strokeWidth={1.6} />
                              </button>

                              <button
                                type="button"
                                disabled={idx >= boundaryRows.length - 1}
                                onClick={() => handleMergeWithNext(idx)}
                                className="w-7 h-7 rounded-full inline-flex items-center justify-center text-[var(--ink-secondary)] hover:bg-[var(--bg-subtle)] hover:text-[var(--ink-primary)] disabled:opacity-30 cursor-pointer"
                                title="Merge with next chapter"
                              >
                                <Merge className="w-3.5 h-3.5" strokeWidth={1.6} />
                              </button>

                              <button
                                type="button"
                                disabled={boundaryRows.length <= 1}
                                onClick={() => handleDeleteRow(idx)}
                                className="w-7 h-7 rounded-full inline-flex items-center justify-center text-[var(--ink-secondary)] hover:bg-[var(--status-danger-soft)] hover:text-[var(--status-danger)] disabled:opacity-30 cursor-pointer"
                                title="Remove row"
                              >
                                <Trash2 className="w-3.5 h-3.5" strokeWidth={1.6} />
                              </button>
                            </div>
                          </div>

                          {splitTargetIdx === idx && (
                            <div className="mt-2.5 ml-8 px-4 py-2.5 rounded-xl bg-[var(--bg-subtle)] flex flex-wrap items-center gap-3 text-[12.5px]">
                              <span className="text-[var(--ink-secondary)]">
                                Start second chapter at page:
                              </span>
                              <input
                                type="number"
                                min={row.start_page + 1}
                                max={row.end_page}
                                value={splitPage}
                                onChange={(e) => setSplitPage(Number(e.target.value))}
                                className="w-16 px-2 py-1 rounded-lg bg-[var(--bg-sheet)] font-mono-tech text-center text-[12.5px] focus:outline-none"
                              />
                              <button
                                type="button"
                                onClick={() => handleConfirmSplit(idx)}
                                className="btn-primary !py-1 !px-3 !text-[12px]"
                              >
                                Apply Split
                              </button>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>

                  <div className="pt-5 mt-2 border-t border-[var(--border-hairline)] flex flex-wrap items-center justify-between gap-3">
                    <button
                      type="button"
                      onClick={() => {
                        const last = boundaryRows[boundaryRows.length - 1];
                        const start = last
                          ? Math.min(selectedBook.page_count, last.end_page + 1)
                          : 1;
                        setBoundaryRows([
                          ...boundaryRows,
                          {
                            title: `Chapter ${boundaryRows.length + 1}`,
                            start_page: start,
                            end_page: selectedBook.page_count,
                            scope: 'assigned',
                          },
                        ]);
                      }}
                      className="inline-flex items-center gap-1.5 text-[13px] font-medium text-[var(--accent)] hover:underline underline-offset-4 cursor-pointer bg-transparent border-0 p-0"
                    >
                      <Plus className="w-3.5 h-3.5" strokeWidth={1.8} />
                      <span>Add chapter range</span>
                    </button>
                    <span className="text-[12px] text-[var(--ink-muted)]">
                      Chapters over 20 pages auto-slice into 15–20p extraction chunks
                    </span>
                  </div>
                </div>
              )}
            </section>
          </div>
        )}
      </div>
    </div>
  );
};
