import { useEffect, useState } from 'react';
import type { ModelKind, ModelProfile } from '../../../types/models';
import { useModelsStore } from '../../../store/useModelsStore';
import { Feedback } from '../resources/ResourceUI';
import { ProfileEditor, type ProfileDraft } from './ProfileEditor';
import { newModel } from './profileDefaults';
import { useModelFeedback } from './useModelFeedback';
import type { ModelTask } from './types';

export function ModelCreationDialog({ kind, onClose, onCreated, onBusyChange, returnFocus }: {
  kind: ModelKind;
  onClose: () => void;
  onCreated: (profile: ModelProfile) => Promise<void>;
  onBusyChange: (busy: boolean) => void;
  returnFocus: () => HTMLElement | null;
}) {
  const [model, setModel] = useState<ProfileDraft | null>(() => ({ value: newModel(kind) }));
  const reload = useModelsStore((state) => state.reload);
  const { busy, error, notice, run, setError } = useModelFeedback(reload);
  useEffect(() => { if (!model && !busy) onClose(); }, [model, busy, onClose]);
  const save: ModelTask = async (task, refresh) => {
    onBusyChange(true);
    try { await run(task, refresh); }
    finally { onBusyChange(false); }
  };
  return <ProfileEditor model={model} setModel={setModel} run={save} busy={busy} setError={setError}
    feedback={<Feedback error={error} notice={notice} />}
    allowKindSelection finalFocus={returnFocus}
    onCreated={async (profile) => {
      // The POST succeeded even if the subsequent status refresh failed.
      useModelsStore.setState((state) => ({ profiles: state.profiles.some((item) => item.id === profile.id)
        ? state.profiles : [...state.profiles, profile] }));
      await onCreated(profile);
    }} />;
}
