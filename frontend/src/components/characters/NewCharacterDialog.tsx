import { useCallback, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Field, FieldLabel, FieldDescription } from '@/components/ui/field';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import type { Character, CharacterKind } from '../../types/characters';
import type { LeaveGuard } from '../settings/resources/ResourceUI';
import type { SettingsNavigate } from '../settings/navigation';
import { CharacterEditor } from './CharacterEditor';

export function NewCharacterDialog({ onClose, onSaved, onNavigate }: {
  onClose: () => void; onSaved: (character: Character) => void; onNavigate: SettingsNavigate;
}) {
  const { t } = useTranslation('personas');
  const [kind, setKind] = useState<CharacterKind | null>(null);
  const guard = useRef<LeaveGuard>(async () => true);
  const register = useCallback((value: LeaveGuard) => { guard.current = value; }, []);
  const leave = async (url?: string) => {
    if (!(await guard.current(new URL(url || window.location.href, window.location.href)))) return false;
    if (url && !(await onNavigate(url))) return false;
    onClose(); return true;
  };
  return <Dialog open onOpenChange={(open) => { if (!open) void leave(); }}>
    <DialogContent className="sm:max-w-3xl">
      <DialogHeader><DialogTitle>{t('newCharacter')}</DialogTitle></DialogHeader>
      <Field>
        <FieldLabel>{t('characterType')}</FieldLabel>
        <ToggleGroup value={kind ? [kind] : []} variant="outline" aria-label={t('characterType')}
          onValueChange={(value) => {
            const next = value[0] as CharacterKind | undefined;
            if (next && next !== kind) void guard.current(new URL(window.location.href)).then((allowed) => { if (allowed) setKind(next); });
          }}>
          <ToggleGroupItem value="normal">{t('characterKinds.normal')}</ToggleGroupItem>
          <ToggleGroupItem value="qqbot">{t('characterKinds.qqbot')}</ToggleGroupItem>
        </ToggleGroup>
        <FieldDescription>{t('characterTypeFixed')}</FieldDescription>
      </Field>
      {kind ? <CharacterEditor key={kind} kind={kind} dialog onSaved={onSaved} onNavigate={leave} onLeaveGuardChange={register} /> : null}
    </DialogContent>
  </Dialog>;
}
