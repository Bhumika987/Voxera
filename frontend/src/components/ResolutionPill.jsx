import { titleCase } from '../utils/format.js'

const STYLES = {
  resolved: 'bg-mood-happy/15 text-mood-happy',
  unresolved: 'bg-mood-angry/15 text-mood-angry',
}

export default function ResolutionPill({ resolution, className = '' }) {
  const style = STYLES[resolution] || 'bg-app-border/60 text-app-text-secondary'
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${style} ${className}`}>
      {titleCase(resolution) || 'Unknown'}
    </span>
  )
}
