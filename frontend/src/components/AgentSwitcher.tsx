import { Bot, ChevronDown } from 'lucide-react';
import { useWorkbenchStore } from '../store/useWorkbenchStore';

export function AgentSwitcher() {
  const { agents, currentSession, updateDefaultAgent } = useWorkbenchStore();

  return (
    <label className="agent-switcher">
      <Bot size={16} />
      <select
        value={currentSession?.default_agent_id || 'chat'}
        onChange={(event) => void updateDefaultAgent(event.target.value)}
        disabled={!currentSession}
      >
        {agents.map((agent) => (
          <option key={agent.id} value={agent.id} disabled={!agent.enabled}>
            {agent.name}{agent.enabled ? '' : ' (disabled)'}
          </option>
        ))}
      </select>
      <ChevronDown size={15} className="agent-switcher-caret" />
    </label>
  );
}
