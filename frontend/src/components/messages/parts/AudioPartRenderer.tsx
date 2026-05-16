import { Pause, Play } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { AudioMessagePart } from '../../../types';

export function AudioPartRenderer({ part }: { part: AudioMessagePart }) {
  const { t } = useTranslation(['renderers']);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(durationSeconds(part.duration_ms));
  const [failed, setFailed] = useState(false);
  const url = part.source === 'attachment' && isLocalAttachmentUrl(part.url) ? part.url : '';
  const label = part.title || part.filename || part.attachment_id;
  const details = [part.filename, part.mime_type].filter(Boolean).join(' - ');
  const effectiveDuration = duration > 0 ? duration : durationSeconds(part.duration_ms);
  const progressMax = effectiveDuration > 0 ? effectiveDuration : 0;

  useEffect(() => {
    setIsPlaying(false);
    setCurrentTime(0);
    setDuration(durationSeconds(part.duration_ms));
    setFailed(false);
  }, [part.attachment_id, part.duration_ms, part.url]);

  if (!url) {
    return <div className="message-content message-part-notice warning">{label}</div>;
  }

  function updateMetadata() {
    const audio = audioRef.current;
    if (!audio) return;
    if (Number.isFinite(audio.duration) && audio.duration > 0) {
      setDuration(audio.duration);
    }
  }

  function updateTime() {
    const audio = audioRef.current;
    if (!audio) return;
    setCurrentTime(Number.isFinite(audio.currentTime) ? audio.currentTime : 0);
  }

  async function togglePlayback() {
    const audio = audioRef.current;
    if (!audio || failed) return;
    if (audio.paused) {
      try {
        await audio.play();
      } catch {
        setFailed(true);
        setIsPlaying(false);
      }
    } else {
      audio.pause();
    }
  }

  function seek(value: string) {
    const audio = audioRef.current;
    if (!audio) return;
    const nextTime = Number(value);
    if (!Number.isFinite(nextTime)) return;
    audio.currentTime = nextTime;
    setCurrentTime(nextTime);
  }

  return (
    <div className={`audio-part ${failed ? 'error' : ''}`}>
      <audio
        ref={audioRef}
        src={url}
        preload="metadata"
        onLoadedMetadata={updateMetadata}
        onDurationChange={updateMetadata}
        onTimeUpdate={updateTime}
        onPlay={() => setIsPlaying(true)}
        onPause={() => setIsPlaying(false)}
        onEnded={() => {
          setIsPlaying(false);
          setCurrentTime(0);
          if (audioRef.current) audioRef.current.currentTime = 0;
        }}
        onError={() => {
          setFailed(true);
          setIsPlaying(false);
        }}
      />
      <div className="audio-part-header">
        <button
          className="audio-part-play"
          type="button"
          onClick={togglePlayback}
          disabled={failed}
          aria-label={isPlaying ? t('audio.pause') : t('audio.play')}
          title={isPlaying ? t('audio.pause') : t('audio.play')}
        >
          {isPlaying ? <Pause size={16} /> : <Play size={16} />}
        </button>
        <div className="audio-part-copy">
          <div className="audio-part-title">{label}</div>
          {details ? <div className="audio-part-meta">{details}</div> : null}
        </div>
      </div>
      <div className="audio-part-controls">
        <span className="audio-part-time">{formatTime(currentTime)}</span>
        <input
          className="audio-part-progress"
          type="range"
          min="0"
          max={progressMax || currentTime || 0}
          step="0.01"
          value={Math.min(currentTime, progressMax || currentTime)}
          onChange={(event) => seek(event.currentTarget.value)}
          disabled={failed || progressMax <= 0}
          aria-label={t('audio.seek')}
        />
        <span className="audio-part-time">{formatTime(effectiveDuration)}</span>
      </div>
      {failed ? <div className="audio-part-error">{t('audio.loadFailed')}</div> : null}
    </div>
  );
}

function isLocalAttachmentUrl(value: string | null | undefined): value is string {
  return typeof value === 'string' && /^\/api\/attachments\/[A-Za-z0-9_-]+\.[A-Za-z0-9]+$/.test(value);
}

function durationSeconds(value: number | null | undefined): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) return 0;
  return value / 1000;
}

function formatTime(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '0:00';
  const totalSeconds = Math.floor(value);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, '0')}`;
}
