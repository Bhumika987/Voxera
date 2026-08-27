import { Link } from 'react-router-dom'
import { Clock3, CornerUpLeft } from 'lucide-react'
import { formatTimestamp, truncate } from '../utils/format.js'
import { useAudioPlayerOptional } from '../context/AudioPlayerContext.jsx'

/**
 * The evidence citation chip — this product's core differentiator ("a claim with no
 * evidence scores zero"). Three variants:
 *   - default: ⏱ mm:ss "quote" — click seeks the audio player + scrolls/flashes the
 *     matching transcript segment (via AudioPlayerContext, when rendered inside one).
 *   - linked: for evidence in a DIFFERENT call (e.g. "repeat contact") — no timestamp,
 *     links to that call instead.
 *   - ghost: dashed "Evidence pending" — for a judgment whose evidence field the live
 *     API doesn't populate yet (e.g. resolution_evidence_segment_id), so the slot
 *     reads as intentionally reserved rather than silently missing.
 */
export default function EvidenceChip({
  timestamp,
  quote,
  segmentId,
  linkedCallId,
  linkedDate,
  className = '',
}) {
  const audio = useAudioPlayerOptional()

  if (linkedCallId) {
    return (
      <Link
        to={`/calls/${linkedCallId}`}
        className={`inline-flex items-center gap-1.5 rounded-full border border-app-border bg-app-panel-raised px-2 py-1 text-xs text-app-text-secondary transition hover:border-app-accent hover:text-app-accent ${className}`}
      >
        <CornerUpLeft size={11} />
        <span>See call{linkedDate ? ` · ${linkedDate}` : ''}</span>
      </Link>
    )
  }

  const hasEvidence = segmentId != null && timestamp != null

  if (!hasEvidence) {
    return (
      <span
        className={`inline-flex items-center gap-1.5 rounded-full border border-dashed border-app-border px-2 py-1 text-xs text-app-text-secondary opacity-70 ${className}`}
        title="No evidence segment recorded for this judgment yet"
      >
        <Clock3 size={11} />
        <span>Evidence pending</span>
      </span>
    )
  }

  const handleClick = () => {
    audio?.jumpToSegment(segmentId, timestamp)
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      title={quote ? `"${quote}"` : undefined}
      className={`inline-flex max-w-full items-center gap-1.5 rounded-full border border-app-border bg-app-panel-raised px-2 py-1 text-xs text-app-text-secondary transition hover:border-app-accent hover:text-app-text ${audio ? 'cursor-pointer' : 'cursor-default'} ${className}`}
    >
      <Clock3 size={11} className="shrink-0 text-app-accent" />
      <span className="font-mono-data shrink-0">{formatTimestamp(timestamp)}</span>
      {quote && <span className="truncate italic">&ldquo;{truncate(quote, 60)}&rdquo;</span>}
    </button>
  )
}
