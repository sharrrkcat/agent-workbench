import { useEffect, useState } from 'react';
import { X } from 'lucide-react';
import { FileContentRenderer, type FilePreview } from './MessageBubble';
import type { FileContentPayload } from '../types';

export function FilePreviewModal({ file, onClose }: { file: FilePreview | null; onClose: () => void }) {
  const [payload, setPayload] = useState<FileContentPayload | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!file) return;
    let cancelled = false;
    setLoading(true);
    setError('');
    setPayload(null);
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
        if (!cancelled) setPayload(nextPayload);
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
        {!loading && !error && payload ? <FileContentRenderer payload={payload} /> : null}
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
