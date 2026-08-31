import { getScoreBand, scoreBandLabel, scoreColor } from '../utils/scoreBands.js'

const SIZES = {
  sm: 'px-1.5 py-0.5 text-xs',
  md: 'px-2 py-1 text-sm',
  lg: 'px-3 py-1.5 text-base',
}

/** Numeric attention score, colored by the shared 3-band scale (reused identically
 * everywhere a score appears: queue table, customer rows, call detail). */
export default function ScorePill({ score, size = 'md', showBandLabel = false, className = '' }) {
  const color = scoreColor(score)
  const band = getScoreBand(score)
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md font-bold ${SIZES[size] || SIZES.md} ${className}`}
      style={{ color, backgroundColor: `color-mix(in srgb, ${color} 16%, transparent)` }}
      title={`Attention score ${score ?? '—'} · ${scoreBandLabel(score)}`}
    >
      <span className="font-mono-data" style={{ fontSize: '1.15em', fontWeight: 700 }}>
        {score ?? '—'}
      </span>
      {showBandLabel && <span className="font-normal opacity-90">{scoreBandLabel(score)}</span>}
    </span>
  )
}

export { getScoreBand }
