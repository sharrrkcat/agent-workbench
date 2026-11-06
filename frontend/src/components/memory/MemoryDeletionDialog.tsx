import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { FieldGroup, FieldLegend, FieldSet } from '@/components/ui/field';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { memoriesApi } from '../../api/memories';
import { useCharactersStore } from '../../store/useCharactersStore';
import { usePersonasStore } from '../../store/usePersonasStore';
import type { MemoryDeletionChoice, MemoryDeletionPreview } from '../../types/memory';
import { Feedback, ResourceLoading, errorText } from '../settings/resources/ResourceUI';
import { MemorySelect } from './MemoryFields';

export function MemoryDeletionDialog({ kind, id, name, onClose, onDelete }: {
  kind: 'session' | 'character'; id: string; name: string; onClose: () => void;
  onDelete: (choice: MemoryDeletionChoice) => Promise<void>;
}) {
  const { t } = useTranslation('memory');
  const [preview, setPreview] = useState<MemoryDeletionPreview | null>(null);
  const [choice, setChoice] = useState<MemoryDeletionChoice>({});
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false); const [reload, setReload] = useState(0);
  const characters = useCharactersStore((s) => s.characters).filter((c) => c.kind === 'normal' && c.id !== id);
  const personas = usePersonasStore((s) => s.personas);
  useEffect(() => {
    let live = true; setPreview(null); setChoice({}); setError('');
    void Promise.all([memoriesApi.deletionPreview(kind, id), useCharactersStore.getState().reload(), usePersonasStore.getState().reload()])
      .then(([value]) => { if (live) { setPreview(value); setChoice({ expected_revision: value.revision }); } })
      .catch((reason) => { if (live) setError(errorText(reason)); });
    return () => { live = false; };
  }, [kind, id, reload]);
  const ready = preview && (!preview.local.length || !!choice.local) && (!preview.general.length || !!choice.general)
    && (choice.local !== 'transfer' || !!choice.target_character_id);
  async function remove() {
    if (!ready || busy) return; setBusy(true); setError('');
    try { await onDelete(choice); onClose(); }
    catch (reason) { setError(errorText(reason)); }
    finally { setBusy(false); }
  }
  return <Dialog open onOpenChange={(open) => { if (!open && !busy) onClose(); }}><DialogContent className="sm:max-w-3xl">
    <DialogHeader><DialogTitle>{t('deleteOwner', { name })}</DialogTitle></DialogHeader>
    <div className="settings-dialog-body"><Feedback error={error} />
      {!preview ? <ResourceLoading error={error} retry={() => setReload((v) => v + 1)} /> : <FieldGroup>
        {(['local', 'general'] as const).map((pool) => preview[pool].length ? <FieldSet key={pool} disabled={busy}>
          <FieldLegend>{t(pool === 'local' ? 'deleteLocal' : 'deleteGeneral', { count: preview[pool].length })}</FieldLegend>
          <div className="max-h-44 overflow-y-auto"><ul className="flex list-disc flex-col gap-2 pl-5">
            {preview[pool].map((entry) => <li key={entry.id}>{entry.summary} <span className="settings-note">· {personas.find((p) => p.id === entry.persona_id)?.name ?? t('deletedSource')}</span></li>)}
          </ul></div>
          <ToggleGroup variant="outline" className="flex-wrap" value={choice[pool] ? [choice[pool]!] : []}
            aria-label={t(pool === 'local' ? 'deleteLocal' : 'deleteGeneral', { count: preview[pool].length })}
            onValueChange={(values) => setChoice((current) => ({ ...current, [pool]: values[0] }))}>
            <ToggleGroupItem value="delete">{t('delete')}</ToggleGroupItem>
            {pool === 'general' || kind === 'session' ? <ToggleGroupItem value="keep">{t('keep')}</ToggleGroupItem> : <>
              <ToggleGroupItem value="transfer">{t('transfer')}</ToggleGroupItem><ToggleGroupItem value="publish">{t('publishAll')}</ToggleGroupItem>
            </>}
          </ToggleGroup>
          {pool === 'local' && choice.local === 'keep' ? <p className="settings-note">{t('keepSessionNotice')}</p> : null}
          {pool === 'local' && choice.local === 'publish' ? <p className="settings-note">{t('publishAllNotice')}</p> : null}
          {pool === 'local' && choice.local === 'transfer' ? <MemorySelect label={t('destination')} value={choice.target_character_id ?? ''}
            options={[{ value: '', label: t('choose') }, ...characters.map((c) => ({ value: c.id, label: c.name }))]}
            onChange={(target_character_id) => setChoice({ ...choice, target_character_id })} /> : null}
        </FieldSet> : null)}
      </FieldGroup>}
    </div>
    <DialogFooter><Button type="button" variant="outline" disabled={busy} onClick={onClose}>{t('cancel')}</Button>
      {error ? <Button type="button" variant="outline" disabled={busy} onClick={() => setReload((v) => v + 1)}>{t('reload')}</Button> : null}
      <Button type="button" variant="destructive" disabled={busy || !ready} onClick={() => void remove()}>{t('deleteConfirm')}</Button></DialogFooter>
  </DialogContent></Dialog>;
}
