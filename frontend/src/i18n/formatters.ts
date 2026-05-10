import type { TFunction } from 'i18next';
import type { ApiError } from '../api/client';

export type DisplayError = {
  code: string;
  message: string;
  originalMessage?: string;
  details?: Record<string, unknown>;
};

export function getStatusLabel(status: string | undefined | null, t: TFunction, namespace = 'status:common'): string {
  if (!status) return '';
  return t(`${namespace}.${status}`, { defaultValue: humanizeStatus(status) });
}

export function getRunStatusLabel(status: string | undefined | null, t: TFunction): string {
  if (!status) return '';
  return t(`runs:status.${status}`, { defaultValue: humanizeStatus(status) });
}

export function getProviderStatusLabel(status: string | undefined | null, t: TFunction): string {
  if (!status) return '';
  return t(`status:llmProvider.${status}`, { defaultValue: humanizeStatus(status) });
}

export function getKnowledgeIndexStatusLabel(status: string | undefined | null, t: TFunction): string {
  if (!status) return '';
  return t(`status:knowledgeIndex.${status}`, { defaultValue: humanizeStatus(status) });
}

export function getKnowledgeSourceStatusLabel(status: string | undefined | null, t: TFunction): string {
  if (!status) return '';
  return t(`status:knowledgeSource.${status}`, { defaultValue: humanizeStatus(status) });
}

export function getRunStepLabel(label: string | undefined | null, t: TFunction): string {
  if (!label) return '';
  const key = normalizedRunStepKey(label);
  return key ? t(`runs:steps.${key}`, { defaultValue: label }) : label;
}

export function formatApiError(error: { code?: string; message?: string; details?: Record<string, unknown> } | ApiError, t: TFunction, fallback = ''): DisplayError {
  const code = typeof error.code === 'string' && error.code ? error.code : 'ERROR';
  const originalMessage = typeof error.message === 'string' ? error.message : '';
  const message = t(`errors:${code}`, { defaultValue: originalMessage || fallback || code });
  return {
    code,
    message,
    originalMessage: originalMessage && originalMessage !== message ? originalMessage : undefined,
    details: error.details,
  };
}

function normalizedRunStepKey(label: string): string {
  const normalized = label.trim().toLowerCase().replace(/[_-]+/g, ' ');
  if (normalized === 'building context') return 'buildingContext';
  if (normalized === 'calling llm' || normalized === 'llm') return 'callingLlm';
  if (normalized === 'running script') return 'runningScript';
  if (normalized === 'running command') return 'runningCommand';
  if (normalized === 'knowledge retrieval' || normalized === 'retrieving knowledge') return 'knowledgeRetrieval';
  if (normalized === 'preparing response') return 'preparingResponse';
  return '';
}

function humanizeStatus(value: string): string {
  return value
    .toLowerCase()
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (match) => match.toUpperCase());
}
