import { Pause, Play } from 'lucide-react';
import type { KeyboardEvent, PointerEvent } from 'react';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { AudioMessagePart } from '../../../types';

export function AudioPartRenderer({ part }: { part: AudioMessagePart }) {
  const { t } = useTranslation(['renderers']);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const progressTrackRef = useRef<HTMLDivElement | null>(null);
  const isScrubbingRef = useRef(false);
  const isSeekingRef = useRef(false);
  const pendingSeekTimeRef = useRef<number | null>(null);
  const scrubTimeRef = useRef(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(durationSeconds(part.duration_ms));
  const [failed, setFailed] = useState(false);
  const [isScrubbing, setIsScrubbing] = useState(false);
  const [scrubTime, setScrubTime] = useState(0);
  const url = part.source === 'attachment' && isLocalAttachmentUrl(part.url) ? part.url : '';
  const label = part.title || part.filename || part.attachment_id;
  const details = [part.filename, part.mime_type].filter(Boolean).join(' - ');
  const fallbackDuration = durationSeconds(part.duration_ms);
  const effectiveDuration = duration > 0 ? duration : fallbackDuration;
  const displayedTime = isScrubbing ? scrubTime : currentTime;
  const progressPercent = effectiveDuration > 0 ? clamp(displayedTime / effectiveDuration, 0, 1) * 100 : 0;

  useEffect(() => {
    setIsPlaying(false);
    setCurrentTime(0);
    setDuration(durationSeconds(part.duration_ms));
    setFailed(false);
    setIsScrubbing(false);
    isScrubbingRef.current = false;
    isSeekingRef.current = false;
    pendingSeekTimeRef.current = null;
    setScrubTime(0);
    scrubTimeRef.current = 0;
  }, [part.attachment_id, part.url]);

  if (!url) {
    return <div className="message-content message-part-notice warning">{label}</div>;
  }

  function updateMetadata() {
    const audio = audioRef.current;
    if (!audio) return;
    const nextDuration = getAudioDuration(audio);
    if (nextDuration > 0) {
      setDuration(nextDuration);
    }
  }

  function updateTime() {
    const audio = audioRef.current;
    if (!audio) return;
    if (isScrubbingRef.current) return;
    if (isSeekingRef.current) return;
    const nextTime = Number.isFinite(audio.currentTime) ? audio.currentTime : 0;
    setCurrentTime(nextTime);
    setScrubTime(nextTime);
    scrubTimeRef.current = nextTime;
  }

  async function togglePlayback() {
    const audio = audioRef.current;
    if (!audio || failed) return;
    if (audio.paused) {
      try {
        if (audio.ended) {
          audio.currentTime = 0;
          setCurrentTime(0);
          setScrubTime(0);
          scrubTimeRef.current = 0;
        }
        await audio.play();
      } catch {
        setFailed(true);
        setIsPlaying(false);
      }
    } else {
      audio.pause();
    }
  }

  function timeFromPointerEvent(event: PointerEvent<HTMLElement>): number {
    const track = progressTrackRef.current;
    if (!track || effectiveDuration <= 0) return 0;
    const rect = track.getBoundingClientRect();
    const ratio = rect.width > 0 ? (event.clientX - rect.left) / rect.width : 0;
    return clamp(ratio * effectiveDuration, 0, effectiveDuration);
  }

  function handleProgressPointerDown(event: PointerEvent<HTMLDivElement>) {
    if (failed || effectiveDuration <= 0) return;
    event.preventDefault();
    event.currentTarget.focus();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    const nextTime = timeFromPointerEvent(event);
    isScrubbingRef.current = true;
    setIsScrubbing(true);
    setScrubTime(nextTime);
    scrubTimeRef.current = nextTime;
  }

  function handleProgressPointerMove(event: PointerEvent<HTMLDivElement>) {
    if (!isScrubbingRef.current) return;
    const nextTime = timeFromPointerEvent(event);
    setScrubTime(nextTime);
    scrubTimeRef.current = nextTime;
  }

  function handleProgressPointerUp(event: PointerEvent<HTMLDivElement>) {
    if (!isScrubbingRef.current) return;
    const nextTime = timeFromPointerEvent(event);
    commitSeek(nextTime);
    isScrubbingRef.current = false;
    setIsScrubbing(false);
    event.currentTarget.releasePointerCapture?.(event.pointerId);
  }

  function cancelProgressScrub() {
    isScrubbingRef.current = false;
    setIsScrubbing(false);
  }

  function handleProgressKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (failed || effectiveDuration <= 0) return;
    const step = Math.min(5, effectiveDuration * 0.05);
    let nextTime: number | null = null;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowDown') {
      nextTime = displayedTime - step;
    } else if (event.key === 'ArrowRight' || event.key === 'ArrowUp') {
      nextTime = displayedTime + step;
    } else if (event.key === 'Home') {
      nextTime = 0;
    } else if (event.key === 'End') {
      nextTime = effectiveDuration;
    }
    if (nextTime === null) return;
    event.preventDefault();
    commitSeek(nextTime);
  }

  function commitSeek(targetSeconds: number) {
    const audio = audioRef.current;
    if (!audio || effectiveDuration <= 0) {
      return;
    }
    const targetTime = clamp(targetSeconds, 0, effectiveDuration);
    isSeekingRef.current = true;
    pendingSeekTimeRef.current = targetTime;
    try {
      audio.currentTime = targetTime;
    } catch {
      isSeekingRef.current = false;
      pendingSeekTimeRef.current = null;
      return;
    }
    setCurrentTime(targetTime);
    setScrubTime(targetTime);
    scrubTimeRef.current = targetTime;
  }

  function completeSeek() {
    const audio = audioRef.current;
    const pendingTime = pendingSeekTimeRef.current;
    const nextTime = audio && Number.isFinite(audio.currentTime) ? audio.currentTime : pendingTime ?? currentTime;
    setCurrentTime(nextTime);
    setScrubTime(nextTime);
    scrubTimeRef.current = nextTime;
    pendingSeekTimeRef.current = null;
    isSeekingRef.current = false;
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
        onSeeked={completeSeek}
        onPlay={() => setIsPlaying(true)}
        onPause={() => setIsPlaying(false)}
        onEnded={() => {
          setIsPlaying(false);
          setCurrentTime(effectiveDuration);
          setScrubTime(effectiveDuration);
          scrubTimeRef.current = effectiveDuration;
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
        <span className="audio-part-time">{formatTime(displayedTime)}</span>
        <div
          ref={progressTrackRef}
          className="audio-part-progress-track"
          role="slider"
          tabIndex={failed || effectiveDuration <= 0 ? -1 : 0}
          aria-label={t('audio.seek')}
          aria-disabled={failed || effectiveDuration <= 0}
          aria-valuemin={0}
          aria-valuemax={Math.round(effectiveDuration)}
          aria-valuenow={Math.round(displayedTime)}
          aria-valuetext={`${formatTime(displayedTime)} / ${formatTime(effectiveDuration)}`}
          onPointerDown={handleProgressPointerDown}
          onPointerMove={handleProgressPointerMove}
          onPointerUp={handleProgressPointerUp}
          onPointerCancel={cancelProgressScrub}
          onLostPointerCapture={cancelProgressScrub}
          onKeyDown={handleProgressKeyDown}
        >
          <div className="audio-part-progress-fill" style={{ width: `${progressPercent}%` }} />
          <div className="audio-part-progress-thumb" style={{ left: `${progressPercent}%` }} />
        </div>
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
  return finitePositiveNumber(value) / 1000;
}

function finitePositiveNumber(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : 0;
}

function getAudioDuration(audio: HTMLAudioElement | null | undefined): number {
  return finitePositiveNumber(audio?.duration);
}

function clamp(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min;
  return Math.min(Math.max(value, min), max);
}

function formatTime(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '0:00';
  const totalSeconds = Math.floor(value);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, '0')}`;
}
