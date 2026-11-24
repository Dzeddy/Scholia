import React, { useEffect, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { ChevronDown, Moon, Plus, Sun, X } from 'lucide-react';
import type { WorkspaceSummary } from '../types/scholia';

interface TopNavProps {
  workspaces: WorkspaceSummary[];
  activeWorkspace: WorkspaceSummary | null;
  onSelectWorkspace: (slug: string) => void;
  onCreateWorkspace: (name: string, description: string) => Promise<void>;
  dueCount: number;
  activeAgentSummary: string;
  dark: boolean;
  onToggleTheme: () => void;
}

export const TopNav: React.FC<TopNavProps> = ({
  workspaces,
  activeWorkspace,
  onSelectWorkspace,
  onCreateWorkspace,
  dueCount,
  activeAgentSummary,
  dark,
  onToggleTheme,
}) => {
  const { pathname } = useLocation();
  const [wsOpen, setWsOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!wsOpen) return;
    const onDocClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setWsOpen(false);
        setCreating(false);
      }
    };
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, [wsOpen]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName.trim() || submitting) return;
    setSubmitting(true);
    try {
      await onCreateWorkspace(newName.trim(), newDesc.trim());
      setNewName('');
      setNewDesc('');
      setCreating(false);
      setWsOpen(false);
    } finally {
      setSubmitting(false);
    }
  };

  const navItems = [
    {
      to: '/curriculum',
      label: 'Curriculum',
      active: pathname === '/curriculum',
    },
    {
      to: '/',
      label: 'Library',
      active: pathname === '/' || pathname.startsWith('/books') || pathname.startsWith('/study'),
    },
    {
      to: '/review',
      label: 'Review',
      active: pathname.startsWith('/review'),
      badge: dueCount,
    },
    {
      to: '/graph',
      label: 'Graph',
      active: pathname.startsWith('/graph'),
    },
    {
      to: '/settings',
      label: 'Settings',
      active: pathname.startsWith('/settings'),
    },
  ];

  return (
    <header className="h-16 shrink-0 sticky top-0 z-30 bg-[var(--bg-canvas)]/85 backdrop-blur-md px-6 lg:px-8 flex items-center justify-between select-none">
      {/* Left: Geometric Wordmark + Borderless Workspace Dropdown */}
      <div className="flex items-center gap-2.5 min-w-[200px]">
        <Link
          to="/curriculum"
          className="text-[17px] font-semibold tracking-[-0.03em] text-[var(--ink-primary)] no-underline hover:opacity-80 transition-opacity"
        >
          Scholia
        </Link>

        <span className="text-[var(--ink-muted)]/60 font-light text-[15px] select-none">/</span>

        <div ref={menuRef} className="relative">
          <button
            type="button"
            onClick={() => setWsOpen((v) => !v)}
            className="inline-flex items-center gap-1 px-2 py-1 -ml-1 rounded-full text-[13.5px] font-medium text-[var(--ink-secondary)] hover:text-[var(--ink-primary)] hover:bg-[var(--bg-subtle)] transition-colors cursor-pointer"
            title="Switch umbrella workspace"
          >
            <span className="max-w-[140px] truncate">{activeWorkspace?.name || 'Workspace'}</span>
            <ChevronDown className="w-3.5 h-3.5 text-[var(--ink-muted)]" strokeWidth={1.75} />
          </button>

          {wsOpen && (
            <div className="absolute left-0 mt-2 w-[300px] floating-dock overflow-hidden z-40">
              <div className="px-4 py-3 flex items-center justify-between border-b border-[var(--border-hairline)]">
                <span className="meta-label">Workspaces</span>
                <button
                  type="button"
                  onClick={() => setWsOpen(false)}
                  className="p-1 -mr-1 rounded-full text-[var(--ink-muted)] hover:text-[var(--ink-primary)] hover:bg-[var(--bg-subtle)] cursor-pointer"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>

              <div className="p-1.5 max-h-[260px] overflow-y-auto space-y-0.5">
                {workspaces.map((ws) => {
                  const isCurr = activeWorkspace?.id === ws.id;
                  return (
                    <button
                      key={ws.id}
                      type="button"
                      onClick={() => {
                        onSelectWorkspace(ws.slug);
                        setWsOpen(false);
                      }}
                      className={`w-full text-left px-3 py-2.5 rounded-xl cursor-pointer transition-colors ${
                        isCurr
                          ? 'bg-[var(--bg-subtle)] text-[var(--ink-primary)]'
                          : 'hover:bg-[var(--bg-subtle)]/60 text-[var(--ink-primary)]'
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="flex items-center gap-2 text-[13.5px] font-medium">
                          {isCurr && (
                            <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent)] shrink-0" />
                          )}
                          <span>{ws.name}</span>
                        </span>
                        <span className="text-[11.5px] text-[var(--ink-muted)] tabular-nums">
                          {ws.book_count} {ws.book_count === 1 ? 'volume' : 'volumes'}
                        </span>
                      </div>
                      {ws.description && (
                        <div className="text-[12px] text-[var(--ink-secondary)] truncate mt-0.5">
                          {ws.description}
                        </div>
                      )}
                    </button>
                  );
                })}
              </div>

              <div className="p-2.5 border-t border-[var(--border-hairline)]">
                {!creating ? (
                  <button
                    type="button"
                    onClick={() => setCreating(true)}
                    className="w-full inline-flex items-center justify-center gap-1.5 px-3 py-2 rounded-full bg-[var(--bg-subtle)] hover:bg-[var(--bg-subtle-hover)] text-[12.5px] font-medium text-[var(--ink-primary)] transition-colors cursor-pointer"
                  >
                    <Plus className="w-3.5 h-3.5" strokeWidth={1.8} />
                    <span>New workspace</span>
                  </button>
                ) : (
                  <form onSubmit={handleCreate} className="space-y-2 p-1">
                    <input
                      type="text"
                      value={newName}
                      onChange={(e) => setNewName(e.target.value)}
                      placeholder="Workspace name"
                      className="w-full px-3 py-2 rounded-xl bg-[var(--bg-subtle)] text-[13px] text-[var(--ink-primary)] placeholder:text-[var(--ink-muted)] focus:outline-none focus:ring-1 focus:ring-[var(--ink-primary)]/20"
                      autoFocus
                      required
                    />
                    <input
                      type="text"
                      value={newDesc}
                      onChange={(e) => setNewDesc(e.target.value)}
                      placeholder="Short description (optional)"
                      className="w-full px-3 py-2 rounded-xl bg-[var(--bg-subtle)] text-[13px] text-[var(--ink-primary)] placeholder:text-[var(--ink-muted)] focus:outline-none focus:ring-1 focus:ring-[var(--ink-primary)]/20"
                    />
                    <div className="flex items-center justify-end gap-2 pt-1">
                      <button
                        type="button"
                        onClick={() => setCreating(false)}
                        className="px-3 py-1.5 rounded-full text-[12px] text-[var(--ink-secondary)] hover:text-[var(--ink-primary)] cursor-pointer"
                      >
                        Cancel
                      </button>
                      <button
                        type="submit"
                        disabled={submitting || !newName.trim()}
                        className="btn-primary !py-1.5 !px-3.5 !text-[12px]"
                      >
                        Create
                      </button>
                    </div>
                  </form>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Center: Floating Pill Navigation */}
      <nav
        className="flex items-center gap-0.5 bg-[var(--bg-subtle)]/90 rounded-full p-1"
        aria-label="Primary navigation"
      >
        {navItems.map((item) => (
          <Link
            key={item.to}
            to={item.to}
            className={`relative flex items-center gap-1.5 px-4 py-1.5 rounded-full text-[13px] font-medium tracking-[-0.01em] no-underline transition-all ${
              item.active
                ? 'bg-[var(--cta-bg)] text-[var(--cta-ink)] shadow-xs'
                : 'text-[var(--ink-secondary)] hover:text-[var(--ink-primary)]'
            }`}
          >
            <span>{item.label}</span>
            {typeof item.badge === 'number' && item.badge > 0 && (
              <span
                className={`inline-flex items-center justify-center min-w-[17px] h-[17px] px-1 rounded-full text-[10.5px] font-medium tabular-nums ${
                  item.active
                    ? 'bg-[var(--accent)] text-white'
                    : 'bg-[var(--accent-soft)] text-[var(--accent)]'
                }`}
              >
                {item.badge}
              </span>
            )}
          </Link>
        ))}
      </nav>

      {/* Right: Minimal Agent Pill + Icon-Only Theme Toggle */}
      <div className="flex items-center justify-end gap-2 min-w-[200px]">
        <Link
          to="/settings"
          className="hidden md:inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-[var(--bg-subtle)] hover:bg-[var(--bg-subtle-hover)] text-[12px] font-medium text-[var(--ink-secondary)] hover:text-[var(--ink-primary)] no-underline transition-colors"
          title="Configure CLI agent routing"
        >
          <span className="w-1.5 h-1.5 rounded-full bg-[var(--status-forest)] shrink-0" />
          <span>{activeAgentSummary}</span>
        </Link>

        <button
          type="button"
          onClick={onToggleTheme}
          className="w-8 h-8 rounded-full bg-[var(--bg-subtle)] hover:bg-[var(--bg-subtle-hover)] text-[var(--ink-secondary)] hover:text-[var(--ink-primary)] inline-flex items-center justify-center transition-colors cursor-pointer"
          title={dark ? 'Switch to light mode' : 'Switch to dark mode'}
          aria-label={dark ? 'Switch to light mode' : 'Switch to dark mode'}
        >
          {dark ? (
            <Sun className="w-4 h-4" strokeWidth={1.7} />
          ) : (
            <Moon className="w-4 h-4" strokeWidth={1.7} />
          )}
        </button>
      </div>
    </header>
  );
};
