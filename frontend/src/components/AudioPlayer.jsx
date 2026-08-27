import { useEffect, useMemo, useRef } from 'react'
import { Pause, Play } from 'lucide-react'
import { useAudioPlayer } from '../context/AudioPlayerContext.jsx'
import { formatTimestamp } from '../utils/format.js'
import { moodColor } from '../utils/mood.js'

/** Deterministic pseudo-random bar heights per call id, so the waveform-style visual
 * (we don't have real waveform data) is stable across re-renders. */
function barHeights(seed, count) {
  let h = 0
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0
  const heights = []
  for (let i = 0; i < count; i++) {
    h = (h * 1103515245 + 12345) >>> 0
    heights.push(0.22 + ((h >>> 8) % 1000) / 1000 * 0.78)
  }
  return heights
}

export default function AudioPlayer({ callId, src, moodEvents = [], moodShiftSegmentId, durationSeconds }) {
  const {
    audioRef,
    currentTime,
    duration,
    isPlaying,
    setCurrentTime,
    setDuration,
    setIsPlaying,
    seekTo,
    togglePlay,
  } = useAudioPlayer()
  const trackRef = useRef(null)
  const bars = useMemo(() => barHeights(callId || 'call', 96), [callId])
  const totalDuration = duration || durationSeconds || 0

  useEffect(() => {
    const el = audioRef.current
    if (!el) return
    const onTime = () => setCurrentTime(el.currentTime)
    const onLoaded = () => setDuration(el.duration || 0)
    const onPlay = () => setIsPlaying(true)
    const onPause = () => setIsPlaying(false)
    el.addEventListener('timeupdate', onTime)
    el.addEventListener('loadedmetadata', onLoaded)
    el.addEventListener('play', onPlay)
    el.addEventListener('pause', onPause)
    el.addEventListener('ended', onPause)
    return () => {
      el.removeEventListener('timeupdate', onTime)
      el.removeEventListener('loadedmetadata', onLoaded)
      el.removeEventListener('play', onPlay)
      el.removeEventListener('pause', onPause)
      el.removeEventListener('ended', onPause)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [audioRef, callId])

  const handleTrackClick = (e) => {
    const track = trackRef.current
    if (!track || !totalDuration) return
    const rect = track.getBoundingClientRect()
    const pct = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width))
    seekTo(pct * totalDuration)
  }

  const progressPct = totalDuration ? (currentTime / totalDuration) * 100 : 0

  return (
    <div className="rounded-lg border border-app-border bg-app-panel p-3">
      {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
      <audio ref={audioRef} src={src} preload="metadata" />
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={togglePlay}
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-app-accent text-white transition hover:opacity-90"
          aria-label={isPlaying ? 'Pause' : 'Play'}
        >
          {isPlaying ? <Pause size={16} fill="currentColor" /> : <Play size={16} fill="currentColor" className="ml-0.5" />}
        </button>

        <div
          ref={trackRef}
          onClick={handleTrackClick}
          className="relative flex h-10 flex-1 cursor-pointer items-end gap-px overflow-hidden rounded"
        >
          {bars.map((h, i) => {
            const barPct = (i / bars.length) * 100
            const played = barPct <= progressPct
            return (
              <div
                key={i}
                className="min-w-0 flex-1 rounded-sm"
                style={{
                  height: `${h * 100}%`,
                  backgroundColor: played ? 'var(--color-app-accent)' : 'var(--color-app-border)',
                }}
              />
            )
          })}

          {moodEvents.map((e, i) => {
            const leftPct = totalDuration ? (e.timestamp / totalDuration) * 100 : 0
            const isShift = e.segment_id === moodShiftSegmentId
            return (
              <div
                key={i}
                className="pointer-events-none absolute top-0 bottom-0"
                style={{
                  left: `${leftPct}%`,
                  width: isShift ? '2px' : '1px',
                  backgroundColor: moodColor(e.mood_after),
                  opacity: isShift ? 1 : 0.8,
                }}
              />
            )
          })}
        </div>

        <div className="w-24 shrink-0 text-right font-mono-data text-xs text-app-text-secondary">
          {formatTimestamp(currentTime)} / {formatTimestamp(totalDuration)}
        </div>
      </div>
    </div>
  )
}
