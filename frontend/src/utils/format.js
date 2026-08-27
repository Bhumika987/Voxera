/** Formats seconds as mm:ss (or h:mm:ss for calls over an hour). Used everywhere a
 * timestamp appears — always paired with the monospace data font. */
export function formatTimestamp(totalSeconds) {
  if (totalSeconds == null || Number.isNaN(totalSeconds)) return '--:--'
  const s = Math.max(0, Math.floor(totalSeconds))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  if (h > 0) {
    return `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
  }
  return `${m}:${String(sec).padStart(2, '0')}`
}

/** Same as formatTimestamp but always mm:ss, for handle-time columns where an hour+
 * call is not expected and a stable column width matters more. */
export function formatDuration(totalSeconds) {
  return formatTimestamp(totalSeconds)
}

export function formatRelativeTime(isoString) {
  if (!isoString) return '—'
  const date = new Date(isoString)
  if (Number.isNaN(date.getTime())) return '—'
  const diffMs = Date.now() - date.getTime()
  const diffSec = Math.round(diffMs / 1000)
  const diffMin = Math.round(diffSec / 60)
  const diffHr = Math.round(diffMin / 60)
  const diffDay = Math.round(diffHr / 24)

  if (diffSec < 60) return 'just now'
  if (diffMin < 60) return `${diffMin}m ago`
  if (diffHr < 24) return `${diffHr}h ago`
  if (diffDay < 30) return `${diffDay}d ago`
  return formatDate(isoString)
}

export function formatDate(isoString) {
  if (!isoString) return '—'
  const date = new Date(isoString)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

export function formatDateTime(isoString) {
  if (!isoString) return '—'
  const date = new Date(isoString)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

export function initials(name) {
  if (!name) return '?'
  const parts = name.trim().split(/\s+/)
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

/** The API returns free-text `intent` (e.g. "request replacement credit card"),
 * not a closed enum — title-case it for consistent badge display. */
export function titleCase(str) {
  if (!str) return ''
  return str
    .split(' ')
    .map((w) => (w.length ? w[0].toUpperCase() + w.slice(1) : w))
    .join(' ')
}

export function truncate(str, maxLen) {
  if (!str) return ''
  if (str.length <= maxLen) return str
  return str.slice(0, maxLen - 1).trimEnd() + '…'
}
