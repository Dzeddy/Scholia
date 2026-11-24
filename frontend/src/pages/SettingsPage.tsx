import React, { useEffect, useState } from 'react';
import { Save } from 'lucide-react';
import { api } from '../lib/api';
import type {
  AgentCLIStatus,
  EffortLevel,
  ProviderName,
  SettingsResponse,
  StageRoute,
} from '../types/scholia';

const STAGE_META: { key: string; title: string; desc: string }[] = [
  {
    key: 'extraction_planning',
    title: 'Extraction & Lesson Planning',
    desc: 'Reads sliced chapter sources, synthesizes study notes, and links prerequisite DAG nodes.',
  },
  {
    key: 'socratic_dialogue',
    title: 'Socratic Dialogue',
    desc: 'Concise 2–4 sentence reasoning turns with clickable [p. N] citations.',
  },
  {
    key: 'oral_exam_grading',
    title: 'Oral Exam & Frontier Grading',
    desc: 'Understanding-first semantic grading, Core Bar gating, and continuous Frontier Probing.',
  },
  {
    key: 'note_enrichment',
    title: 'Post-Session Note Enrichment',
    desc: 'Appends confusions, breakthroughs, and discovered frontiers to persistent notes.md.',
  },
];

export const SettingsPage: React.FC<{ onRefreshGlobal?: () => void }> = ({ onRefreshGlobal }) => {
  const [agents, setAgents] = useState<AgentCLIStatus[]>([]);
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [routing, setRouting] = useState<Record<string, StageRoute>>({});
  const [vaultDir, setVaultDir] = useState('');
  const [maxSlice, setMaxSlice] = useState(20);
  const [saving, setSaving] = useState(false);
  const [savedNotice, setSavedNotice] = useState<string | null>(null);
  const [contractTab, setContractTab] = useState<'voice' | 'notes'>('voice');

  useEffect(() => {
    Promise.all([api.getAgentsStatus(), api.getSettings()]).then(([aRes, sRes]) => {
      setAgents(aRes.agents);
      setSettings(sRes);
      setRouting(sRes.routing);
      setVaultDir(sRes.vault_dir);
      setMaxSlice(sRes.max_pdf_pages_per_slice);
    });
  }, []);

  const updateStage = (stageKey: string, patch: Partial<StageRoute>) => {
    setRouting((prev) => {
      const current = prev[stageKey] || { provider: 'claude', model: 'opus', effort: 'high' };
      const next: StageRoute = { ...current, ...patch };
      if (patch.provider) {
        const meta = agents.find((a) => a.provider === patch.provider);
        if (
          meta &&
          meta.recommended_models.length > 0 &&
          !meta.recommended_models.includes(next.model)
        ) {
          next.model = meta.recommended_models[0];
        }
      }
      return { ...prev, [stageKey]: next };
    });
  };

  const handleSave = async () => {
    setSaving(true);
    setSavedNotice(null);
    try {
      const updated = await api.updateSettings({
        vault_dir: vaultDir,
        routing,
        max_pdf_pages_per_slice: maxSlice,
      });
      setSettings(updated);
      setSavedNotice('Configuration saved to config.json.');
      onRefreshGlobal?.();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-[1140px] mx-auto px-6 sm:px-8 pt-10 pb-20 space-y-8">
        {/* Confident Page Header */}
        <header className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-[36px] sm:text-[40px] font-medium tracking-[-0.03em] leading-[1.1] text-[var(--ink-primary)] m-0">
              Settings
            </h1>
            <p className="text-[15px] text-[var(--ink-secondary)] mt-2 mb-0">
              Local CLI agent routing, vault path, and pedagogical contracts
            </p>
          </div>

          <button
            type="button"
            disabled={saving}
            onClick={() => void handleSave()}
            className="btn-primary"
          >
            <Save className="w-3.5 h-3.5" strokeWidth={1.8} />
            <span>{saving ? 'Saving...' : 'Save Configuration'}</span>
          </button>
        </header>

        {savedNotice && (
          <div className="px-4 py-3 rounded-xl bg-[var(--status-forest-soft)] text-[var(--status-forest)] text-[13px]">
            {savedNotice}
          </div>
        )}

        {/* Section 1: Detected Local Backends (Single Clean Gallery Sheet) */}
        <section className="gallery-sheet p-7 sm:p-8">
          <div className="mb-5">
            <h2 className="text-[20px] font-semibold tracking-[-0.02em] m-0 text-[var(--ink-primary)]">
              Detected Local Backends
            </h2>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-7 pt-5 border-t border-[var(--border-hairline)]">
            {agents.map((ag) => (
              <div key={ag.provider} className="space-y-1.5">
                <div className="inline-flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-[0.06em] text-[var(--ink-muted)]">
                  <span
                    className="w-1.5 h-1.5 rounded-full"
                    style={{
                      backgroundColor: ag.available
                        ? 'var(--status-forest)'
                        : 'var(--status-muted)',
                    }}
                  />
                  <span>{ag.available ? 'Ready' : 'Offline'}</span>
                </div>

                <div className="text-[14.5px] font-semibold tracking-[-0.01em] text-[var(--ink-primary)] leading-snug">
                  {ag.display_name}
                </div>

                {ag.version && (
                  <div className="font-mono-tech text-[11.5px] text-[var(--ink-secondary)]">
                    {ag.version}
                  </div>
                )}
                {ag.binary_path && (
                  <div
                    className="font-mono-tech text-[11px] text-[var(--ink-muted)] truncate"
                    title={ag.binary_path}
                  >
                    {ag.binary_path}
                  </div>
                )}
                {!ag.available && (
                  <p className="text-[12px] text-[var(--ink-muted)] m-0 pt-1 leading-snug">
                    {ag.setup_hint}
                  </p>
                )}
              </div>
            ))}
          </div>
        </section>

        {/* Section 2: Per-Stage Model & Effort Routing */}
        <section className="gallery-sheet p-7 sm:p-8">
          <div className="mb-2">
            <h2 className="text-[20px] font-semibold tracking-[-0.02em] m-0 text-[var(--ink-primary)]">
              Stage Routing
            </h2>
            <p className="text-[13.5px] text-[var(--ink-secondary)] mt-1 mb-0">
              Assign local CLI backends, models, and reasoning effort per pedagogical stage.
            </p>
          </div>

          <div className="mt-5 border-t border-[var(--border-hairline)] divide-y divide-[var(--border-hairline)]">
            {STAGE_META.map((stage) => {
              const current = routing[stage.key] || {
                provider: 'claude' as ProviderName,
                model: 'opus',
                effort: 'high' as EffortLevel,
              };
              const providerInfo = agents.find((a) => a.provider === current.provider);
              const models = providerInfo?.recommended_models || [current.model];
              const efforts = providerInfo?.supported_efforts || ['low', 'medium', 'high'];

              return (
                <div
                  key={stage.key}
                  className="py-5 grid grid-cols-1 lg:grid-cols-12 gap-5 items-center"
                >
                  <div className="lg:col-span-5">
                    <div className="text-[14.5px] font-medium text-[var(--ink-primary)]">
                      {stage.title}
                    </div>
                    <div className="text-[13px] text-[var(--ink-secondary)] mt-0.5 leading-snug">
                      {stage.desc}
                    </div>
                  </div>

                  <div className="lg:col-span-7 grid grid-cols-1 sm:grid-cols-3 gap-3">
                    <label className="flex flex-col gap-1.5">
                      <span className="meta-label">Backend</span>
                      <select
                        value={current.provider}
                        onChange={(e) =>
                          updateStage(stage.key, { provider: e.target.value as ProviderName })
                        }
                        className="scholia-select px-3 py-2 rounded-xl bg-[var(--bg-subtle)] text-[13px] font-medium text-[var(--ink-primary)] focus:outline-none cursor-pointer"
                      >
                        <option value="agy">agy (Antigravity)</option>
                        <option value="claude">claude (Claude Code)</option>
                        <option value="codex">codex (Codex CLI)</option>
                        <option value="demo">demo (Offline)</option>
                      </select>
                    </label>

                    <label className="flex flex-col gap-1.5">
                      <span className="meta-label">Model</span>
                      <select
                        value={current.model}
                        onChange={(e) => updateStage(stage.key, { model: e.target.value })}
                        className="scholia-select px-3 py-2 rounded-xl bg-[var(--bg-subtle)] text-[13px] font-medium text-[var(--ink-primary)] focus:outline-none cursor-pointer"
                      >
                        {!models.includes(current.model) && (
                          <option value={current.model}>{current.model}</option>
                        )}
                        {models.map((m) => (
                          <option key={m} value={m}>
                            {m}
                          </option>
                        ))}
                      </select>
                    </label>

                    <label className="flex flex-col gap-1.5">
                      <span className="meta-label">Effort</span>
                      <select
                        value={current.effort}
                        onChange={(e) =>
                          updateStage(stage.key, { effort: e.target.value as EffortLevel })
                        }
                        className="scholia-select px-3 py-2 rounded-xl bg-[var(--bg-subtle)] text-[13px] font-medium text-[var(--ink-primary)] capitalize focus:outline-none cursor-pointer"
                      >
                        {efforts.map((eff) => (
                          <option key={eff} value={eff}>
                            {eff}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        {/* Section 3: Vault & Pedagogical Contracts */}
        <section className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
          <div className="lg:col-span-5 gallery-sheet p-7 sm:p-8 space-y-6">
            <h2 className="text-[20px] font-semibold tracking-[-0.02em] m-0 text-[var(--ink-primary)]">
              Vault & Runtime
            </h2>

            <div className="space-y-4">
              <label className="flex flex-col gap-1.5">
                <span className="meta-label">Vault Path</span>
                <input
                  type="text"
                  value={vaultDir}
                  onChange={(e) => setVaultDir(e.target.value)}
                  className="px-3.5 py-2.5 rounded-xl bg-[var(--bg-subtle)] font-mono-tech text-[12.5px] text-[var(--ink-primary)] focus:outline-none"
                />
              </label>

              <label className="flex flex-col gap-1.5">
                <span className="meta-label">Max PDF Slice (Pages)</span>
                <input
                  type="number"
                  min={5}
                  max={30}
                  value={maxSlice}
                  onChange={(e) => setMaxSlice(Number(e.target.value) || 20)}
                  className="w-28 px-3.5 py-2 rounded-xl bg-[var(--bg-subtle)] font-mono-tech text-[13px] text-[var(--ink-primary)] focus:outline-none"
                />
              </label>
            </div>

            <div className="pt-5 border-t border-[var(--border-hairline)] space-y-1.5">
              <div className="meta-label">Companion FastMCP Server</div>
              <p className="text-[13px] text-[var(--ink-secondary)] leading-relaxed m-0">
                Exposes{' '}
                <code className="font-mono-tech text-[12px]">list_books</code>,{' '}
                <code className="font-mono-tech text-[12px]">get_chapter_notes</code>,{' '}
                <code className="font-mono-tech text-[12px]">get_lesson_plan</code>,{' '}
                <code className="font-mono-tech text-[12px]">get_learner_memory</code>,{' '}
                <code className="font-mono-tech text-[12px]">log_confusion_or_frontier</code>,{' '}
                <code className="font-mono-tech text-[12px]">record_concept_mastery</code>,{' '}
                <code className="font-mono-tech text-[12px]">get_due_reviews</code>, and{' '}
                <code className="font-mono-tech text-[12px]">query_topic_graph</code>.
              </p>
            </div>
          </div>

          <div className="lg:col-span-7 gallery-sheet p-7 sm:p-8">
            <div className="pb-4 border-b border-[var(--border-hairline)] flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-[20px] font-semibold tracking-[-0.02em] m-0 text-[var(--ink-primary)]">
                Pedagogical Contracts
              </h2>

              <div className="inline-flex items-center gap-0.5 p-0.5 rounded-full bg-[var(--bg-subtle)]">
                <button
                  type="button"
                  onClick={() => setContractTab('voice')}
                  className={`px-3 py-1 rounded-full text-[12px] font-medium transition-colors cursor-pointer ${
                    contractTab === 'voice'
                      ? 'bg-[var(--cta-bg)] text-[var(--cta-ink)]'
                      : 'text-[var(--ink-secondary)] hover:text-[var(--ink-primary)]'
                  }`}
                >
                  Voice Rules
                </button>
                <button
                  type="button"
                  onClick={() => setContractTab('notes')}
                  className={`px-3 py-1 rounded-full text-[12px] font-medium transition-colors cursor-pointer ${
                    contractTab === 'notes'
                      ? 'bg-[var(--cta-bg)] text-[var(--cta-ink)]'
                      : 'text-[var(--ink-secondary)] hover:text-[var(--ink-primary)]'
                  }`}
                >
                  Notes Contract
                </button>
              </div>
            </div>

            <pre className="pt-5 m-0 text-[12.5px] leading-relaxed font-mono-tech text-[var(--ink-secondary)] whitespace-pre-wrap max-h-[300px] overflow-y-auto">
              {contractTab === 'voice'
                ? settings?.voice_rules_preview || ''
                : settings?.study_notes_contract_preview || ''}
            </pre>
          </div>
        </section>
      </div>
    </div>
  );
};
