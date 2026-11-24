import React, { useCallback, useEffect, useState } from 'react';
import { BrowserRouter, Route, Routes, useSearchParams } from 'react-router-dom';
import { TopNav } from './components/TopNav';
import { CurriculumPage } from './pages/CurriculumPage';
import { LibraryPage } from './pages/LibraryPage';
import { ChapterStudyPage } from './pages/ChapterStudyPage';
import { ReviewQueuePage } from './pages/ReviewQueuePage';
import { TopicGraphPage } from './pages/TopicGraphPage';
import { SettingsPage } from './pages/SettingsPage';
import { api } from './lib/api';
import type { WorkspaceSummary } from './types/scholia';

function formatAgentPill(model: string, effort: string): string {
  const cleanModel = model
    .replace(/^gemini-4-/, 'Gemini ')
    .replace(/^claude-/, '')
    .split(/[-_]/)[0];
  const capModel = cleanModel ? cleanModel.charAt(0).toUpperCase() + cleanModel.slice(1) : 'Agent';
  const capEffort = effort ? effort.charAt(0).toUpperCase() + effort.slice(1).toLowerCase() : '';
  return capEffort ? `${capModel} · ${capEffort}` : capModel;
}

const AppShell: React.FC = () => {
  const [searchParams] = useSearchParams();
  const [dark, setDark] = useState<boolean>(() => {
    const paramTheme = new URLSearchParams(window.location.search).get('theme');
    if (paramTheme === 'dark') return true;
    if (paramTheme === 'light') return false;
    return localStorage.getItem('scholia-theme') === 'dark';
  });
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [activeWorkspaceSlug, setActiveWorkspaceSlug] = useState<string>(() => {
    const paramWs = new URLSearchParams(window.location.search).get('workspace');
    return paramWs || localStorage.getItem('scholia-workspace') || '';
  });
  const [dueCount, setDueCount] = useState<number>(0);
  const [agentSummary, setAgentSummary] = useState<string>('Opus · High');

  useEffect(() => {
    const paramTheme = searchParams.get('theme');
    if (paramTheme === 'dark') setDark(true);
    else if (paramTheme === 'light') setDark(false);
    const paramWs = searchParams.get('workspace');
    if (paramWs) setActiveWorkspaceSlug(paramWs);
  }, [searchParams]);

  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark);
    localStorage.setItem('scholia-theme', dark ? 'dark' : 'light');
  }, [dark]);

  const activeWorkspace =
    workspaces.find(
      (w) =>
        w.slug.toLowerCase() === activeWorkspaceSlug.toLowerCase() ||
        w.id === activeWorkspaceSlug
    ) ||
    workspaces[0] ||
    null;

  const refreshGlobal = useCallback(() => {
    api
      .listWorkspaces()
      .then((res) => {
        setWorkspaces(res.workspaces);
        setActiveWorkspaceSlug((prev) => {
          if (prev && res.workspaces.some((w) => w.slug.toLowerCase() === prev.toLowerCase())) {
            return prev;
          }
          const def = res.default_workspace?.slug || res.workspaces[0]?.slug || '';
          if (def) localStorage.setItem('scholia-workspace', def);
          return def;
        });
      })
      .catch(() => {});

    api
      .getAgentsStatus()
      .then((res) => {
        const examRoute = res.routing?.oral_exam_grading || res.routing?.extraction_planning;
        if (examRoute) {
          setAgentSummary(formatAgentPill(examRoute.model, examRoute.effort));
        }
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    refreshGlobal();
  }, [refreshGlobal]);

  useEffect(() => {
    const ws = activeWorkspace?.slug;
    if (!ws) return;
    localStorage.setItem('scholia-workspace', ws);
    api
      .listBooks(ws)
      .then((res) => setDueCount(res.due_reviews_count || 0))
      .catch(() => {});
  }, [activeWorkspace?.slug]);

  const handleSelectWorkspace = (slug: string) => {
    setActiveWorkspaceSlug(slug);
    localStorage.setItem('scholia-workspace', slug);
  };

  const handleCreateWorkspace = async (name: string, description: string) => {
    const created = await api.createWorkspace({ name, description });
    setWorkspaces((prev) => [...prev, created]);
    setActiveWorkspaceSlug(created.slug);
    localStorage.setItem('scholia-workspace', created.slug);
  };

  return (
    <div className="h-full flex flex-col bg-[var(--bg-canvas)] text-[var(--ink-primary)]">
      <TopNav
        workspaces={workspaces}
        activeWorkspace={activeWorkspace}
        onSelectWorkspace={handleSelectWorkspace}
        onCreateWorkspace={handleCreateWorkspace}
        dueCount={dueCount}
        activeAgentSummary={agentSummary}
        dark={dark}
        onToggleTheme={() => setDark((d) => !d)}
      />

      <main className="flex-1 flex flex-col min-h-0 overflow-hidden">
        <Routes>
          <Route path="/curriculum" element={<CurriculumPage workspace={activeWorkspace} />} />
          <Route
            path="/"
            element={<LibraryPage workspace={activeWorkspace} onRefreshGlobal={refreshGlobal} />}
          />
          <Route
            path="/books/:bookId/boundaries"
            element={<LibraryPage workspace={activeWorkspace} onRefreshGlobal={refreshGlobal} />}
          />
          <Route path="/study/:chapterId" element={<ChapterStudyPage />} />
          <Route
            path="/review"
            element={<ReviewQueuePage workspace={activeWorkspace} onRefreshGlobal={refreshGlobal} />}
          />
          <Route path="/graph" element={<TopicGraphPage workspace={activeWorkspace} />} />
          <Route path="/settings" element={<SettingsPage onRefreshGlobal={refreshGlobal} />} />
        </Routes>
      </main>
    </div>
  );
};

export const App: React.FC = () => (
  <BrowserRouter>
    <AppShell />
  </BrowserRouter>
);

export default App;
