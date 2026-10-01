import { Fragment, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, Settings2 } from 'lucide-react';
import { InputGroupButton } from '@/components/ui/input-group';
import {
  DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuGroup,
  DropdownMenuLabel, DropdownMenuRadioGroup, DropdownMenuRadioItem,
  DropdownMenuCheckboxItem, DropdownMenuItem, DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu';
import { useCogitaStore } from '../store/useCogitaStore';
import { useModelsStore } from '../store/useModelsStore';
import { useChatConfiguration } from '../hooks/useChatConfiguration';
import type { SessionPatch } from '../types/chat';
import { HarnessSettingsSheet } from './personas/HarnessSettingsSheet';

export function ChatModelMenu({ disabled, onBusyChange }: {
  disabled: boolean; onBusyChange: (busy: boolean) => void;
}) {
  const { t } = useTranslation('personas');
  const session = useCogitaStore((state) => state.currentSession);
  const draft = useCogitaStore((state) => state.chatDraft);
  const updateSession = useCogitaStore((state) => state.updateSession);
  const sessionEpoch = useCogitaStore((state) => state.sessionEpoch);
  const profiles = useModelsStore((state) => state.profiles);
  const providers = useModelsStore((state) => state.providers);
  const configuration = useChatConfiguration();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const target = session ?? draft;
  const options = profiles.filter((profile) => profile.kind === 'llm');
  const selected = options.find((profile) => profile.id === configuration?.model_profile_id);
  const emptyLabel = t(options.some((profile) => profile.enabled) ? 'selectModel' : 'noModels');
  const label = selected ? selected.name + (selected.enabled ? '' : ` (${t('disabled')})`)
    : configuration?.model_profile_id ? t('unavailable') : emptyLabel;
  const groups = [
    { id: 'local', label: t('localModels'), models: options.filter((profile) => profile.source?.type === 'local') },
    ...providers.map((provider) => ({
      id: provider.id, label: provider.name,
      models: options.filter((profile) => profile.source?.type === 'provider' && profile.source.provider_profile_id === provider.id),
    })),
    { id: 'unconfigured', label: t('unconfiguredSource'), models: options.filter((profile) => !profile.source) },
    { id: 'unavailable', label: t('unavailable'), models: options.filter((profile) => profile.source?.type === 'provider'
      && !providers.some((provider) => profile.source?.type === 'provider' && provider.id === profile.source.provider_profile_id)) },
  ].filter((group) => group.models.length);

  async function save(patch: SessionPatch) {
    if (disabled || busy) return;
    setBusy(true);
    onBusyChange(true);
    await updateSession(patch);
    if (useCogitaStore.getState().sessionEpoch !== sessionEpoch) return;
    setBusy(false);
    onBusyChange(false);
  }

  return <>
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger render={<InputGroupButton ref={triggerRef} size="sm" variant="outline"
        className="chat-model-select h-7 max-w-30 min-w-0 rounded-full sm:max-w-40"
        aria-label={t('model')} title={label} disabled={disabled || busy} />}>
        <span className="truncate">{label}</span><ChevronDown data-icon="inline-end" />
      </DropdownMenuTrigger>
      <DropdownMenuContent side="top" align="end" className="w-64 max-w-[calc(100vw-1.5rem)]"
        onClick={(event) => event.stopPropagation()}
        finalFocus={editing ? false : triggerRef}>
        <DropdownMenuGroup aria-label={t('model')} aria-labelledby={undefined}>
          <DropdownMenuRadioGroup value={configuration?.model_profile_id ?? ''} onValueChange={(model_profile_id) => {
            if (model_profile_id !== configuration?.model_profile_id) void save(target?.kind === 'workspace'
              ? { overrides: { model_profile_id } } : { model_profile_id });
          }}>
            {groups.map((group) => <Fragment key={group.id}>
              <DropdownMenuLabel>{group.label}</DropdownMenuLabel>
              {group.models.map((profile) => <DropdownMenuRadioItem key={profile.id} value={profile.id}
                closeOnClick disabled={!profile.enabled || disabled || busy} title={profile.name}>
                <span className="truncate">{profile.name}{profile.enabled ? '' : ` (${t('disabled')})`}</span>
              </DropdownMenuRadioItem>)}
            </Fragment>)}
          </DropdownMenuRadioGroup>
          {!configuration?.model_profile_id || !selected ? <DropdownMenuItem disabled>{label}</DropdownMenuItem> : null}
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuGroup>
          <div className="flex items-center">
            <DropdownMenuCheckboxItem className="min-w-0 flex-1" checked={configuration?.harness_enabled ?? false}
              indicator={t(configuration?.harness_enabled ? 'harnessOn' : 'harnessOff')}
              disabled={disabled || busy} onCheckedChange={(harness_enabled) => void save(target?.kind === 'workspace'
                ? { overrides: { harness_enabled } } : { harness_enabled })}>
              {t('harness')}
            </DropdownMenuCheckboxItem>
            <DropdownMenuItem className="size-7 shrink-0 justify-center p-0 pointer-coarse:size-11"
              aria-label={t('harnessSettings')} title={t('harnessSettings')} disabled={disabled || busy}
              onClick={() => { setOpen(false); setEditing(true); }}>
              <Settings2 />
            </DropdownMenuItem>
          </div>
          <DropdownMenuCheckboxItem checked={configuration?.reasoning ?? true}
            indicator={t(configuration?.reasoning === false ? 'reasoningOff' : 'reasoningOn')}
            disabled={disabled || busy} onCheckedChange={(reasoning) => void save(target?.kind === 'workspace'
              ? { overrides: { reasoning } } : { reasoning })}>
            {t('reasoning')}
          </DropdownMenuCheckboxItem>
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
    {editing && target ? <HarnessSettingsSheet session={target} onClose={() => setEditing(false)}
      finalFocus={triggerRef} onBusyChange={onBusyChange} /> : null}
  </>;
}
