import GlobalSearch from './GlobalSearch.jsx'

/** Shared header on every page: a left slot for a page title / breadcrumb, and the
 * global search bar (works the same from any page) on the right. */
export default function TopBar({ children }) {
  return (
    <header className="flex h-16 shrink-0 items-center justify-between gap-6 border-b border-app-border bg-app-panel px-6">
      <div className="min-w-0 flex-1">{children}</div>
      <GlobalSearch />
    </header>
  )
}
