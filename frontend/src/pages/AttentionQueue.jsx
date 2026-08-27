import { useNavigate } from 'react-router-dom'
import { AlertOctagon, Phone, CheckCircle2, Frown } from 'lucide-react'
import TopBar from '../components/TopBar.jsx'
import ScorePill from '../components/ScorePill.jsx'
import MoodChip from '../components/MoodChip.jsx'
import ResolutionPill from '../components/ResolutionPill.jsx'
import { LoadingState, ErrorState, EmptyState } from '../components/PageState.jsx'
import { useApi } from '../hooks/useApi.js'
import { getAttentionQueue, getDashboardOverview } from '../api/client.js'
import { formatDuration, initials, titleCase } from '../utils/format.js'
import { moodColor } from '../utils/mood.js'

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

export default function AttentionQueue() {
  const navigate = useNavigate()
  const { data: overview, loading: overviewLoading, error: overviewError } = useApi(getDashboardOverview, [])
  const { data: queue, loading: queueLoading, error: queueError } = useApi(getAttentionQueue, [])

  const loading = overviewLoading || queueLoading
  const error = overviewError || queueError

  const negativePct = (() => {
    if (!overview?.mood_distribution) return null
    const dist = overview.mood_distribution
    const total = Object.values(dist).reduce((a, b) => a + b, 0)
    if (!total) return 0
    const negative = (dist.frustrated || 0) + (dist.angry || 0)
    return Math.round((negative / total) * 100)
  })()

  return (
    <>
      <TopBar>
        <h1 className="text-sm font-semibold text-app-text">Attention Queue</h1>
        <p className="text-xs text-app-text-secondary">Calls needing a manager's attention today, ranked</p>
      </TopBar>

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
                sub={`${overview.resolved} resolved · ${overview.unresolved} unresolved`}
              />
              <KpiCard
                icon={Frown}
                label="Negative sentiment"
                value={negativePct != null ? `${negativePct}%` : '—'}
                sub="Calls ending frustrated or angry"
              />
            </div>

            <div className="mt-6 flex items-center gap-4 rounded-lg border border-app-border bg-app-panel p-4">
              <span className="shrink-0 text-xs font-medium uppercase tracking-wide text-app-text-secondary">
                Mood distribution
              </span>
              <div className="flex h-3 flex-1 overflow-hidden rounded-full">
                {Object.entries(overview.mood_distribution).map(([mood, count]) => {
                  const total = Object.values(overview.mood_distribution).reduce((a, b) => a + b, 0) || 1
                  const pct = (count / total) * 100
                  if (pct <= 0) return null
                  return <div key={mood} style={{ width: `${pct}%`, backgroundColor: moodColor(mood) }} title={`${mood}: ${count}`} />
                })}
              </div>
              <div className="hidden shrink-0 flex-wrap items-center gap-3 md:flex">
                {Object.entries(overview.mood_distribution).map(([mood, count]) => (
                  <span key={mood} className="flex items-center gap-1 text-xs text-app-text-secondary">
                    <span className="h-2 w-2 rounded-full" style={{ backgroundColor: moodColor(mood) }} />
                    {titleCase(mood)} ({count})
                  </span>
                ))}
              </div>
            </div>
          </>
        )}

        {!loading && !error && queue && (
          <div className="mt-6 overflow-hidden rounded-lg border border-app-border bg-app-panel">
            <div className="border-b border-app-border px-4 py-3">
              <h2 className="text-sm font-semibold text-app-text">
                Needs a manager's attention today — top {queue.count} by score
              </h2>
            </div>

            {queue.calls.length === 0 ? (
              <EmptyState message="No calls currently need attention." />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[900px] text-left text-sm">
                  <thead>
                    <tr className="border-b border-app-border text-xs uppercase tracking-wide text-app-text-secondary">
                      <th className="px-4 py-2 font-medium">Mood</th>
                      <th className="px-4 py-2 font-medium">Customer / Agent</th>
                      <th className="px-4 py-2 font-medium">Intent</th>
                      <th className="px-4 py-2 font-medium">Resolution</th>
                      <th className="px-4 py-2 font-medium">Duration</th>
                      <th className="px-4 py-2 font-medium">Score</th>
                      <th className="px-4 py-2 font-medium">Top reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {queue.calls.map((call, i) => (
                      <tr
                        key={call.call_id}
                        onClick={() => navigate(`/calls/${call.call_id}`)}
                        className={`cursor-pointer border-b border-app-border last:border-b-0 hover:bg-app-panel-raised ${
                          i < 3 ? 'relative' : ''
                        }`}
                        style={i < 3 ? { boxShadow: `inset 3px 0 0 0 ${moodColor(call.final_mood)}` } : undefined}
                      >
                        <td className="px-4 py-3">
                          <MoodChip mood={call.final_mood} size="sm" />
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-app-accent/15 text-[11px] font-semibold text-app-accent">
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
                            className="inline-flex max-w-[200px] truncate rounded-full border border-app-border px-2 py-0.5 text-xs text-app-text-secondary"
                          >
                            {titleCase(call.intent) || 'Unknown'}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <ResolutionPill resolution={call.resolution} />
                        </td>
                        <td className="px-4 py-3 font-mono-data text-xs text-app-text-secondary">
                          {formatDuration(call.duration_seconds)}
                        </td>
                        <td className="px-4 py-3">
                          <ScorePill score={call.attention_score} size="sm" />
                        </td>
                        <td className="px-4 py-3 max-w-[240px] truncate text-xs text-app-text-secondary" title={call.top_reason}>
                          {call.top_reason || '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </main>
    </>
  )
}
