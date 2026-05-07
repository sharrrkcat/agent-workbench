import { useEffect, useState } from 'react';
import { X } from 'lucide-react';
import type { FilePreview } from './MessageBubble';

export function FilePreviewModal({ file, onClose }: { file: FilePreview | null; onClose: () => void }) {
  const [content, setContent] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!file) return;
    let cancelled = false;
    setLoading(true);
    setError('');
    setContent('');
    fetch(file.url)
      .then(async (response) => {
        if (!response.ok) throw new Error(`Preview failed: ${response.status}`);
        return response.text();
      })
      .then((text) => {
        if (!cancelled) setContent(text);
      })
      .catch((cause) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : 'Preview not available');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [file]);

  if (!file) return null;

  return (
    <div className="preview-backdrop" role="dialog" aria-modal="true" aria-label="File preview" onClick={onClose}>
      <div className="file-preview-modal" onClick={(event) => event.stopPropagation()}>
        <header>
          <div>
            <strong>{file.name}</strong>
            <span>{file.mime_type} · {formatBytes(file.size)}</span>
          </div>
          <button type="button" onClick={onClose} title="Close file preview">
            <X size={18} />
          </button>
        </header>
        {loading ? <div className="file-preview-status">Loading...</div> : null}
        {error ? <div className="file-preview-status">{error || 'Preview not available'}</div> : null}
        {!loading && !error ? (
          <pre className="file-preview-content">
            <code>{content}</code>
          </pre>
        ) : null}
      </div>
    </div>
  );
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(value < 10 * 1024 ? 1 : 0)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}
