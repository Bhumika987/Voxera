import { useMemo } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import TopBar from '../components/TopBar.jsx'
import { LoadingState, ErrorState, EmptyState } from '../components/PageState.jsx'
import { useApi } from '../hooks/useApi.js'
import { getAgents, getTrends } from '../api/client.js'
import { formatDuration, titleCase, truncate } from '../utils/format.js'

function trendColor(unresolvedCount, count) {
  const ratio = count > 0 ? unresolvedCount / count : 0
  if (ratio >= 0.3) return 'var(--color-mood-angry)'
  if (ratio >= 0.15) return 'var(--color-mood-confused)'
  return 'var(--color-mood-happy)'
}

function TrendTooltip({ active, payload }) {
  if (!active || !payload?.length) return null
  const d = payload[0].payload
  return (
    <div className="rounded-md border border-app-border bg-app-panel-raised p-2.5 text-xs shadow-lg">
      <div className="font-medium text-app-text">{titleCase(d.intent) || 'Unknown'}</div>
      <div className="mt-1 text-app-text-secondary">{d.count} calls · {d.unresolved_count} unresolved</div>
      <div className="text-app-text-secondary">Avg attention {d.avg_attention_score}</div>
    </div>
  )
}

export default function AgentsTrends() {
  const { data: agentsData, loading: agentsLoading, error: agentsError } = useApi(getAgents, [])
  const { data: trendsData, loading: trendsLoading, error: trendsError } = useApi(getTrends, [])

  const loading = agentsLoading || trendsLoading
  const error = agentsError || trendsError

  // Default API order is total_calls desc — re-sort by attention_calls desc so the
  // agents needing coaching attention surface first.
  const agents = useMemo(() => {
    if (!agentsData?.agents) return []
    return [...agentsData.agents].sort((a, b) => b.attention_calls - a.attention_calls)
  }, [agentsData])

  const trendRows = useMemo(() => {
    if (!trendsData?.trends) return []
    return trendsData.trends.map((t) => ({ ...t, label: truncate(titleCase(t.intent) || 'Unknown', 28) }))
  }, [trendsData])

  return (
    <>
      <TopBar
        title="Agents & Trends"
        subtitle="Coaching priorities and trending issues, not daily triage"
      />

      <main className="flex-1 overflow-y-auto p-6">
        {loading && <LoadingState label="Loading agent and trend data…" />}
        {!loading && error && <ErrorState message="Couldn't load agent/trend data." />}

        {!loading && !error && (
          <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
            <section className="overflow-hidden rounded-lg border border-app-border bg-app-panel">
              <div className="border-b border-app-border px-4 py-3">
                <h2 className="text-sm font-semibold text-app-text">Agent leaderboard</h2>
                <p className="text-xs text-app-text-secondary">Sorted by attention-needing calls — coaching priority first</p>
              </div>
              {agents.length === 0 ? (
                <EmptyState message="No agent data yet." />
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[560px] text-left text-sm">
                    <thead>
                      <tr className="border-b border-app-border text-xs uppercase tracking-wide text-app-text-secondary">
                        <th className="px-4 py-2 font-medium">Agent</th>
                        <th className="px-4 py-2 text-right font-medium">Calls</th>
                        <th className="px-4 py-2 font-medium">Resolution</th>
                        <th className="px-4 py-2 text-right font-medium">Avg handle time</th>
                        <th className="px-4 py-2 font-medium">Attention calls</th>
                      </tr>
                    </thead>
                    <tbody>
                      {agents.map((a) => (
                        <tr key={a.agent_id} className="border-b border-app-border last:border-b-0">
                          <td className="px-4 py-3 font-medium text-app-text">{a.name}</td>
                          <td className="px-4 py-3 text-right text-app-text-secondary">{a.total_calls}</td>
                          <td className="px-4 py-3 text-app-text-secondary">
                            {a.resolution_rate}%
                            <span className="ml-1 text-xs">
                              ({a.resolved}/{a.unresolved})
                            </span>
                          </td>
                          <td className="px-4 py-3 text-right font-mono-data text-xs text-app-text-secondary">
                            {formatDuration(a.avg_duration)}
                          </td>
                          <td className="px-4 py-3">
                            <span
                              className={`inline-flex min-w-[1.75rem] items-center justify-center rounded-full px-2 py-0.5 text-xs font-semibold ${
                                a.attention_calls > 0 ? 'bg-mood-angry/15 text-mood-angry' : 'bg-app-border/60 text-app-text-secondary'
                              }`}
                            >
                              {a.attention_calls}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            <section className="overflow-hidden rounded-lg border border-app-border bg-app-panel">
              <div className="border-b border-app-border px-4 py-3">
                <h2 className="text-sm font-semibold text-app-text">Trending intents</h2>
                <p className="text-xs text-app-text-secondary">Top {trendsData?.count ?? 0} by call volume · colored by unresolved share</p>
              </div>
              {trendRows.length === 0 ? (
                <EmptyState message="No trend data yet." />
              ) : (
                <div className="p-2" style={{ height: Math.max(280, trendRows.length * 42) }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={trendRows} layout="vertical" margin={{ top: 8, right: 24, bottom: 8, left: 8 }}>
                      <CartesianGrid horizontal={false} stroke="var(--color-app-border)" />
                      <XAxis type="number" tick={{ fill: 'var(--color-app-text-secondary)', fontSize: 11 }} axisLine={{ stroke: 'var(--color-app-border)' }} tickLine={false} />
                      <YAxis
                        type="category"
                        dataKey="label"
                        width={150}
                        tick={{ fill: 'var(--color-app-text-secondary)', fontSize: 11 }}
                        axisLine={{ stroke: 'var(--color-app-border)' }}
                        tickLine={false}
                      />
                      <Tooltip content={<TrendTooltip />} cursor={{ fill: 'var(--color-app-border)', opacity: 0.3 }} />
                      <Bar dataKey="count" radius={[0, 4, 4, 0]} barSize={16}>
                        {trendRows.map((row, i) => (
                          <Cell key={i} fill={trendColor(row.unresolved_count, row.count)} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </section>
          </div>
        )}
      </main>
    </>
  )
}
