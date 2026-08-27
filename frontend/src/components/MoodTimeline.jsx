import { Flag } from 'lucide-react'
import MoodChip from './MoodChip.jsx'
import EvidenceChip from './EvidenceChip.jsx'
import { moodColor } from '../utils/mood.js'
import { formatTimestamp } from '../utils/format.js'

/**
 * Horizontal banded timeline: bands colored by mood, width proportional to elapsed
 * time, built from initial_mood -> mood_events[] -> final_mood. Every mood_events
 * entry gets a small dot marker; the one matching mood_shift_segment_id (the call's
 * headline "moment mood shifted") gets a distinct pinned/flagged marker so it's
 * unmistakable at a glance — mirrored by the same flag in the list below.
 */
export default function MoodTimeline({
  initialMood,
  finalMood,
  moodEvents = [],
  moodShiftSegmentId,
  durationSeconds,
}) {
  const duration = durationSeconds > 0 ? durationSeconds : 1
  const sortedEvents = [...moodEvents].sort((a, b) => a.timestamp - b.timestamp)

  const points = [{ t: 0, mood: initialMood }, ...sortedEvents.map((e) => ({ t: e.timestamp, mood: e.mood_after }))]
  const bands = points.map((p, i) => {
    const end = i < points.length - 1 ? points[i + 1].t : duration
    return { mood: p.mood, start: p.t, end, widthPct: Math.max(0, ((end - p.t) / duration) * 100) }
  })

  const shiftFirst = (a, b) => {
    const aShift = a.segment_id === moodShiftSegmentId ? 0 : 1
    const bShift = b.segment_id === moodShiftSegmentId ? 0 : 1
    return aShift - bShift
  }

  return (
    <div>
      <div className="flex items-center justify-between text-xs text-app-text-secondary">
        <MoodChip mood={initialMood} size="sm" />
        <span>→</span>
        <MoodChip mood={finalMood} size="sm" />
      </div>

      <div className="relative mt-3 flex h-7 w-full overflow-visible rounded-md">
        {bands.map((b, i) => (
          <div
            key={i}
            className="h-full first:rounded-l-md last:rounded-r-md"
            style={{ width: `${b.widthPct}%`, backgroundColor: moodColor(b.mood) }}
            title={`${b.mood} · ${formatTimestamp(b.start)}–${formatTimestamp(b.end)}`}
          />
        ))}
        {sortedEvents.map((e, i) => {
          const leftPct = (e.timestamp / duration) * 100
          const isShift = e.segment_id === moodShiftSegmentId
          return (
            <div key={i} className="absolute top-0 h-full" style={{ left: `${leftPct}%` }}>
              {isShift ? (
                <div className="relative h-full">
                  <div className="absolute inset-y-0 w-0.5 bg-app-text" />
                  <Flag size={12} className="absolute -top-4 -translate-x-1/2 text-app-text" fill="currentColor" />
                </div>
              ) : (
                <div className="absolute top-1/2 h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-app-panel bg-app-text-secondary" />
              )}
            </div>
          )
        })}
      </div>
      <div className="mt-1 flex justify-between font-mono-data text-[11px] text-app-text-secondary">
        <span>0:00</span>
        <span>{formatTimestamp(duration)}</span>
      </div>

      {sortedEvents.length > 0 && (
        <ul className="mt-3 space-y-2 border-t border-app-border pt-3">
          {[...sortedEvents].sort(shiftFirst).map((e, i) => {
            const isShift = e.segment_id === moodShiftSegmentId
            return (
              <li key={i} className="flex flex-wrap items-center gap-2 text-sm">
                {isShift && <Flag size={12} className="shrink-0 text-app-text" fill="currentColor" />}
                <span className="flex items-center gap-1.5">
                  <MoodChip mood={e.mood_before} size="sm" />
                  <span className="text-app-text-secondary">→</span>
                  <MoodChip mood={e.mood_after} size="sm" />
                </span>
                <EvidenceChip
                  timestamp={e.evidence_start_time ?? e.timestamp}
                  quote={e.evidence_text}
                  segmentId={e.segment_id}
                />
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
