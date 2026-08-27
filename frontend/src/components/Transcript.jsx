import { useEffect, useRef, useState } from 'react'
import { Flag } from 'lucide-react'
import { useAudioPlayer } from '../context/AudioPlayerContext.jsx'
import { formatTimestamp } from '../utils/format.js'

function TranscriptBubble({ seg, isMoodShift }) {
  const { registerSegmentNode, jump, jumpToSegment } = useAudioPlayer()
  const ref = useRef(null)
  const [flash, setFlash] = useState(false)
  const isAgent = seg.speaker === 'agent'

  useEffect(() => {
    registerSegmentNode(seg.segment_id, ref.current)
    return () => registerSegmentNode(seg.segment_id, null)
  }, [seg.segment_id, registerSegmentNode])

  useEffect(() => {
    if (jump && jump.segmentId === seg.segment_id) {
      setFlash(true)
      const t = setTimeout(() => setFlash(false), 900)
      return () => clearTimeout(t)
    }
  }, [jump, seg.segment_id])

  return (
    <div ref={ref} className={`flex ${isAgent ? 'justify-start' : 'justify-end'}`}>
      <button
        type="button"
        onClick={() => jumpToSegment(seg.segment_id, seg.start_time)}
        style={{
          boxShadow: isMoodShift ? 'inset 3px 0 0 0 var(--color-mood-frustrated)' : undefined,
          backgroundColor: flash ? 'color-mix(in srgb, var(--color-app-accent) 30%, transparent)' : undefined,
        }}
        className={`max-w-[82%] rounded-lg px-3 py-2 text-left text-sm transition-colors duration-300 ${
          isAgent ? 'bg-app-panel-raised' : 'bg-app-accent/10'
        }`}
      >
        <div className="mb-1 flex items-center gap-1.5 text-[11px] text-app-text-secondary">
          <span className="font-mono-data">{formatTimestamp(seg.start_time)}</span>
          <span>· {isAgent ? 'Agent' : 'Customer'}</span>
          {isMoodShift && (
            <span className="flex items-center gap-1 text-mood-frustrated">
              <Flag size={10} fill="currentColor" /> mood shift
            </span>
          )}
        </div>
        <p className="whitespace-pre-line text-app-text">{seg.text}</p>
      </button>
    </div>
  )
}

/** Two-lane chat transcript — agent left, customer right. Any evidence chip on the
 * page can command a bubble here to scroll-into-view + flash via AudioPlayerContext.
 * The segment matching mood_shift_segment_id gets a persistent flagged style. */
export default function Transcript({ segments, moodShiftSegmentId }) {
  if (!segments || segments.length === 0) {
    return <p className="text-sm text-app-text-secondary">No transcript available for this call.</p>
  }

  return (
    <div className="flex flex-col gap-3">
      {segments.map((seg) => (
        <TranscriptBubble key={seg.segment_id} seg={seg} isMoodShift={seg.segment_id === moodShiftSegmentId} />
      ))}
    </div>
  )
}
