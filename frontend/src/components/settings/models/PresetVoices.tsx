import { RefreshCw } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { modelsApi } from '../../../api/models';
import type { PresetVoice } from '../../../types/models';

export function PresetVoices({ profileId }: { profileId: string }) {
  const { t } = useTranslation('llm');
  const [voices, setVoices] = useState<PresetVoice[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true;
    setVoices([]); setError(''); setLoading(true);
    void modelsApi.getModelVoices(profileId).then((items) => {
      if (active) setVoices(items);
    }).catch((reason: Error) => {
      if (active) setError(reason.message);
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [profileId, revision]);
  const languages = [...new Set(voices.map((voice) => voice.language))];
  return <section aria-label={t('voices.title')}>
    <div className="tts-voices-heading"><h3>{t('voices.title')}</h3>
      <button type="button" className="icon-button" title={t('refresh')} aria-label={t('refresh')} disabled={loading}
        onClick={() => setRevision((value) => value + 1)}><RefreshCw size={16} /></button>
    </div>
    {error ? <p role="alert">{error}</p> : null}
    {loading ? <p role="status">{t('voices.loading')}</p> : null}
    <div className="tts-voices-list"><table>
      <thead><tr><th>{t('voices.id')}</th><th>{t('voices.availability')}</th></tr></thead>
      {languages.map((language) => <tbody key={language}>
        <tr><th colSpan={2}>{t('voices.languages.' + language)}</th></tr>
        {voices.filter((voice) => voice.language === language).map((voice) => <tr key={voice.id}>
          <td><code>{voice.id}</code></td><td>{voice.available ? t('voices.available') : t('voices.missing')}</td>
        </tr>)}
      </tbody>)}
    </table></div>
  </section>;
}
