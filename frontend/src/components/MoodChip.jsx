import { moodColor, moodLabel } from '../utils/mood.js'

const SIZES = {
  sm: { dot: 'h-1.5 w-1.5', text: 'text-xs', gap: 'gap-1.5' },
  md: { dot: 'h-2 w-2', text: 'text-sm', gap: 'gap-2' },
}

/** Dot + label, colored by the shared mood scale. Never color alone — always paired
 * with the text label for accessibility. */
export default function MoodChip({ mood, size = 'md', showLabel = true, className = '' }) {
  const s = SIZES[size] || SIZES.md
  return (
    <span className={`inline-flex items-center ${s.gap} ${className}`}>
      <span className={`shrink-0 rounded-full ${s.dot}`} style={{ backgroundColor: moodColor(mood) }} />
      {showLabel && <span className={`${s.text} text-app-text-secondary`}>{moodLabel(mood)}</span>}
    </span>
  )
}
