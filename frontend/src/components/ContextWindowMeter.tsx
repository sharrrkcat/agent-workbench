import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { HoverCard, HoverCardContent, HoverCardTrigger } from '@/components/ui/hover-card';
import { InputGroupButton } from '@/components/ui/input-group';
import { useCogitaStore } from '../store/useCogitaStore';
import type { ModelProfile } from '../types/models';
import type { Run } from '../types/runs';
import { configuredContextWindow, latestContextUsage } from './contextUsage';

export function ContextWindowMeter({ profile, generating, runs: suppliedRuns }: { profile: ModelProfile | undefined; generating: boolean; runs?: Run[] }) {
  const { t, i18n } = useTranslation('chat');
  const sessionId = useCogitaStore((state) => state.currentSession?.session_id);
  const runs = useCogitaStore((state) => state.runs);
  const usage = latestContextUsage(suppliedRuns ?? runs, sessionId, profile);
  const configured = configuredContextWindow(profile);
  const [open, setOpen] = useState(false);
  const pressed = useRef(false);
  const number = (value: number) => value.toLocaleString(i18n.language);
  const percent = usage?.ratio == null ? null
    : usage.ratio.toLocaleString(i18n.language, { style: 'percent', maximumFractionDigits: 1 });
  const empty = t(configured === null ? 'contextMeter.windowUnknown' : usage ? 'contextMeter.usageUnknown' : 'contextMeter.noCalls');
  const label = percent === null ? empty : `${percent} · ${number(usage!.used!)} / ${number(usage!.budget.window_tokens)} tokens`;

  return <HoverCard open={open} onOpenChange={(next, event) => {
    if (!next && pressed.current && (event.reason === 'trigger-hover' || event.reason === 'trigger-focus')) return;
    if (!next) pressed.current = false;
    setOpen(next);
  }}>
    <HoverCardTrigger delay={150} closeDelay={150} render={<InputGroupButton variant="ghost" size="icon-sm"
      className="context-meter rounded-full" aria-label={`${t('contextMeter.title')}: ${label}`}
      onFocus={() => setOpen(true)} onClick={() => { pressed.current = true; setOpen(true); }} />}>
      <svg viewBox="0 0 24 24" className="context-meter-ring" aria-hidden="true"
        data-known={percent !== null} data-full={usage?.used != null && usage.used > usage.budget.window_tokens}>
        <circle className="context-meter-track" cx="12" cy="12" r="9" />
        <circle className="context-meter-fill" cx="12" cy="12" r="9" pathLength="100"
          strokeDasharray={`${Math.min(100, Math.max(0, (usage?.ratio ?? 0) * 100))} 100`} />
      </svg>
    </HoverCardTrigger>
    <HoverCardContent side="top" align="end" className="context-meter-card">
      <p className="font-medium">{t('contextMeter.title')}</p>
      {generating ? <p className="text-muted-foreground">{t('contextMeter.generating')}</p> : null}
      <p className="context-meter-value">{label}</p>
      <dl>
        <div><dt>{t('contextMeter.output')}</dt><dd>{usage ? number(usage.budget.output_tokens) : '—'}</dd></div>
        <div><dt>{t('contextMeter.inputBudget')}</dt><dd>{usage ? number(usage.budget.input_budget_tokens) : '—'}</dd></div>
        {usage && usage.budget.removed_turns > 0 ? <div><dt>{t('contextMeter.removed')}</dt><dd>{number(usage.budget.removed_turns)}</dd></div> : null}
      </dl>
    </HoverCardContent>
  </HoverCard>;
}
