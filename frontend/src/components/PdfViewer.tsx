import React, { useEffect, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut, FileText } from 'lucide-react';
import * as pdfjsLib from 'pdfjs-dist';
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;

interface PdfViewerProps {
  chapterId: string;
  startBookPage: number;
  targetBookPage: number | null;
  hasPdf: boolean;
}

export const PdfViewer: React.FC<PdfViewerProps> = ({
  chapterId,
  startBookPage,
  targetBookPage,
  hasPdf,
}) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const pdfDocRef = useRef<pdfjsLib.PDFDocumentProxy | null>(null);
  const renderTaskRef = useRef<pdfjsLib.RenderTask | null>(null);

  const [numPages, setNumPages] = useState<number>(0);
  const [localPage, setLocalPage] = useState<number>(1);
  const [scale, setScale] = useState<number>(1.08);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!hasPdf) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);

    const loadingTask = pdfjsLib.getDocument({ url: `/api/chapters/${chapterId}/pdf` });
    loadingTask.promise
      .then((doc) => {
        if (cancelled) {
          void loadingTask.destroy();
          return;
        }
        pdfDocRef.current = doc;
        setNumPages(doc.numPages);
        const initialLocal =
          targetBookPage !== null
            ? Math.min(doc.numPages, Math.max(1, targetBookPage - startBookPage + 1))
            : 1;
        setLocalPage(initialLocal);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Unable to load chapter PDF.');
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
      pdfDocRef.current = null;
      void loadingTask.destroy();
    };
  }, [chapterId, hasPdf, startBookPage]);

  useEffect(() => {
    if (targetBookPage !== null && numPages > 0) {
      const mapped = Math.min(numPages, Math.max(1, targetBookPage - startBookPage + 1));
      setLocalPage(mapped);
    }
  }, [targetBookPage, numPages, startBookPage]);

  useEffect(() => {
    const doc = pdfDocRef.current;
    const canvas = canvasRef.current;
    if (!doc || !canvas || numPages === 0) return;

    let cancelled = false;
    doc.getPage(localPage).then((page) => {
      if (cancelled) return;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const viewport = page.getViewport({ scale });
      canvas.width = Math.floor(viewport.width * dpr);
      canvas.height = Math.floor(viewport.height * dpr);
      canvas.style.width = `${Math.floor(viewport.width)}px`;
      canvas.style.height = `${Math.floor(viewport.height)}px`;

      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      if (renderTaskRef.current) {
        try {
          renderTaskRef.current.cancel();
        } catch {
          // ignore
        }
      }
      const task = page.render({ canvasContext: ctx, viewport, canvas });
      renderTaskRef.current = task;
      task.promise.catch(() => {
        // ignore cancel errors
      });
    });

    return () => {
      cancelled = true;
    };
  }, [localPage, scale, numPages]);

  if (!hasPdf) {
    return (
      <div className="flex flex-col items-center justify-center h-full px-8 text-center text-[var(--ink-secondary)]">
        <FileText className="w-7 h-7 mb-3 opacity-50" strokeWidth={1.5} />
        <p className="text-[16px] font-medium text-[var(--ink-primary)] mb-1">
          Text-Native Chapter Source
        </p>
        <p className="text-[13.5px] max-w-md text-[var(--ink-secondary)]">
          This chapter was ingested from Markdown or EPUB without an embedded PDF page stream. Study Notes contain the full structured reconstruction.
        </p>
      </div>
    );
  }

  const currentBookPage = startBookPage + localPage - 1;

  return (
    <div className="flex flex-col h-full bg-[var(--bg-canvas)]">
      {/* Minimal Pill Toolbar */}
      <div className="flex items-center justify-between px-5 py-2.5 border-b border-[var(--border-hairline)] bg-[var(--bg-sheet)] text-xs">
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            disabled={localPage <= 1}
            onClick={() => setLocalPage((p) => Math.max(1, p - 1))}
            className="w-7 h-7 rounded-full inline-flex items-center justify-center bg-[var(--bg-subtle)] hover:bg-[var(--bg-subtle-hover)] disabled:opacity-35 cursor-pointer"
            aria-label="Previous page"
          >
            <ChevronLeft className="w-3.5 h-3.5" strokeWidth={1.7} />
          </button>
          <span className="font-mono-tech text-[12px] text-[var(--ink-primary)] px-2">
            p. {currentBookPage}{' '}
            <span className="text-[var(--ink-muted)]">
              ({localPage}/{numPages || '—'})
            </span>
          </span>
          <button
            type="button"
            disabled={localPage >= numPages}
            onClick={() => setLocalPage((p) => Math.min(numPages, p + 1))}
            className="w-7 h-7 rounded-full inline-flex items-center justify-center bg-[var(--bg-subtle)] hover:bg-[var(--bg-subtle-hover)] disabled:opacity-35 cursor-pointer"
            aria-label="Next page"
          >
            <ChevronRight className="w-3.5 h-3.5" strokeWidth={1.7} />
          </button>
        </div>

        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => setScale((s) => Math.max(0.7, Number((s - 0.12).toFixed(2))))}
            className="w-7 h-7 rounded-full inline-flex items-center justify-center bg-[var(--bg-subtle)] hover:bg-[var(--bg-subtle-hover)] cursor-pointer"
            aria-label="Zoom out"
          >
            <ZoomOut className="w-3.5 h-3.5" strokeWidth={1.7} />
          </button>
          <span className="font-mono-tech text-[12px] text-[var(--ink-secondary)] w-11 text-center">
            {Math.round(scale * 100)}%
          </span>
          <button
            type="button"
            onClick={() => setScale((s) => Math.min(1.8, Number((s + 0.12).toFixed(2))))}
            className="w-7 h-7 rounded-full inline-flex items-center justify-center bg-[var(--bg-subtle)] hover:bg-[var(--bg-subtle-hover)] cursor-pointer"
            aria-label="Zoom in"
          >
            <ZoomIn className="w-3.5 h-3.5" strokeWidth={1.7} />
          </button>
        </div>
      </div>

      {/* Rendered Page Canvas */}
      <div className="flex-1 overflow-auto p-6 flex justify-center items-start">
        {loading && (
          <div className="py-12 text-[13px] text-[var(--ink-muted)]">
            Rendering chapter page...
          </div>
        )}
        {error && (
          <div className="py-12 text-[13px] text-[var(--status-danger)]">{error}</div>
        )}
        <canvas
          ref={canvasRef}
          className={`rounded-lg bg-white shadow-md ${loading ? 'hidden' : 'block'}`}
        />
      </div>
    </div>
  );
};
