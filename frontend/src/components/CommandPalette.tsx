import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../api/client';
import { useWorkbenchStore } from '../store/useWorkbenchStore';
import type { Command } from '../types';

type PaletteMode = 'commands' | 'command-arguments' | 'agents' | 'actions' | 'current-actions' | 'none';

export type CommandPaletteItem = {
  key: string;
  label: string;
  detail?: string;
  value: string;
  disabled?: boolean;
};

export type CommandArgumentAutocompleteContext = {
  command: Command;
  prefix: string;
  args: string[];
  provider?: string;
  dynamic: boolean;
};

export function CommandPalette({
  mode,
  token,
  selectedIndex = 0,
  onPick,
  onItemsChange,
}: {
  mode: PaletteMode;
  token: string;
  selectedIndex?: number;
  onPick: (value: string) => void;
  onItemsChange?: (items: CommandPaletteItem[]) => void;
}) {
  const { t } = useTranslation();
  const { agents, commands, currentSession } = useWorkbenchStore();
  const [dynamicItems, setDynamicItems] = useState<CommandPaletteItem[]>([]);
  const requestSeqRef = useRef(0);
  const listRef = useRef<HTMLDivElement | null>(null);
  const actionAgentId = token.match(/^@([a-zA-Z][a-zA-Z0-9_-]*):/)?.[1];
  const agent = agents.find((item) => item.id === actionAgentId);
  const currentAgent = agents.find((item) => item.id === currentSession?.default_agent_id);
  const query = token.slice(1).toLowerCase();
  const actionQuery = token.split(':')[1]?.toLowerCase() ?? '';
  const currentActionQuery = token.slice(1).toLowerCase();
  const argumentContext = mode === 'command-arguments' ? parseCommandArgumentToken(token, commands) : null;
  const dynamicRequestKey = argumentContext?.dynamic
    ? `${argumentContext.command.name}\n${argumentContext.args.join('\n')}\n${argumentContext.prefix}\n${currentSession?.session_id || ''}`
    : '';

  useEffect(() => {
    if (!argumentContext?.dynamic || !argumentContext.provider) {
      requestSeqRef.current += 1;
      setDynamicItems([]);
      return;
    }
    const requestSeq = requestSeqRef.current + 1;
    requestSeqRef.current = requestSeq;
    setDynamicItems([]);
    const controller = new AbortController();
    const timeout = window.setTimeout(() => {
      void api
        .commandArgumentSuggestions(
          {
            command: argumentContext.command.name,
            args: argumentContext.args,
            prefix: argumentContext.prefix,
            session_id: currentSession?.session_id || null,
          },
          controller.signal,
        )
        .then((response) => {
          if (requestSeqRef.current !== requestSeq) return;
          setDynamicItems(
            response.suggestions.map((suggestion) => ({
              key: `${argumentContext.command.name}:${argumentContext.args.join(':')}:${suggestion.value}`,
              label: suggestion.label || suggestion.value,
              detail: suggestion.description || '',
              value: `${argumentContext.command.name} ${argumentContext.args[0]} ${suggestion.value} `,
            })),
          );
        })
        .catch(() => {
          if (requestSeqRef.current === requestSeq) setDynamicItems([]);
        });
    }, 150);
    return () => {
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [currentSession?.session_id, dynamicRequestKey]);

  const items: CommandPaletteItem[] =
    mode === 'none'
      ? []
      : mode === 'command-arguments' && argumentContext?.dynamic
      ? dynamicItems
      : mode === 'command-arguments' && argumentContext
      ? argumentContext.command.argument_suggestions
          ?.filter((suggestion) => suggestion.value.toLowerCase().startsWith(argumentContext.prefix.toLowerCase()))
          .map((suggestion) => ({
            key: `${argumentContext.command.name}:${suggestion.value}`,
            label: suggestion.label || suggestion.value,
            detail: suggestion.description || '',
            value: `${argumentContext.command.name} ${suggestion.value} `,
          })) ?? []
      : mode === 'commands'
      ? commands
          .filter((command) => command.name.toLowerCase().startsWith(token.toLowerCase()))
          .map((command) => ({
            key: command.name,
            label: command.capability_enabled ? command.name : `${command.name} (disabled)`,
            detail: command.description,
            value: `${command.name} `,
            disabled: !command.capability_enabled,
          }))
      : mode === 'actions' && agent
        ? agent.actions
            .filter((action) => action.id !== 'default' && action.callable !== false)
            .filter((action) => action.id.toLowerCase().startsWith(actionQuery))
            .map((action) => ({
              key: action.id,
              label: `${agent.id}:${action.id}`,
              detail: action.description,
              value: `@${agent.id}:${action.id} `,
              disabled: !agent.enabled,
            }))
        : mode === 'current-actions'
          ? currentAgent
            ? currentAgent.actions
                .filter((action) => action.callable !== false)
                .filter((action) => action.id.toLowerCase().startsWith(currentActionQuery))
                .map((action) => ({
                  key: action.id,
                  label: `:${action.id}`,
                  detail: action.description || t('chat:currentAgentDetail', { name: currentAgent.name }),
                  value: `:${action.id} `,
                  disabled: !currentAgent.enabled,
                }))
            : [
                {
                  key: 'no-current-agent',
                  label: t('chat:noCurrentAgent'),
                  detail: '',
                  value: '',
                  disabled: true,
                },
              ]
      : agents
            .filter((item) => item.id.toLowerCase().startsWith(query))
            .map((item) => ({
              key: item.id,
            label: item.enabled ? `@${item.id}` : `@${item.id} (${t('chat:disabledSuffix')})`,
              detail: item.description,
              value: `@${item.id} `,
              disabled: !item.enabled,
            }));

  const visibleItems =
    mode === 'current-actions' && !items.length
      ? [
          {
            key: 'no-current-agent-actions',
            label: t('chat:noMatchingActions'),
            detail: '',
            value: '',
            disabled: true,
          },
        ]
      : items;
  const enabledItems = useMemo(() => visibleItems.filter((item) => !item.disabled && item.value), [visibleItems]);

  useEffect(() => {
    onItemsChange?.(enabledItems);
  }, [enabledItems, onItemsChange]);

  const activeKey = enabledItems[Math.min(selectedIndex, Math.max(enabledItems.length - 1, 0))]?.key;

  useEffect(() => {
    if (!activeKey) return;
    const activeItem = listRef.current?.querySelector('[data-active="true"]') as HTMLElement | null;
    activeItem?.scrollIntoView({ block: 'nearest' });
  }, [activeKey]);

  if (mode === 'none' || !visibleItems.length) return null;

  return (
    <div className="command-palette" ref={listRef}>
      {mode === 'command-arguments' ? <div className="command-palette-heading">{t('chat:argumentSuggestions')}</div> : null}
      {visibleItems.map((item) => (
        <button type="button" key={item.key} data-active={item.key === activeKey ? 'true' : undefined} onClick={() => !item.disabled && onPick(item.value)} className={`${item.disabled ? 'disabled' : ''} ${item.key === activeKey ? 'selected' : ''}`.trim()} disabled={item.disabled}>
          <span>{item.label}</span>
          <small>{item.detail}</small>
        </button>
      ))}
    </div>
  );
}

export function commandArgumentAutocompleteMode(token: string, commands: Command[]): boolean {
  return parseCommandArgumentToken(token, commands) !== null;
}

export function parseCommandArgumentToken(token: string, commands: Command[]): CommandArgumentAutocompleteContext | null {
  const match = token.match(/^(\/[a-zA-Z][a-zA-Z0-9_-]*)(?:\s+([^\s]*)(?:\s+([^\s]*))?)?$/);
  if (!match) return null;
  const command = commands.find((item) => item.name === match[1]);
  if (!command?.argument_suggestions?.length) return null;
  const firstArg = match[2] ?? '';
  const secondArg = match[3];
  const firstSuggestion = command.argument_suggestions.find((suggestion) => suggestion.value === firstArg);
  if (firstSuggestion?.next_suggestions) {
    return {
      command,
      prefix: secondArg ?? '',
      args: [firstArg],
      provider: firstSuggestion.next_suggestions.provider,
      dynamic: true,
    };
  }
  if (secondArg !== undefined) return null;
  return { command, prefix: firstArg, args: [], dynamic: false };
}
