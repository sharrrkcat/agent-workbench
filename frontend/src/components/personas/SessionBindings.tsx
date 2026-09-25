import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { LockKeyhole } from 'lucide-react';
import { chatApi } from '../../api/chat';
import { useCogitaStore } from '../../store/useCogitaStore';
import { BindingsField } from './ConfigurationFields';
import { ResourceLoading, errorText } from '../settings/resources/ResourceUI';

export function SessionBindings({ personaId, userPersonaId, projectIds, items, ids, onChange }: {
  personaId: string; userPersonaId: string; projectIds?: string[];
  items: Array<{ id: string; name: string; enabled: boolean }>;
  ids: string[]; onChange: (ids: string[]) => void;
}) {
  const { t } = useTranslation('personas');
  const sessionVersion = useCogitaStore((state) => state.sessionVersion);
  const [bindings, setBindings] = useState<{ user: string[]; agent: string[] } | null>(null);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let live = true;
    setBindings(null); setError('');
    void Promise.all([chatApi.getPersonaKnowledge(userPersonaId), chatApi.getPersonaKnowledge(personaId)])
      .then(([user, agent]) => { if (live) setBindings({ user: user.knowledge_base_ids, agent: agent.knowledge_base_ids }); })
      .catch((reason) => { if (live) setError(errorText(reason)); });
    return () => { live = false; };
  }, [personaId, userPersonaId, reload, sessionVersion]);
  if (!bindings) return <ResourceLoading error={error} retry={() => setReload((n) => n + 1)} />;
  const sections = [
    { label: t('userPersonaBindings'), ids: bindings.user },
    { label: t('agentPersonaBindings'), ids: bindings.agent },
    ...(projectIds ? [{ label: t('projectBindings'), ids: projectIds }] : []),
  ];
  const inherited = new Set(sections.flatMap((section) => section.ids));
  return <div className="flex flex-col gap-4">
    {sections.map((section) => <section key={section.label} aria-label={section.label}>
      <h3 className="binding-section-heading"><LockKeyhole size={15} aria-hidden="true" />{section.label}</h3>
      {section.ids.length ? <BindingsField items={items.filter((item) => section.ids.includes(item.id))}
        ids={section.ids} onChange={() => undefined} disabled /> : <p className="model-empty">{t('noBindings')}</p>}
    </section>)}
    <section aria-label={t('sessionAdditions')}>
      <h3>{t('sessionAdditions')}</h3>
      <BindingsField items={items.filter((item) => !inherited.has(item.id) || ids.includes(item.id))} ids={ids} onChange={onChange} />
    </section>
  </div>;
}
