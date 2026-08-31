import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search, ArrowUpDown, ChevronUp, ChevronDown, ChevronRight } from 'lucide-react'
import TopBar from '../components/TopBar.jsx'
import { LoadingState, ErrorState, EmptyState } from '../components/PageState.jsx'
import { useApi } from '../hooks/useApi.js'
import { getCustomers } from '../api/client.js'
import { formatDateTime, formatRelativeTime, initials } from '../utils/format.js'
import { scoreColor } from '../utils/scoreBands.js'
import { getAvatarColor } from '../utils/avatarColor.js'

const COLUMNS = [
  { key: 'name', label: 'Customer' },
  { key: 'total_calls', label: 'Total calls', align: 'right' },
  { key: 'unresolved_calls', label: 'Unresolved', align: 'right' },
  { key: 'last_call_at', label: 'Last call' },
  { key: 'avg_attention_score', label: 'Avg attention', align: 'right' },
]

export default function CustomerList() {
  const navigate = useNavigate()
  const { data, loading, error } = useApi(getCustomers, [])
  const [query, setQuery] = useState('')
  const [sortKey, setSortKey] = useState('last_call_at')
  const [sortDir, setSortDir] = useState('desc')

  const rows = useMemo(() => {
    if (!data?.customers) return []
    const filtered = query.trim()
      ? data.customers.filter((c) => c.name?.toLowerCase().includes(query.trim().toLowerCase()))
      : data.customers
    const sorted = [...filtered].sort((a, b) => {
      const av = a[sortKey]
      const bv = b[sortKey]
      if (av == null) return 1
      if (bv == null) return -1
      if (typeof av === 'string') return sortDir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av)
      return sortDir === 'asc' ? av - bv : bv - av
    })
    return sorted
  }, [data, query, sortKey, sortDir])

  const toggleSort = (key) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  return (
    <>
      <TopBar title="Customers" subtitle={data ? `${data.count} customers` : 'Browse by name'} />

      <main className="flex-1 overflow-y-auto p-6">
        {loading && <LoadingState label="Loading customers…" />}
        {!loading && error && <ErrorState message="Couldn't load customers." />}

        {!loading && !error && data && (
          <>
            <div className="mb-4 flex items-center gap-2 rounded-md border border-app-border bg-app-panel px-3 py-2 sm:max-w-sm">
              <Search size={15} className="text-app-text-secondary" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Filter by name…"
                className="w-full bg-transparent text-sm text-app-text placeholder:text-app-text-secondary focus:outline-none"
              />
            </div>

            {rows.length === 0 ? (
              <EmptyState message="No customers match that filter." />
            ) : (
              <div className="overflow-hidden rounded-lg border border-app-border bg-app-panel">
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[720px] text-left text-sm">
                    <thead>
                      <tr className="border-b border-app-border text-xs uppercase tracking-wide text-app-text-secondary">
                        {COLUMNS.map((col) => (
                          <th
                            key={col.key}
                            className={`px-4 py-2 font-medium ${col.align === 'right' ? 'text-right' : ''}`}
                          >
                            <button
                              type="button"
                              onClick={() => toggleSort(col.key)}
                              className={`flex items-center gap-1 hover:text-app-text ${
                                col.align === 'right' ? 'ml-auto' : ''
                              }`}
                            >
                              {col.label}
                              {sortKey === col.key ? (
                                sortDir === 'asc' ? (
                                  <ChevronUp size={12} />
                                ) : (
                                  <ChevronDown size={12} />
                                )
                              ) : (
                                <ArrowUpDown size={11} className="opacity-40" />
                              )}
                            </button>
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((c) => (
                        <tr
                          key={c.customer_id}
                          onClick={() => navigate(`/customers/${c.customer_id}`)}
                          className="group cursor-pointer border-b border-app-border last:border-b-0 hover:bg-app-panel-raised"
                        >
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-2.5">
                              <span
                                style={{ background: getAvatarColor(c.name || '') }}
                                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold text-white"
                              >
                                {initials(c.name)}
                              </span>
                              <span className="font-medium text-app-text">{c.name}</span>
                            </div>
                          </td>
                          <td className="px-4 py-3 text-right text-app-text-secondary">{c.total_calls}</td>
                          <td className="px-4 py-3 text-right">
                            {c.unresolved_calls > 0 ? (
                              <span className="inline-flex items-center gap-1.5 text-mood-angry">
                                <span className="h-1.5 w-1.5 rounded-full bg-mood-angry" />
                                {c.unresolved_calls}
                              </span>
                            ) : (
                              <span className="text-app-text-secondary">0</span>
                            )}
                          </td>
                          <td className="px-4 py-3 text-app-text-secondary">
                            <span title={formatDateTime(c.last_call_at)}>{formatRelativeTime(c.last_call_at)}</span>
                          </td>
                          <td className="relative px-4 py-3 pr-7 text-right">
                            <div className="flex items-center justify-end gap-2">
                              <span className="font-mono-data text-xs text-app-text-secondary">
                                {c.avg_attention_score}
                              </span>
                              <div className="h-1.5 w-16 overflow-hidden rounded-full bg-app-border">
                                <div
                                  className="h-full rounded-full"
                                  style={{
                                    width: `${Math.min(100, c.avg_attention_score)}%`,
                                    backgroundColor: scoreColor(c.avg_attention_score),
                                  }}
                                />
                              </div>
                            </div>
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
