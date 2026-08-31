import { useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, ChevronRight } from 'lucide-react'
import TopBar from '../components/TopBar.jsx'
import ScorePill from '../components/ScorePill.jsx'
import ResolutionPill from '../components/ResolutionPill.jsx'
import MoodChip from '../components/MoodChip.jsx'
import { LoadingState, ErrorState, EmptyState } from '../components/PageState.jsx'
import { useApi } from '../hooks/useApi.js'
import { getCustomerCalls } from '../api/client.js'
import { formatDate, formatDuration, formatRelativeTime, initials, titleCase, truncate } from '../utils/format.js'
import { getAvatarColor } from '../utils/avatarColor.js'

export default function CustomerDetail() {
  const { customerId } = useParams()
  const navigate = useNavigate()
  const { data, loading, error } = useApi(() => getCustomerCalls(customerId), [customerId])

  // The customer-calls endpoint doesn't return aggregate stats itself (only the
  // customer-list endpoint does) — derive them here from the same calls it returns.
  const stats = useMemo(() => {
    if (!data?.calls?.length) return null
    const unresolved = data.calls.filter((c) => c.resolution === 'unresolved').length
    const avgScore = Math.round(
      data.calls.reduce((sum, c) => sum + (c.attention_score ?? 0), 0) / data.calls.length,
    )
    return { unresolved, avgScore }
  }, [data])

  return (
    <>
      <TopBar>
        <button
          type="button"
          onClick={() => navigate('/customers')}
          className="mb-1.5 inline-flex items-center gap-1.5 rounded-md border border-app-border bg-app-panel px-3 py-1.5 text-sm font-medium text-app-text-secondary transition hover:border-app-accent hover:text-app-text"
        >
          <ArrowLeft size={15} /> Back
        </button>
        {data && <h1 className="text-lg font-semibold text-app-text">{data.customer_name}</h1>}
      </TopBar>

      <main className="flex-1 overflow-y-auto p-6">
        {loading && <LoadingState label="Loading customer…" />}
        {!loading && error && (
          <ErrorState message={error?.response?.status === 404 ? 'Customer not found.' : "Couldn't load this customer."} />
        )}

        {!loading && !error && data && (
          <>
            <div className="mb-6 flex items-center gap-4 rounded-lg border border-app-border bg-app-panel p-4">
              <span
                style={{ background: getAvatarColor(data.customer_name || '') }}
                className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full text-base font-semibold text-white"
              >
                {initials(data.customer_name)}
              </span>
              <div className="grid flex-1 grid-cols-3 gap-4">
                <div>
                  <div className="text-xs uppercase tracking-wide text-app-text-secondary">Total calls</div>
                  <div className="mt-1 text-xl font-semibold text-app-text">{data.total_calls}</div>
                </div>
                <div>
                  <div className="text-xs uppercase tracking-wide text-app-text-secondary">Unresolved</div>
                  <div className={`mt-1 text-xl font-semibold ${stats?.unresolved ? 'text-mood-angry' : 'text-app-text'}`}>
                    {stats?.unresolved ?? 0}
                  </div>
                </div>
                <div>
                  <div className="text-xs uppercase tracking-wide text-app-text-secondary">Avg attention</div>
                  <div className="mt-1 text-xl font-semibold text-app-text">{stats?.avgScore ?? '—'}</div>
                </div>
              </div>
            </div>

            {data.calls.length === 0 ? (
              <EmptyState message="No processed calls for this customer." />
            ) : (
              <div className="overflow-hidden rounded-lg border border-app-border bg-app-panel">
                <div className="border-b border-app-border px-4 py-3">
                  <h2 className="text-sm font-semibold text-app-text">Call history</h2>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[760px] text-left text-sm">
                    <thead>
                      <tr className="border-b border-app-border text-xs uppercase tracking-wide text-app-text-secondary">
                        <th className="px-4 py-2 font-medium">Date</th>
                        <th className="px-4 py-2 font-medium">Intent</th>
                        <th className="px-4 py-2 font-medium">Mood shift</th>
                        <th className="px-4 py-2 font-medium">Resolution</th>
                        <th className="px-4 py-2 text-right font-medium">Duration</th>
                        <th className="px-4 py-2 text-right font-medium">Score</th>
                        <th className="px-4 py-2 font-medium">Summary</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.calls.map((call) => (
                        <tr
                          key={call.call_id}
                          onClick={() => navigate(`/calls/${call.call_id}`)}
                          className="group cursor-pointer border-b border-app-border last:border-b-0 hover:bg-app-panel-raised"
                        >
                          <td className="px-4 py-3 whitespace-nowrap text-app-text-secondary">
                            <span title={formatDate(call.started_at)}>{formatRelativeTime(call.started_at)}</span>
                          </td>
                          <td className="px-4 py-3">
                            <span
                              title={titleCase(call.intent)}
                              className="inline-block max-w-[180px] truncate text-xs text-app-text-secondary"
                            >
                              {titleCase(call.intent) || 'Unknown'}
                            </span>
                          </td>
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-1.5">
                              <MoodChip mood={call.initial_mood} size="sm" showLabel={false} />
                              <span className="text-app-text-secondary">→</span>
                              <MoodChip mood={call.final_mood} size="sm" />
                            </div>
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
                            className="relative px-4 py-3 pr-7 max-w-[260px] truncate text-xs text-app-text-secondary"
                            title={call.summary}
                          >
                            {truncate(call.summary, 70)}
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
              </div>
            )}
          </>
        )}
      </main>
    </>
  )
}
