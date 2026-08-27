import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react'

const AudioPlayerContext = createContext(null)

/**
 * Scoped to one Call Detail page. Holds the <audio> element ref and the transcript
 * segment DOM node refs, so ANY evidence chip anywhere on the page can command the
 * player to seek AND the transcript to scroll-to + flash the matching segment,
 * regardless of how deeply either is nested.
 */
export function AudioPlayerProvider({ children }) {
  const audioRef = useRef(null)
  const segmentNodes = useRef(new Map())

  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [isPlaying, setIsPlaying] = useState(false)
  const [jump, setJump] = useState(null) // { segmentId, nonce } — Transcript reacts to this

  const registerSegmentNode = useCallback((segmentId, node) => {
    if (node) segmentNodes.current.set(segmentId, node)
    else segmentNodes.current.delete(segmentId)
  }, [])

  const seekTo = useCallback((seconds) => {
    const el = audioRef.current
    if (el && Number.isFinite(seconds)) {
      el.currentTime = seconds
      setCurrentTime(seconds)
    }
  }, [])

  const togglePlay = useCallback(() => {
    const el = audioRef.current
    if (!el) return
    if (el.paused) el.play().catch(() => {})
    else el.pause()
  }, [])

  /** The one entry point every evidence chip calls: seeks the audio (if a timestamp
   * is known) and tells the transcript to scroll to + flash the segment. */
  const jumpToSegment = useCallback(
    (segmentId, timestamp) => {
      if (timestamp != null) seekTo(timestamp)
      if (segmentId) {
        setJump({ segmentId, nonce: Date.now() + Math.random() })
        segmentNodes.current.get(segmentId)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
      }
    },
    [seekTo],
  )

  const value = useMemo(
    () => ({
      audioRef,
      currentTime,
      duration,
      isPlaying,
      jump,
      setCurrentTime,
      setDuration,
      setIsPlaying,
      registerSegmentNode,
      seekTo,
      togglePlay,
      jumpToSegment,
    }),
    [currentTime, duration, isPlaying, jump, registerSegmentNode, seekTo, togglePlay],
  )

  return <AudioPlayerContext.Provider value={value}>{children}</AudioPlayerContext.Provider>
}

/** Throws outside a provider — use inside Call Detail's tree only. */
export function useAudioPlayer() {
  const ctx = useContext(AudioPlayerContext)
  if (!ctx) throw new Error('useAudioPlayer must be used within an AudioPlayerProvider')
  return ctx
}

/** Non-throwing variant for shared components (e.g. EvidenceChip) that render both
 * inside and outside a Call Detail page. */
export function useAudioPlayerOptional() {
  return useContext(AudioPlayerContext)
}
