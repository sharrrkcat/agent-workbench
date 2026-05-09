import { useWorkbenchStore } from '../store/useWorkbenchStore';

type PaletteMode = 'commands' | 'agents' | 'actions' | 'current-actions' | 'none';

export function CommandPalette({ mode, token, onPick }: { mode: PaletteMode; token: string; onPick: (value: string) => void }) {
  const { agents, commands, currentSession } = useWorkbenchStore();
  if (mode === 'none') return null;

  const actionAgentId = token.match(/^@([a-zA-Z][a-zA-Z0-9_-]*):/)?.[1];
  const agent = agents.find((item) => item.id === actionAgentId);
  const currentAgent = agents.find((item) => item.id === currentSession?.default_agent_id);
  const query = token.slice(1).toLowerCase();
  const actionQuery = token.split(':')[1]?.toLowerCase() ?? '';
  const currentActionQuery = token.slice(1).toLowerCase();

  const items =
    mode === 'commands'
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
                  detail: action.description || `Current agent: ${currentAgent.name}`,
                  value: `:${action.id} `,
                  disabled: !currentAgent.enabled,
                }))
            : [
                {
                  key: 'no-current-agent',
                  label: 'No current agent selected.',
                  detail: '',
                  value: '',
                  disabled: true,
                },
              ]
        : agents
            .filter((item) => item.id.toLowerCase().startsWith(query))
            .map((item) => ({
              key: item.id,
              label: item.enabled ? `@${item.id}` : `@${item.id} (disabled)`,
              detail: item.description,
              value: `@${item.id} `,
              disabled: !item.enabled,
            }));

  const visibleItems =
    mode === 'current-actions' && !items.length
      ? [
          {
            key: 'no-current-agent-actions',
            label: 'No matching actions for current agent.',
            detail: '',
            value: '',
            disabled: true,
          },
        ]
      : items;

  if (!visibleItems.length) return null;

  return (
    <div className="command-palette">
      {visibleItems.map((item) => (
        <button type="button" key={item.key} onClick={() => !item.disabled && onPick(item.value)} className={item.disabled ? 'disabled' : ''} disabled={item.disabled}>
          <span>{item.label}</span>
          <small>{item.detail}</small>
        </button>
      ))}
    </div>
  );
}
