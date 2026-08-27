import { useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import TopBar from '../components/TopBar.jsx'
import ScorePill from '../components/ScorePill.jsx'
import ResolutionPill from '../components/ResolutionPill.jsx'
import MoodChip from '../components/MoodChip.jsx'
import { LoadingState, ErrorState, EmptyState } from '../components/PageState.jsx'
import { useApi } from '../hooks/useApi.js'
import { getCustomerCalls } from '../api/client.js'
import { formatDate, formatDuration, initials, titleCase, truncate } from '../utils/format.js'

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
          className="mb-1 flex items-center gap-1 text-xs text-app-text-secondary hover:text-app-text"
        >
          <ArrowLeft size={12} /> Customers
        </button>
        {data && <h1 className="text-sm font-semibold text-app-text">{data.customer_name}</h1>}
      </TopBar>

      <main className="flex-1 overflow-y-auto p-6">
        {loading && <LoadingState label="Loading customer…" />}
        {!loading && error && (
          <ErrorState message={error?.response?.status === 404 ? 'Customer not found.' : "Couldn't load this customer."} />
        )}

        {!loading && !error && data && (
          <>
            <div className="mb-6 flex items-center gap-4 rounded-lg border border-app-border bg-app-panel p-4">
              <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-app-accent/15 text-base font-semibold text-app-accent">
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
                        <th className="px-4 py-2 font-medium">Duration</th>
                        <th className="px-4 py-2 font-medium">Score</th>
                        <th className="px-4 py-2 font-medium">Summary</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.calls.map((call) => (
                        <tr
                          key={call.call_id}
                          onClick={() => navigate(`/calls/${call.call_id}`)}
                          className="cursor-pointer border-b border-app-border last:border-b-0 hover:bg-app-panel-raised"
                        >
                          <td className="px-4 py-3 whitespace-nowrap text-app-text-secondary">{formatDate(call.started_at)}</td>
                          <td className="px-4 py-3">
                            <span
                              title={titleCase(call.intent)}
                              className="inline-flex max-w-[180px] truncate rounded-full border border-app-border px-2 py-0.5 text-xs text-app-text-secondary"
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
                          <td className="px-4 py-3 font-mono-data text-xs text-app-text-secondary">
                            {formatDuration(call.duration_seconds)}
                          </td>
                          <td className="px-4 py-3">
                            <ScorePill score={call.attention_score} size="sm" />
                          </td>
                          <td className="px-4 py-3 max-w-[260px] truncate text-xs text-app-text-secondary" title={call.summary}>
                            {truncate(call.summary, 70)}
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
