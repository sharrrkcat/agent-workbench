import { useWorkbenchStore } from '../store/useWorkbenchStore';

type PaletteMode = 'commands' | 'agents' | 'actions' | 'none';

export function CommandPalette({ mode, token, onPick }: { mode: PaletteMode; token: string; onPick: (value: string) => void }) {
  const { agents, commands } = useWorkbenchStore();
  if (mode === 'none') return null;

  const actionAgentId = token.match(/^@([a-zA-Z][a-zA-Z0-9_-]*):/)?.[1];
  const agent = agents.find((item) => item.id === actionAgentId);
  const query = token.slice(1).toLowerCase();
  const actionQuery = token.split(':')[1]?.toLowerCase() ?? '';

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
            .filter((action) => action.id !== 'default' && action.callable)
            .filter((action) => action.id.toLowerCase().startsWith(actionQuery))
            .map((action) => ({
              key: action.id,
              label: `${agent.id}:${action.id}`,
              detail: action.description,
              value: `@${agent.id}:${action.id} `,
              disabled: !agent.enabled,
            }))
        : agents
            .filter((item) => item.id.toLowerCase().startsWith(query))
            .map((item) => ({
              key: item.id,
              label: item.enabled ? `@${item.id}` : `@${item.id} (disabled)`,
              detail: item.description,
              value: `@${item.id} `,
              disabled: !item.enabled,
            }));

  if (!items.length) return null;

  return (
    <div className="command-palette">
      {items.map((item) => (
        <button type="button" key={item.key} onClick={() => onPick(item.value)} className={item.disabled ? 'disabled' : ''}>
          <span>{item.label}</span>
          <small>{item.detail}</small>
        </button>
      ))}
    </div>
  );
}
