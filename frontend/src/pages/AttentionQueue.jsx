import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertOctagon, Phone, CheckCircle2, Frown, ChevronLeft, ChevronRight, X } from 'lucide-react'
import TopBar from '../components/TopBar.jsx'
import ScorePill from '../components/ScorePill.jsx'
import MoodChip from '../components/MoodChip.jsx'
import ResolutionPill from '../components/ResolutionPill.jsx'
import { LoadingState, ErrorState, EmptyState } from '../components/PageState.jsx'
import { useApi } from '../hooks/useApi.js'
import { getAttentionQueue, getDashboardOverview, getIntents } from '../api/client.js'
import { formatDuration, initials, titleCase } from '../utils/format.js'
import { moodColor } from '../utils/mood.js'
import { getAvatarColor } from '../utils/avatarColor.js'

function KpiCard({ icon: Icon, label, value, sub, tone = 'default' }) {
  const toneClass =
    tone === 'critical'
      ? 'border-mood-angry/30 bg-mood-angry/8'
      : 'border-app-border bg-app-panel'
  return (
    <div className={`relative overflow-hidden rounded-lg border p-4 ${toneClass}`}>
      {tone === 'critical' && (
        <div
          className="pointer-events-none absolute -right-8 -top-8 h-28 w-28 rounded-full opacity-25"
          style={{ background: 'conic-gradient(from 0deg, var(--color-mood-angry), transparent 60%)' }}
        />
      )}
      <div className="relative flex items-center gap-2 text-app-text-secondary">
        <Icon size={15} className={tone === 'critical' ? 'text-mood-angry' : ''} />
        <span className="text-xs font-medium uppercase tracking-wide">{label}</span>
      </div>
      <div className={`relative mt-2 text-3xl font-semibold ${tone === 'critical' ? 'text-mood-angry' : 'text-app-text'}`}>
        {value}
      </div>
      {sub && <div className="relative mt-1 text-xs text-app-text-secondary">{sub}</div>}
    </div>
  )
}

// Same red/amber the score pill uses (var(--color-score-critical) / var(--color-score-high))
// — below 40 the row gets no accent, matching ScorePill's own "nothing to flag" reading.
function severityBorderColor(score) {
  if (score >= 70) return 'var(--color-score-critical)'
  if (score >= 40) return 'var(--color-score-high)'
  return 'transparent'
}

function FilterChip({ label, onClear }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-app-accent/40 bg-app-accent/10 px-2 py-0.5 text-xs text-app-accent">
      {label}
      <button type="button" onClick={onClear} aria-label={`Clear ${label}`} className="hover:opacity-70">
        <X size={12} />
      </button>
    </span>
  )
}

const PAGE_SIZE = 20

export default function AttentionQueue() {
  const navigate = useNavigate()
  const [offset, setOffset] = useState(0)
  const [filters, setFilters] = useState({ intent: null, mood: null })

  const { data: overview, loading: overviewLoading, error: overviewError } = useApi(getDashboardOverview, [])
  const { data: intentsData } = useApi(getIntents, [])
  const {
    data: queue,
    loading: queueLoading,
    error: queueError,
  } = useApi(
    () => getAttentionQueue({ limit: PAGE_SIZE, offset, intent: filters.intent, final_mood: filters.mood }),
    [offset, filters.intent, filters.mood],
  )

  const loading = overviewLoading || queueLoading
  const error = overviewError || queueError

  // Applying or clearing any filter always jumps back to the first page.
  const applyFilter = (patch) => {
    setFilters((f) => ({ ...f, ...patch }))
    setOffset(0)
  }
  const clearAllFilters = () => {
    setFilters({ intent: null, mood: null })
    setOffset(0)
  }

  const intentOptions = useMemo(
    () =>
      (intentsData?.intents || []).map((i) => ({
        value: i.intent,
        label: titleCase(i.intent),
        count: i.count,
      })),
    [intentsData],
  )

  const isFiltered = Boolean(filters.intent || filters.mood)

  const queueHeading = (() => {
    if (!isFiltered) return "Needs a manager's attention today — ranked by score"
    const parts = []
    if (filters.intent) parts.push(`intent “${titleCase(filters.intent)}”`)
    if (filters.mood) parts.push(`${titleCase(filters.mood)} mood`)
    return `All calls — ${parts.join(' + ')}`
  })()

  const negativePct = (() => {
    if (!overview?.mood_distribution) return null
    const dist = overview.mood_distribution
    const total = Object.values(dist).reduce((a, b) => a + b, 0)
    if (!total) return 0
    const negative = (dist.frustrated || 0) + (dist.angry || 0)
    if (negative === 0) return 0
    // round to 1 decimal instead of a whole percent — a real but small share
    // (e.g. 6/1441 = 0.4%) would otherwise display as a misleading flat "0%"
    return Math.round((negative / total) * 1000) / 10
  })()

  const moodTotal = overview?.mood_distribution
    ? Object.values(overview.mood_distribution).reduce((a, b) => a + b, 0) || 1
    : 1

  return (
    <>
      <TopBar
        title="Attention Queue"
        subtitle="Calls needing a manager's attention today, ranked"
        filter={{
          label: 'Filter by intent',
          options: intentOptions,
          value: filters.intent,
          onApply: (value) => applyFilter({ intent: value }),
        }}
      />

      <main className="flex-1 overflow-y-auto p-6">
        {loading && <LoadingState label="Loading dashboard…" />}
        {!loading && error && <ErrorState message="Couldn't reach the API. Is the backend running on :8000?" />}

        {!loading && !error && overview && (
          <>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <KpiCard
                icon={AlertOctagon}
                label="Needs attention today"
                value={overview.needs_attention}
                sub="Score ≥ 30 or escalation requested"
                tone="critical"
              />
              <KpiCard icon={Phone} label="Total calls" value={overview.total_calls} />
              <KpiCard
                icon={CheckCircle2}
                label="Resolution rate"
                value={`${overview.resolution_rate}%`}
                sub={`${overview.resolved} resolved · ${overview.unresolved} unresolved · ${overview.unknown} unknown`}
              />
              <KpiCard
                icon={Frown}
                label="Ended negative"
                value={negativePct != null ? `${negativePct}%` : '—'}
                sub="Calls ending frustrated or angry"
              />
            </div>

            <div className="mt-6 rounded-lg border border-app-border bg-app-panel p-4">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium uppercase tracking-wide text-app-text-secondary">
                  Mood distribution
                </span>
                <span className="text-xs text-app-text-secondary">Click a mood to filter the list</span>
              </div>
              <div className="mt-3 flex h-3 overflow-hidden rounded-full">
                {Object.entries(overview.mood_distribution).map(([mood, count]) => {
                  const pct = (count / moodTotal) * 100
                  if (pct <= 0) return null
                  const active = filters.mood === mood
                  return (
                    <button
                      key={mood}
                      type="button"
                      onClick={() => applyFilter({ mood: active ? null : mood })}
                      title={`${titleCase(mood)}: ${count} — click to filter`}
                      style={{ width: `${pct}%`, backgroundColor: moodColor(mood) }}
                      className={`h-full transition-opacity hover:opacity-80 ${
                        filters.mood && !active ? 'opacity-40' : ''
                      }`}
                    />
                  )
                })}
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                {Object.entries(overview.mood_distribution).map(([mood, count]) => {
                  const active = filters.mood === mood
                  return (
                    <button
                      key={mood}
                      type="button"
                      onClick={() => applyFilter({ mood: active ? null : mood })}
                      className={`flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs transition ${
                        active
                          ? 'border-app-accent bg-app-accent/10 text-app-text'
                          : 'border-app-border text-app-text-secondary hover:border-app-accent hover:text-app-text'
                      }`}
                    >
                      <span className="h-2 w-2 rounded-full" style={{ backgroundColor: moodColor(mood) }} />
                      {titleCase(mood)} ({count})
                    </button>
                  )
                })}
              </div>
            </div>
          </>
        )}

        {!loading && !error && queue && (
          <div className="mt-6 overflow-hidden rounded-lg border border-app-border bg-app-panel">
            <div className="border-b border-app-border px-4 py-3">
              <h2 className="text-sm font-semibold text-app-text">{queueHeading}</h2>
              <p className="mt-0.5 text-xs text-app-text-secondary">
                {queue.total === 0
                  ? 'None'
                  : `Showing ${queue.offset + 1}–${queue.offset + queue.count} of ${queue.total}`}
              </p>
              {isFiltered && (
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  {filters.intent && (
                    <FilterChip
                      label={`Intent: ${titleCase(filters.intent)}`}
                      onClear={() => applyFilter({ intent: null })}
                    />
                  )}
                  {filters.mood && (
                    <FilterChip
                      label={`Mood: ${titleCase(filters.mood)}`}
                      onClear={() => applyFilter({ mood: null })}
                    />
                  )}
                  <button
                    type="button"
                    onClick={clearAllFilters}
                    className="text-xs text-app-accent hover:underline"
                  >
                    Clear all
                  </button>
                </div>
              )}
            </div>

            {queue.calls.length === 0 ? (
              <EmptyState
                message={
                  isFiltered
                    ? 'No calls match the current filter.'
                    : 'No calls currently need attention.'
                }
              />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[900px] text-left text-sm">
                  <thead>
                    <tr className="border-b border-app-border text-xs uppercase tracking-wide text-app-text-secondary">
                      <th className="px-4 py-2 font-medium">Mood</th>
                      <th className="px-4 py-2 font-medium">Customer / Agent</th>
                      <th className="px-4 py-2 font-medium">Intent</th>
                      <th className="px-4 py-2 font-medium">Resolution</th>
                      <th className="px-4 py-2 text-right font-medium">Duration</th>
                      <th className="px-4 py-2 text-right font-medium">Score</th>
                      <th className="px-4 py-2 font-medium">Top reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {queue.calls.map((call) => (
                      <tr
                        key={call.call_id}
                        onClick={() => navigate(`/calls/${call.call_id}`)}
                        className="group cursor-pointer border-b border-app-border last:border-b-0 hover:bg-app-panel-raised"
                        style={{ boxShadow: `inset 3px 0 0 0 ${severityBorderColor(call.attention_score)}` }}
                      >
                        <td className="px-4 py-3">
                          <MoodChip mood={call.final_mood} size="sm" />
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <span
                              style={{ background: getAvatarColor(call.customer_name || '') }}
                              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold text-white"
                            >
                              {initials(call.customer_name)}
                            </span>
                            <div className="min-w-0">
                              <div className="truncate font-medium text-app-text">{call.customer_name || 'Unknown'}</div>
                              <div className="truncate text-xs text-app-text-secondary">with {call.agent_name || 'unknown agent'}</div>
                            </div>
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <span
                            title={titleCase(call.intent)}
                            className="inline-block max-w-[200px] truncate text-xs text-app-text-secondary"
                          >
                            {titleCase(call.intent) || 'Unknown'}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <ResolutionPill resolution={call.resolution} />
                        </td>
                        <td className="px-4 py-3 text-right font-mono-data text-xs text-app-text-secondary">
                          {formatDuration(call.duration_seconds)}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <ScorePill score={call.attention_score} size="sm" />
                        </td>
                        <td
                          className="relative px-4 py-3 pr-7 max-w-[240px] truncate text-xs text-app-text-secondary"
                          title={call.top_reason}
                        >
                          {call.top_reason || '—'}
                          <ChevronRight
                            size={14}
                            className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-app-text-secondary opacity-0 transition-opacity duration-[120ms] group-hover:opacity-100"
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {queue.total > PAGE_SIZE && (
              <div className="flex items-center justify-between border-t border-app-border px-4 py-3 text-xs">
                <button
                  type="button"
                  disabled={offset === 0}
                  onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
                  className="flex items-center gap-1 rounded-md border border-app-border px-2 py-1 text-app-text-secondary hover:text-app-text disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <ChevronLeft size={13} /> Previous
                </button>
                <span className="text-app-text-secondary">
                  Page {Math.floor(offset / PAGE_SIZE) + 1} of {Math.ceil(queue.total / PAGE_SIZE)}
                </span>
                <button
                  type="button"
                  disabled={offset + PAGE_SIZE >= queue.total}
                  onClick={() => setOffset((o) => o + PAGE_SIZE)}
                  className="flex items-center gap-1 rounded-md border border-app-border px-2 py-1 text-app-text-secondary hover:text-app-text disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Next <ChevronRight size={13} />
                </button>
              </div>
            )}
          </div>
        )}
      </main>
    </>
  )
}
