import { useCallback, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Loader2,
  CircleDot,
  CheckCircle2,
  XCircle,
  ChevronDown,
  ChevronRight,
  UserPlus,
  RotateCcw,
} from 'lucide-react'
import TopBar from '../components/TopBar.jsx'
import ResolutionPill from '../components/ResolutionPill.jsx'
import MoodChip from '../components/MoodChip.jsx'
import { LoadingState, ErrorState, EmptyState } from '../components/PageState.jsx'
import { useApi } from '../hooks/useApi.js'
import { getActionItems, getActionItem, updateActionItem } from '../api/client.js'
import { formatRelativeTime, titleCase } from '../utils/format.js'

const PRIORITY = {
  high: { dot: 'var(--color-score-critical)', label: 'High priority' },
  medium: { dot: 'var(--color-mood-frustrated)', label: 'Medium priority' },
  low: { dot: 'var(--color-mood-confused)', label: 'Low priority' },
}

const STATUS_STYLE = {
  open: 'bg-app-border/60 text-app-text-secondary',
  investigating: 'bg-mood-confused/15 text-mood-confused',
  resolved: 'bg-mood-happy/15 text-mood-happy',
  dismissed: 'bg-app-border/50 text-app-text-secondary line-through',
}

const STATUS_LABEL = {
  open: 'Open',
  investigating: 'Investigating',
  resolved: 'Resolved',
  dismissed: 'Dismissed',
}

const TABS = [
  { key: 'active', label: 'Active', match: (s) => s === 'open' || s === 'investigating' },
  { key: 'resolved', label: 'Resolved', match: (s) => s === 'resolved' },
  { key: 'dismissed', label: 'Dismissed', match: (s) => s === 'dismissed' },
  { key: 'all', label: 'All', match: () => true },
]

function Kpi({ icon: Icon, label, value, tone }) {
  return (
    <div className="rounded-lg border border-app-border bg-app-panel p-4">
      <div className="flex items-center gap-2 text-app-text-secondary">
        <Icon size={15} className={tone} />
        <span className="text-xs font-medium uppercase tracking-wide">{label}</span>
      </div>
      <div className="mt-2 text-3xl font-semibold text-app-text">{value}</div>
    </div>
  )
}

function ActionButton({ onClick, busy, children, primary }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy}
      className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium transition disabled:opacity-40 ${
        primary
          ? 'border-app-accent bg-app-accent/10 text-app-accent hover:bg-app-accent/20'
          : 'border-app-border text-app-text-secondary hover:border-app-accent hover:text-app-text'
      }`}
    >
      {children}
    </button>
  )
}

function EntityList({ action }) {
  const navigate = useNavigate()
  const { data, loading, error } = useApi(() => getActionItem(action.id), [action.id, action.updated_at])

  if (loading) {
    return (
      <div className="flex items-center gap-2 px-4 py-3 text-xs text-app-text-secondary">
        <Loader2 size={13} className="animate-spin" /> Loading affected records…
      </div>
    )
  }
  if (error) return <div className="px-4 py-3 text-xs text-mood-angry">Couldn't load the affected records.</div>

  const entities = data?.entities || []
  if (entities.length === 0) {
    return <div className="px-4 py-3 text-xs text-app-text-secondary">No matching records remain.</div>
  }

  return (
    <div className="overflow-x-auto border-t border-app-border">
      <table className="w-full min-w-[560px] text-left text-sm">
        <tbody>
          {entities.map((e) =>
            e.type === 'call' ? (
              <tr
                key={e.call_id}
                onClick={() => navigate(`/calls/${e.call_id}`)}
                className="group cursor-pointer border-b border-app-border last:border-b-0 hover:bg-app-panel-raised"
              >
                <td className="px-4 py-2.5">
                  <div className="font-medium text-app-text">{e.customer_name || 'Unknown'}</div>
                  <div className="text-xs text-app-text-secondary">with {e.agent_name || 'unknown agent'}</div>
                </td>
                <td className="px-4 py-2.5 text-xs text-app-text-secondary">{titleCase(e.intent) || '—'}</td>
                <td className="px-4 py-2.5">
                  <MoodChip mood={e.final_mood} size="sm" />
                </td>
                <td className="px-4 py-2.5">
                  <ResolutionPill resolution={e.resolution} />
                </td>
                <td className="px-4 py-2.5 text-right text-xs text-app-text-secondary">
                  {formatRelativeTime(e.started_at)}
                  <ChevronRight size={13} className="ml-1 inline opacity-0 transition group-hover:opacity-100" />
                </td>
              </tr>
            ) : (
              <tr
                key={e.customer_id}
                onClick={() => navigate(`/customers/${e.customer_id}`)}
                className="group cursor-pointer border-b border-app-border last:border-b-0 hover:bg-app-panel-raised"
              >
                <td className="px-4 py-2.5 font-medium text-app-text">{e.name}</td>
                <td className="px-4 py-2.5 text-xs text-app-text-secondary">{e.total_calls} calls</td>
                <td className="px-4 py-2.5 text-xs text-mood-angry">{e.unresolved_calls} unresolved</td>
                <td className="px-4 py-2.5 text-right text-xs text-app-text-secondary">
                  last {formatRelativeTime(e.last_call_at)}
                  <ChevronRight size={13} className="ml-1 inline opacity-0 transition group-hover:opacity-100" />
                </td>
              </tr>
            ),
          )}
        </tbody>
      </table>
    </div>
  )
}

function ActionCard({ action, onMutate }) {
  const [expanded, setExpanded] = useState(false)
  const [busy, setBusy] = useState(false)
  const p = PRIORITY[action.priority] || PRIORITY.low
  const isActive = action.status === 'open' || action.status === 'investigating'

  const mutate = async (patch) => {
    setBusy(true)
    try {
      await updateActionItem(action.id, patch)
      await onMutate()
    } finally {
      setBusy(false)
    }
  }

  const assign = () => {
    const name = window.prompt('Assign follow-up to:', action.assigned_to || '')
    if (name !== null) mutate({ assigned_to: name })
  }
  const dismiss = () => {
    const reason = window.prompt('Reason for dismissing this task (optional):', '')
    if (reason !== null) mutate({ status: 'dismissed', note: reason })
  }

  return (
    <div className="overflow-hidden rounded-lg border border-app-border bg-app-panel">
      <div className="flex items-start gap-3 p-4">
        <span
          className="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full"
          style={{ backgroundColor: p.dot }}
          title={p.label}
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-base font-semibold text-app-text">{action.title}</h3>
            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLE[action.status]}`}>
              {STATUS_LABEL[action.status]}
            </span>
            {action.auto_resolved && (
              <span className="text-xs text-app-text-secondary">· auto-resolved</span>
            )}
          </div>

          {action.description && (
            <p className="mt-1 text-sm text-app-text-secondary">{action.description}</p>
          )}

          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-app-text-secondary">
            <span className="rounded-full border border-app-border px-2 py-0.5">{action.group_label}</span>
            <span>{p.label}</span>
            {action.assigned_to && (
              <span className="text-app-text">
                <UserPlus size={12} className="mr-1 inline" />
                {action.assigned_to}
              </span>
            )}
            <span>updated {formatRelativeTime(action.updated_at)}</span>
          </div>

          {action.note && !action.auto_resolved && (
            <p className="mt-2 rounded-md bg-app-panel-raised px-2.5 py-1.5 text-xs text-app-text-secondary">
              {action.note}
            </p>
          )}

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              className="inline-flex items-center gap-1 text-xs font-medium text-app-accent hover:underline"
            >
              {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
              {action.entity_count} {action.entity_type === 'customer' ? 'customers' : 'calls'}
            </button>

            <div className="mx-1 h-4 w-px bg-app-border" />

            {isActive ? (
              <>
                {action.status !== 'investigating' && (
                  <ActionButton onClick={() => mutate({ status: 'investigating' })} busy={busy} primary>
                    Investigating
                  </ActionButton>
                )}
                <ActionButton onClick={() => mutate({ status: 'resolved' })} busy={busy}>
                  <CheckCircle2 size={13} /> Resolved
                </ActionButton>
                <ActionButton onClick={assign} busy={busy}>
                  <UserPlus size={13} /> {action.assigned_to ? 'Reassign' : 'Assign follow-up'}
                </ActionButton>
                <ActionButton onClick={dismiss} busy={busy}>
                  <XCircle size={13} /> Dismiss
                </ActionButton>
              </>
            ) : (
              <ActionButton onClick={() => mutate({ status: 'open' })} busy={busy}>
                <RotateCcw size={13} /> Reopen
              </ActionButton>
            )}
          </div>
        </div>
      </div>

      {expanded && <EntityList action={action} />}
    </div>
  )
}

export default function ActionCenter() {
  const [refreshKey, setRefreshKey] = useState(0)
  const [tab, setTab] = useState('active')
  const { data, loading, error } = useApi(() => getActionItems(), [refreshKey])

  const refetch = useCallback(async () => setRefreshKey((k) => k + 1), [])

  const counts = data?.status_counts || {}
  const activeMatch = TABS.find((t) => t.key === tab).match
  const visible = useMemo(
    () => (data?.actions || []).filter((a) => activeMatch(a.status)),
    [data, activeMatch],
  )

  return (
    <>
      <TopBar
        title="Action Center"
        subtitle="Tasks Voxera created from the call data — track each one to closure"
      />

      <main className="flex-1 overflow-y-auto p-6">
        {loading && <LoadingState label="Building the action list…" />}
        {!loading && error && (
          <ErrorState message="Couldn't reach the API. Is the backend running on :8000?" />
        )}

        {!loading && !error && data && (
          <>
            <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
              <Kpi icon={CircleDot} label="Open" value={counts.open ?? 0} tone="text-app-text-secondary" />
              <Kpi icon={Loader2} label="Investigating" value={counts.investigating ?? 0} tone="text-mood-confused" />
              <Kpi icon={CheckCircle2} label="Resolved" value={counts.resolved ?? 0} tone="text-mood-happy" />
              <Kpi icon={XCircle} label="Dismissed" value={counts.dismissed ?? 0} tone="text-app-text-secondary" />
            </div>

            <div className="mt-6 flex items-center gap-1 border-b border-app-border">
              {TABS.map((t) => {
                const n = (data.actions || []).filter((a) => t.match(a.status)).length
                return (
                  <button
                    key={t.key}
                    type="button"
                    onClick={() => setTab(t.key)}
                    className={`-mb-px border-b-2 px-3 py-2 text-sm transition ${
                      tab === t.key
                        ? 'border-app-accent font-medium text-app-text'
                        : 'border-transparent text-app-text-secondary hover:text-app-text'
                    }`}
                  >
                    {t.label} <span className="text-xs text-app-text-secondary">({n})</span>
                  </button>
                )
              })}
            </div>

            <div className="mt-4 space-y-3">
              {visible.length === 0 ? (
                <EmptyState
                  message={
                    tab === 'active'
                      ? 'No open tasks — Voxera hasn’t flagged anything that needs action.'
                      : 'Nothing here.'
                  }
                />
              ) : (
                visible.map((action) => (
                  <ActionCard key={action.id} action={action} onMutate={refetch} />
                ))
              )}
            </div>
          </>
        )}
      </main>
    </>
  )
}
