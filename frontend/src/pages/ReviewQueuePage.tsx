import React, { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { CheckCircle2, RefreshCw } from 'lucide-react';
import { api } from '../lib/api';
import { StudyComposer } from '../components/StudyComposer';
import type {
  ReviewAnswerResponse,
  ReviewCard,
  ReviewTopicSummary,
  WorkspaceSummary,
} from '../types/scholia';

export const ReviewQueuePage: React.FC<{
  workspace: WorkspaceSummary | null;
  onRefreshGlobal?: () => void;
}> = ({ workspace, onRefreshGlobal }) => {
  const [searchParams, setSearchParams] = useSearchParams();
  const [topics, setTopics] = useState<ReviewTopicSummary[]>([]);
  const [totalUniqueDue, setTotalUniqueDue] = useState<number>(0);
  const [selectedTopic, setSelectedTopic] = useState<string>(searchParams.get('topic') || '');
  const [cards, setCards] = useState<ReviewCard[]>([]);
  const [activeIndex, setActiveIndex] = useState(0);
  const [answer, setAnswer] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [lastResult, setLastResult] = useState<ReviewAnswerResponse | null>(null);
  const [loading, setLoading] = useState(true);

  const loadQueue = async (topicFilter: string) => {
    setLoading(true);
    setLastResult(null);
    setAnswer('');
    try {
      const ws = workspace?.slug;
      const [tRes, cRes] = await Promise.all([
        api.getReviewTopics(ws),
        api.getDueReviews(topicFilter || undefined, false, ws),
      ]);
      setTopics(tRes.topics);
      setTotalUniqueDue(tRes.total_unique_due ?? cRes.cards.length);
      setCards(cRes.cards);
      setActiveIndex(0);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadQueue(selectedTopic);
  }, [selectedTopic, workspace?.slug]);

  const selectTopic = (topic: string) => {
    setSelectedTopic(topic);
    if (topic) setSearchParams({ topic });
    else setSearchParams({});
  };

  const currentCard = cards[activeIndex] || null;

  const submitAnswer = async (selfRating?: number) => {
    if (!currentCard || submitting) return;
    if (!selfRating && !answer.trim()) return;
    setSubmitting(true);
    try {
      const res = await api.answerReview(currentCard.concept.id, {
        answer: answer.trim() || `Self-assessed rating: ${selfRating}`,
        probe_question: currentCard.probe_question,
        self_rating: selfRating,
      });
      setLastResult(res);
      onRefreshGlobal?.();
    } finally {
      setSubmitting(false);
    }
  };

  const advanceNext = async () => {
    await loadQueue(selectedTopic);
  };

  const totalDue = totalUniqueDue;

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-[1180px] mx-auto px-6 sm:px-8 pt-10 pb-20">
        {/* Confident Page Header (Zero Kicker Clutter) */}
        <header className="pb-8 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-[36px] sm:text-[40px] font-medium tracking-[-0.03em] leading-[1.1] text-[var(--ink-primary)] m-0">
              Review Queue
            </h1>
            <p className="text-[15px] text-[var(--ink-secondary)] mt-2 mb-0 tabular-nums">
              {totalDue} due across {topics.length} topic {topics.length === 1 ? 'area' : 'areas'}
            </p>
          </div>
        </header>

        <div className="flex flex-col lg:flex-row gap-10 items-start">
          {/* Left Rail: Borderless Topic List */}
          <aside className="w-full lg:w-[300px] shrink-0 space-y-1">
            <button
              type="button"
              onClick={() => selectTopic('')}
              className={`w-full text-left px-4 py-3 rounded-xl flex items-center justify-between transition-colors cursor-pointer ${
                selectedTopic === ''
                  ? 'bg-[var(--bg-subtle)]'
                  : 'hover:bg-[var(--bg-subtle)]/55'
              }`}
            >
              <div>
                <div className="text-[14.5px] font-medium text-[var(--ink-primary)]">
                  All Topics
                </div>
                <div className="text-[12px] text-[var(--ink-muted)] mt-0.5">
                  Combined active deck
                </div>
              </div>
              <span className="inline-flex items-center gap-1.5 text-[12.5px] font-medium tabular-nums text-[var(--ink-secondary)]">
                {totalDue > 0 && (
                  <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent)]" />
                )}
                <span>{totalDue}</span>
              </span>
            </button>

            {topics.map((t) => {
              const active = selectedTopic === t.topic;
              return (
                <button
                  key={t.topic}
                  type="button"
                  onClick={() => selectTopic(t.topic)}
                  className={`w-full text-left px-4 py-3 rounded-xl flex items-center justify-between transition-colors cursor-pointer ${
                    active
                      ? 'bg-[var(--bg-subtle)]'
                      : 'hover:bg-[var(--bg-subtle)]/55'
                  }`}
                >
                  <div className="min-w-0 pr-3">
                    <div className="text-[14.5px] font-medium text-[var(--ink-primary)] truncate">
                      {t.topic}
                    </div>
                    <div className="text-[12px] text-[var(--ink-muted)] mt-0.5 tabular-nums">
                      {t.total_count} enrolled · avg {t.average_stability_days}d
                    </div>
                  </div>
                  <span className="inline-flex items-center gap-1.5 text-[12.5px] font-medium tabular-nums text-[var(--ink-secondary)] shrink-0">
                    {t.due_count > 0 && (
                      <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent)]" />
                    )}
                    <span>{t.due_count}</span>
                  </span>
                </button>
              );
            })}

            {cards.length > 0 && (
              <div className="pt-6">
                <div className="meta-label px-4 mb-2">
                  Due Queue ({cards.length})
                </div>
                <div className="divide-y divide-[var(--border-hairline)]">
                  {cards.map((card, idx) => (
                    <button
                      key={card.concept.id}
                      type="button"
                      onClick={() => {
                        setActiveIndex(idx);
                        setLastResult(null);
                        setAnswer('');
                      }}
                      className={`w-full text-left px-4 py-2.5 flex items-center justify-between gap-2 text-[13px] transition-colors cursor-pointer ${
                        idx === activeIndex
                          ? 'text-[var(--accent)] font-medium'
                          : 'text-[var(--ink-secondary)] hover:text-[var(--ink-primary)]'
                      }`}
                    >
                      <span className="truncate">{card.concept.name}</span>
                      <span className="font-mono-tech text-[11.5px] text-[var(--ink-muted)] shrink-0">
                        {Math.round(card.retrievability * 100)}%
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </aside>

          {/* Right Main Area: Elevated Gallery Sheet Understanding Probe */}
          <section className="flex-1 min-w-0 w-full">
            {loading ? (
              <div className="py-16 text-center text-[13.5px] text-[var(--ink-muted)]">
                Loading understanding probes...
              </div>
            ) : !currentCard ? (
              <div className="gallery-sheet p-12 text-center">
                <CheckCircle2
                  className="w-7 h-7 mx-auto mb-3 text-[var(--status-forest)]"
                  strokeWidth={1.6}
                />
                <h2 className="text-[22px] font-semibold tracking-[-0.02em] m-0 mb-2">
                  All caught up
                </h2>
                <p className="text-[14.5px] text-[var(--ink-secondary)] max-w-md mx-auto m-0">
                  Every enrolled concept in {selectedTopic || 'your vault'} remains above its FSRS target retention threshold.
                </p>
              </div>
            ) : (
              <div className="gallery-sheet p-7 sm:p-9">
                {/* Provenance & Rhythm-Style FSRS Telemetry */}
                <div className="pb-6 border-b border-[var(--border-hairline)] flex flex-wrap items-baseline justify-between gap-4">
                  <div className="text-[13.5px] text-[var(--ink-secondary)]">
                    <span className="font-medium text-[var(--ink-primary)]">
                      {currentCard.book_title}
                    </span>
                    <span className="mx-2 text-[var(--ink-muted)]">/</span>
                    <span>{currentCard.chapter_title}</span>
                  </div>

                  <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-[12.5px] tabular-nums">
                    <span className="inline-flex items-baseline gap-1.5">
                      <span className="meta-label">Stability</span>
                      <span className="font-mono-tech text-[var(--ink-primary)]">
                        {currentCard.concept.fsrs_stability.toFixed(1)}d
                      </span>
                    </span>
                    <span className="inline-flex items-baseline gap-1.5">
                      <span className="meta-label">Retrievability</span>
                      <span className="font-mono-tech text-[var(--ink-primary)]">
                        {Math.round(currentCard.retrievability * 100)}%
                      </span>
                    </span>
                    <span className="inline-flex items-center gap-1.5 text-[var(--accent)] font-medium">
                      <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent)]" />
                      <span>
                        {currentCard.days_overdue > 0
                          ? `${currentCard.days_overdue}d overdue`
                          : 'Due now'}
                      </span>
                    </span>
                  </div>
                </div>

                {/* Concept & Understanding Probe */}
                <div className="pt-6">
                  <div className="flex flex-wrap items-center gap-2 text-[12.5px] text-[var(--ink-muted)] mb-2">
                    <span>
                      Card {activeIndex + 1} of {cards.length}
                    </span>
                    {currentCard.concept.topic_areas.length > 0 && (
                      <>
                        <span>·</span>
                        <span>{currentCard.concept.topic_areas.join(', ')}</span>
                      </>
                    )}
                  </div>

                  <h2 className="text-[26px] font-semibold tracking-[-0.025em] text-[var(--ink-primary)] m-0 mb-5">
                    {currentCard.concept.name}
                  </h2>

                  <div className="mb-6">
                    <div className="meta-label mb-2">Understanding Probe</div>
                    <p className="font-serif-editorial text-[19px] leading-relaxed text-[var(--ink-primary)] m-0">
                      {currentCard.probe_question}
                    </p>
                  </div>

                  {currentCard.prior_frontiers.length > 0 && (
                    <div className="mb-6 px-4 py-3 rounded-xl bg-[var(--accent-soft)] text-[13px] text-[var(--ink-primary)]">
                      <span className="meta-label !text-[var(--accent)] mr-2.5">
                        Prior Frontier
                      </span>
                      <span>{currentCard.prior_frontiers[0]}</span>
                    </div>
                  )}

                  {!lastResult ? (
                    <div className="space-y-4">
                      <StudyComposer
                        value={answer}
                        onChange={setAnswer}
                        onSubmit={() => void submitAnswer()}
                        disabled={submitting}
                        rows={4}
                        submitOnEnter={false}
                        submitLabel={submitting ? 'Grading...' : 'Evaluate'}
                        placeholder="Reconstruct the mechanism, equation, or boundary condition in your own words..."
                      />

                      <div className="flex flex-wrap items-center gap-2 pt-1">
                        <span className="meta-label mr-2">Manual Rating</span>
                        {[
                          { r: 1, label: 'Again' },
                          { r: 2, label: 'Hard' },
                          { r: 3, label: 'Good' },
                          { r: 4, label: 'Easy' },
                        ].map((opt) => (
                          <button
                            key={opt.r}
                            type="button"
                            disabled={submitting}
                            onClick={() => void submitAnswer(opt.r)}
                            className="btn-secondary !py-1 !px-3.5 !text-[12px]"
                          >
                            {opt.label}
                          </button>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <div className="pt-5 border-t border-[var(--border-hairline)] space-y-4">
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <span className="inline-flex items-center gap-2 text-[14px] font-semibold">
                          <span
                            className="w-2 h-2 rounded-full"
                            style={{
                              backgroundColor: lastResult.passed
                                ? 'var(--status-forest)'
                                : 'var(--status-danger)',
                            }}
                          />
                          <span>FSRS Rating: {lastResult.rating_label}</span>
                        </span>
                        <span className="text-[13px] text-[var(--ink-secondary)] tabular-nums">
                          Next review in <strong>{lastResult.scheduled_days}d</strong> · Stability{' '}
                          {lastResult.new_stability.toFixed(1)}d
                        </span>
                      </div>

                      <p className="text-[14.5px] leading-relaxed text-[var(--ink-primary)] m-0">
                        {lastResult.feedback}
                      </p>

                      <div className="pt-2 flex justify-end">
                        <button
                          type="button"
                          onClick={() => void advanceNext()}
                          className="btn-primary"
                        >
                          <RefreshCw className="w-3.5 h-3.5" strokeWidth={1.8} />
                          <span>Next Concept</span>
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
};
