import { useEffect, useState, type RefObject } from 'react';
import { useTranslation } from 'react-i18next';
import { Save, Undo2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { FieldGroup, FieldLegend, FieldSet } from '@/components/ui/field';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription, SheetFooter } from '@/components/ui/sheet';
import { useConfirmDialog } from '@/hooks/useConfirmDialog';
import { toolsApi } from '../../api/tools';
import { useCogitaStore } from '../../store/useCogitaStore';
import { useProjectsStore } from '../../store/useProjectsStore';
import type { ChatDraft, Session } from '../../types/chat';
import type { HarnessTool } from '../../types/tools';
import { Feedback, ResourceLoading, errorText } from '../settings/resources/ResourceUI';
import { ToolsField } from './ConfigurationFields';

export function HarnessSettingsSheet({ session, onClose, finalFocus, onBusyChange }: {
  session: Session | ChatDraft; onClose: () => void;
  finalFocus: RefObject<HTMLButtonElement | null>; onBusyChange: (busy: boolean) => void;
}) {
  const { t } = useTranslation('personas');
  const { confirm, confirmation } = useConfirmDialog();
  const updateSession = useCogitaStore((state) => state.updateSession);
  const sessionVersion = useCogitaStore((state) => state.sessionVersion);
  const sessionEpoch = useCogitaStore((state) => state.sessionEpoch);
  const project = useProjectsStore((state) => state.projects.find((item) => item.id === session.project_id));
  const workspace = project?.kind === 'workspace' ? project : null;
  const [initialTools] = useState(() => session.kind === 'ordinary' ? session.tools_allowed : session.overrides.tools_allowed ?? null);
  const [selectedTools, setSelectedTools] = useState(initialTools);
  const [restoreHarness, setRestoreHarness] = useState(false);
  const [tools, setTools] = useState<HarnessTool[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  const toolsChanged = JSON.stringify(selectedTools) !== JSON.stringify(initialTools);
  const dirty = toolsChanged || restoreHarness;
  const inheritedHarness = session.kind === 'workspace' && (restoreHarness || session.overrides.harness_enabled == null);

  useEffect(() => { setOpen(true); }, []);

  useEffect(() => {
    let live = true;
    setError('');
    setLoading(true);
    void toolsApi.listTools().then((catalog) => {
      if (live) { setTools(catalog); setLoading(false); }
    }).catch((reason) => { if (live) setError(errorText(reason)); });
    return () => { live = false; };
  }, [reload]);
  useEffect(() => {
    if (!session.project_id) return;
    let live = true;
    void useProjectsStore.getState().load(session.project_id)
      .catch((reason) => { if (live) setError(errorText(reason)); });
    return () => { live = false; };
  }, [session.project_id, sessionVersion, reload]);

  async function close() {
    if (!busy && (!dirty || await confirm(t('discardChanges')))) setOpen(false);
  }
  async function save() {
    if (busy || !dirty) return;
    setBusy(true); onBusyChange(true); setError('');
    const saved = await updateSession(session.kind === 'workspace' ? { overrides: {
      ...(restoreHarness ? { harness_enabled: null } : {}),
      ...(toolsChanged ? { tools_allowed: selectedTools } : {}),
    } } : { tools_allowed: selectedTools! });
    if (useCogitaStore.getState().sessionEpoch !== sessionEpoch) return;
    setBusy(false); onBusyChange(false);
    if (saved) setOpen(false);
    else setError(useCogitaStore.getState().error ?? '');
  }
  return <Sheet open={open} onOpenChange={(next) => { if (!next) void close(); }}
    onOpenChangeComplete={(next) => { if (!next) onClose(); }}>
    <SheetContent side="right" className="data-[side=right]:w-full" finalFocus={finalFocus}>
      <SheetHeader>
        <SheetTitle>{t('harnessSettings')}</SheetTitle>
        <SheetDescription>{t('harnessSettingsDescription')}</SheetDescription>
      </SheetHeader>
      <form className="flex min-h-0 flex-1 flex-col" onSubmit={(event) => { event.preventDefault(); void save(); }}>
        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-6 pb-4">
          <Feedback error={error} />
          {loading || (session.kind === 'workspace' && !workspace)
            ? <ResourceLoading error={error} retry={() => setReload((value) => value + 1)} />
            : <FieldGroup>
              {session.kind === 'workspace' ? <FieldSet disabled={busy} className="gap-3">
                <FieldLegend>{t('harness')}</FieldLegend>
                <p className="settings-note">{t(inheritedHarness ? 'inheritedFromProject' : 'sessionOverride')}</p>
                <Button type="button" variant="ghost" size="sm" disabled={inheritedHarness}
                  aria-label={t('restoreInheritanceFor', { field: t('harness') })} onClick={() => setRestoreHarness(true)}>
                  <Undo2 data-icon="inline-start" />{t('restoreInheritance')}
                </Button>
              </FieldSet> : null}
              <FieldSet disabled={busy} className="gap-3">
                <FieldLegend>{t('tools')}</FieldLegend>
                {session.kind === 'workspace' ? <>
                  <p className="settings-note">{t(selectedTools === null ? 'inheritedFromProject' : 'sessionOverride')}</p>
                  <Button type="button" variant="ghost" size="sm" disabled={selectedTools === null}
                    aria-label={t('restoreInheritanceFor', { field: t('tools') })} onClick={() => setSelectedTools(null)}>
                    <Undo2 data-icon="inline-start" />{t('restoreInheritance')}
                  </Button>
                </> : null}
                <ToolsField tools={tools} value={selectedTools ?? workspace!.tools_allowed}
                  allowed={workspace?.tools_allowed} onChange={setSelectedTools} />
              </FieldSet>
            </FieldGroup>}
        </div>
        <SheetFooter>
          <Button type="submit" disabled={busy || loading || !dirty || (session.kind === 'workspace' && !workspace)}>
            <Save data-icon="inline-start" />{t('save')}
          </Button>
        </SheetFooter>
      </form>
      {confirmation}
    </SheetContent>
  </Sheet>;
}
