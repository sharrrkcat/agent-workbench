import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { BookOpen, Database, Save, Settings2, UserRound, X } from 'lucide-react';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Drawer, DrawerContent, DrawerFooter, DrawerHeader, DrawerTitle } from '@/components/ui/drawer';
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia } from '@/components/ui/empty';
import { Field, FieldGroup, FieldLabel, FieldSet } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { useConfirmDialog } from '@/hooks/useConfirmDialog';
import { useIsMobile } from '@/hooks/use-mobile';
import { cn } from '@/lib/utils';
import { toolsApi } from '../../api/tools';
import { API_BASE_URL, resolveAttachmentUrlFromBase } from '../../api/url';
import { useCharactersStore } from '../../store/useCharactersStore';
import { useCogitaStore } from '../../store/useCogitaStore';
import { useModelsStore } from '../../store/useModelsStore';
import { usePersonasStore } from '../../store/usePersonasStore';
import type { NormalCharacter } from '../../types/characters';
import type { HarnessTool } from '../../types/tools';
import { ContextAdvancedFields, ContextFields, GenerationFields, ModelField, PersonaField, ToolsField } from '../personas/ConfigurationFields';
import { IdentityAvatarField } from '../personas/IdentityAvatarField';
import { MemoryEnabledField } from '../memory/MemoryFields';
import { MemoryManager } from '../memory/MemoryManager';
import { Feedback, ResourceLoading, errorText, type LeaveGuard } from '../settings/resources/ResourceUI';

const sections = {
  profile: ['name', 'avatar_attachment_id', 'system_prompt'],
  execution: ['persona_id', 'model_profile_id', 'temperature', 'reasoning', 'harness_enabled'],
  context: ['context_policy'],
  memory: ['memory_enabled', 'memory_external_isolation'],
  tools: ['tools_allowed'],
  advanced: ['context_policy'],
} as const;
type Section = keyof typeof sections;
type DrawerSection = 'profile' | 'tools' | 'advanced';
type Setting = typeof sections[Section][number];
type Values = Pick<NormalCharacter, Setting>;
type SectionFeedback = { error: string; notice?: string };
const allKeys = [...new Set(Object.values(sections).flat())];
const equal = (left: unknown, right: unknown) => JSON.stringify(left) === JSON.stringify(right);
const pick = (values: Values, keys: readonly Setting[]) => Object.fromEntries(keys.map((key) => [key, values[key]])) as Partial<Values>;

export function CharacterSettings({ character, onLeaveGuardChange }: {
  character: NormalCharacter; onLeaveGuardChange: (guard: LeaveGuard) => void;
}) {
  const { t } = useTranslation('personas');
  const { confirm, confirmation } = useConfirmDialog();
  const mobile = useIsMobile();
  const id = useId();
  const [draft, setDraft] = useState(() => pick(character, allKeys) as Values);
  const [baseline, setBaseline] = useState(draft);
  const [feedback, setFeedback] = useState<Partial<Record<Section, SectionFeedback>>>({});
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [reload, setReload] = useState(0);
  const [tools, setTools] = useState<HarnessTool[]>([]);
  const [memoryActions, setMemoryActions] = useState<HTMLDivElement | null>(null);
  const personas = usePersonasStore((state) => state.personas);
  const profiles = useModelsStore((state) => state.profiles);
  const [drawerSection, setDrawerSection] = useState<DrawerSection | null>(null);
  const drawerSnapshot = useRef<Partial<Values>>({});
  const profileTrigger = useRef<HTMLButtonElement>(null);
  const toolsTrigger = useRef<HTMLButtonElement>(null);
  const advancedTrigger = useRef<HTMLButtonElement>(null);
  const live = useRef(true);
  const status = useRef({ dirty: false, busy: false });
  const locked = busy || uploading;
  status.current = { dirty: !equal(draft, baseline), busy: locked };
  const changed = (section: Section) => sections[section].some((key) => !equal(draft[key], baseline[key]));
  const update = (values: Partial<Values>) => setDraft((current) => ({ ...current, ...values }));
  const guard = useCallback<LeaveGuard>(async () => !status.current.busy &&
    (!status.current.dirty || await confirm(t('discardChanges'))), [confirm, t]);

  useEffect(() => { onLeaveGuardChange(guard); return () => onLeaveGuardChange(async () => true); }, [guard, onLeaveGuardChange]);
  useEffect(() => {
    live.current = true;
    const unload = (event: BeforeUnloadEvent) => {
      if (status.current.dirty || status.current.busy) { event.preventDefault(); event.returnValue = ''; }
    };
    window.addEventListener('beforeunload', unload);
    return () => { live.current = false; window.removeEventListener('beforeunload', unload); };
  }, []);
  useEffect(() => {
    let active = true;
    setLoading(true); setLoadError('');
    void Promise.all([toolsApi.listTools(), usePersonasStore.getState().reload(), useModelsStore.getState().reloadProfiles()])
      .then(([catalog]) => { if (active) { setTools(catalog.filter((tool) => tool.scope !== 'qqbot')); setLoading(false); } })
      .catch((reason) => { if (active) setLoadError(errorText(reason)); });
    return () => { active = false; };
  }, [reload]);

  async function save(section: Section, next = draft, automatic = false, fields: readonly Setting[] = sections[section]) {
    if (status.current.busy) return;
    const keys = fields.filter((key) => !equal(next[key], baseline[key]));
    if (!keys.length) return;
    const previous = pick(baseline, keys);
    status.current.busy = true; setBusy(true);
    setFeedback((current) => ({ ...current, [section]: { error: '' } }));
    try {
      const saved = await useCharactersStore.getState().patch(character.id, pick(next, keys));
      if (!live.current || saved.kind !== 'normal') return;
      const values = pick(saved, keys);
      setDraft((current) => ({ ...current, ...values }));
      setBaseline((current) => ({ ...current, ...values }));
      Object.assign(drawerSnapshot.current, values);
      setFeedback((current) => ({ ...current, [section]: { error: '', notice: automatic ? undefined : t('saved') } }));
      void useCogitaStore.getState().refreshCurrent();
    } catch (reason) {
      if (live.current) {
        if (automatic) update(previous);
        setFeedback((current) => ({ ...current, [section]: { error: errorText(reason) } }));
      }
    } finally {
      if (live.current) { status.current.busy = false; setBusy(false); }
    }
  }
  function autosave(section: 'execution' | 'context' | 'memory', values: Partial<Values>) {
    if (status.current.busy) return;
    const next = { ...draft, ...values };
    update(values);
    void save(section, next, true, Object.keys(values) as Setting[]);
  }
  function openDrawer(section: DrawerSection) {
    if (status.current.busy) return;
    drawerSnapshot.current = pick(draft, sections[section]);
    setFeedback((current) => ({ ...current, [section]: { error: '' } }));
    setDrawerSection(section);
  }
  async function closeDrawer() {
    if (status.current.busy || !drawerSection) return;
    const keys = sections[drawerSection];
    const dirty = keys.some((key) => !equal(draft[key], drawerSnapshot.current[key]));
    if (dirty && !(await confirm(t('discardChanges')))) return;
    if (dirty) update(pick(drawerSnapshot.current as Values, keys));
    setDrawerSection(null);
  }
  const sectionForm = (section: Section, title: string, children: ReactNode, unavailable = false) => (
    <form aria-label={title} onSubmit={(event) => event.preventDefault()}>
      <CardContent className="flex flex-col gap-3"><FieldSet disabled={locked || unavailable}><FieldGroup>{children}</FieldGroup></FieldSet>
        <Feedback {...(feedback[section] ?? { error: '' })} />
      </CardContent>
    </form>
  );
  const drawerTitles = { profile: t('characterCards.profile'), tools: t('harnessSettings'), advanced: t('compactionAdvanced') };
  const triggers = { profile: profileTrigger, tools: toolsTrigger, advanced: advancedTrigger };

  return <div className="character-settings">
    <div className="character-settings-grid">
      <div className="character-settings-column" data-character-column="profile">
        <Card className="character-profile-card py-8" data-character-card="profile">
          <CardHeader className="justify-items-center gap-3 px-5 text-center">
            <Avatar className="size-20">
              {baseline.avatar_attachment_id ? <AvatarImage src={resolveAttachmentUrlFromBase(API_BASE_URL, `local://attachments/${baseline.avatar_attachment_id}`)} alt={baseline.name} /> : null}
              <AvatarFallback><UserRound /></AvatarFallback>
            </Avatar>
            <CardTitle className="w-full break-words">{baseline.name}</CardTitle>
          </CardHeader>
          <CardContent className="px-5"><CardDescription className="line-clamp-4 whitespace-pre-wrap break-words" data-profile-prompt>
            {baseline.system_prompt || t('characterCards.emptyPrompt')}
          </CardDescription></CardContent>
          <button ref={profileTrigger} type="button" className="absolute inset-0 cursor-pointer rounded-[inherit] outline-none"
            aria-label={t('characterCards.editProfile')} aria-haspopup="dialog" disabled={locked} onClick={() => openDrawer('profile')} />
        </Card>
        <Card data-character-card="memory">
          <CardHeader><CardTitle>{t('characterCards.memorySettings')}</CardTitle></CardHeader>
          {sectionForm('memory', t('characterCards.memorySettings'), <>
            <MemoryEnabledField value={draft.memory_enabled} onChange={(memory_enabled) => autosave('memory', { memory_enabled })} />
            <Field orientation="horizontal"><Switch id={id + '-isolation'} checked={draft.memory_external_isolation} onCheckedChange={(memory_external_isolation) => autosave('memory', { memory_external_isolation })} />
              <FieldLabel htmlFor={id + '-isolation'}>{t('memory:externalIsolation')}</FieldLabel></Field>
          </>)}
          <CardFooter ref={setMemoryActions} />
        </Card>
      </div>
      <div className="character-settings-column" data-character-column="execution">
        <Card data-character-card="execution">
          <CardHeader><CardTitle>{t('characterCards.execution')}</CardTitle>
            {loading ? <ResourceLoading error={loadError} retry={() => setReload((value) => value + 1)} /> : null}</CardHeader>
          {sectionForm('execution', t('characterCards.execution'), <>
            <PersonaField label={t('defaultPersona')} personas={personas} value={draft.persona_id} onChange={(persona_id) => autosave('execution', { persona_id })} />
            <ModelField profiles={profiles} value={draft.model_profile_id} inheritLabel={t('selectModel')} onChange={(value) => autosave('execution', { model_profile_id: value || null })} />
            <GenerationFields value={{ temperature: draft.temperature }} onChange={(value) => update({ temperature: value.temperature ?? null })}
              onCommit={() => autosave('execution', { temperature: draft.temperature })} />
            <Field orientation="horizontal"><Switch id={id + '-reasoning'} checked={draft.reasoning} onCheckedChange={(reasoning) => autosave('execution', { reasoning })} />
              <FieldLabel htmlFor={id + '-reasoning'}>{t('reasoning')}</FieldLabel></Field>
            <Field orientation="horizontal" className="[&>[data-slot=field-label]]:flex-none">
              <Switch id={id + '-harness'} checked={draft.harness_enabled} onCheckedChange={(harness_enabled) => autosave('execution', { harness_enabled })} />
              <FieldLabel htmlFor={id + '-harness'}>{t('harness')}</FieldLabel>
              <Button ref={toolsTrigger} type="button" variant="ghost" size="icon" aria-haspopup="dialog" aria-label={t('characterCards.configureTools')}
                title={t('characterCards.configureTools')} onClick={() => openDrawer('tools')}><Settings2 /></Button>
            </Field>
          </>, loading)}
        </Card>
        <Card data-character-card="context">
          <CardHeader><CardTitle>{t('context')}</CardTitle></CardHeader>
          {sectionForm('context', t('context'), <ContextFields value={draft.context_policy} harnessEnabled={draft.harness_enabled}
            onChange={(context_policy) => {
              if (!equal(context_policy.message_window, draft.context_policy.message_window)) update({ context_policy });
              else {
                // Numeric edits are committed separately; switches never submit an unfinished count.
                const policy = { ...context_policy, message_window: baseline.context_policy.message_window };
                autosave('context', { context_policy: policy });
              }
            }}
            onMessageLimitCommit={() => autosave('context', { context_policy: draft.context_policy })}
            advancedAction={<Button ref={advancedTrigger} type="button" variant="ghost" size="icon" aria-haspopup="dialog"
              aria-label={t('compactionAdvanced')} title={t('compactionAdvanced')} onClick={() => openDrawer('advanced')}><Settings2 /></Button>} />)}
        </Card>
      </div>
      <div className="character-settings-column" data-character-column="resources">
        {(['knowledge', 'worldbook'] as const).map((resource) => {
          const Icon = resource === 'knowledge' ? Database : BookOpen;
          return <Card key={resource} data-character-card={resource}>
            <CardHeader><CardTitle>{t(resource)}</CardTitle></CardHeader>
            <CardContent className="flex flex-1"><Empty><EmptyHeader>
              <EmptyMedia variant="icon"><Icon /></EmptyMedia>
              <EmptyDescription>{t('characterCards.resourceUnavailable')}</EmptyDescription>
            </EmptyHeader></Empty></CardContent>
          </Card>;
        })}
      </div>
    </div>
      <Card className="character-memory-list" data-character-card="memories">
        <CardHeader><CardTitle>{t('characterCards.memories')}</CardTitle></CardHeader>
        <CardContent><MemoryManager characterId={character.id} addButtonContainer={memoryActions} /></CardContent>
      </Card>
    {(['profile', 'tools', 'advanced'] as const).map((section) => <Drawer key={section} open={drawerSection === section}
      swipeDirection={mobile ? 'down' : 'right'} showSwipeHandle={mobile} onOpenChange={(open) => { if (!open) void closeDrawer(); }}>
      <DrawerContent className={cn('data-[swipe-axis=y]:max-h-[90dvh]', section === 'profile'
        ? 'data-[swipe-axis=x]:w-[30rem] data-[swipe-axis=y]:h-[90dvh]' : 'data-[swipe-axis=x]:w-96')}
        finalFocus={triggers[section]}>
        <DrawerHeader className="flex-row items-center justify-between pb-4">
          <DrawerTitle>{drawerTitles[section]}</DrawerTitle>
          <Button type="button" variant="ghost" size="icon" aria-label={t('close')} disabled={locked} onClick={() => void closeDrawer()}><X /></Button>
        </DrawerHeader>
        <form aria-label={section === 'tools' ? t('tools') : drawerTitles[section]} className="flex min-h-0 flex-1 flex-col"
          onSubmit={(event) => { event.preventDefault(); void save(section); }}>
          <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto overscroll-contain px-4 pb-4">
            <FieldSet disabled={locked} className={section === 'profile' ? 'min-h-0 flex-1' : undefined}>
              {section === 'profile' ? <FieldGroup className="min-h-0 flex-1">
              <IdentityAvatarField name={draft.name} value={draft.avatar_attachment_id} persistedValue={baseline.avatar_attachment_id} disabled={locked}
                onChange={(avatar_attachment_id) => update({ avatar_attachment_id })}
                onBusyChange={(value) => { status.current.busy = value; setUploading(value); }}
                onError={(error) => setFeedback((current) => ({ ...current, profile: { error } }))} />
              <Field><FieldLabel htmlFor={id + '-name'}>{t('characterName')}</FieldLabel>
                <Input id={id + '-name'} required maxLength={128} value={draft.name} onChange={(event) => update({ name: event.target.value })} /></Field>
              <Field className="min-h-40 flex-1"><FieldLabel htmlFor={id + '-prompt'}>{t('systemPrompt')}</FieldLabel>
                <Textarea id={id + '-prompt'} className="min-h-32 flex-1 field-sizing-fixed" rows={4} maxLength={100000} value={draft.system_prompt}
                  onChange={(event) => update({ system_prompt: event.target.value })} /></Field>
              </FieldGroup> : section === 'tools' ? loading ? <ResourceLoading error={loadError} retry={() => setReload((value) => value + 1)} /> :
                <ToolsField tools={tools} value={draft.tools_allowed} onChange={(tools_allowed) => update({ tools_allowed })} /> :
                <ContextAdvancedFields value={draft.context_policy} onChange={(context_policy) => update({ context_policy })} />}
            </FieldSet>
          </div>
          <DrawerFooter>
            <Feedback {...(feedback[section] ?? { error: '' })} />
            <Button type="submit" disabled={locked || (section === 'tools' && loading) || !changed(section)}><Save data-icon="inline-start" />{t('save')}</Button>
          </DrawerFooter>
        </form>
        {drawerSection === section ? confirmation : null}
      </DrawerContent>
    </Drawer>)}
    {!drawerSection ? confirmation : null}
  </div>;
}
