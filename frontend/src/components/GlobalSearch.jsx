import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search, X, Loader2 } from 'lucide-react'
import { searchCalls } from '../api/client.js'
import { titleCase, truncate } from '../utils/format.js'
import ScorePill from './ScorePill.jsx'

const MIN_QUERY_LENGTH = 3
const DEBOUNCE_MS = 350

/** Global semantic search — lives in the top bar on every page, not a route of its
 * own. Wraps GET /api/search (ChromaDB similarity over call summaries). */
export default function GlobalSearch() {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [open, setOpen] = useState(false)
  const containerRef = useRef(null)
  const requestId = useRef(0)
  const navigate = useNavigate()

  useEffect(() => {
    const trimmed = query.trim()
    if (trimmed.length < MIN_QUERY_LENGTH) {
      setResults([])
      setLoading(false)
      setError(null)
      return
    }
    const id = ++requestId.current
    setLoading(true)
    setError(null)
    const timer = setTimeout(() => {
      searchCalls(trimmed)
        .then((data) => {
          if (requestId.current !== id) return // a newer query has since fired
          setResults(data.results || [])
        })
        .catch((err) => {
          if (requestId.current !== id) return
          const status = err?.response?.status
          setError(status === 503 ? 'Search index unavailable right now.' : 'Search failed.')
          setResults([])
        })
        .finally(() => {
          if (requestId.current === id) setLoading(false)
        })
    }, DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [query])

  useEffect(() => {
    const onClickOutside = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) setOpen(false)
    }
    const onKeyDown = (e) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onClickOutside)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onClickOutside)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [])

  const showDropdown = open && query.trim().length >= MIN_QUERY_LENGTH

  const handleSelect = (callId) => {
    navigate(`/calls/${callId}`)
    setOpen(false)
    setQuery('')
  }

  return (
    <div ref={containerRef} className="relative w-full max-w-md">
      <div className="flex items-center gap-2 rounded-md border border-app-border bg-app-bg px-3 py-1.5 focus-within:border-app-accent">
        <Search size={15} className="shrink-0 text-app-text-secondary" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => setOpen(true)}
          placeholder="Search calls by meaning — e.g. “angry customer unresolved”"
          className="w-full bg-transparent text-sm text-app-text placeholder:text-app-text-secondary focus:outline-none"
        />
        {loading && <Loader2 size={14} className="shrink-0 animate-spin text-app-text-secondary" />}
        {!loading && query && (
          <button type="button" onClick={() => setQuery('')} aria-label="Clear search">
            <X size={14} className="text-app-text-secondary hover:text-app-text" />
          </button>
        )}
      </div>

      {showDropdown && (
        <div className="absolute left-0 right-0 top-full z-30 mt-2 max-h-[70vh] overflow-y-auto rounded-lg border border-app-border bg-app-panel shadow-xl">
          {error && <div className="p-4 text-sm text-app-text-secondary">{error}</div>}

          {!error && !loading && results.length === 0 && (
            <div className="p-4 text-sm text-app-text-secondary">No calls match “{query.trim()}”.</div>
          )}

          {!error &&
            results.map((r) => (
              <button
                key={r.call_id}
                type="button"
                onClick={() => handleSelect(r.call_id)}
                className="flex w-full items-start gap-3 border-b border-app-border px-4 py-3 text-left last:border-b-0 hover:bg-app-panel-raised"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-app-text">{r.customer_name || 'Unknown customer'}</span>
                    <span className="text-xs text-app-text-secondary">with {r.agent_name || 'unknown agent'}</span>
                    <span className="rounded-full border border-app-border px-2 py-0.5 text-xs text-app-text-secondary">
                      {titleCase(r.intent) || 'Unknown intent'}
                    </span>
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs ${
                        r.resolution === 'unresolved'
                          ? 'bg-mood-angry/15 text-mood-angry'
                          : 'bg-mood-happy/15 text-mood-happy'
                      }`}
                    >
                      {titleCase(r.resolution) || 'Unknown'}
                    </span>
                  </div>
                  <p className="mt-1 truncate text-sm text-app-text-secondary">{truncate(r.summary, 110)}</p>
                </div>
                <div className="flex shrink-0 flex-col items-end gap-1.5">
                  <ScorePill score={r.attention_score} size="sm" />
                  <span className="rounded-full border border-app-accent/40 px-2 py-0.5 text-xs text-app-accent">
                    {Math.round((r.similarity_score ?? 0) * 100)}% match
                  </span>
                </div>
              </button>
            ))}
        </div>
      )}
    </div>
  )
}
