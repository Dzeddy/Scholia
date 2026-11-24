import React, { useEffect, useMemo, useState } from 'react';
import katex from 'katex';
import { marked } from 'marked';
import { X, ZoomIn } from 'lucide-react';

interface MarkdownMathProps {
  content: string;
  variant?: 'notes' | 'dialogue';
  onCitePage?: (bookPage: number) => void;
}

marked.setOptions({
  gfm: true,
  breaks: false,
});

function escapeHtml(raw: string): string {
  return raw
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function renderWithMathAndCitations(markdown: string): string {
  const codeBlockTokens: string[] = [];
  const inlineCodeTokens: string[] = [];
  const mathTokens: string[] = [];

  // 0a. Protect fenced code blocks before math processing so $ in code is never parsed as KaTeX
  let processed = markdown.replace(/```([a-zA-Z0-9_+-]*)\n([\s\S]*?)```/g, (_match, lang: string, code: string) => {
    const idx = codeBlockTokens.length;
    const label = (lang || 'code').trim();
    const cleanCode = code.replace(/\n$/, '');
    codeBlockTokens.push(
      `<div class="scholia-code-block"><div class="scholia-code-header"><span>${escapeHtml(label)}</span></div><pre><code>${escapeHtml(cleanCode)}</code></pre></div>`
    );
    return `\n\n@@SCHOLIA_CODEBLOCK_${idx}@@\n\n`;
  });

  // 0b. Protect inline code spans `...` before inline math regex
  processed = processed.replace(/`([^`\n]+?)`/g, (_match, code: string) => {
    const idx = inlineCodeTokens.length;
    inlineCodeTokens.push(`<code>${escapeHtml(code)}</code>`);
    return `@@SCHOLIA_INLINECODE_${idx}@@`;
  });

  // 1. Protect display math $$...$$
  processed = processed.replace(/\$\$([\s\S]+?)\$\$/g, (_match, expr: string) => {
    const idx = mathTokens.length;
    try {
      const rendered = katex.renderToString(expr.trim(), {
        displayMode: true,
        throwOnError: false,
        strict: false,
      });
      mathTokens.push(`<div class="scholia-math-block">${rendered}</div>`);
    } catch {
      mathTokens.push(`<pre>${escapeHtml(expr)}</pre>`);
    }
    return `\n\n@@SCHOLIA_MATH_${idx}@@\n\n`;
  });

  // 2. Protect inline math $...$ (avoid matching currency like $100)
  processed = processed.replace(/(?<!\\)\$([^\n$]+?)\$/g, (_match, expr: string) => {
    const trimmed = expr.trim();
    if (!trimmed || /^\d+(\.\d+)?$/.test(trimmed)) return _match;
    const idx = mathTokens.length;
    try {
      const rendered = katex.renderToString(trimmed, {
        displayMode: false,
        throwOnError: false,
        strict: false,
      });
      mathTokens.push(rendered);
    } catch {
      mathTokens.push(`<code>${escapeHtml(trimmed)}</code>`);
    }
    return `@@SCHOLIA_MATH_${idx}@@`;
  });

  // 3. Parse Markdown to HTML
  let html = marked.parse(processed) as string;

  // 4. Restore protected blocks (unwrap <p> around block-level tokens)
  html = html.replace(/<p>\s*@@SCHOLIA_CODEBLOCK_(\d+)@@\s*<\/p>/g, (_m, i: string) => codeBlockTokens[Number(i)] || '');
  html = html.replace(/@@SCHOLIA_CODEBLOCK_(\d+)@@/g, (_m, i: string) => codeBlockTokens[Number(i)] || '');
  html = html.replace(/@@SCHOLIA_INLINECODE_(\d+)@@/g, (_m, i: string) => inlineCodeTokens[Number(i)] || '');
  html = html.replace(/<p>\s*@@SCHOLIA_MATH_(\d+)@@\s*<\/p>/g, (_m, i: string) => mathTokens[Number(i)] || '');
  html = html.replace(/@@SCHOLIA_MATH_(\d+)@@/g, (_m, i: string) => mathTokens[Number(i)] || '');

  // 5. Convert [p. N] citations to clickable buttons
  html = html.replace(
    /\[p\.\s*(\d+)\]/g,
    (_m, pageNum: string) =>
      `<button type="button" class="citation-btn" data-cite-page="${pageNum}" title="Jump to page ${pageNum}">p.&nbsp;${pageNum}</button>`
  );

  return html;
}

export const MarkdownMath: React.FC<MarkdownMathProps> = ({
  content,
  variant = 'notes',
  onCitePage,
}) => {
  const html = useMemo(() => renderWithMathAndCitations(content || ''), [content]);
  const [lightbox, setLightbox] = useState<{ src: string; alt: string } | null>(null);

  useEffect(() => {
    if (!lightbox) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setLightbox(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [lightbox]);

  const handleClick = (e: React.MouseEvent<HTMLDivElement>) => {
    const target = e.target as HTMLElement | null;
    const btn = target?.closest<HTMLButtonElement>('button[data-cite-page]');
    if (btn && onCitePage) {
      const pno = Number(btn.getAttribute('data-cite-page'));
      if (!Number.isNaN(pno)) {
        onCitePage(pno);
      }
      return;
    }
    const img = target?.closest<HTMLImageElement>('img');
    if (img && img.src) {
      setLightbox({ src: img.src, alt: img.alt || 'Figure' });
    }
  };

  return (
    <>
      <div
        className={variant === 'notes' ? 'scholia-prose' : 'scholia-dialogue'}
        onClick={handleClick}
        dangerouslySetInnerHTML={{ __html: html }}
      />

      {lightbox && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-6"
          onClick={() => setLightbox(null)}
          role="dialog"
          aria-modal="true"
          aria-label="Figure lightbox"
        >
          <div
            className="max-w-[92vw] max-h-[90vh] flex flex-col gallery-sheet overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="px-5 py-3 border-b border-[var(--border-hairline)] flex items-center justify-between gap-4">
              <div className="flex items-center gap-2 text-[12.5px] text-[var(--ink-secondary)] truncate">
                <ZoomIn className="w-3.5 h-3.5 text-[var(--accent)] shrink-0" strokeWidth={1.7} />
                <span className="truncate">{lightbox.alt}</span>
              </div>
              <button
                type="button"
                onClick={() => setLightbox(null)}
                className="w-7 h-7 rounded-full inline-flex items-center justify-center text-[var(--ink-secondary)] hover:text-[var(--ink-primary)] hover:bg-[var(--bg-subtle)] cursor-pointer"
                title="Close figure (Esc)"
              >
                <X className="w-4 h-4" strokeWidth={1.7} />
              </button>
            </div>
            <div className="p-6 overflow-auto bg-white flex items-center justify-center">
              <img
                src={lightbox.src}
                alt={lightbox.alt}
                className="max-w-[85vw] max-h-[78vh] object-contain"
              />
            </div>
          </div>
        </div>
      )}
    </>
  );
};
