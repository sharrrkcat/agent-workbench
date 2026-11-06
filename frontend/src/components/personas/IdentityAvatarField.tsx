import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Upload, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { chatApi } from '../../api/chat';
import { PersonaAvatar } from './ConfigurationFields';
import { errorText } from '../settings/resources/ResourceUI';

export function IdentityAvatarField({ name, value, disabled, onChange, onBusyChange, onError }: {
  name: string; value: string | null; disabled: boolean; onChange: (id: string | null) => void;
  onBusyChange: (busy: boolean) => void; onError: (error: string) => void;
}) {
  const { t } = useTranslation('personas');
  const input = useRef<HTMLInputElement>(null);
  const temporary = useRef(new Set<string>());
  const live = useRef(true);
  const [uploading, setUploading] = useState(false);
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
      void Promise.allSettled([...temporary.current].map((id) => chatApi.deleteAttachment(id)));
    };
  }, []);
  async function upload(file: File) {
    setUploading(true); onBusyChange(true); onError('');
    try {
      const attachment = await chatApi.uploadAttachment(file);
      const id = attachment.uri.replace('local://attachments/', '');
      if (!live.current) { await chatApi.deleteAttachment(id); return; }
      temporary.current.add(id); onChange(id);
    } catch (reason) { if (live.current) onError(errorText(reason)); }
    finally { if (live.current) { setUploading(false); onBusyChange(false); } }
  }
  return <div className="persona-avatar-editor">
    <PersonaAvatar name={name} attachmentId={value} />
    <input ref={input} type="file" hidden accept="image/png,image/jpeg,image/webp,image/gif" onChange={(event) => {
      const file = event.currentTarget.files?.[0]; event.currentTarget.value = ''; if (file) void upload(file);
    }} />
    <Button type="button" variant="ghost" size="icon" aria-label={t('uploadAvatar')} title={t('uploadAvatar')}
      disabled={disabled || uploading} onClick={() => input.current?.click()}><Upload data-icon="inline-start" /></Button>
    <Button type="button" variant="ghost" size="icon" aria-label={t('removeAvatar')} title={t('removeAvatar')}
      disabled={disabled || uploading || !value} onClick={() => onChange(null)}><X data-icon="inline-start" /></Button>
  </div>;
}
