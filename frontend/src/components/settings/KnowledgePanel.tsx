import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { knowledgeApi } from '../../api/knowledge';
import type { KnowledgeBase, KnowledgeSettings } from '../../types/knowledge';
import { Loading, NumberField, Panel, Toggle } from './fields';
import type { SettingsTask } from './useSettingsFeedback';
import { useModelsStore } from '../../store/useModelsStore';

export function KnowledgePanel({ save }: { save: SettingsTask }) {
  const [settings, setSettings] = useState<KnowledgeSettings | null>(null);
  const [bases, setBases] = useState<KnowledgeBase[]>([]);
  const { t } = useTranslation('knowledge');
  const models = useModelsStore((state) => state.profiles);
  const reloadModels = useModelsStore((state) => state.reload);
  const embeddings = models.filter((p) => p.kind === 'embedding' && p.enabled);
  const [newBase, setNewBase] = useState({ name: '', embedding_model_profile_id: '' });
  const reload = () =>
    Promise.all([knowledgeApi.getKnowledgeSettings(), knowledgeApi.listKnowledgeBases(), reloadModels()]).then(
      ([s, b]) => {
        setSettings(s);
        setBases(b);
      },
    );
  useEffect(() => {
    void reload();
  }, []);
  if (!settings) return <Loading />;
  const patch = (key: string, value: unknown) => setSettings({ ...settings, [key]: value } as KnowledgeSettings);
  return (
    <Panel title={t('title')}>
      <Toggle
        label={t('hybrid')}
        checked={settings.hybrid_search_enabled}
        onChange={(value) => patch('hybrid_search_enabled', value)}
      />
      <Toggle
        label={t('reranker')}
        checked={settings.reranker_enabled}
        onChange={(value) => patch('reranker_enabled', value)}
      />
      <label className="settings-field">
        <span>{t('llm:kinds.reranker')}</span>
        <select
          value={settings.reranker_model_profile_id || ''}
          onChange={(e) => patch('reranker_model_profile_id', e.currentTarget.value || null)}
        >
          <option value="">{t('llm:unconfigured')}</option>
          {models
            .filter((p) => p.kind === 'reranker' && p.enabled)
            .map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
        </select>
      </label>
      <NumberField
        label={t('chunkSize')}
        value={settings.default_chunk_size}
        onChange={(value) => patch('default_chunk_size', value)}
      />
      <NumberField
        label={t('chunkOverlap')}
        value={settings.default_chunk_overlap}
        onChange={(value) => patch('default_chunk_overlap', value)}
      />
      <NumberField
        label={t('finalResults')}
        value={settings.default_final_top_k}
        onChange={(value) => patch('default_final_top_k', value)}
      />
      <button
        className="primary-button"
        type="button"
        onClick={() =>
          save(() =>
            knowledgeApi
              .updateKnowledgeSettings(Object.fromEntries(Object.entries(settings).filter(([key]) => key !== 'id')))
              .then(() => undefined),
          )
        }
      >
        {t('save')}
      </button>
      <h3>{t('bases')}</h3>
      <div className="settings-list">
        {bases.map((base) => (
          <div className="settings-list-row" key={base.id}>
            <span>
              {base.name}
              <small>{base.index_status}</small>
            </span>
            <button
              type="button"
              onClick={() => save(() => knowledgeApi.deleteKnowledgeBase(base.id).then(() => reload()))}
            >
              {t('common:delete')}
            </button>
          </div>
        ))}
      </div>
      <div className="inline-form">
        <input
          placeholder={t('baseName')}
          value={newBase.name}
          onChange={(event) => setNewBase({ ...newBase, name: event.currentTarget.value })}
        />
        <select
          value={newBase.embedding_model_profile_id}
          onChange={(event) => setNewBase({ ...newBase, embedding_model_profile_id: event.currentTarget.value })}
        >
          <option value="">{t('embeddingProfile')}</option>
          {embeddings.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
        <button
          className="secondary-button"
          type="button"
          disabled={!newBase.name || !newBase.embedding_model_profile_id}
          onClick={() =>
            save(() =>
              knowledgeApi.createKnowledgeBase(newBase).then(() => {
                setNewBase({ name: '', embedding_model_profile_id: newBase.embedding_model_profile_id });
                return reload();
              }),
            )
          }
        >
          {t('addBase')}
        </button>
      </div>
    </Panel>
  );
}
