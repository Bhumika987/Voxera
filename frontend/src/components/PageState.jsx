import { Loader2, AlertTriangle, Inbox } from 'lucide-react'

export function LoadingState({ label = 'Loading…' }) {
  return (
    <div className="flex flex-1 items-center justify-center gap-2 py-24 text-sm text-app-text-secondary">
      <Loader2 size={16} className="animate-spin" />
      {label}
    </div>
  )
}

export function ErrorState({ message = 'Something went wrong.' }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-2 py-24 text-sm text-app-text-secondary">
      <AlertTriangle size={20} className="text-mood-angry" />
      {message}
    </div>
  )
}

export function EmptyState({ message = 'Nothing here yet.' }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-2 py-24 text-sm text-app-text-secondary">
      <Inbox size={20} />
      {message}
    </div>
  )
}
