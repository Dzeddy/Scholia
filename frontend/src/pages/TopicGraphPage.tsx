import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Plus, Trash2, GitMerge, ArrowUpRight, Layers } from 'lucide-react';
import { api } from '../lib/api';
import type { ConceptRecord, GraphResponse, WorkspaceSummary } from '../types/scholia';

interface PositionedNode {
  concept: ConceptRecord;
  x: number;
  y: number;
  width: number;
  height: number;
  layer: number;
}

const MASTERY_STYLE: Record<string, { dot: string; label: string }> = {
  mastered: { dot: 'var(--status-forest)', label: 'Mastered' },
  core_passed: { dot: 'var(--status-forest)', label: 'Core Passed' },
  learning: { dot: 'var(--accent)', label: 'In Study' },
  needs_review: { dot: 'var(--accent)', label: 'Needs Review' },
  unseen: { dot: 'var(--status-muted)', label: 'Unseen' },
};

function layoutDAG(
  nodes: ConceptRecord[],
  edges: { parent_id: string; child_id: string }[]
): { positioned: PositionedNode[]; width: number; height: number } {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const parentsMap = new Map<string, string[]>();
  for (const n of nodes) parentsMap.set(n.id, []);
  for (const e of edges) {
    if (byId.has(e.parent_id) && byId.has(e.child_id)) {
      parentsMap.get(e.child_id)!.push(e.parent_id);
    }
  }

  const memo = new Map<string, number>();
  const visiting = new Set<string>();
  const depthOf = (id: string): number => {
    if (memo.has(id)) return memo.get(id)!;
    if (visiting.has(id)) return 0;
    visiting.add(id);
    const ps = parentsMap.get(id) || [];
    const d = ps.length === 0 ? 0 : Math.max(...ps.map((p) => depthOf(p) + 1));
    visiting.delete(id);
    memo.set(id, d);
    return d;
  };

  const columns = new Map<number, ConceptRecord[]>();
  for (const n of nodes) {
    const l = depthOf(n.id);
    if (!columns.has(l)) columns.set(l, []);
    columns.get(l)!.push(n);
  }

  const sortedLayers = Array.from(columns.keys()).sort((a, b) => a - b);
  const nodeW = 212;
  const nodeH = 72;
  const colGap = 246;
  const rowGap = 96;
  const padX = 28;
  const padY = 40;

  let maxRows = 1;
  for (const l of sortedLayers) {
    const arr = columns.get(l)!;
    arr.sort((a, b) => {
      const ta = a.topic_areas[0] || '';
      const tb = b.topic_areas[0] || '';
      if (ta !== tb) return ta.localeCompare(tb);
      return a.name.localeCompare(b.name);
    });
    maxRows = Math.max(maxRows, arr.length);
  }

  const totalH = Math.max(520, padY * 2 + (maxRows - 1) * rowGap + nodeH);
  const totalW = Math.max(820, padX * 2 + Math.max(1, sortedLayers.length - 1) * colGap + nodeW);

  const positioned: PositionedNode[] = [];
  for (const l of sortedLayers) {
    const arr = columns.get(l)!;
    const colHeight = (arr.length - 1) * rowGap + nodeH;
    const startY = Math.max(padY, (totalH - colHeight) / 2);
    arr.forEach((concept, idx) => {
      positioned.push({
        concept,
        x: padX + l * colGap,
        y: startY + idx * rowGap,
        width: nodeW,
        height: nodeH,
        layer: l,
      });
    });
  }

  return { positioned, width: totalW, height: totalH };
}

export const TopicGraphPage: React.FC<{ workspace: WorkspaceSummary | null }> = ({ workspace }) => {
  const navigate = useNavigate();
  const [graph, setGraph] = useState<GraphResponse | null>(null);
  const [topicFilter, setTopicFilter] = useState<string>('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [newParentId, setNewParentId] = useState<string>('');
  const [mergeTargetId, setMergeTargetId] = useState<string>('');
  const [notice, setNotice] = useState<string | null>(null);

  const loadGraph = async (topic: string) => {
    const data = await api.getGraph(topic || undefined, workspace?.slug);
    setGraph(data);
    setSelectedId((prev) => {
      if (prev && data.nodes.some((n) => n.id === prev)) return prev;
      const dp = data.nodes.find((n) => n.name === 'Dynamic Programming');
      if (dp) return dp.id;
      const richest = [...data.nodes].sort((a, b) => b.parent_ids.length - a.parent_ids.length)[0];
      return richest ? richest.id : data.nodes[0]?.id || null;
    });
  };

  useEffect(() => {
    setTopicFilter('');
  }, [workspace?.slug]);

  useEffect(() => {
    void loadGraph(topicFilter);
  }, [topicFilter, workspace?.slug]);

  const layout = useMemo(() => {
    if (!graph) return { positioned: [], width: 920, height: 540 };
    return layoutDAG(graph.nodes, graph.edges);
  }, [graph]);

  const posMap = useMemo(
    () => new Map(layout.positioned.map((p) => [p.concept.id, p])),
    [layout.positioned]
  );

  const selectedNode = graph?.nodes.find((n) => n.id === selectedId) || null;
  const nodesById = useMemo(
    () => new Map((graph?.nodes || []).map((n) => [n.id, n])),
    [graph]
  );

  const handleAddParent = async () => {
    if (!selectedNode || !newParentId) return;
    setNotice(null);
    try {
      await api.addGraphEdge(newParentId, selectedNode.id);
      setNewParentId('');
      await loadGraph(topicFilter);
      setNotice('Prerequisite edge added.');
    } catch (err) {
      setNotice(err instanceof Error ? err.message : 'Unable to add edge.');
    }
  };

  const handleDeleteEdge = async (parentId: string, childId: string) => {
    setNotice(null);
    await api.deleteGraphEdge(parentId, childId);
    await loadGraph(topicFilter);
  };

  const handleMerge = async () => {
    if (!selectedNode || !mergeTargetId) return;
    await api.mergeConcepts(selectedNode.id, mergeTargetId);
    setMergeTargetId('');
    setSelectedId(mergeTargetId);
    await loadGraph(topicFilter);
    setNotice('Concepts merged and edges preserved.');
  };

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
      {/* Clean Header Bar (Zero Uppercase Kicker) */}
      <div className="shrink-0 px-6 lg:px-8 pt-6 pb-4 flex flex-wrap items-center justify-between gap-4 border-b border-[var(--border-hairline)] bg-[var(--bg-canvas)]">
        <h1 className="text-[28px] font-medium tracking-[-0.03em] leading-tight text-[var(--ink-primary)] m-0">
          Concept Graph
        </h1>

        {/* Sleek Pill Topic Filters */}
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={() => setTopicFilter('')}
            className={`px-3.5 py-1.5 rounded-full text-[12.5px] font-medium transition-colors cursor-pointer tabular-nums ${
              topicFilter === ''
                ? 'bg-[var(--cta-bg)] text-[var(--cta-ink)]'
                : 'bg-[var(--bg-subtle)] text-[var(--ink-secondary)] hover:text-[var(--ink-primary)]'
            }`}
          >
            All ({graph?.nodes.length || 0})
          </button>
          {(graph?.topics || []).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTopicFilter(t)}
              className={`px-3.5 py-1.5 rounded-full text-[12.5px] font-medium transition-colors cursor-pointer ${
                topicFilter === t
                  ? 'bg-[var(--cta-bg)] text-[var(--cta-ink)]'
                  : 'bg-[var(--bg-subtle)] text-[var(--ink-secondary)] hover:text-[var(--ink-primary)]'
              }`}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      {/* Antigravity-Inspired Open Spatial Canvas + Floating Gallery Inspector */}
      <div className="flex-1 flex min-h-0 overflow-hidden dot-grid-bg">
        {/* Interactive SVG DAG Canvas */}
        <div className="flex-1 overflow-auto relative">
          {/* Floating Minimal Legend Pill */}
          <div className="sticky top-4 left-6 z-10 inline-flex flex-wrap items-center gap-4 px-4 py-1.5 ml-6 mt-4 rounded-full bg-[var(--bg-sheet)]/90 backdrop-blur-md border border-[var(--border-sheet)] shadow-xs text-[12px] text-[var(--ink-secondary)]">
            <span className="inline-flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--status-forest)]" />
              Mastered / Cleared
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent)]" />
              Active / Frontier
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--status-muted)]" />
              Unseen
            </span>
            <span className="text-[var(--ink-muted)]">· Prerequisite → Dependent</span>
          </div>

          <svg
            width={layout.width}
            height={layout.height}
            viewBox={`0 0 ${layout.width} ${layout.height}`}
            className="block"
          >
            <defs>
              <filter id="node-shadow" x="-10%" y="-15%" width="120%" height="145%">
                <feDropShadow
                  dx="0"
                  dy="4"
                  stdDeviation="6"
                  floodColor="#141413"
                  floodOpacity="0.06"
                />
              </filter>
              <marker
                id="arrow-default"
                viewBox="0 0 10 10"
                refX="8.5"
                refY="5"
                markerWidth="6"
                markerHeight="6"
                orient="auto"
              >
                <path d="M 0 1.4 L 8.5 5 L 0 8.6 z" fill="var(--ink-muted)" opacity="0.55" />
              </marker>
              <marker
                id="arrow-active"
                viewBox="0 0 10 10"
                refX="8.5"
                refY="5"
                markerWidth="6.5"
                markerHeight="6.5"
                orient="auto"
              >
                <path d="M 0 1.4 L 8.5 5 L 0 8.6 z" fill="var(--accent)" />
              </marker>
            </defs>

            {/* Smooth Bezier Prerequisite Connectors */}
            {(graph?.edges || []).map((edge) => {
              const p = posMap.get(edge.parent_id);
              const c = posMap.get(edge.child_id);
              if (!p || !c) return null;

              const x1 = p.x + p.width;
              const y1 = p.y + p.height / 2;
              const x2 = c.x - 5;
              const y2 = c.y + c.height / 2;
              const dx = Math.max(58, (x2 - x1) * 0.48);
              const pathD = `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;

              const isLinked = selectedId === edge.child_id || selectedId === edge.parent_id;
              const stroke = isLinked ? 'var(--accent)' : 'var(--ink-muted)';
              const marker = isLinked ? 'url(#arrow-active)' : 'url(#arrow-default)';

              return (
                <path
                  key={`${edge.parent_id}-${edge.child_id}`}
                  d={pathD}
                  fill="none"
                  stroke={stroke}
                  strokeWidth={isLinked ? 1.85 : 1.15}
                  opacity={selectedId ? (isLinked ? 0.95 : 0.25) : 0.5}
                  markerEnd={marker}
                />
              );
            })}

            {/* Pure Floating Rounded-XL Concept Nodes (Zero Left Stripe Bars) */}
            {layout.positioned.map(({ concept, x, y, width, height }) => {
              const st = MASTERY_STYLE[concept.mastery_state] || MASTERY_STYLE.unseen;
              const isSelected = selectedId === concept.id;
              const isNeighbor =
                selectedNode &&
                (selectedNode.parent_ids.includes(concept.id) ||
                  selectedNode.child_ids.includes(concept.id));
              const multiParent = concept.parent_ids.length >= 2;

              const rawTopic = concept.topic_areas[0] || 'General';
              const shortMap: Record<string, string> = {
                'Distributed Systems': 'Dist. Systems',
                'ML Systems & Parallelism': 'ML Systems',
                'GPU Kernels & CUDA': 'GPU Kernels',
                'Performance Engineering': 'Perf. Engineering',
                'Fleet Reliability': 'Fleet Reliability',
                'TPU Architecture': 'TPU Architecture',
              };
              const shortTopic =
                shortMap[rawTopic] ||
                (rawTopic.length > 18 ? `${rawTopic.slice(0, 17)}…` : rawTopic);
              const subMeta = multiParent
                ? `${shortTopic} · ${concept.parent_ids.length} prereqs`
                : shortTopic;

              return (
                <g
                  key={concept.id}
                  transform={`translate(${x}, ${y})`}
                  onClick={() => setSelectedId(concept.id)}
                  style={{ cursor: 'pointer' }}
                  opacity={selectedId && !isSelected && !isNeighbor ? 0.6 : 1}
                >
                  <rect
                    width={width}
                    height={height}
                    rx={12}
                    fill="var(--bg-sheet)"
                    stroke={
                      isSelected
                        ? 'var(--ink-primary)'
                        : isNeighbor
                          ? 'var(--border-strong)'
                          : 'var(--border-sheet)'
                    }
                    strokeWidth={isSelected ? 1.65 : 1}
                    filter="url(#node-shadow)"
                  />

                  {/* Crisp 6px Status Dot */}
                  <circle
                    cx={18}
                    cy={26}
                    r={3.2}
                    fill={isSelected ? 'var(--accent)' : st.dot}
                  />

                  {/* Crisp Tight-Tracked Title */}
                  <text
                    x={30}
                    y={30}
                    fill="var(--ink-primary)"
                    style={{
                      fontFamily: 'var(--font-sans)',
                      fontSize: '12.5px',
                      fontWeight: 600,
                      letterSpacing: '-0.015em',
                    }}
                  >
                    {concept.name.length > 23 ? `${concept.name.slice(0, 22)}…` : concept.name}
                  </text>

                  {/* Quiet Metadata */}
                  <text
                    x={30}
                    y={50}
                    fill="var(--ink-muted)"
                    style={{
                      fontFamily: 'var(--font-sans)',
                      fontSize: '11px',
                      fontWeight: 400,
                    }}
                  >
                    {subMeta}
                  </text>

                  {concept.fsrs_stability > 0 && (
                    <text
                      x={width - 14}
                      y={52}
                      textAnchor="end"
                      fill="var(--ink-muted)"
                      style={{
                        fontFamily: 'var(--font-mono)',
                        fontSize: '10.5px',
                      }}
                    >
                      {concept.fsrs_stability.toFixed(0)}d
                    </text>
                  )}
                </g>
              );
            })}
          </svg>
        </div>

        {/* Elevated Gallery Sheet Inspector (Right Panel) */}
        <aside className="w-[360px] shrink-0 m-4 ml-0 gallery-sheet overflow-y-auto p-7">
          {selectedNode ? (
            <div className="space-y-6">
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <span
                    className="w-1.5 h-1.5 rounded-full"
                    style={{
                      backgroundColor: (
                        MASTERY_STYLE[selectedNode.mastery_state] || MASTERY_STYLE.unseen
                      ).dot,
                    }}
                  />
                  <span className="meta-label">
                    {(MASTERY_STYLE[selectedNode.mastery_state] || MASTERY_STYLE.unseen).label}
                  </span>
                </div>

                <h2 className="text-[22px] font-semibold tracking-[-0.025em] leading-snug m-0 mb-2 text-[var(--ink-primary)]">
                  {selectedNode.name}
                </h2>
                <p className="text-[13.5px] text-[var(--ink-secondary)] leading-relaxed m-0">
                  {selectedNode.summary}
                </p>

                {/* Rhythm-Style Metadata List */}
                <dl className="mt-4 space-y-1.5 text-[12.5px]">
                  <div className="flex items-baseline gap-2.5">
                    <dt className="meta-label w-20 shrink-0">Topics</dt>
                    <dd className="m-0 text-[var(--ink-primary)]">
                      {selectedNode.topic_areas.join(', ') || 'General'}
                    </dd>
                  </div>
                  {selectedNode.fsrs_stability > 0 && (
                    <div className="flex items-baseline gap-2.5">
                      <dt className="meta-label w-20 shrink-0">Stability</dt>
                      <dd className="m-0 font-mono-tech text-[var(--ink-primary)]">
                        {selectedNode.fsrs_stability.toFixed(1)} days
                      </dd>
                    </div>
                  )}
                </dl>

                <div className="mt-5 flex flex-wrap items-center gap-3">
                  {selectedNode.chapter_id && (
                    <button
                      type="button"
                      onClick={() => navigate(`/study/${selectedNode.chapter_id}`)}
                      className="inline-flex items-center gap-1 text-[13px] font-medium text-[var(--accent)] hover:text-[var(--accent-hover)] hover:underline underline-offset-4 cursor-pointer bg-transparent border-0 p-0"
                    >
                      <span>Open Chapter</span>
                      <ArrowUpRight className="w-3.5 h-3.5" strokeWidth={1.8} />
                    </button>
                  )}
                  {selectedNode.topic_areas[0] && (
                    <button
                      type="button"
                      onClick={() =>
                        navigate(`/review?topic=${encodeURIComponent(selectedNode.topic_areas[0])}`)
                      }
                      className="btn-secondary !py-1.5 !px-3.5 !text-[12px]"
                    >
                      <Layers className="w-3.5 h-3.5" strokeWidth={1.6} />
                      <span>Review Topic</span>
                    </button>
                  )}
                </div>
              </div>

              {notice && (
                <div className="px-3.5 py-2 rounded-xl bg-[var(--accent-soft)] text-[var(--accent)] text-[12.5px]">
                  {notice}
                </div>
              )}

              {/* Prerequisite Parents */}
              <div className="pt-5 border-t border-[var(--border-hairline)]">
                <div className="meta-label mb-3">
                  Prerequisites ({selectedNode.parent_ids.length})
                </div>
                {selectedNode.parent_ids.length === 0 ? (
                  <p className="text-[13px] text-[var(--ink-muted)] m-0 mb-3">
                    Foundational root concept.
                  </p>
                ) : (
                  <div className="divide-y divide-[var(--border-hairline)] mb-3.5">
                    {selectedNode.parent_ids.map((pid) => {
                      const parent = nodesById.get(pid);
                      if (!parent) return null;
                      return (
                        <div
                          key={pid}
                          className="py-2 flex items-center justify-between gap-2 text-[13px]"
                        >
                          <button
                            type="button"
                            onClick={() => setSelectedId(pid)}
                            className="font-medium text-[var(--ink-primary)] hover:text-[var(--accent)] transition-colors cursor-pointer bg-transparent border-0 p-0 text-left truncate"
                          >
                            {parent.name}
                          </button>
                          <button
                            type="button"
                            onClick={() => void handleDeleteEdge(pid, selectedNode.id)}
                            className="p-1 rounded-full text-[var(--ink-muted)] hover:text-[var(--status-danger)] hover:bg-[var(--status-danger-soft)] cursor-pointer shrink-0"
                            title="Remove prerequisite edge"
                          >
                            <Trash2 className="w-3.5 h-3.5" strokeWidth={1.6} />
                          </button>
                        </div>
                      );
                    })}
                  </div>
                )}

                <div className="flex items-center gap-2">
                  <select
                    value={newParentId}
                    onChange={(e) => setNewParentId(e.target.value)}
                    className="scholia-select flex-1 min-w-0 px-3 py-2 rounded-xl bg-[var(--bg-subtle)] text-[12.5px] text-[var(--ink-primary)] focus:outline-none cursor-pointer"
                  >
                    <option value="">Add prerequisite...</option>
                    {(graph?.nodes || [])
                      .filter(
                        (n) => n.id !== selectedNode.id && !selectedNode.parent_ids.includes(n.id)
                      )
                      .map((n) => (
                        <option key={n.id} value={n.id}>
                          {n.name}
                        </option>
                      ))}
                  </select>
                  <button
                    type="button"
                    disabled={!newParentId}
                    onClick={() => void handleAddParent()}
                    className="w-8 h-8 rounded-full bg-[var(--cta-bg)] text-[var(--cta-ink)] inline-flex items-center justify-center disabled:opacity-35 cursor-pointer shrink-0"
                    title="Add prerequisite"
                  >
                    <Plus className="w-4 h-4" strokeWidth={2} />
                  </button>
                </div>
              </div>

              {/* Dependent Children */}
              <div className="pt-5 border-t border-[var(--border-hairline)]">
                <div className="meta-label mb-3">
                  Unlocks ({selectedNode.child_ids.length})
                </div>
                {selectedNode.child_ids.length === 0 ? (
                  <p className="text-[13px] text-[var(--ink-muted)] m-0">
                    Terminal frontier node.
                  </p>
                ) : (
                  <div className="flex flex-wrap gap-1.5">
                    {selectedNode.child_ids.map((cid) => {
                      const child = nodesById.get(cid);
                      if (!child) return null;
                      return (
                        <button
                          key={cid}
                          type="button"
                          onClick={() => setSelectedId(cid)}
                          className="px-3 py-1.5 rounded-full bg-[var(--bg-subtle)] hover:bg-[var(--bg-subtle-hover)] text-[12.5px] font-medium text-[var(--ink-primary)] transition-colors cursor-pointer"
                        >
                          {child.name}
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>

              {/* Logged Frontiers */}
              {selectedNode.frontiers.length > 0 && (
                <div className="pt-5 border-t border-[var(--border-hairline)]">
                  <div className="meta-label !text-[var(--accent)] mb-2">Logged Frontiers</div>
                  <ul className="pl-4 m-0 space-y-1.5 text-[13px] text-[var(--ink-secondary)] list-disc">
                    {selectedNode.frontiers.map((f, i) => (
                      <li key={i}>{f}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Merge Duplicate Concept */}
              <div className="pt-5 border-t border-[var(--border-hairline)]">
                <div className="meta-label mb-2.5">Merge Into Existing</div>
                <div className="flex items-center gap-2">
                  <select
                    value={mergeTargetId}
                    onChange={(e) => setMergeTargetId(e.target.value)}
                    className="scholia-select flex-1 min-w-0 px-3 py-2 rounded-xl bg-[var(--bg-subtle)] text-[12.5px] text-[var(--ink-primary)] focus:outline-none cursor-pointer"
                  >
                    <option value="">Select target...</option>
                    {(graph?.nodes || [])
                      .filter((n) => n.id !== selectedNode.id)
                      .map((n) => (
                        <option key={n.id} value={n.id}>
                          {n.name}
                        </option>
                      ))}
                  </select>
                  <button
                    type="button"
                    disabled={!mergeTargetId}
                    onClick={() => void handleMerge()}
                    className="btn-secondary !py-2 !px-3.5 !text-[12px]"
                  >
                    <GitMerge className="w-3.5 h-3.5" strokeWidth={1.6} />
                    <span>Merge</span>
                  </button>
                </div>
              </div>
            </div>
          ) : (
            <div className="text-[13.5px] text-[var(--ink-muted)] py-16 text-center">
              Select a concept node to inspect prerequisites and frontiers.
            </div>
          )}
        </aside>
      </div>
    </div>
  );
};
