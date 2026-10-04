import { useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Field, FieldGroup, FieldLabel, FieldSet } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectGroup, SelectItem } from '@/components/ui/select';
import { useConfirmDialog } from '@/hooks/useConfirmDialog';
import { Feedback, errorText } from '../settings/resources/ResourceUI';
import { qqApi } from '../../api/qq';
import { useCogitaStore } from '../../store/useCogitaStore';

export function QQSessionDialog({ projectId, onClose, onSaved }: {
  projectId: string; onClose: () => void; onSaved: (id: string) => void;
}) {
  const { t } = useTranslation('personas');
  const id = useId();
  const { confirm, confirmation } = useConfirmDialog();
  const [title, setTitle] = useState('');
  const [kind, setKind] = useState<'group' | 'friend'>('group');
  const [target, setTarget] = useState('');
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const [error, setError] = useState('');
  async function close() {
    if (lock.current) return;
    if ((title || target) && !(await confirm(t('discardChanges')))) return;
    onClose();
  }
  async function save() {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError('');
    try {
      const session = await qqApi.createSession(projectId, { title, target_kind: kind, target_id: target });
      await useCogitaStore.getState().reloadSessions(projectId);
      onSaved(session.session_id);
    } catch (reason) { setError(errorText(reason)); }
    finally { lock.current = false; setBusy(false); }
  }
  return <Dialog open onOpenChange={(open) => { if (!open) void close(); }}>
    <DialogContent><DialogHeader><DialogTitle>{t('qq.bindConversation')}</DialogTitle></DialogHeader>
      <form onSubmit={(e) => { e.preventDefault(); void save(); }}><FieldSet disabled={busy}><FieldGroup>
        <Feedback error={error} />
        <Field><FieldLabel htmlFor={id + '-title'}>{t('qq.sessionTitle')}</FieldLabel><Input id={id + '-title'} value={title} maxLength={120} onChange={(e) => setTitle(e.target.value)} /></Field>
        <Field><FieldLabel htmlFor={id + '-kind'}>{t('qq.targetKind')}</FieldLabel>
          <Select value={kind} items={['group', 'friend'].map((value) => ({ value, label: t('qq.' + value) }))} onValueChange={(value) => { if (value === 'group' || value === 'friend') setKind(value); }}>
            <SelectTrigger id={id + '-kind'}><SelectValue /></SelectTrigger><SelectContent><SelectGroup><SelectItem value="group">{t('qq.group')}</SelectItem><SelectItem value="friend">{t('qq.friend')}</SelectItem></SelectGroup></SelectContent>
          </Select>
        </Field>
        <Field><FieldLabel htmlFor={id + '-target'}>{t('qq.targetId')}</FieldLabel><Input id={id + '-target'} required inputMode="numeric" pattern="[1-9][0-9]{0,19}" value={target} onChange={(e) => setTarget(e.target.value)} /></Field>
        <Button type="submit" disabled={busy}>{t('qq.bindConversation')}</Button>
      </FieldGroup></FieldSet></form>{confirmation}
    </DialogContent>
  </Dialog>;
}
