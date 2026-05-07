import { useEffect, useState } from 'react';
import { Check, Copy, X } from 'lucide-react';
import { FileContentRenderer, defaultWrapLines, type FilePreview } from './MessageBubble';
import type { FileContentPayload } from '../types';
import { useWorkbenchStore } from '../store/useWorkbenchStore';

export function FilePreviewModal({ file, onClose }: { file: FilePreview | null; onClose: () => void }) {
  const setWorkbenchError = useWorkbenchStore((state) => state.setError);
  const [payload, setPayload] = useState<FileContentPayload | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [wrapLines, setWrapLines] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!file) return;
    let cancelled = false;
    setLoading(true);
    setError('');
    setPayload(null);
    setCopied(false);
    fetch(file.url)
      .then(async (response) => {
        if (!response.ok) throw new Error(`Preview failed: ${response.status}`);
        const contentType = response.headers.get('content-type')?.split(';')[0].trim().toLowerCase() || file.mime_type.toLowerCase();
        if (!isPreviewableText(contentType, file.name)) {
          throw new Error('Preview not available');
        }
        const text = await response.text();
        if (looksLikeViteIndexHtml(text, contentType)) {
          throw new Error('Attachment preview returned the frontend app instead of file content.');
        }
        return {
          filename: file.name,
          language: file.language || languageForFilename(file.name),
          mime_type: contentType,
          content: text,
          size: file.size,
          truncated: false,
        } satisfies FileContentPayload;
      })
      .then((nextPayload) => {
        if (!cancelled) {
          setPayload(nextPayload);
          setWrapLines(defaultWrapLines(nextPayload.filename, nextPayload.language));
        }
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

  async function copyFileContent() {
    if (!payload) return;
    try {
      await navigator.clipboard.writeText(payload.content);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1300);
    } catch (cause) {
      setWorkbenchError(cause, 'Failed to copy file content');
    }
  }

  return (
    <div className="preview-backdrop" role="dialog" aria-modal="true" aria-label="File preview" onClick={onClose}>
      <div className="file-preview-modal" onClick={(event) => event.stopPropagation()}>
        <header className="file-preview-header">
          <div className="file-preview-title">
            <strong>{file.name}</strong>
            <span>{file.mime_type} · {formatBytes(file.size)}</span>
          </div>
          <div className="file-preview-header-actions">
            {payload && !loading && !error ? (
              <>
                <button type="button" className="file-preview-action-button" onClick={() => setWrapLines((current) => !current)}>
                  {wrapLines ? 'No wrap' : 'Wrap'}
                </button>
                <button type="button" className="file-preview-action-button" onClick={() => void copyFileContent()} title="Copy file content">
                  {copied ? <Check size={13} /> : <Copy size={13} />}
                  <span>{copied ? 'Copied' : 'Copy'}</span>
                </button>
              </>
            ) : null}
            <button type="button" className="file-preview-close-button" onClick={onClose} title="Close file preview">
              <X size={18} />
            </button>
          </div>
        </header>
        {loading ? <div className="file-preview-status">Loading...</div> : null}
        {error ? <div className="file-preview-status">{error || 'Preview not available'}</div> : null}
        {!loading && !error && payload ? <FileContentRenderer payload={payload} variant="modal" wrapLines={wrapLines} /> : null}
      </div>
    </div>
  );
}

function isPreviewableText(mimeType: string, name: string): boolean {
  const extension = fileExtension(name);
  return (
    mimeType.startsWith('text/') ||
    ['application/json', 'application/xml', 'application/yaml', 'application/x-yaml', 'application/toml', 'application/sql'].includes(mimeType) ||
    ['.txt', '.md', '.py', '.js', '.ts', '.tsx', '.jsx', '.json', '.yaml', '.yml', '.toml', '.xml', '.html', '.css', '.env', '.log', '.csv', '.sql', '.sh', '.ps1', '.bat', '.ini', '.cfg'].includes(extension)
  );
}

function looksLikeViteIndexHtml(text: string, mimeType: string): boolean {
  const sample = text.slice(0, 300).toLowerCase();
  return mimeType === 'text/html' && sample.includes('<!doctype html') && sample.includes('/src/main.');
}

function languageForFilename(name: string): string {
  return (
    {
      '.md': 'markdown',
      '.py': 'python',
      '.js': 'javascript',
      '.ts': 'typescript',
      '.tsx': 'tsx',
      '.jsx': 'jsx',
      '.json': 'json',
      '.yaml': 'yaml',
      '.yml': 'yaml',
      '.toml': 'toml',
      '.xml': 'xml',
      '.html': 'html',
      '.css': 'css',
      '.env': 'dotenv',
      '.log': 'log',
      '.csv': 'csv',
      '.sql': 'sql',
      '.sh': 'shell',
      '.ps1': 'powershell',
      '.bat': 'batch',
      '.ini': 'ini',
      '.cfg': 'ini',
    }[fileExtension(name)] || 'text'
  );
}

function fileExtension(name: string): string {
  const match = name.toLowerCase().match(/(\.[^.]+)$/);
  return match ? match[1] : '';
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(value < 10 * 1024 ? 1 : 0)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}
