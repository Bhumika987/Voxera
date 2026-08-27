import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search, ArrowUpDown, ChevronUp, ChevronDown } from 'lucide-react'
import TopBar from '../components/TopBar.jsx'
import { LoadingState, ErrorState, EmptyState } from '../components/PageState.jsx'
import { useApi } from '../hooks/useApi.js'
import { getCustomers } from '../api/client.js'
import { formatRelativeTime, initials } from '../utils/format.js'
import { scoreColor } from '../utils/scoreBands.js'

const COLUMNS = [
  { key: 'name', label: 'Customer' },
  { key: 'total_calls', label: 'Total calls' },
  { key: 'unresolved_calls', label: 'Unresolved' },
  { key: 'last_call_at', label: 'Last call' },
  { key: 'avg_attention_score', label: 'Avg attention' },
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
      <TopBar>
        <h1 className="text-sm font-semibold text-app-text">Customers</h1>
        <p className="text-xs text-app-text-secondary">{data ? `${data.count} customers` : 'Browse by name'}</p>
      </TopBar>

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
                          <th key={col.key} className="px-4 py-2 font-medium">
                            <button
                              type="button"
                              onClick={() => toggleSort(col.key)}
                              className="flex items-center gap-1 hover:text-app-text"
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
                          className="cursor-pointer border-b border-app-border last:border-b-0 hover:bg-app-panel-raised"
                        >
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-2.5">
                              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-app-accent/15 text-[11px] font-semibold text-app-accent">
                                {initials(c.name)}
                              </span>
                              <span className="font-medium text-app-text">{c.name}</span>
                            </div>
                          </td>
                          <td className="px-4 py-3 text-app-text-secondary">{c.total_calls}</td>
                          <td className="px-4 py-3">
                            {c.unresolved_calls > 0 ? (
                              <span className="inline-flex items-center gap-1.5 text-mood-angry">
                                <span className="h-1.5 w-1.5 rounded-full bg-mood-angry" />
                                {c.unresolved_calls}
                              </span>
                            ) : (
                              <span className="text-app-text-secondary">0</span>
                            )}
                          </td>
                          <td className="px-4 py-3 text-app-text-secondary">{formatRelativeTime(c.last_call_at)}</td>
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-2">
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
