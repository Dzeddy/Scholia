import React, { useRef, useState } from 'react';
import { ArrowUp, Code2, Eye, PencilLine, Sigma } from 'lucide-react';
import { MarkdownMath } from './MarkdownMath';

interface StudyComposerProps {
  value: string;
  onChange: (next: string) => void;
  onSubmit: () => void;
  disabled?: boolean;
  placeholder?: string;
  submitLabel?: string;
  rows?: number;
  submitOnEnter?: boolean;
  defaultPreview?: boolean;
}

export const StudyComposer: React.FC<StudyComposerProps> = ({
  value,
  onChange,
  onSubmit,
  disabled = false,
  placeholder = 'Write your response...',
  submitLabel = 'Send',
  rows = 3,
  submitOnEnter = true,
  defaultPreview = false,
}) => {
  const [preview, setPreview] = useState(defaultPreview);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const insertSnippet = (before: string, after: string, fallbackInner: string) => {
    const el = textareaRef.current;
    if (!el) {
      onChange(`${value}${value && !value.endsWith('\n') ? '\n' : ''}${before}${fallbackInner}${after}`);
      return;
    }
    const start = el.selectionStart ?? value.length;
    const end = el.selectionEnd ?? value.length;
    const selected = value.slice(start, end) || fallbackInner;
    const next = value.slice(0, start) + before + selected + after + value.slice(end);
    onChange(next);
    setPreview(false);
    requestAnimationFrame(() => {
      el.focus();
      const pos = start + before.length + selected.length;
      el.setSelectionRange(pos, pos);
    });
  };

  return (
    <div className="floating-dock p-3.5 transition-shadow focus-within:ring-1 focus-within:ring-[var(--border-strong)]">
      {/* Main Input or Live Preview */}
      {preview ? (
        <div className="min-h-[76px] max-h-[240px] overflow-y-auto px-1.5 py-1">
          {value.trim() ? (
            <MarkdownMath content={value} variant="dialogue" />
          ) : (
            <span className="text-[13px] text-[var(--ink-muted)]">
              Nothing to preview yet. Insert math or code below.
            </span>
          )}
        </div>
      ) : (
        <textarea
          ref={textareaRef}
          rows={rows}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (submitOnEnter && e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              if (!disabled && value.trim()) onSubmit();
            }
          }}
          placeholder={placeholder}
          className="w-full resize-none px-1.5 py-1 bg-transparent border-0 text-[14px] leading-relaxed text-[var(--ink-primary)] placeholder:text-[var(--ink-muted)] focus:outline-none"
        />
      )}

      {/* Dock Bottom Action Row */}
      <div className="mt-2.5 pt-2.5 border-t border-[var(--border-hairline)] flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            disabled={disabled}
            onClick={() => insertSnippet('$$\n', '\n$$', 'I = \\frac{\\text{FLOPs}}{\\text{Bytes}}')}
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-[var(--bg-subtle)] hover:bg-[var(--bg-subtle-hover)] text-[12px] font-medium text-[var(--ink-secondary)] hover:text-[var(--ink-primary)] transition-colors cursor-pointer"
            title="Insert display LaTeX block"
          >
            <Sigma className="w-3.5 h-3.5" strokeWidth={1.7} />
            <span>Math</span>
          </button>

          <button
            type="button"
            disabled={disabled}
            onClick={() => insertSnippet('```python\n', '\n```', '# kernel or trace\n')}
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-[var(--bg-subtle)] hover:bg-[var(--bg-subtle-hover)] text-[12px] font-medium text-[var(--ink-secondary)] hover:text-[var(--ink-primary)] transition-colors cursor-pointer"
            title="Insert fenced code block"
          >
            <Code2 className="w-3.5 h-3.5" strokeWidth={1.7} />
            <span>Code</span>
          </button>

          <button
            type="button"
            onClick={() => setPreview((p) => !p)}
            className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[12px] font-medium transition-colors cursor-pointer ${
              preview
                ? 'bg-[var(--cta-bg)] text-[var(--cta-ink)]'
                : 'bg-[var(--bg-subtle)] hover:bg-[var(--bg-subtle-hover)] text-[var(--ink-secondary)] hover:text-[var(--ink-primary)]'
            }`}
            title="Toggle KaTeX and code block preview"
          >
            {preview ? (
              <>
                <PencilLine className="w-3.5 h-3.5" strokeWidth={1.7} />
                <span>Edit</span>
              </>
            ) : (
              <>
                <Eye className="w-3.5 h-3.5" strokeWidth={1.7} />
                <span>Preview</span>
              </>
            )}
          </button>
        </div>

        <div className="flex items-center gap-3">
          <span className="hidden sm:inline text-[11.5px] text-[var(--ink-muted)]">
            {submitOnEnter ? 'Enter to send' : 'LaTeX & code supported'}
          </span>

          <button
            type="button"
            disabled={disabled || !value.trim()}
            onClick={onSubmit}
            className="btn-primary !py-1.5 !px-3.5 !text-[12.5px]"
          >
            <span>{submitLabel}</span>
            <ArrowUp className="w-3.5 h-3.5" strokeWidth={2} />
          </button>
        </div>
      </div>
    </div>
  );
};
